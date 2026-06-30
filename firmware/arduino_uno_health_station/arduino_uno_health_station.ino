/*
 * ============================================================================
 *  Smart Patient/Elderly Monitoring Station -- Arduino UNO firmware
 *  (Use this NOW with the UNO; swap to the ESP32 sketch later -- the edge
 *   server / Python side is identical, it just reads JSON over USB serial.)
 * ============================================================================
 *  Differences vs the ESP32 version:
 *    - UNO logic is 5V (ESP32 is 3.3V). IMPORTANT: power the RC522 from the
 *      UNO's 3.3V pin, NOT 5V, or you can damage it.
 *    - UNO ADC is 10-bit (0-1023). We scale the sound reading x4 so it shares
 *      the same 0-4095 range / thresholds as the ESP32 -> no edge config change.
 *    - I2C is fixed on A4(SDA)/A5(SCL); hardware SPI is fixed on D10-D13.
 *
 *  SENSORS : DHT11/22 (digital), KY-037 AO (analog), RC522 RFID (SPI)
 *  ACTUATORS: LED red/green, fan (via MOSFET/relay), I2C 16x2 LCD
 *  COMMS   : USB serial, 115200 baud, newline-delimited JSON.
 *
 *  Libraries (Arduino IDE -> Library Manager):
 *    DHT sensor library (Adafruit) + Adafruit Unified Sensor,
 *    LiquidCrystal_I2C, MFRC522, ArduinoJson
 *  Board: select "Arduino Uno" (built-in, no board manager needed).
 * ============================================================================
 */
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SPI.h>
#include <MFRC522.h>
#include <DHT.h>
#include <ArduinoJson.h>

// ----------------------------- Pin map (UNO) --------------------------------
#define DHT_PIN     2
#define DHT_TYPE    DHT11        // change to DHT22 if you have it
#define SOUND_PIN   A0          // KY-037 AO  (analog input)
#define LED_RED     5
#define LED_GREEN   6
#define FAN_PIN     3           // -> MOSFET gate (IRLZ44N) or relay module IN
#define RFID_SS     10          // SPI fixed: SCK=13, MISO=12, MOSI=11
#define RFID_RST    9
// I2C LCD fixed on A4=SDA, A5=SCL

DHT dht(DHT_PIN, DHT_TYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2);     // try 0x3F if 0x27 shows nothing
MFRC522 rfid(RFID_SS, RFID_RST);

const unsigned long SEND_INTERVAL = 1000;   // ms
unsigned long lastSend = 0;
String pendingUID = "";

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

void applyCommand(JsonDocument &cmd) {
  if (cmd.containsKey("fan")) {
    digitalWrite(FAN_PIN, cmd["fan"].as<int>() ? HIGH : LOW);
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
    StaticJsonDocument<200> cmd;
    if (deserializeJson(cmd, line) == DeserializationError::Ok) applyCommand(cmd);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_RED, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(LED_GREEN, HIGH);          // green = normal at boot
  digitalWrite(LED_RED, LOW);
  digitalWrite(FAN_PIN, LOW);

  dht.begin();
  Wire.begin();                           // UNO: no pin args
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0); lcd.print("Health Station");
  lcd.setCursor(0, 1); lcd.print("Booting...");

  SPI.begin();                            // UNO: hardware SPI pins
  rfid.PCD_Init();
}

void loop() {
  readCommands();

  String uid = readRFID();
  if (uid != "") pendingUID = uid;

  if (millis() - lastSend >= SEND_INTERVAL) {
    lastSend = millis();

    float t = dht.readTemperature();
    float h = dht.readHumidity();
    int   sound = analogRead(SOUND_PIN) * 4;   // 0-1023 -> ~0-4092 (match ESP32)
    if (isnan(t)) t = 0;
    if (isnan(h)) h = 0;

    StaticJsonDocument<200> doc;
    doc["type"]  = "reading";
    doc["temp"]  = t;
    doc["hum"]   = h;
    doc["sound"] = sound;
    if (pendingUID != "") doc["rfid"] = pendingUID;

    serializeJson(doc, Serial);
    Serial.println();
    pendingUID = "";
  }
}
