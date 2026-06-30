"""
Edge analytics -- the conditional rule engine (Task#4).

Pure function: given the latest reading and the current settings (which the
user can edit from the Web UI), decide what the actuators should do and which
events to log. Keeping it pure makes it trivial to unit-test.
"""


def _as_bool(v):
    return str(v) == "1"


def evaluate(reading, settings):
    """
    Returns (command, events)
      command : dict for the ESP32, e.g. {"fan":1,"led":"red","lcd":"..."}
      events  : list of (type, severity, message) tuples to persist
    """
    if not _as_bool(settings.get("rules_enabled", "1")):
        return {}, []

    temp = float(reading.get("temp") or 0)
    sound = float(reading.get("sound") or 0)

    temp_high = float(settings.get("temp_high", 20.5))
    sound_high = float(settings.get("sound_high", 700))
    fan_auto = _as_bool(settings.get("fan_auto", "1"))

    cmd, events = {}, []
    fever = temp >= temp_high
    loud = sound >= sound_high

    if fever:
        if fan_auto:
            cmd["fan"] = 1
        cmd["led"] = "red"
        cmd["lcd"] = f"FEVER {temp:.1f}C FanON"
        events.append(
            ("fever", "warning", f"High temperature {temp:.1f}C >= {temp_high}C")
        )
    elif loud:
        cmd["led"] = "red"
        cmd["lcd"] = f"Noise alert {int(sound)}"
        events.append(
            ("noise", "info", f"Loud sound {int(sound)} >= {int(sound_high)}")
        )
    else:
        if fan_auto:
            cmd["fan"] = 0
        cmd["led"] = "green"
        cmd["lcd"] = f"OK T:{temp:.1f} S:{int(sound)}"

    return cmd, events
