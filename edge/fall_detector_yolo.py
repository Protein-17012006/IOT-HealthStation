"""
GPU fall-detection service (runs in WSL on the RTX 4060).

This is the project's "AI on the edge" component. It is intentionally DECOUPLED
from the Windows edge server: it reads a camera/video stream, runs YOLOv8-pose on
the GPU, and when a person stays horizontal for ~FALL_SECONDS it POSTs a fall
alert to the Flask dashboard's /api/fall endpoint. It ALSO streams the annotated
video (skeleton + boxes + the FALL banner) to the dashboard so the detection
overlay shows up inside the web page instead of a separate desktop window.

Why a separate process (instead of edge/ai_fall_detection.py)?
  The microcontroller I/O + MariaDB + dashboard run on Windows; the GPU and a
  clean ML stack live in WSL. Splitting on the HTTP boundary lets each side use
  the environment that suits it -- and mirrors the real Jetson-Nano deployment,
  where the AI runs on the edge box and talks to the rest over the network.

Fall heuristic (COCO-17 keypoints from YOLOv8-pose):
  When the pose is trustworthy (shoulders + hips confident) the POSE decides:
  a person is "lying" only when the torso is tilted well past vertical OR the
  shoulders and hips are at nearly the same height. A confident upright pose
  (vertical torso, hips clearly below shoulders) VETOES a merely-wide bounding
  box -- this is what stops a person sitting still close to the camera from being
  flagged. Only when no trustworthy keypoints exist do we fall back to a strict
  bounding-box width test. A candidate fall must also persist for FALL_SECONDS
  before it is confirmed.

  IMPORTANT: the heuristic assumes the camera's "up" is gravity. Phone IP-cam
  apps often deliver a rotated frame -- set ROTATE so you appear upright on the
  preview, otherwise a seated person reads as "lying down".

Run (inside the WSL venv):
  CAMERA_SOURCE=rtsp://<iphone-ip>:8554/live \
  DASHBOARD_URL=http://<windows-host>:5000 \
  ROTATE=90 \
  /root/iot-ai/.venv/bin/python edge/fall_detector_yolo.py

Env vars:
  CAMERA_SOURCE        rtsp URL | http MJPEG | path/to/video.mp4 | 0 (webcam)
  DASHBOARD_URL        base URL of the Flask dashboard      default http://localhost:5000
  YOLO_MODEL           pose weights (auto-downloads)        default yolov8n-pose.pt
  ROTATE               rotate frames 0/90/180/270 deg       default 0
  SHOW_WINDOW          1 = also open a local preview window default 0
  STREAM_TO_DASHBOARD  1 = push annotated frames to the web default 1
  STREAM_FPS           annotated frames/sec sent to the web default 12
  FALL_SECONDS         seconds a fall must persist          default 1.5
"""
import math
import os
import threading
import time

import cv2
import requests
from ultralytics import YOLO

try:
    import torch
    _HAS_CUDA = torch.cuda.is_available()
except Exception:
    _HAS_CUDA = False


# ---- config from environment ------------------------------------------------
CAMERA_SOURCE = os.environ.get("CAMERA_SOURCE", "0")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:5000").rstrip("/")
# Shared secret the cloud dashboard requires on ingestion endpoints
# (/api/fall, /api/ai_frame). Empty = the dashboard has auth disabled (local).
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "")


def _ingest_headers(extra=None):
    """Auth header for POSTs to the dashboard (empty token -> no header)."""
    h = dict(extra or {})
    if INGEST_TOKEN:
        h["X-Ingest-Token"] = INGEST_TOKEN
    return h

# RTSP over Wi-Fi drops badly on UDP; force TCP transport before OpenCV opens it.
if CAMERA_SOURCE.startswith("rtsp"):
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

YOLO_MODEL = os.environ.get("YOLO_MODEL", "yolov8n-pose.pt")
SHOW_WINDOW = os.environ.get("SHOW_WINDOW", "0") == "1"
STREAM_TO_DASHBOARD = os.environ.get("STREAM_TO_DASHBOARD", "1") == "1"
STREAM_FPS = int(os.environ.get("STREAM_FPS", "12"))
FALL_SECONDS = float(os.environ.get("FALL_SECONDS", "1.5"))

try:
    ROTATE = int(os.environ.get("ROTATE", "0"))
except ValueError:
    ROTATE = 0
if ROTATE not in (0, 90, 180, 270):
    print(f"[AI] ignoring invalid ROTATE={ROTATE} (use 0/90/180/270)")
    ROTATE = 0

