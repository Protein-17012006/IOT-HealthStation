#!/usr/bin/env bash
# Launch the GPU YOLOv8-pose fall detector inside WSL (RTX 4060).
#
# Usage (run from a WSL terminal, in the edge/ folder):
#   ./run_fall_detector.sh /mnt/c/Users/huyho/OneDrive/Desktop/IOT/clip.mp4   # a recorded video
#   ./run_fall_detector.sh "http://admin:170106@192.168.100.236:8081/video"   # iPhone MJPEG stream
#   ./run_fall_detector.sh rtsp://<iphone-ip>:8554/live                       # iPhone RTSP stream
#   ./run_fall_detector.sh                                                    # default source (0)
#
# The annotated video (skeleton + boxes + FALL banner) now shows up INSIDE the web
# dashboard's "Live patient feed" panel -- no separate window. The Windows dashboard
# + MariaDB must be running first (edge/webapp/app.py).
#
# If you appear lying down while actually sitting upright, the camera is rotated --
# set ROTATE so you look upright on the dashboard overlay:
#   ROTATE=90  ./run_fall_detector.sh "http://...:8081/video"    # try 90, 180, or 270
#
# Extra knobs:
#   SHOW_WINDOW=1   also open a local OpenCV preview window (off by default)
#   FALL_SECONDS=2  seconds a fall must persist before alerting (default 1.5)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV=/root/iot-ai/.venv/bin/python
HOST_IP="$(ip route show default | awk '{print $3}')"   # Windows host as seen from WSL

export CAMERA_SOURCE="${1:-0}"
export DASHBOARD_URL="${DASHBOARD_URL:-http://${HOST_IP}:5000}"
export ROTATE="${ROTATE:-0}"
export SHOW_WINDOW="${SHOW_WINDOW:-0}"

echo "camera : $CAMERA_SOURCE"
echo "rotate : $ROTATE deg"
echo "report : $DASHBOARD_URL/api/fall"
echo "video  : $DASHBOARD_URL/api/ai_camera  (shown in the dashboard)"
exec "$VENV" "$DIR/fall_detector_yolo.py"
