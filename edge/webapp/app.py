"""
Web user interface (Task#5) -- Flask dashboard.

Shows live data from the physical layer, plots history, computes statistics
(mean / min / max), lets the user edit the rule thresholds, and sends manual
actuator commands. It only talks to the database; the edge server (main.py)
picks up setting/command changes on its next loop.

Real-time:
  /api/stream  Server-Sent Events -- pushes the latest snapshot every second
               (the browser falls back to polling /api/latest if SSE fails).
  /api/camera  reverse-proxies the iPhone MJPEG stream so the browser loads it
               same-origin and the camera credentials never reach the page.

Run:  python app.py    (from the edge/webapp folder)
"""
import base64
import hmac
import json
import os
import pathlib
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from flask import (Flask, Response, abort, jsonify, render_template, request,
                   send_from_directory)

# allow importing db.py / config.py from the parent edge/ folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
import db  # noqa: E402
import rules  # noqa: E402

# Built React/Vite app (frontend/dist). Served at the app root; falls back to the
# bundled Jinja template if the SPA hasn't been built yet.
DIST = pathlib.Path(__file__).resolve().parent / "frontend" / "dist"
app = Flask(__name__, static_folder=str(DIST), static_url_path="")
# Cap request bodies: the only large POST is one annotated JPEG frame to
# /api/ai_frame, which is well under this. Stops an unbounded body from being
# buffered into memory.
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

SETTINGS_KEYS = {"rules_enabled", "fall_detection", "fan_auto",
                 "temp_high", "temp_low", "hum_high", "sound_high", "camera_url"}

# ---- Access control ---------------------------------------------------------
# Two-tier auth so the same app is safe on the public internet but still runs
# locally with no setup:
#   * humans (dashboard + all read/control APIs) -> HTTP Basic Auth
#   * devices (the GPU detector POSTing falls/frames) -> a shared X-Ingest-Token
# Both are OFF when their env var is empty, so local dev / SIM mode is unchanged;
# in the cloud, ECS injects DASH_PASS + INGEST_TOKEN from Secrets Manager.
DASH_USER = os.environ.get("DASH_USER", "admin")
DASH_PASS = os.environ.get("DASH_PASS", "")
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "")
# machine-to-machine ingestion endpoints -> token instead of Basic Auth
INGEST_PATHS = {"/api/fall", "/api/ai_frame", "/api/ingest"}


@app.before_request
def _require_auth():
    path = request.path
    if path == "/healthz":
        return  # unauthenticated liveness probe for the load balancer
    if path in INGEST_PATHS:
        # device ingestion: constant-time token check (skipped if not configured)
        if INGEST_TOKEN and not hmac.compare_digest(
                request.headers.get("X-Ingest-Token", ""), INGEST_TOKEN):
            return Response("forbidden\n", status=403)
        return
    # everything else (dashboard, SPA assets, read/control APIs): Basic Auth
    if DASH_PASS:
        auth = request.authorization
        ok = (auth is not None
              and hmac.compare_digest(auth.username or "", DASH_USER)
              and hmac.compare_digest(auth.password or "", DASH_PASS))
        if not ok:
            return Response("login required\n", status=401,
                            headers={"WWW-Authenticate":
                                     'Basic realm="Health Station"'})
    return


@app.route("/healthz")
def healthz():
    """Cheap, auth-free, DB-free liveness check for the ALB target group."""
    return "ok", 200

# Latest annotated frame pushed by the GPU detector (edge/fall_detector_yolo.py,
# running in WSL). We hold the most recent JPEG in memory and re-serve it as an
# MJPEG stream at /api/ai_camera, so the browser sees the detection overlay
# same-origin -- the detector itself never has to be web-reachable.
_ai_lock = threading.Lock()
_ai_frame = {"jpeg": None, "ts": 0.0}
AI_STREAM_FPS = 12          # frames/sec the browser MJPEG stream is paced at
AI_STALE_SECONDS = 5.0      # no push within this -> the AI feed is "offline"


def _ai_active():
    """True when the detector pushed a frame recently (drives the UI to show the
    annotated feed instead of the raw camera proxy)."""
    return (_ai_frame["jpeg"] is not None
            and (time.time() - _ai_frame["ts"]) < AI_STALE_SECONDS)


def _latest_payload():
    """The full live snapshot shared by /api/latest and the SSE stream."""
    r = db.latest_reading()
    patient = None
    if r and r.get("patient_uid"):
        p = db.get_patient(r["patient_uid"])
        patient = p["name"] if p else "Unknown"
    return {
        "reading": r,
        "patient": patient,
        "events": db.recent_events(8),
        "settings": db.get_settings(),
        # seconds since the last fall (None if never) -> lets the banner auto-clear
        "last_fall_age": db.seconds_since_last_fall(),
        # whether the GPU detector is currently pushing annotated video
        "ai_active": _ai_active(),
    }