# ---- tunables ---------------------------------------------------------------
TORSO_ANGLE = 55.0      # torso tilted more than this many deg from vertical -> lying
VGAP_MIN = 0.08         # hips this fraction of box-height below shoulders -> upright
ASPECT_VETO = 0.6       # a clearly tall box (aspect <= this) can never be a fall
BOX_RATIO_NOKP = 1.3    # no trusted pose: box must be at least this wide -> lying
KP_CONF = 0.5           # min keypoint confidence to trust a landmark
PERSON_CONF = 0.4       # min person-detection confidence
COOLDOWN = 5.0          # seconds before a new fall can be reported again

# COCO-17 keypoint indices
L_SH, R_SH, L_HIP, R_HIP = 5, 6, 11, 12


def _source():
    """A digit string means a local webcam index; anything else is a URL/path."""
    return int(CAMERA_SOURCE) if CAMERA_SOURCE.isdigit() else CAMERA_SOURCE


def rotate_frame(frame, deg):
    """Rotate a BGR frame clockwise by deg (0/90/180/270). Corrects a camera
    that is mounted/streamed sideways so 'up' in the image is gravity again."""
    if deg == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if deg == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if deg == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def pose_metrics(box_xyxy, kp_xy=None, kp_conf=None):
    """Geometry shared by the decision and the on-screen diagnostics.

    Returns a dict with:
      aspect : bounding-box width / height
      angle  : torso tilt from vertical in deg (None if pose untrusted)
      vgap   : (hip_y - shoulder_y) / box_height; positive = hips below
               shoulders = upright (None if pose untrusted)
      kp_ok  : whether shoulders + hips were confident enough to trust
    """
    x1, y1, x2, y2 = box_xyxy
    w, h = (x2 - x1), (y2 - y1)
    aspect = w / (h + 1e-6)

    angle = None
    vgap = None
    kp_ok = False
    if kp_xy is not None:
        kc = kp_conf if kp_conf is not None else [1.0] * len(kp_xy)
        trunk = (L_SH, R_SH, L_HIP, R_HIP)
        # YOLO returns undetected keypoints at the origin (0,0); those are not
        # real measurements, so a confident trunk also means none sit at (0,0).
        found = all(kp_xy[k][0] != 0 or kp_xy[k][1] != 0 for k in trunk)
        if found and min(kc[L_SH], kc[R_SH], kc[L_HIP], kc[R_HIP]) > KP_CONF:
            kp_ok = True
            sx = (kp_xy[L_SH][0] + kp_xy[R_SH][0]) / 2
            sy = (kp_xy[L_SH][1] + kp_xy[R_SH][1]) / 2
            hx = (kp_xy[L_HIP][0] + kp_xy[R_HIP][0]) / 2
            hy = (kp_xy[L_HIP][1] + kp_xy[R_HIP][1]) / 2
            dx, dy = hx - sx, hy - sy
            angle = math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6))
            vgap = (hy - sy) / (h + 1e-6)
    return {"aspect": aspect, "angle": angle, "vgap": vgap, "kp_ok": kp_ok}


def decide_fall(box_xyxy, kp_xy=None, kp_conf=None):
    """Pure decision function -- kept free of any ultralytics/torch types so it
    can be unit-tested with plain numbers (see edge/test_fall_detector.py).

    box_xyxy : (x1, y1, x2, y2) person bounding box in pixels
    kp_xy    : optional 17x2 array of COCO keypoints in pixels
    kp_conf  : optional 17 keypoint confidences (None -> trust all)
    returns  : (fall_now: bool, confidence: float in 0..1)
    """
    m = pose_metrics(box_xyxy, kp_xy, kp_conf)
    aspect, angle, vgap = m["aspect"], m["angle"], m["vgap"]

    if m["kp_ok"]:
        # Trust the pose. "Lying" = torso past TORSO_ANGLE from vertical, OR the
        # shoulders and hips are at nearly the same height. A confident upright
        # pose vetoes a merely-wide box (close-up / partial framing while seated).
        #
        # The aspect > ASPECT_VETO guard keeps a clearly tall box from firing:
        # from a single frame, "bending over while standing" (tall box, torso
        # horizontal) is geometrically indistinguishable from "collapsing
        # straight toward/away from the camera" (also a tall box). We err toward
        # NOT alarming, which is why a side-on camera view (a fall -> wide box)
        # is the reliable setup; a person collapsing along the camera axis is the
        # known blind spot. Most falls land sideways -> wide box -> detected.
        lying = (angle > TORSO_ANGLE) or (vgap < VGAP_MIN)
        fall_now = lying and aspect > ASPECT_VETO
    else:
        # No trustworthy keypoints: require a clearly wide box so partial
        # detections don't trivially trip the alarm.
        fall_now = aspect > BOX_RATIO_NOKP

    confidence = max(min(aspect / 2.0, 1.0), min((angle or 0.0) / 90.0, 1.0))
    return fall_now, float(confidence)


