"""
Web user interface (Task#5) -- Flask dashboard.

Shows live data from the physical layer, plots history, computes statistics
(mean / min / max), lets the user edit the rule thresholds, and sends manual
actuator commands. It only talks to the database; the edge server (main.py)
picks up setting/command changes on its next loop.

Run:  python app.py    (from the edge/webapp folder)
"""
import os
import sys

from flask import Flask, jsonify, render_template, request

# allow importing db.py / config.py from the parent edge/ folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
import db  # noqa: E402

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/latest")
def api_latest():
    r = db.latest_reading()
    patient = None
    if r and r.get("patient_uid"):
        p = db.get_patient(r["patient_uid"])
        patient = p["name"] if p else "Unknown"
    return jsonify({
        "reading": r,
        "patient": patient,
        "events": db.recent_events(8),
        "settings": db.get_settings(),
        # seconds since the last fall (None if never) -> lets the banner auto-clear
        "last_fall_age": db.seconds_since_last_fall(),
    })


@app.route("/api/history")
def api_history():
    metric = request.args.get("metric", "temp")
    n = request.args.get("n", 60)
    return jsonify(db.history(metric, n))


@app.route("/api/stats")
def api_stats():
    metric = request.args.get("metric", "temp")
    minutes = request.args.get("minutes", 60)
    s = db.stats(metric, minutes)
    # round floats for display
    for k in ("mean", "min", "max"):
        if s.get(k) is not None:
            s[k] = round(float(s[k]), 2)
    return jsonify(s)


@app.route("/api/settings", methods=["POST"])
def api_settings():
    updates = request.get_json(force=True) or {}
    allowed = {"rules_enabled", "fall_detection", "fan_auto",
               "temp_high", "temp_low", "hum_high", "sound_high"}
    clean = {k: v for k, v in updates.items() if k in allowed}
    db.update_settings(clean)
    return jsonify({"ok": True, "updated": clean})


@app.route("/api/fall", methods=["POST"])
def api_fall():
    """Receive a fall alert from the GPU detector (edge/fall_detector_yolo.py,
    running in WSL) and log it so the dashboard banner lights up."""
    data = request.get_json(force=True) or {}
    try:
        conf = float(data.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        conf = 0.0
    source = str(data.get("source", "AI"))[:32]
    db.insert_event("fall", "critical",
                    f"FALL DETECTED by {source} (confidence {conf:.2f})")
    return jsonify({"ok": True})


@app.route("/api/command", methods=["POST"])
def api_command():
    cmd = request.get_json(force=True) or {}
    payload = {}
    if "fan" in cmd:
        payload["fan"] = 1 if cmd["fan"] else 0
    if "led" in cmd:
        payload["led"] = cmd["led"]
    if "lcd" in cmd:
        payload["lcd"] = str(cmd["lcd"])[:32]
    if payload:
        db.add_command(payload)
    return jsonify({"ok": True, "queued": payload})


if __name__ == "__main__":
    db.init_db()
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)
