/*
 * ============================================================================
 *  Smart Patient/Elderly Monitoring Station -- Arduino UNO firmware
 *  (Use this NOW with the UNO; swap to the ESP32 sketch later -- the edge
 *   server / Python side is identical, it just reads JSON over USB serial.)
 * ============================================================================
 *  Differences vs the ESP32 version:
 *    - UNO logic is 5V (ESP32 is 3.3V).
 *    - UNO ADC is 10-bit (0-1023). We scale the sound reading x4 so it shares
 *      the same 0-4095 range / thresholds as the ESP32 -> no edge config change.
 *    - I2C is fixed on A4(SDA)/A5(SCL).
 *
 *  SENSORS : DHT11/22 (digital), KY-037 AO (analog)
 *  ACTUATORS: LED red/green, fan (via MOSFET/relay), I2C 16x2 LCD
 *  COMMS   : USB serial, 115200 baud, newline-delimited JSON.
 *
 *  Libraries (Arduino IDE -> Library Manager):
 *    DHT sensor library (Adafruit) + Adafruit Unified Sensor,
 *    LiquidCrystal_I2C, ArduinoJson
 *  Board: select "Arduino Uno" (built-in, no board manager needed).
 * ============================================================================
 */
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <ArduinoJson.h>

// ----------------------------- Pin map (UNO) --------------------------------
#define DHT_PIN     2
#define DHT_TYPE    DHT11        // change to DHT22 if you have it
#define SOUND_PIN   A0          // KY-037 AO  (analog input)
#define LED_RED     5
#define LED_GREEN   6
#define FAN_PIN     3           // -> MOSFET gate (IRLZ44N) or relay module IN
// I2C LCD fixed on A4=SDA, A5=SCL

DHT dht(DHT_PIN, DHT_TYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2);     // try 0x3F if 0x27 shows nothing

const unsigned long SEND_INTERVAL = 1000;   // ms
unsigned long lastSend = 0;

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
}

void loop() {
  readCommands();

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

    serializeJson(doc, Serial);
    Serial.println();
  }
}
