/*
 * Minimal DHT11 test -- isolates the sensor from the rest of the project.
 * Upload this, open Serial Monitor @ 115200.
 *   - "Temp: 28.5 C  Hum: 62 %"  -> sensor + wiring OK
 *   - "FAILED to read DHT"        -> wiring / power / type problem
 */
#include <DHT.h>

#define DHT_PIN   4        // sensor DATA ("s") -> ESP32 G4
#define DHT_TYPE  DHT11    // blue 3-pin module = DHT11

DHT dht(DHT_PIN, DHT_TYPE);

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println();
  Serial.println("=== DHT11 isolation test on GPIO4 ===");
  dht.begin();
}

void loop() {
  delay(2000);                       // DHT11 needs >=1s between reads
  float h = dht.readHumidity();
  float t = dht.readTemperature();

  if (isnan(h) || isnan(t)) {
    Serial.println("FAILED to read DHT -> check: middle pin to 3V3, s->G4, - ->GND, try other jumper wires");
  } else {
    Serial.print("Temp: "); Serial.print(t);
    Serial.print(" C  Hum: "); Serial.print(h); Serial.println(" %");
  }
}
