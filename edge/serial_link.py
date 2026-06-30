"""
Serial link to the ESP32 (Task#2).

Reads newline-delimited JSON from the microcontroller into a thread-safe queue
and sends JSON command lines back. Set SIM=1 (config.SIMULATE_SERIAL) to run a
built-in data generator instead of opening a real port -- handy for developing
the database / rules / web UI with no hardware attached.
"""
import json
import math
import queue
import random
import threading
import time

import config

try:
    import serial  # pyserial
except ImportError:
    serial = None


class SerialLink:
    def __init__(self):
        self.rx = queue.Queue()
        self._ser = None
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        self._running = True
        if config.SIMULATE_SERIAL:
            print("[serial] SIMULATION mode -- generating fake sensor data")
            threading.Thread(target=self._sim_loop, daemon=True).start()
            return
        if serial is None:
            raise RuntimeError("pyserial not installed; run `pip install pyserial`")
        self._ser = serial.Serial(config.SERIAL_PORT, config.SERIAL_BAUD, timeout=1)
        time.sleep(2)  # let the ESP32 reset after the port opens
        print(f"[serial] connected on {config.SERIAL_PORT} @ {config.SERIAL_BAUD}")
        threading.Thread(target=self._read_loop, daemon=True).start()

    # -- real port -----------------------------------------------------------
    def _read_loop(self):
        while self._running:
            try:
                line = self._ser.readline().decode("utf-8", "ignore").strip()
                if not line:
                    continue
                self.rx.put(json.loads(line))
            except Exception:
                continue  # ignore malformed / partial lines

    # -- simulator -----------------------------------------------------------
    def _sim_loop(self):
        t0 = time.time()
        cards = ["A1B2C3D4", "11223344", None, None, None]
        while self._running:
            el = time.time() - t0
            temp = 36.6 + 1.6 * math.sin(el / 25) + random.uniform(-0.2, 0.2)
            hum = 55 + 10 * math.sin(el / 40) + random.uniform(-1, 1)
            sound = int(380 + 260 * abs(math.sin(el / 9)) + random.uniform(0, 90))
            msg = {"type": "reading", "temp": round(temp, 1),
                   "hum": round(hum, 1), "sound": sound}
            if random.random() < 0.04:
                uid = random.choice(cards)
                if uid:
                    msg["rfid"] = uid
            self.rx.put(msg)
            time.sleep(1)

    # -- public --------------------------------------------------------------
    def send_command(self, cmd: dict):
        line = json.dumps(cmd) + "\n"
        if config.SIMULATE_SERIAL or self._ser is None:
            print("[serial->ESP32]", line.strip())
            return
        with self._lock:
            self._ser.write(line.encode())

    def get_nowait(self):
        try:
            return self.rx.get_nowait()
        except queue.Empty:
            return None

    def stop(self):
        self._running = False
        if self._ser:
            self._ser.close()
