"""
Edge server orchestrator (Jetson Nano).

Ties everything together:
  serial in  -> store reading -> apply rules (Task#4) -> command back to ESP32
  AI thread  -> fall detection -> log event + override actuators
  web UI     -> queues manual commands / threshold changes via the database

Run the web UI (webapp/app.py) as a separate process.
"""
import time

import config
import db
from ai_fall_detection import FallDetector
from rules import evaluate
from serial_link import SerialLink


def main():
    print("== Smart Patient/Elderly Monitoring Station -- edge server ==")
    print("Initializing database...")
    db.init_db()

    link = SerialLink()
    link.start()

    detector = FallDetector()
    if config.LOCAL_AI and db.get_settings().get("fall_detection", "1") == "1":
        detector.start(on_fall=lambda c: _on_fall(c))
        print("[AI] local in-process fall detector started (LOCAL_AI=1)")
    else:
        print("[AI] local detector OFF -- expecting the GPU detector in WSL "
              "to report via POST /api/fall")

    print("Running. Press Ctrl+C to stop.")
    try:
        while True:
            msg = link.get_nowait()
            if msg and msg.get("type") == "reading":
                _handle_reading(msg, link, detector)

            # forward any manual commands queued by the web UI
            for cmd in db.fetch_unconsumed_commands():
                link.send_command(cmd)

            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopping...")
        link.stop()
        detector.stop()


def _on_fall(confidence):
    db.insert_event("fall", "critical",
                    f"FALL DETECTED by AI (confidence {confidence:.2f})")
    print(f"[ALERT] FALL DETECTED (confidence {confidence:.2f})")


def _handle_reading(msg, link, detector):
    temp = msg.get("temp")
    hum = msg.get("hum")
    sound = msg.get("sound")
    uid = msg.get("rfid")

    db.insert_reading(temp, hum, sound, uid)
    print(f"[reading] temp={temp} hum={hum} sound={sound}"
          + (f" rfid={uid}" if uid else ""))

    if uid:
        patient = db.get_patient(uid)
        name = patient["name"] if patient else "Unknown card"
        db.insert_event("rfid", "info", f"Patient check-in: {name} ({uid})")

    settings = db.get_settings()
    cmd, events = evaluate({"temp": temp, "sound": sound}, settings)
    for etype, sev, message in events:
        db.insert_event(etype, sev, message)

    # an active fall alert overrides the normal rule output
    if detector.status == "fall":
        cmd["led"] = "red"
        cmd["lcd"] = "FALL! Help needed"

    if cmd:
        link.send_command(cmd)


if __name__ == "__main__":
    main()