def analyze(r):
    """Extract the most prominent person from an ultralytics Result and decide.

    Returns (fall_now, confidence, dbg) where dbg is the pose_metrics dict (or
    None when no person was found) -- used for the on-screen diagnostics overlay.
    """
    if r.boxes is None or len(r.boxes) == 0:
        return False, 0.0, None

    # pick the largest-area person box
    xyxy = r.boxes.xyxy.cpu().numpy()
    confs = r.boxes.conf.cpu().numpy()
    areas = (xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1])
    i = int(areas.argmax())
    if confs[i] < PERSON_CONF:
        return False, 0.0, None

    kp_xy = kp_conf = None
    kpts = r.keypoints
    if kpts is not None and kpts.xy is not None and len(kpts.xy) > i:
        kp_xy = kpts.xy[i].cpu().numpy()
        kp_conf = (kpts.conf[i].cpu().numpy()
                   if kpts.conf is not None else None)
    fall_now, confidence = decide_fall(xyxy[i], kp_xy, kp_conf)
    dbg = pose_metrics(xyxy[i], kp_xy, kp_conf)
    dbg["person"] = float(confs[i])
    return fall_now, confidence, dbg


class Reporter:
    """Debounce candidate falls and POST a confirmed fall to the dashboard."""

    def __init__(self):
        self.fall_since = None
        self.last_fire = 0.0
        self.state = "monitoring"

    def update(self, fall_now, confidence):
        now = time.time()
        if fall_now:
            if self.fall_since is None:
                self.fall_since = now
            elif (now - self.fall_since >= FALL_SECONDS
                  and self.state != "fall"
                  and now - self.last_fire > COOLDOWN):
                self.state = "fall"
                self.last_fire = now
                self._fire(confidence)
        else:
            self.fall_since = None
            if self.state == "fall" and now - self.last_fire > COOLDOWN:
                self.state = "monitoring"
        return self.state

    def _fire(self, confidence):
        print(f"[ALERT] FALL DETECTED (confidence {confidence:.2f}) "
              f"-> {DASHBOARD_URL}/api/fall")
        try:
            requests.post(f"{DASHBOARD_URL}/api/fall",
                          json={"confidence": confidence, "source": "yolov8-pose"},
                          headers=_ingest_headers(), timeout=3)
        except Exception as e:
            print("[warn] could not reach dashboard:", e)


