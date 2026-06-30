/*
 * ============================================================================
 *  Smart Patient/Elderly Monitoring Station  --  ESP32 firmware (Physical Layer)
 * ============================================================================
 *  Role in IoT architecture: the "Arduino" microcontroller of the physical layer.
 *
 *  SENSORS
 *    - DHT11/DHT22  : temperature + humidity        (DIGITAL sensor)
 *    - KY-037       : ambient sound level (AO pin)  (ANALOG  sensor)
 *    - RC522 RFID   : patient ID card               (SPI / digital input)
 *
 *  ACTUATORS
 *    - LED red / green : status & alert indicator
 *    - Fan             : cooling (driven via MOSFET gate or relay module)
 *    - I2C 16x2 LCD    : on-station information display
 *
 *  COMMUNICATION (Task#2): USB Serial, 115200 baud, newline-delimited JSON.
 *    ESP32 -> Jetson : {"type":"reading","temp":36.8,"hum":55.2,"sound":512,"rfid":"A1B2C3D4"}
 *    Jetson -> ESP32 : {"fan":1,"led":"red","lcd":"FEVER 37.8C"}
 *
 *  Required libraries (Arduino IDE -> Library Manager):
 *    DHT sensor library (Adafruit), LiquidCrystal_I2C, MFRC522, ArduinoJson
 * ============================================================================
 */
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SPI.h>
#include <MFRC522.h>
#include <DHT.h>
#include <ArduinoJson.h>

// ----------------------------- Pin map --------------------------------------
#define DHT_PIN     4
#define DHT_TYPE    DHT11        // change to DHT22 if that is what you have
#define SOUND_PIN   34          // KY-037 AO  (ADC1, input-only pin)
#define LED_RED     12
#define LED_GREEN   14
#define FAN_PIN     13          // -> MOSFET gate (IRLZ44N) or relay module IN
#define RFID_SS     5
#define RFID_RST    27
// I2C LCD uses SDA=21, SCL=22 (ESP32 defaults)
// SPI for RC522 uses SCK=18, MISO=19, MOSI=23

// Relay polarity: most cheap 1-channel relay modules are ACTIVE-LOW
// (drive the IN/S pin LOW to switch the fan ON). Flip these two if you ever
// use an active-HIGH driver (e.g. a bare MOSFET gate).
#define FAN_ON   LOW
#define FAN_OFF  HIGH

DHT dht(DHT_PIN, DHT_TYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2);     // try 0x3F if 0x27 shows nothing
MFRC522 rfid(RFID_SS, RFID_RST);

const unsigned long SEND_INTERVAL = 1000;   // ms between readings
unsigned long lastSend = 0;
String pendingUID = "";
bool rfidPresent = false;

// ----------------------------- RFID -----------------------------------------
String readRFID() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return "";
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  rfid.PICC_HaltA();
  return uid;
}

// ------------------------ Apply command from edge ---------------------------
void applyCommand(JsonDocument &cmd) {
  if (cmd.containsKey("fan")) {
    digitalWrite(FAN_PIN, cmd["fan"].as<int>() ? FAN_ON : FAN_OFF);
  }
  if (cmd.containsKey("led")) {
    String c = cmd["led"].as<String>();
    if (c == "red")        { digitalWrite(LED_RED, HIGH); digitalWrite(LED_GREEN, LOW);  }
    else if (c == "green") { digitalWrite(LED_RED, LOW);  digitalWrite(LED_GREEN, HIGH); }
    else                   { digitalWrite(LED_RED, LOW);  digitalWrite(LED_GREEN, LOW);  }
  }
  if (cmd.containsKey("lcd")) {
    String msg = cmd["lcd"].as<String>();
    lcd.clear();
    lcd.setCursor(0, 0); lcd.print(msg.substring(0, 16));
    if (msg.length() > 16) { lcd.setCursor(0, 1); lcd.print(msg.substring(16, 32)); }
  }
}

void readCommands() {
  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) continue;
    StaticJsonDocument<256> cmd;
    if (deserializeJson(cmd, line) == DeserializationError::Ok) applyCommand(cmd);
  }
}

// ------------------------------- Setup --------------------------------------
void setup() {
  Serial.begin(115200);
  pinMode(LED_RED, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(LED_GREEN, HIGH);          // green = normal at boot
  digitalWrite(LED_RED, LOW);
  digitalWrite(FAN_PIN, FAN_OFF);         // active-LOW relay: HIGH = fan OFF at boot

  dht.begin();
  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0); lcd.print("Health Station");
  lcd.setCursor(0, 1); lcd.print("Booting...");

  SPI.begin(18, 19, 23, RFID_SS);
  rfid.PCD_Init();
  byte ver = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  rfidPresent = (ver != 0x00 && ver != 0xFF);   // skip phantom reads if RC522 not wired yet
}

// -------------------------------- Loop --------------------------------------
void loop() {
  readCommands();

  if (rfidPresent) {
    String uid = readRFID();
    if (uid != "") pendingUID = uid;
  }

  if (millis() - lastSend >= SEND_INTERVAL) {
    lastSend = millis();

    float t = dht.readTemperature();
    float h = dht.readHumidity();
    int   sound = analogRead(SOUND_PIN);
    if (isnan(t)) t = 0;
    if (isnan(h)) h = 0;

    StaticJsonDocument<256> doc;
    doc["type"]  = "reading";
    doc["temp"]  = t;
    doc["hum"]   = h;
    doc["sound"] = sound;
    if (pendingUID != "") doc["rfid"] = pendingUID;

    serializeJson(doc, Serial);
    Serial.println();
    pendingUID = "";                       // report each card scan only once
  }
}
