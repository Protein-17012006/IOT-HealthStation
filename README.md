# Smart Patient / Elderly Monitoring Station (IoT + AI)

An edge-computing IoT health monitoring station. The physical layer (ESP32)
reads body/room **temperature & humidity**, **ambient sound**, and **RFID
patient check-in**, and drives an **LED**, **fan**, and **LCD**. An **edge
server (Jetson Nano)** stores everything in **MariaDB**, runs **AI fall
detection** on the **iPhone camera** stream, applies **conditional rules**, and
serves a **web dashboard**.

> Theme: Healthcare + AI. Maps the assignment's "Arduino" role onto the **ESP32**
> and the "Raspberry Pi / edge server" role onto the **Jetson Nano**.

```
ESP32 (physical layer)  --USB serial JSON-->  Jetson Nano (edge server)  --HTTP-->  Browser
  DHT11/22  (digital)                            MariaDB (store)                       dashboard
  KY-037    (analog)                             rules engine (analytics)              charts / stats
  RC522     (RFID)                               AI fall detection  <-- iPhone camera  threshold editor
  LED / Fan / LCD (actuators)                    Flask web UI                          manual control
```

## How this meets the 5 tasks
| Task | Where |
|------|-------|
| 1. Physical layer (≥1 digital + ≥1 analog sensor, ≥2 actuators) | `firmware/esp32_health_station/` — DHT(digital), KY-037(analog), RC522; LED+Fan+LCD |
| 2. Serial communication | `edge/serial_link.py` (USB serial, JSON both ways) |
| 3. Database | `edge/db.py`, `edge/schema.sql` (MariaDB) |
| 4. Edge analytics (conditional rule) | `edge/rules.py` + `edge/main.py` |
| 5. User interface (live data + edit rule + stats) | `edge/webapp/` |
| AI (theme) | `edge/ai_fall_detection.py` (MediaPipe Pose, OpenCV fallback) |

---

## 1. Wiring (ESP32 DevKit)
| Component | ESP32 pin | Notes |
|-----------|-----------|-------|
| DHT11/22 data | GPIO 4 | digital sensor |
| KY-037 `AO` | GPIO 34 | analog sensor (ADC1, input-only) |
| LED red | GPIO 12 | + 220 Ω resistor |
| LED green | GPIO 14 | + 220 Ω resistor |
| Fan | GPIO 13 | **via MOSFET (IRLZ44N) or relay module** — do not drive the motor directly from a GPIO |
| RC522 SDA/SS | GPIO 5 | SPI |
| RC522 RST | GPIO 27 | |
| RC522 SCK/MISO/MOSI | 18 / 19 / 23 | SPI bus |
| LCD I2C SDA/SCL | 21 / 22 | address 0x27 (or 0x3F) |

Arduino IDE libraries: **DHT sensor library (Adafruit)**, **LiquidCrystal_I2C**,
**MFRC522**, **ArduinoJson**. Flash `firmware/esp32_health_station/esp32_health_station.ino`.

## 2. iPhone as the AI camera
Install an IP-camera app (e.g. *IP Camera Lite* or *Larix Broadcaster*) and start
an RTSP/MJPEG stream. Note the URL it shows, then set it on the Jetson:
```bash
export CAMERA_SOURCE="rtsp://<iphone-ip>:8554/live"
```
For a quick test with a laptop webcam use `CAMERA_SOURCE=0`.

### AI fall detection on the GPU (`edge/fall_detector_yolo.py`)
The fall detector runs as a **separate process** (designed for the Jetson, or a
WSL2 box with an NVIDIA GPU). It runs **YOLOv8-pose** on CUDA, reads the iPhone
stream, and `POST`s a fall alert to the dashboard's `/api/fall` endpoint — so it
stays decoupled from the serial/DB side. A fall = the person's bounding box is
wider than tall, or the torso is past ~50° from vertical, sustained ~1.2 s.

```bash
# in the GPU environment (e.g. WSL), with the dashboard already running:
pip install ultralytics                                   # pulls torch + CUDA
cd edge
./run_fall_detector.sh "http://<iphone-ip>:8081/video"    # or an rtsp:// URL
```
The in-process MediaPipe/HOG detector in `main.py` is OFF by default
(`LOCAL_AI=0`); set `LOCAL_AI=1` to run everything on one machine instead.
The fall logic is unit-tested in `edge/test_fall_detector.py`.

## 3. Database (Jetson)
```bash
sudo apt install mariadb-server
sudo mysql < edge/schema.sql          # creates DB, tables, seed data
# then create the app user (see comment at bottom of schema.sql)
```

## 4. Run the edge server
```bash
cd edge
pip install -r requirements.txt

# point at your ESP32 port (Linux: /dev/ttyUSB0, Windows: COM3)
cd c:\Users\huyho\OneDrive\Desktop\IOT\edge
$env:SIM=0
$env:SERIAL_PORT="COM7"
$env:DB_PASS="yourpassword"   # your MariaDB password (not committed to git)
python main.py
```
In a second terminal:
```bash
cd edge/webapp
python app.py             # dashboard at http://<jetson-ip>:5000
```

## 5. Try it with NO hardware (development on your laptop)
You can run the whole stack — DB, rules, web UI — using the built-in data
simulator, then add the real ESP32 later.
```bash
# requires only MariaDB + the pip packages
set SIM=1          &  (Windows PowerShell:  $env:SIM=1)
python edge/main.py            # generates fake temp/humidity/sound + RFID scans
python edge/webapp/app.py      # open http://localhost:5000
```
Fall detection needs a camera; without one the dashboard just shows
`AI: monitoring` and the rest works normally.

---

## Suggested 2–3 min demo flow (for the video)
1. Show the wired ESP32; readings appear on the LCD and stream in the dashboard.
2. Scan an RFID card → "Current patient" updates + a check-in event is logged.
3. Warm the DHT (or lower the fever threshold in the UI) → **fan turns on**, LED
   goes red, a `fever` event is logged → show it persists in MariaDB.
4. Step in front of the iPhone camera and lie down → **FALL DETECTED** banner +
   critical event.
5. Show the history chart and the mean/min/max statistics.
6. Use manual controls to toggle the fan / LED / LCD message.

## Repo layout
```
firmware/esp32_health_station/   ESP32 Arduino sketch (physical layer)
edge/
  config.py            settings (env-overridable)
  db.py / schema.sql   MariaDB layer + schema
  serial_link.py       ESP32 serial link (+ simulator)
  rules.py             conditional rule engine (edge analytics)
  ai_fall_detection.py AI fall detection from the camera (MediaPipe/HOG, in-process)
  fall_detector_yolo.py  GPU fall detector (YOLOv8-pose, separate process)
  test_fall_detector.py  unit tests for the fall-detection logic
  run_fall_detector.sh   launcher for the GPU detector (WSL)
  main.py              edge orchestrator
  webapp/              Flask dashboard (live data, stats, settings, control)
```
