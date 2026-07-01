# Smart Patient / Elderly Monitoring Station (IoT + AI)
<img width="960" height="1280" alt="IOT_Device" src="https://github.com/user-attachments/assets/ec4d9559-d6bd-45c6-904e-d381990438e9" />

An edge-computing IoT health monitoring station. The physical layer (ESP32)
reads body/room **temperature & humidity**, **ambient sound**, and **RFID
patient check-in**, and drives an **LED**, **fan**, and **LCD**. An **edge
server (Jetson Nano)** stores everything in **MariaDB**, runs **AI fall
detection** on the **iPhone camera** stream, applies **conditional rules**, and
serves a **web dashboard**.

> Theme: Healthcare + AI. Maps the assignment's "Arduino" role onto the **ESP32**
> and the "Raspberry Pi / edge server" role onto the **Jetson Nano**.

> **Deployment:** runs fully **local** (Jetson/PC + MariaDB) **or** on **AWS
> cloud** — RDS + ECS Fargate + ALB + API Gateway, provisioned by
> **CloudFormation**, with the ESP32 and the GPU fall-detector staying on-site
> and talking to the cloud over authenticated HTTP (hybrid edge ↔ cloud). See
> [Cloud deployment (AWS)](#cloud-deployment-aws--hybrid-edge--cloud) below.

```
ESP32 (physical layer)  --USB serial JSON-->  Jetson Nano (edge server)  --HTTP-->  Browser
  DHT11/22  (digital)                            MariaDB (store)                       dashboard
  KY-037    (analog)                             rules engine (analytics)              charts / stats
  RC522     (RFID)                               AI fall detection  <-- iPhone camera  threshold editor
  LED / Fan / LCD (actuators)                    Flask web UI                          manual control
```

## 5 criteria
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
aws/                   Cloud deployment (CloudFormation + Docker + scripts)
  cloudformation/ecr.yaml    ECR repository
  cloudformation/main.yaml   VPC + RDS + ECS Fargate + ALB + API Gateway
  deploy.sh / teardown.sh    one-shot deploy / cleanup
  .env.aws.example           local env pointing the edge devices at the cloud
```

---

## Cloud deployment (AWS) — hybrid edge + cloud

The database and the dashboard can run on AWS while the parts that need real
hardware stay at home. This is a **hybrid** architecture: the **ESP32 serial
reader** (`main.py`) and the **GPU YOLO detector** must run on the local machine
(USB + GPU can't move to Fargate), so they connect to the cloud backend over the
internet.

```
[ESP32]--serial-->[main.py @home]--POST /api/ingest (token)--\
[YOLO @GPU home]--POST /api/fall,/api/ai_frame (token)--\     \
                                                         v     v
Browser --> API Gateway (HTTP API) --proxy--> ALB :80 --> ECS Fargate (Flask, :8080) --> RDS MySQL
        \--> ALB DNS (full features: SSE + live video) ---/                               (PRIVATE, VPC-only)
```
All edge devices reach the cloud over **authenticated HTTP** through the ALB —
the database is **private** (never exposed to the internet).

| AWS service | Role |
|-------------|------|
| **RDS** (MySQL 8) | the `health_station` database (was local MariaDB) |
| **ECS Fargate** | runs the Flask dashboard container (serves the React SPA + REST) |
| **ALB** | internet-facing entry — SSE + MJPEG video work here |
| **API Gateway** (HTTP API) | managed public API URL, proxies to the ALB |
| **ECR** | holds the built dashboard image |
| **Secrets Manager** | RDS credentials, injected into the ECS task |
| **CloudFormation** | provisions everything (`aws/cloudformation/*.yaml`) |

### Deploy
Prereqs: AWS CLI logged in, Docker Desktop **running**, bash + curl.
```bash
bash aws/deploy.sh          # builds+pushes the image, creates both stacks
```
It prints the outputs (**AlbUrl**, **ApiGatewayUrl**, **RdsEndpoint**, secret
ARNs, region `ap-southeast-1`) plus the **dashboard login** and the **detector
token**. RDS takes ~5–10 min the first time.

### Point the local edge devices at the cloud
Copy `aws/.env.aws.example`, fill in the outputs, then run the local processes.
Both use the ingest **token** (the cloud rejects unauthenticated POSTs with 403);
neither touches the database directly:
```bash
# edge server: ESP32 serial -> POSTs readings to the cloud over HTTP
$env:CLOUD_URL="<AlbUrl>"; $env:INGEST_TOKEN="<token>"
$env:SERIAL_PORT="COM7"; $env:SIM=0
python edge/main.py

# GPU detector: falls + annotated video -> cloud dashboard (use the ALB URL)
DASHBOARD_URL=<AlbUrl> INGEST_TOKEN=<token> \
  ./run_fall_detector.sh "http://<iphone-ip>:8081/video"
```

Open **AlbUrl** in a browser, **log in** with the dashboard username/password,
and you get the full dashboard (live video + SSE). The **ApiGatewayUrl** serves
the same app, but because API Gateway buffers and times out long-lived
connections, SSE falls back to 2 s polling and the MJPEG video feeds don't
stream through it.

### Turn off / teardown
See **[aws/RUNBOOK.md](aws/RUNBOOK.md)** for the full on/off checklist. Quick
options: **pause** (scale ECS to 0 + stop RDS — keeps the stack, data and URLs,
~$0.5/day) or **teardown** (`bash aws/teardown.sh` — deletes everything, ~$0).

### Security
- **Private database.** RDS is **not publicly accessible** — only the ECS tasks
  (inside the VPC) can reach it. The local edge devices never open a DB
  connection; they push data through the authenticated app tier (`POST
  /api/ingest`). This also sidesteps home CGNAT (no fixed IP to allow-list).
- **Authentication.** The dashboard + all read/control APIs require **HTTP Basic
  Auth**; the device-ingest endpoints (`/api/ingest`, `/api/fall`,
  `/api/ai_frame`) require a shared **`X-Ingest-Token`** instead. Both
  credentials are auto-generated into **Secrets Manager** and injected into the
  ECS task — nothing secret is in git. (Auth is off when the env vars are empty,
  so local/SIM runs are unchanged.)
- **Encryption.** RDS storage is **encrypted at rest** (KMS). API Gateway is
  HTTPS; the ALB is HTTP-only for demo simplicity (real TLS needs a domain +
  ACM certificate).
- **Least privilege.** The ECS task role can read only its three specific
  Secrets Manager secrets; security groups allow only ALB→ECS→RDS hops.
- **Fall-alert email.** On a fall, the dashboard publishes to an SNS topic that
  emails the caregiver address (`AlertEmail`). Confirm the SNS subscription email
  once after the first deploy.

> **Cost note.** Left fully running this is ~US$1–2/day (ALB + RDS + Fargate).
