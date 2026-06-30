"""
Database layer (Task#3) -- MariaDB / MySQL access via PyMySQL.

A new short-lived connection is opened per call. The data rate is low
(~1 reading/second) and this keeps the code thread-safe across the serial
reader, AI thread and the Flask web app without a connection pool.
"""
import json
import pymysql
import config

# Columns the web UI is allowed to query/aggregate (prevents SQL injection
# when the metric name comes from the browser).
METRIC_COLUMNS = {
    "temp": "temp",
    "humidity": "humidity",
    "sound": "sound",
}

_DEFAULT_SETTINGS = {
    "rules_enabled": "1",
    "fall_detection": "1",
    "fan_auto": "1",
    "temp_high": "37.5",     # fever threshold (deg C)
    "temp_low": "10",
    "hum_high": "80",
    "sound_high": "700",     # KY-037 raw ADC threshold (0-4095)
}

_SEED_PATIENTS = [
    ("A1B2C3D4", "Nguyen Van A", "Room 101"),
    ("11223344", "Tran Thi B", "Room 102"),
]


def _connect(with_db=True):
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASS,
        database=config.DB_NAME if with_db else None,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


# --------------------------------------------------------------------------- #
#  Schema setup
# --------------------------------------------------------------------------- #
def init_db():
    """Create the database, tables and seed defaults if they do not exist."""
    conn = _connect(with_db=False)
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS {config.DB_NAME} "
            "CHARACTER SET utf8mb4"
        )
        cur.execute(f"USE {config.DB_NAME}")
        cur.execute(
            """CREATE TABLE IF NOT EXISTS readings (
                   id INT AUTO_INCREMENT PRIMARY KEY,
                   ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   temp FLOAT, humidity FLOAT, sound INT,
                   patient_uid VARCHAR(32) NULL
               )"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS events (
                   id INT AUTO_INCREMENT PRIMARY KEY,
                   ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   type VARCHAR(32), severity VARCHAR(16),
                   message VARCHAR(255)
               )"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS settings (
                   skey VARCHAR(64) PRIMARY KEY,
                   svalue VARCHAR(255)
               )"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS patients (
                   uid VARCHAR(32) PRIMARY KEY,
                   name VARCHAR(64), note VARCHAR(255)
               )"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS commands (
                   id INT AUTO_INCREMENT PRIMARY KEY,
                   ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   payload VARCHAR(255), consumed TINYINT DEFAULT 0
               )"""
        )
        for k, v in _DEFAULT_SETTINGS.items():
            cur.execute(
                "INSERT IGNORE INTO settings (skey, svalue) VALUES (%s, %s)",
                (k, v),
            )
        for uid, name, note in _SEED_PATIENTS:
            cur.execute(
                "INSERT IGNORE INTO patients (uid, name, note) VALUES (%s,%s,%s)",
                (uid, name, note),
            )
    conn.close()


# --------------------------------------------------------------------------- #
#  Writes
# --------------------------------------------------------------------------- #
def insert_reading(temp, humidity, sound, uid=None):
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO readings (temp, humidity, sound, patient_uid) "
            "VALUES (%s,%s,%s,%s)",
            (temp, humidity, sound, uid),
        )
    conn.close()


def insert_event(etype, severity, message):
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (type, severity, message) VALUES (%s,%s,%s)",
            (etype, severity, message),
        )
    conn.close()


def add_command(payload: dict):
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO commands (payload) VALUES (%s)", (json.dumps(payload),)
        )
    conn.close()


def fetch_unconsumed_commands():
    """Return pending UI commands as dicts and mark them consumed."""
    conn = _connect()
    out = []
    with conn.cursor() as cur:
        cur.execute("SELECT id, payload FROM commands WHERE consumed=0 ORDER BY id")
        rows = cur.fetchall()
        for r in rows:
            try:
                out.append(json.loads(r["payload"]))
            except Exception:
                pass
            cur.execute("UPDATE commands SET consumed=1 WHERE id=%s", (r["id"],))
    conn.close()
    return out


def update_settings(updates: dict):
    conn = _connect()
    with conn.cursor() as cur:
        for k, v in updates.items():
            cur.execute(
                "INSERT INTO settings (skey, svalue) VALUES (%s,%s) "
                "ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)",
                (k, str(v)),
            )
    conn.close()


# --------------------------------------------------------------------------- #
#  Reads
# --------------------------------------------------------------------------- #
def get_settings():
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT skey, svalue FROM settings")
        rows = cur.fetchall()
    conn.close()
    return {r["skey"]: r["svalue"] for r in rows}


def get_patient(uid):
    if not uid:
        return None
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT uid, name, note FROM patients WHERE uid=%s", (uid,))
        row = cur.fetchone()
    conn.close()
    return row


def latest_reading():
    conn = _connect()
    with conn.cursor() as cur:
        # No query args here, so PyMySQL does NOT turn %% into % -- use a single
        # % (otherwise MySQL receives '%%Y...' and returns the literal "%Y-...").
        cur.execute(
            "SELECT id, DATE_FORMAT(ts,'%Y-%m-%d %H:%i:%s') AS ts, "
            "temp, humidity, sound, patient_uid "
            "FROM readings ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
    conn.close()
    return row


def history(metric, n=60):
    col = METRIC_COLUMNS.get(metric, "temp")
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DATE_FORMAT(ts,'%%H:%%i:%%s') AS ts, {col} AS value "
            "FROM readings ORDER BY id DESC LIMIT %s",
            (int(n),),
        )
        rows = cur.fetchall()
    conn.close()
    return list(reversed(rows))


def stats(metric, minutes=60):
    col = METRIC_COLUMNS.get(metric, "temp")
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT AVG({col}) AS mean, MIN({col}) AS min, "
            f"MAX({col}) AS max, COUNT(*) AS count "
            "FROM readings WHERE ts >= NOW() - INTERVAL %s MINUTE",
            (int(minutes),),
        )
        row = cur.fetchone()
    conn.close()
    return row


def recent_events(n=10):
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DATE_FORMAT(ts,'%%Y-%%m-%%d %%H:%%i:%%s') AS ts, "
            "type, severity, message FROM events ORDER BY id DESC LIMIT %s",
            (int(n),),
        )
        rows = cur.fetchall()
    conn.close()
    return rows


def seconds_since_last_fall():
    """Seconds since the most recent fall event, or None if there has never been
    one. Computed with the DB clock so the banner does not depend on the
    browser's timezone. Lets the UI auto-clear the alert instead of latching on
    old rows still sitting in recent_events()."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TIMESTAMPDIFF(SECOND, MAX(ts), NOW()) AS age "
            "FROM events WHERE type='fall'"
        )
        row = cur.fetchone()
    conn.close()
    return row["age"] if row else None
