# Conceptual Design — Block Diagram & UML

Diagrams for the project report (Smart Patient/Elderly Monitoring Station).
Each block matches the actual code in this repo.

## How to render these into images for the report
- **Mermaid blocks** → open <https://mermaid.live>, paste the code, *Actions → PNG/SVG*.
  In VS Code you can also install the extension **"Markdown Preview Mermaid Support"**
  and open the Markdown preview (Ctrl+Shift+V) — diagrams render inline.
- **PlantUML block** (use case) → open <https://www.plantuml.com/plantuml>, paste,
  export PNG. Or install the VS Code **"PlantUML"** extension.

---

## 1. Block Diagram — IoT architecture (hardware + software)
> Shows the three tiers: physical layer (ESP32 + sensors/actuators), edge server
> (Jetson Nano: serial, database, rules, AI), and the user/presentation tier.

```mermaid
flowchart LR
  subgraph PHYS["PHYSICAL LAYER — ESP32 DevKit"]
    direction TB
    DHT["DHT11/22<br/>Temp + Humidity<br/>(DIGITAL)"]
    KY["KY-037<br/>Sound level AO<br/>(ANALOG)"]
    RFID["RC522 RFID<br/>Patient ID (SPI)"]
    ESP["ESP32 firmware<br/>(reads sensors,<br/>drives actuators,<br/>JSON over serial)"]
    LED["LED red / green"]
    FAN["Fan<br/>(via MOSFET / relay)"]
    LCD["I2C LCD 16x2"]
    DHT --> ESP
    KY --> ESP
    RFID --> ESP
    ESP --> LED
    ESP --> FAN
    ESP --> LCD
  end

  subgraph EDGE["EDGE SERVER — Jetson Nano"]
    direction TB
    SER["serial_link.py<br/>(pyserial)"]
    MAIN["main.py<br/>orchestrator"]
    RULES["rules.py<br/>edge analytics"]
    AI["ai_fall_detection.py<br/>MediaPipe / OpenCV"]
    WEB["webapp/app.py<br/>Flask REST + UI"]
    DB[("MariaDB<br/>readings · events<br/>settings · patients<br/>commands")]
    SER --> MAIN
    MAIN --> RULES
    MAIN --> DB
    AI --> DB
    WEB --> DB
  end

  PHONE["iPhone 12<br/>IP-camera app<br/>(RTSP/MJPEG)"]
  USER["Caregiver / Nurse<br/>(web browser)"]

  ESP <-->|"USB Serial (JSON)"| SER
  MAIN -->|"command JSON"| SER
  PHONE -->|"video stream"| AI
  USER <-->|"HTTP / dashboard"| WEB
```

---

## 2. Use Case Diagram (PlantUML)
> Actors and what they can do with the system.

```plantuml
@startuml
left to right direction
skinparam packageStyle rectangle

actor "Caregiver / Nurse" as Nurse
actor "Patient" as Patient
actor "AI Camera (iPhone)" as Cam

rectangle "Smart Patient Monitoring Station" {
  usecase "Check in via RFID"                       as UC1
  usecase "Monitor live vitals\n(temp / humidity / sound)" as UC2
  usecase "Detect fall (AI)"                        as UC3
  usecase "Trigger automatic actuator\n(fan / LED / LCD)"  as UC4
  usecase "Receive alert / notification"            as UC5
  usecase "Adjust rule thresholds"                  as UC6
  usecase "View statistics & charts\n(mean / min / max)"   as UC7
  usecase "Manual actuator control"                 as UC8
}

Patient --> UC1
Patient --> UC2
Cam     --> UC3
UC2 ..> UC4 : <<include>>
UC3 ..> UC5 : <<include>>
UC4 ..> UC5 : <<extend>>
Nurse --> UC2
Nurse --> UC5
Nurse --> UC6
Nurse --> UC7
Nurse --> UC8
@enduml
```

---

## 3. Activity Diagram — edge server main loop (Task#4 logic)
> The software process: ingest a reading → store → apply rules → fall override →
> command the actuators → forward any manual UI commands.

