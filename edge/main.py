"""
Edge server orchestrator (Jetson Nano).

Ties everything together:
  serial in  -> store reading -> apply rules (Task#4) -> command back to ESP32
  AI thread  -> fall detection -> log event + override actuators
  web UI     -> queues manual commands / threshold changes via the database

Run the web UI (webapp/app.py) as a separate process.
"""
import json
import time
import urllib.request

import config
import db
from ai_fall_detection import FallDetector
from rules import evaluate
from serial_link import SerialLink


def main():
    print("== Smart Patient/Elderly Monitoring Station -- edge server ==")
    cloud = bool(config.CLOUD_URL)
    if cloud:
        # DB lives on AWS (private) -> push readings over HTTP, don't touch it.
        print(f"[cloud] pushing readings to {config.CLOUD_URL}/api/ingest")
    else:
        print("Initializing database...")
        db.init_db()

    link = SerialLink()
    link.start()

    detector = FallDetector()
    if (not cloud and config.LOCAL_AI
            and db.get_settings().get("fall_detection", "1") == "1"):
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
                if cloud:
                    _handle_reading_cloud(msg, link)
                else:
                    _handle_reading(msg, link, detector)

            # In local mode, forward manual UI commands here. In cloud mode the
            # /api/ingest response already carries them, so nothing to poll.
            if not cloud:
                for cmd in db.fetch_unconsumed_commands():
                    link.send_command(cmd)

            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopping...")
        link.stop()
        detector.stop()


def _handle_reading_cloud(msg, link):
    """Cloud mode: POST the reading to the dashboard and relay the command it
    returns to the ESP32. The server does the DB writes + rules + fall override,
    so RDS never has to be reachable from here (see webapp api_ingest)."""
    payload = {"temp": msg.get("temp"), "hum": msg.get("hum"),
               "sound": msg.get("sound"), "rfid": msg.get("rfid")}
    req = urllib.request.Request(
        f"{config.CLOUD_URL}/api/ingest",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "X-Ingest-Token": config.INGEST_TOKEN},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            resp = json.loads(r.read().decode())
    except Exception as e:  # network blip -> skip this reading, keep running
        print("[cloud] ingest failed:", e)
        return

    print(f"[reading->cloud] temp={payload['temp']} hum={payload['hum']} "
          f"sound={payload['sound']}"
          + (f" rfid={payload['rfid']}" if payload["rfid"] else ""))
    cmd = resp.get("command") or {}
    if cmd:
        link.send_command(cmd)


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
