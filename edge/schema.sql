-- ===========================================================================
--  Smart Elderly Monitoring Station -- database schema (Task#3)
--  Run once on the edge PC:  sudo mysql < schema.sql
--  (db.init_db() also creates everything automatically, this is for reference
--   and for the project report appendix.)
-- ===========================================================================

CREATE DATABASE IF NOT EXISTS health_station CHARACTER SET utf8mb4;
USE health_station;

-- Time-series sensor data from the physical layer ---------------------------
CREATE TABLE IF NOT EXISTS readings (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    ts       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    temp     FLOAT,
    humidity FLOAT,
    sound    INT
);

-- Alerts / rule hits / AI events --------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    ts       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    type     VARCHAR(32),
    severity VARCHAR(16),
    message  VARCHAR(255)
);

-- Editable thresholds / rule toggles (changed from the Web UI, Task#5) -------
CREATE TABLE IF NOT EXISTS settings (
    skey   VARCHAR(64) PRIMARY KEY,
    svalue VARCHAR(255)
);

-- Manual actuator commands queued by the Web UI ------------------------------
CREATE TABLE IF NOT EXISTS commands (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    ts       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    payload  VARCHAR(255),
    consumed TINYINT DEFAULT 0
);

-- Default settings -----------------------------------------------------------
INSERT IGNORE INTO settings (skey, svalue) VALUES
    ('rules_enabled', '1'),
    ('fall_detection', '1'),
    ('fan_auto', '1'),
    ('temp_high', '37.5'),
    ('temp_low', '10'),
    ('hum_high', '80'),
    ('sound_high', '700');

-- Application user (run as root once, then use this account in config.py) ----
-- CREATE USER IF NOT EXISTS 'iot'@'localhost' IDENTIFIED BY 'iotpass';
-- GRANT ALL PRIVILEGES ON health_station.* TO 'iot'@'localhost';
-- FLUSH PRIVILEGES;
