"""
GPU fall-detection service (runs in WSL on the RTX 4060).

This is the project's "AI on the edge" component. It is intentionally DECOUPLED
from the Windows edge server: it reads a camera/video stream, runs YOLOv8-pose on
the GPU, and when a person stays horizontal for ~1.2 s it POSTs a fall alert to
the Flask dashboard's /api/fall endpoint. The dashboard logs the event and shows
the red "FALL DETECTED" banner -- no shared database or serial port is needed.

Why a separate process (instead of edge/ai_fall_detection.py)?
  The microcontroller I/O + MariaDB + dashboard run on Windows; the GPU and a
  clean ML stack live in WSL. Splitting on the HTTP boundary lets each side use
  the environment that suits it -- and mirrors the real Jetson-Nano deployment,
  where the AI runs on the edge box and talks to the rest over the network.

Fall heuristic (COCO-17 keypoints from YOLOv8-pose):
  - the person's bounding box is wider than it is tall (w/h > BOX_RATIO), OR
  - the torso (shoulders -> hips) is tilted more than TORSO_ANGLE deg from vertical
  A candidate fall must persist for FALL_SECONDS before it is confirmed, which
  suppresses false positives from bending down or sitting.

Run (inside the WSL venv):
  CAMERA_SOURCE=rtsp://<iphone-ip>:8554/live \
  DASHBOARD_URL=http://<windows-host>:5000 \
  /root/iot-ai/.venv/bin/python edge/fall_detector_yolo.py

Env vars:
  CAMERA_SOURCE  rtsp URL | path/to/video.mp4 | 0 (webcam)     default 0
  DASHBOARD_URL  base URL of the Flask dashboard               default http://localhost:5000
  YOLO_MODEL     pose weights (auto-downloads on first use)    default yolov8n-pose.pt
  SHOW_WINDOW    1 = open an annotated preview window (WSLg)   default 1
  FALL_SECONDS   seconds a fall must persist before firing     default 1.2
"""
import math
import os
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

# RTSP over Wi-Fi drops badly on UDP; force TCP transport before OpenCV opens it.
if CAMERA_SOURCE.startswith("rtsp"):
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

YOLO_MODEL = os.environ.get("YOLO_MODEL", "yolov8n-pose.pt")
SHOW_WINDOW = os.environ.get("SHOW_WINDOW", "1") == "1"
FALL_SECONDS = float(os.environ.get("FALL_SECONDS", "1.2"))

# ---- tunables ---------------------------------------------------------------
BOX_RATIO = 1.1       # bounding box wider than tall -> lying down
TORSO_ANGLE = 50.0    # degrees from vertical -> torso is horizontal
KP_CONF = 0.5         # min keypoint confidence to trust a landmark
PERSON_CONF = 0.4     # min person-detection confidence
COOLDOWN = 5.0        # seconds before a new fall can be reported again

# COCO-17 keypoint indices
L_SH, R_SH, L_HIP, R_HIP = 5, 6, 11, 12


def _source():
    """A digit string means a local webcam index; anything else is a URL/path."""
    return int(CAMERA_SOURCE) if CAMERA_SOURCE.isdigit() else CAMERA_SOURCE


