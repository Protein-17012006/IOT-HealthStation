#!/usr/bin/env bash
# Launch the GPU YOLOv8-pose fall detector inside WSL (RTX 4060).
#
# Usage (run from a WSL terminal, in the edge/ folder):
#   ./run_fall_detector.sh /mnt/c/Users/huyho/OneDrive/Desktop/IOT/clip.mp4   # a recorded video
#   ./run_fall_detector.sh rtsp://<iphone-ip>:8554/live                       # the iPhone live stream
#   ./run_fall_detector.sh                                                    # default source (0)
#
# Press 'q' in the preview window to quit. The Windows dashboard + MariaDB must
# be running first (edge/webapp/app.py).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV=/root/iot-ai/.venv/bin/python
HOST_IP="$(ip route show default | awk '{print $3}')"   # Windows host as seen from WSL

export CAMERA_SOURCE="${1:-0}"
export DASHBOARD_URL="${DASHBOARD_URL:-http://${HOST_IP}:5000}"
export SHOW_WINDOW="${SHOW_WINDOW:-1}"

echo "camera : $CAMERA_SOURCE"
echo "report : $DASHBOARD_URL/api/fall"
exec "$VENV" "$DIR/fall_detector_yolo.py"
