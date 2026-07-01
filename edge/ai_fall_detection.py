"""
AI module -- fall detection from the iPhone camera stream (the project's
"AI on the edge" component, running on the PC's GPU via WSL).

Two backends, chosen automatically:
  1. MediaPipe Pose  (preferred) -- tracks body landmarks and flags a fall when
     the torso becomes horizontal and the hips drop into the lower frame.
  2. OpenCV HOG fallback         -- if MediaPipe isn't available, detects a
     person and flags a fall when the bounding box is wider than it is tall.

A fall must persist for ~1.2 s before it is confirmed, which suppresses false
positives from bending down or sitting.
"""
import math
import threading
import time

import config

try:
    import cv2
except ImportError:
    cv2 = None


class FallDetector:
    def __init__(self, source=None):
        self.source = source if source is not None else config.CAMERA_SOURCE
        self.status = "starting"      # starting|monitoring|fall|no_camera|disabled
        self.confidence = 0.0
        self.last_fall_ts = 0.0
        self._running = False
        self._on_fall = None
        self._fall_since = None
        self._pose = None
        self._hog = None

    # ----------------------------------------------------------------- public
    def start(self, on_fall=None):
        self._on_fall = on_fall
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def state(self):
        return {"status": self.status, "confidence": round(self.confidence, 2)}

    # --------------------------------------------------------------- internal
    def _open(self):
        src = self.source
        if isinstance(src, str) and src.isdigit():
            src = int(src)
        return cv2.VideoCapture(src)

    def _init_pose(self):
        try:
            import mediapipe as mp
            self._pose = mp.solutions.pose.Pose(
                model_complexity=0,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            print("[AI] using MediaPipe Pose backend")
            return True
        except Exception as e:
            print("[AI] MediaPipe unavailable -> OpenCV HOG fallback:", e)
            self._hog = cv2.HOGDescriptor()
            self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            return False

    def _loop(self):
        if cv2 is None:
            print("[AI] OpenCV not installed; fall detection disabled.")
            self.status = "disabled"
            return
        cap = self._open()
        if not cap or not cap.isOpened():
            print(f"[AI] cannot open camera source: {self.source}")
            self.status = "no_camera"
            return

        use_pose = self._init_pose()
        self.status = "monitoring"
        while self._running:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.2)
                continue
            fall, conf = (self._detect_pose(frame) if use_pose
                          else self._detect_hog(frame))
            self.confidence = conf
            self._update(fall)
            time.sleep(0.03)
        cap.release()

    def _detect_pose(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self._pose.process(rgb)
        if not res.pose_landmarks:
            return False, 0.0
        lm = res.pose_landmarks.landmark
        sh = ((lm[11].x + lm[12].x) / 2, (lm[11].y + lm[12].y) / 2)  # shoulders
        hp = ((lm[23].x + lm[24].x) / 2, (lm[23].y + lm[24].y) / 2)  # hips
        dx, dy = hp[0] - sh[0], hp[1] - sh[1]
        # angle of the torso away from the vertical axis (0=upright, 90=lying)
        angle = math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6))
        horizontal = angle > 45
        low = hp[1] > 0.6           # hips in the lower 40% of the frame
        return (horizontal and low), min(1.0, angle / 90.0)

    def _detect_hog(self, frame):
        small = cv2.resize(frame, (320, 240))
        rects, _ = self._hog.detectMultiScale(small, winStride=(8, 8))
        if len(rects) == 0:
            return False, 0.0
        x, y, w, h = max(rects, key=lambda r: r[2] * r[3])
        ratio = w / float(h + 1e-6)
        return (ratio > 1.2), min(1.0, ratio / 2.0)

    def _update(self, fall):
        now = time.time()
        if fall:
            if self._fall_since is None:
                self._fall_since = now
            elif now - self._fall_since >= 1.2 and self.status != "fall":
                self.status = "fall"
                self.last_fall_ts = now
                if self._on_fall:
                    self._on_fall(self.confidence)
        else:
            self._fall_since = None
            if self.status == "fall" and now - self.last_fall_ts > 5:
                self.status = "monitoring"