def decide_fall(box_xyxy, kp_xy=None, kp_conf=None):
    """Pure decision function -- kept free of any ultralytics/torch types so it
    can be unit-tested with plain numbers (see edge/test_fall_detector.py).

    box_xyxy : (x1, y1, x2, y2) person bounding box in pixels
    kp_xy    : optional 17x2 array of COCO keypoints in pixels
    kp_conf  : optional 17 keypoint confidences (None -> trust all)
    returns  : (fall_now: bool, confidence: float in 0..1)
    """
    x1, y1, x2, y2 = box_xyxy
    w, h = (x2 - x1), (y2 - y1)
    aspect = w / (h + 1e-6)
    wide = aspect > BOX_RATIO

    # torso angle from keypoints (only if shoulders + hips are confident)
    angle = 0.0
    horizontal = False
    if kp_xy is not None:
        kc = kp_conf if kp_conf is not None else [1.0] * len(kp_xy)
        if min(kc[L_SH], kc[R_SH], kc[L_HIP], kc[R_HIP]) > KP_CONF:
            sx = (kp_xy[L_SH][0] + kp_xy[R_SH][0]) / 2
            sy = (kp_xy[L_SH][1] + kp_xy[R_SH][1]) / 2
            hx = (kp_xy[L_HIP][0] + kp_xy[R_HIP][0]) / 2
            hy = (kp_xy[L_HIP][1] + kp_xy[R_HIP][1]) / 2
            dx, dy = hx - sx, hy - sy
            angle = math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6))
            horizontal = angle > TORSO_ANGLE

    # a wide box is decisive; the torso angle only counts when the box is not
    # clearly upright (avoids flagging someone bending over while standing)
    fall_now = wide or (horizontal and aspect > 0.75)
    confidence = max(min(aspect / 2.0, 1.0), min(angle / 90.0, 1.0))
    return fall_now, float(confidence)


def analyze(r):
    """Extract the most prominent person from an ultralytics Result and decide."""
    if r.boxes is None or len(r.boxes) == 0:
        return False, 0.0

    # pick the largest-area person box
    xyxy = r.boxes.xyxy.cpu().numpy()
    confs = r.boxes.conf.cpu().numpy()
    areas = (xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1])
    i = int(areas.argmax())
    if confs[i] < PERSON_CONF:
        return False, 0.0

    kp_xy = kp_conf = None
    kpts = r.keypoints
    if kpts is not None and kpts.xy is not None and len(kpts.xy) > i:
        kp_xy = kpts.xy[i].cpu().numpy()
        kp_conf = (kpts.conf[i].cpu().numpy()
                   if kpts.conf is not None else None)
    return decide_fall(xyxy[i], kp_xy, kp_conf)


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
                          timeout=3)
        except Exception as e:
            print("[warn] could not reach dashboard:", e)


def _run_once(model, reporter, src, device):
    """Process the stream until it ends/drops. Returns True if the user quit."""
    for r in model.predict(source=src, stream=True, verbose=False,
                           device=device, conf=PERSON_CONF):
        fall_now, confidence = analyze(r)
        state = reporter.update(fall_now, confidence)

        if SHOW_WINDOW:
            frame = r.plot()               # skeleton + boxes drawn by ultralytics
            color = (0, 0, 255) if state == "fall" else (0, 200, 0)
            label = "FALL DETECTED" if state == "fall" else "monitoring"
            cv2.putText(frame, label, (16, 40), cv2.FONT_HERSHEY_SIMPLEX,
                        1.0, color, 2, cv2.LINE_AA)
            cv2.imshow("Fall detection (YOLOv8-pose @ GPU)", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                return True
    return False


def main():
    device = 0 if _HAS_CUDA else "cpu"
    print(f"[AI] loading {YOLO_MODEL} on "
          f"{'GPU (cuda:0)' if _HAS_CUDA else 'CPU'}")
    model = YOLO(YOLO_MODEL)
    reporter = Reporter()
    src = _source()
    is_file = (isinstance(src, str)
               and src.lower().rsplit(".", 1)[-1] in ("mp4", "avi", "mov", "mkv", "m4v"))
    print(f"[AI] camera source : {src}")
    print(f"[AI] dashboard     : {DASHBOARD_URL}/api/fall")
    print("[AI] running -- press 'q' in the preview window to quit")

    # A live camera/RTSP/MJPEG stream can hiccup (Wi-Fi, phone sleeping); a real
    # monitoring station must reconnect rather than die. A finite video file just
    # plays once.
    while True:
        try:
            if _run_once(model, reporter, src, device):
                break
        except Exception as e:
            print("[AI] stream error:", e)
        if is_file:
            break
        print("[AI] stream dropped -- reconnecting in 2s "
              "(keep the iPhone app open + screen unlocked)")
        time.sleep(2)

    if SHOW_WINDOW:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