@app.route("/")
def index():
    if (DIST / "index.html").exists():
        return send_from_directory(str(DIST), "index.html")
    return render_template("index.html")   # fallback to the bundled template


@app.route("/api/latest")
def api_latest():
    return jsonify(_latest_payload())


@app.route("/api/stream")
def api_stream():
    """Server-Sent Events: one JSON snapshot per second, no polling needed."""
    def gen():
        while True:
            try:
                yield "data: " + json.dumps(_latest_payload()) + "\n\n"
            except Exception as e:  # keep the stream alive on a transient DB blip
                yield "event: err\ndata: " + json.dumps(str(e)) + "\n\n"
            time.sleep(1)
    return Response(gen(), content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


def _auth_request(url):
    """Build a urllib Request, moving any user:pass@ in the URL into a Basic
    auth header (urllib does not do this on its own)."""
    parts = urlsplit(url)
    headers = {}
    netloc = parts.netloc
    if "@" in netloc:
        creds, host = netloc.rsplit("@", 1)
        netloc = host
        headers["Authorization"] = "Basic " + base64.b64encode(
            creds.encode()).decode()
    clean = urlunsplit((parts.scheme, netloc, parts.path, parts.query,
                        parts.fragment))
    return urllib.request.Request(clean, headers=headers)


@app.route("/api/camera")
def api_camera():
    """Reverse-proxy the configured camera MJPEG stream (set via camera_url in
    settings) so the browser loads it same-origin without seeing credentials."""
    url = (db.get_settings().get("camera_url") or "").strip()
    if not url:
        abort(404)
    try:
        upstream = urllib.request.urlopen(_auth_request(url), timeout=10)
    except Exception:
        abort(502)
    ctype = upstream.headers.get("Content-Type", "multipart/x-mixed-replace")

    def gen():
        try:
            while True:
                chunk = upstream.read(8192)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()
    return Response(gen(), content_type=ctype)


@app.route("/api/ai_frame", methods=["POST"])
def api_ai_frame():
    """Receive one annotated JPEG frame from the GPU detector and keep it as the
    latest. The detector POSTs here a dozen times a second while it runs."""
    data = request.get_data()
    # only accept a real JPEG (starts with the SOI marker) so a bad/spoofed body
    # can't be re-served to viewers as image/jpeg
    if data[:2] == b"\xff\xd8":
        with _ai_lock:
            _ai_frame["jpeg"] = data
            _ai_frame["ts"] = time.time()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "not a jpeg"}), 415


@app.route("/api/ai_camera")
def api_ai_camera():
    """Re-serve the detector's annotated frames as an MJPEG stream so the browser
    can show the skeleton + boxes + FALL banner inside the dashboard."""
    def gen():
        blank = 0
        while True:
            with _ai_lock:
                jpeg = _ai_frame["jpeg"]
                ts = _ai_frame["ts"]
            fresh = jpeg is not None and (time.time() - ts) < AI_STALE_SECONDS
            if fresh:
                blank = 0
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + jpeg + b"\r\n")
            else:
                # detector not pushing: stop after a grace period so the browser's
                # <img> onError fires and the UI can fall back to the raw feed
                blank += 1
                if blank > AI_STREAM_FPS * 2:
                    break
            time.sleep(1.0 / AI_STREAM_FPS)
    return Response(gen(),
                    content_type="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
    clean = {k: v for k, v in updates.items() if k in SETTINGS_KEYS}
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


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    """Receive one sensor reading from the local edge server (main.py) over HTTP.

    This is what lets the database stay PRIVATE: the edge box (behind CGNAT, no
    fixed IP) never opens a MySQL connection to RDS -- it POSTs the reading here
    with the shared X-Ingest-Token, and the app (already inside the VPC) does the
    DB writes. Mirrors main.py._handle_reading: stores the reading, logs the RFID
    check-in + rule events, applies a fall override, and returns the actuator
    command (merged with any manual commands the UI queued) for the ESP32.
    """
    data = request.get_json(force=True) or {}
    temp = data.get("temp")
    hum = data.get("hum", data.get("humidity"))
    sound = data.get("sound")
    uid = data.get("rfid") or data.get("uid")

    db.insert_reading(temp, hum, sound, uid)
    if uid:
        p = db.get_patient(uid)
        name = p["name"] if p else "Unknown card"
        db.insert_event("rfid", "info", f"Patient check-in: {name} ({uid})")

    settings = db.get_settings()
    cmd, events = rules.evaluate({"temp": temp, "sound": sound}, settings)
    for etype, sev, message in events:
        db.insert_event(etype, sev, message)

    # a fall reported (via /api/fall) in the last few seconds overrides the rules
    age = db.seconds_since_last_fall()
    if age is not None and age <= 10:
        cmd["led"] = "red"
        cmd["lcd"] = "FALL! Help needed"

    # fold in any manual actuator commands queued from the dashboard
    for manual in db.fetch_unconsumed_commands():
        cmd.update(manual)

    return jsonify({"ok": True, "command": cmd})


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
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False,
            threaded=True)
