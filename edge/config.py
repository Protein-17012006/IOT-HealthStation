"""
Central configuration for the edge server (Jetson Nano).
All values can be overridden with environment variables so you don't have to
edit code when moving between your laptop (dev) and the Jetson (deployment).
"""
import os


def _env(name, default):
    return os.environ.get(name, default)


# ---- Serial link to the ESP32 ----------------------------------------------
# Windows example: COM3   |   Linux/Jetson example: /dev/ttyUSB0
SERIAL_PORT = _env("SERIAL_PORT", "COM3")
SERIAL_BAUD = int(_env("SERIAL_BAUD", "115200"))
# Set SIM=1 to generate fake sensor data (no ESP32 needed) for development.
SIMULATE_SERIAL = _env("SIM", "0") == "1"

# ---- MariaDB / MySQL --------------------------------------------------------
DB_HOST = _env("DB_HOST", "localhost")
DB_PORT = int(_env("DB_PORT", "3306"))
DB_USER = _env("DB_USER", "root")
# The real password is NOT committed -- set the DB_PASS environment variable
# (Windows:  setx DB_PASS "yourpassword"  | Linux:  export DB_PASS=yourpassword).
DB_PASS = _env("DB_PASS", "")
DB_NAME = _env("DB_NAME", "health_station")

# ---- AI / camera ------------------------------------------------------------
# iPhone running an IP-camera app:  rtsp://192.168.1.50:8554/live
# or a local webcam for testing:    0
CAMERA_SOURCE = _env("CAMERA_SOURCE", "0")

# The GPU fall-detector runs as a separate process in WSL (fall_detector_yolo.py)
# and reports falls over HTTP (POST /api/fall), so the in-process MediaPipe/HOG
# detector in main.py is OFF by default. Set LOCAL_AI=1 to run the built-in
# detector on this machine instead (e.g. a single-box laptop demo with a webcam).
LOCAL_AI = _env("LOCAL_AI", "0") == "1"

# ---- Web UI -----------------------------------------------------------------
WEB_HOST = _env("WEB_HOST", "0.0.0.0")
WEB_PORT = int(_env("WEB_PORT", "5000"))