```mermaid
flowchart TD
  Start([Start edge server]) --> Init["Init DB,<br/>start serial + AI threads"]
  Init --> Read{"New serial<br/>reading?"}
  Read -- no --> Manual
  Read -- yes --> Store["Store reading in MariaDB"]
  Store --> RFIDq{"RFID UID present?"}
  RFIDq -- yes --> Lookup["Lookup patient +<br/>log check-in event"]
  RFIDq -- no --> Rules
  Lookup --> Rules["Load settings +<br/>evaluate rules"]
  Rules --> Fever{"Temp >= fever<br/>threshold?"}
  Fever -- yes --> FanOn["fan = ON, LED = red<br/>log 'fever' event"]
  Fever -- no --> Loud{"Sound >= loud<br/>threshold?"}
  Loud -- yes --> Noise["LED = red<br/>log 'noise' event"]
  Loud -- no --> Ok["fan = OFF, LED = green"]
  FanOn --> FallChk
  Noise --> FallChk
  Ok --> FallChk
  FallChk{"AI fall<br/>detected?"} -- yes --> Fall["Override: LED = red,<br/>LCD 'FALL! Help needed'<br/>log CRITICAL event"]
  FallChk -- no --> Send
  Fall --> Send["Send command JSON to ESP32"]
  Send --> Manual["Forward queued UI commands"]
  Manual --> Read
```

---

## 4. Sequence Diagram — end-to-end data & control flow
> How the tiers talk to each other over time.

```mermaid
sequenceDiagram
  participant ESP as ESP32 (sensors/actuators)
  participant Edge as Jetson main.py
  participant DB as MariaDB
  participant AI as Fall Detector
  participant Web as Flask UI
  participant User as Caregiver

  loop every 1 second
    ESP->>Edge: reading {temp,hum,sound,rfid}
    Edge->>DB: INSERT reading (+ check-in event)
    Edge->>DB: load settings
    Edge->>Edge: evaluate rules
    Edge-->>ESP: command {fan,led,lcd}
  end

  par AI thread
    AI->>AI: process camera frame (pose)
    AI->>DB: INSERT fall event (critical)
  end

  User->>Web: open dashboard
  Web->>DB: query latest / history / stats
  Web-->>User: live values + charts + stats
  User->>Web: change threshold / manual control
  Web->>DB: UPDATE settings / queue command
  Edge->>DB: poll commands & settings
  Edge-->>ESP: forward manual command
```

---

## 5. Class / Module Diagram — software structure
> The Python modules of the edge server and how they relate.

```mermaid
classDiagram
  class SerialLink {
    +Queue rx
    +start()
    +send_command(cmd)
    +get_nowait()
    +stop()
    -_read_loop()
    -_sim_loop()
  }
  class FallDetector {
    +str status
    +float confidence
    +start(on_fall)
    +state()
    +stop()
    -_detect_pose(frame)
    -_detect_hog(frame)
    -_update(fall)
  }
  class rules {
    <<module>>
    +evaluate(reading, settings)
  }
  class db {
    <<module>>
    +init_db()
    +insert_reading()
    +insert_event()
    +latest_reading()
    +history()
    +stats()
    +get_settings()
    +update_settings()
    +add_command()
    +fetch_unconsumed_commands()
  }
  class main {
    <<module>>
    +main()
    -_handle_reading()
    -_on_fall()
  }
  class FlaskApp {
    +api_latest()
    +api_history()
    +api_stats()
    +api_settings()
    +api_command()
  }
  main --> SerialLink : reads/writes
  main --> FallDetector : monitors
  main --> rules : evaluate()
  main --> db : persist
  FallDetector --> db : log events
  FlaskApp --> db : query/update
```

---

## 6. Entity-Relationship Diagram — database (Task#3)
> The MariaDB schema (see `edge/schema.sql`).

```mermaid
erDiagram
  PATIENTS ||--o{ READINGS : "identified in"
  READINGS {
    int id PK
    timestamp ts
    float temp
    float humidity
    int sound
    string patient_uid FK
  }
  EVENTS {
    int id PK
    timestamp ts
    string type
    string severity
    string message
  }
  SETTINGS {
    string skey PK
    string svalue
  }
  PATIENTS {
    string uid PK
    string name
    string note
  }
  COMMANDS {
    int id PK
    timestamp ts
    string payload
    int consumed
  }
```