class FrameUploader(threading.Thread):
    """Push the latest annotated frame to the dashboard as JPEG, throttled to
    STREAM_FPS. Runs on its own thread so the upload never slows down inference;
    the dashboard re-serves these frames as an MJPEG stream the browser shows."""

    def __init__(self, url, fps):
        super().__init__(daemon=True)
        self.url = url
        self.interval = 1.0 / max(1, fps)
        self._latest = None
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._stop = threading.Event()

    def submit(self, frame):
        with self._lock:
            self._latest = frame

    def run(self):
        last = None
        while not self._stop.is_set():
            with self._lock:
                frame = self._latest
            if frame is not None and frame is not last:
                ok, buf = cv2.imencode(".jpg", frame,
                                       [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    try:
                        self._session.post(
                            self.url, data=buf.tobytes(),
                            headers=_ingest_headers({"Content-Type": "image/jpeg"}),
                            timeout=2)
                    except Exception:
                        pass  # dashboard down / restarting -> just keep going
                last = frame
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()


class FrameGrabber(threading.Thread):
    """Continuously read the newest frame from a capture into a single slot.

    A live RTSP/MJPEG camera keeps producing frames while YOLO inference runs; if
    we read them one-by-one in the same loop, the decoder buffer backs up and the
    overlay lags reality (and can desync/drop). This thread always keeps only the
    LATEST frame, so inference works on what the camera sees *now* and older
    frames are simply skipped -- the correct trade-off for real-time monitoring.
    """

    def __init__(self, cap):
        super().__init__(daemon=True)
        self.cap = cap
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.ended = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                ok, frame = self.cap.read()
            except Exception:
                ok, frame = False, None
            if not ok:
                self.ended.set()
                break
            with self._lock:
                self._frame = frame

    def read(self):
        """Return the newest unseen frame (or None if none arrived since last)."""
        with self._lock:
            frame, self._frame = self._frame, None
            return frame

    def stop(self):
        self._stop.set()


def _annotate(r, state, dbg):
    """Draw the ultralytics skeleton/boxes plus the fall banner and the live
    diagnostics (aspect / torso angle / vgap) so you can see WHY it decided."""
    frame = r.plot()                       # skeleton + boxes drawn by ultralytics
    color = (0, 0, 255) if state == "fall" else (0, 200, 0)
    label = "FALL DETECTED" if state == "fall" else "monitoring"
    cv2.putText(frame, label, (16, 40), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, color, 2, cv2.LINE_AA)
    if dbg:
        line = f"aspect={dbg['aspect']:.2f}"
        if dbg["kp_ok"]:
            line += f"  torso={dbg['angle']:.0f}deg  vgap={dbg['vgap']:.2f}"
        else:
            line += "  (no trusted pose)"
        cv2.putText(frame, line, (16, 70), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 255, 255), 2, cv2.LINE_AA)
    if ROTATE:
        cv2.putText(frame, f"ROTATE={ROTATE}", (16, 95),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2, cv2.LINE_AA)
    return frame


def _run_once(model, reporter, src, device, uploader):
    """Process the stream until it ends/drops. Returns True if the user quit."""
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        cap.release()
        return False
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # hint: keep little decoder backlog
    except Exception:
        pass

    grabber = FrameGrabber(cap)
    grabber.start()
    frames = 0
    try:
        while True:
            if grabber.ended.is_set():
                break                      # stream ended or dropped
            frame = grabber.read()
            if frame is None:
                time.sleep(0.005)          # no new frame yet -> wait briefly
                continue
            if ROTATE:
                frame = rotate_frame(frame, ROTATE)

            r = model.predict(frame, verbose=False, device=device,
                              conf=PERSON_CONF)[0]
            fall_now, confidence, dbg = analyze(r)
            state = reporter.update(fall_now, confidence)

            frames += 1
            if frames % 30 == 0 and dbg:   # one diagnostic line per ~30 frames
                ang = "-" if dbg["angle"] is None else f"{dbg['angle']:.0f}"
                vg = "-" if dbg["vgap"] is None else f"{dbg['vgap']:.2f}"
                print(f"[AI] {state} aspect={dbg['aspect']:.2f} "
                      f"torso={ang} vgap={vg}")

            if uploader is not None or SHOW_WINDOW:
                annotated = _annotate(r, state, dbg)
                if uploader is not None:
                    uploader.submit(annotated)
                if SHOW_WINDOW:
                    cv2.imshow("Fall detection (YOLOv8-pose @ GPU)", annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        return True
    finally:
        grabber.stop()
        cap.release()
    return False


def main():
    device = 0 if _HAS_CUDA else "cpu"
    print(f"[AI] loading {YOLO_MODEL} on "
          f"{'GPU (cuda:0)' if _HAS_CUDA else 'CPU'}")
    model = YOLO(YOLO_MODEL)
    reporter = Reporter()

    uploader = None
    if STREAM_TO_DASHBOARD:
        uploader = FrameUploader(f"{DASHBOARD_URL}/api/ai_frame", STREAM_FPS)
        uploader.start()

    src = _source()
    is_file = (isinstance(src, str)
               and src.lower().rsplit(".", 1)[-1] in ("mp4", "avi", "mov", "mkv", "m4v"))
    print(f"[AI] camera source : {src}")
    print(f"[AI] rotate frames : {ROTATE} deg")
    print(f"[AI] dashboard     : {DASHBOARD_URL}/api/fall")
    if uploader is not None:
        print(f"[AI] web video     : {DASHBOARD_URL}/api/ai_camera (annotated)")
    print("[AI] running -- watch the dashboard 'Live patient feed' for the overlay")

    # A live camera/RTSP/MJPEG stream can hiccup (Wi-Fi, phone sleeping); a real
    # monitoring station must reconnect rather than die. A finite video file just
    # plays once.
    while True:
        try:
            if _run_once(model, reporter, src, device, uploader):
                break
        except Exception as e:
            print("[AI] stream error:", e)
        if is_file:
            break
        print("[AI] stream dropped -- reconnecting in 2s "
              "(keep the iPhone app open + screen unlocked)")
        time.sleep(2)

    if uploader is not None:
        uploader.stop()
    if SHOW_WINDOW:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
