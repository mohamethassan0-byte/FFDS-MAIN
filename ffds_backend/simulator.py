"""
Sensor simulator — stands in for real hardware until Arduino/Raspberry Pi
nodes are deployed.

IMPORTANT: this writes to the exact same `readings` table, via the exact
same insert_reading() function, that the real hardware ingest endpoint
(POST /api/ingest) uses. When real sensors arrive, you turn this simulator
off (SIMULATOR_ENABLED = False in app.py) and point the hardware's HTTP
client at /api/ingest instead — no other code changes needed.
"""
import random
import threading
import time
import math

import db

# Realistic forest-floor baselines for Great Smoky Mountains NP in summer
# (humid subtropical climate, mixed hardwood/conifer forest)
NODE_BASELINES = {
    "N01": {"temp": 23.0, "hum": 72.0, "co2": 420.0, "water": 380.0},   # Look Rock area
    "N02": {"temp": 20.5, "hum": 80.0, "co2": 460.0, "water": 610.0},   # Purchase Knob (higher elev, cooler/wetter)
}

_state = {node: dict(vals) for node, vals in NODE_BASELINES.items()}
_ground_movement = {"N01": 0.0, "N02": 0.0}

_co2_sensor_offline_until = {"N01": 0, "N02": 0}

_running = False
_thread = None


def _drift(value, target, max_step, floor=None, ceil=None):
    """Random-walk a value gently toward a target, bounded."""
    step = random.uniform(-max_step, max_step) + (target - value) * 0.03
    value += step
    if floor is not None:
        value = max(floor, value)
    if ceil is not None:
        value = min(ceil, value)
    return value


def _tick():
    now = time.time()
    for node_id, baseline in NODE_BASELINES.items():
        s = _state[node_id]

        # Diurnal cycle nudges target temp/humidity slightly by time of day
        hour = time.localtime(now).tm_hour
        diurnal_temp = math.sin((hour - 6) / 24 * 2 * math.pi) * 1.5
        diurnal_hum = -diurnal_temp * 2.0

        s["temp"] = _drift(s["temp"], baseline["temp"] + diurnal_temp, 0.15, 10, 34)
        s["hum"] = _drift(s["hum"], baseline["hum"] + diurnal_hum, 0.6, 30, 95)
        s["co2"] = _drift(s["co2"], baseline["co2"], 12, 180, 1800)
        s["water"] = _drift(s["water"], baseline["water"], 3.0, 50, 1200)
        _ground_movement[node_id] = _drift(_ground_movement[node_id], 0.0, 0.02, -2, 2)

        # Rare simulated CO2 sensor dropout (mirrors the kind of real fault we
        # flagged in the original dashboard analysis)
        co2_val = s["co2"]
        if now < _co2_sensor_offline_until[node_id]:
            co2_val = None
        elif random.random() < 0.0008:  # ~0.08% chance per tick
            _co2_sensor_offline_until[node_id] = now + random.uniform(300, 1800)
            db.insert_alert(node_id, "sensor_offline",
                             f"{node_id} CO2 probe stopped responding — check wiring/power", "warning")

        db.insert_reading(
            node_id,
            ground_temp=round(s["temp"], 1),
            ground_humidity=round(s["hum"], 1),
            co2=round(co2_val, 1) if co2_val is not None else None,
            water_level=round(s["water"], 1),
            ground_movement=round(_ground_movement[node_id], 3),
            source="simulated",
        )

        # Sanity-checked alerting — thresholds only fire on plausible real values,
        # never on the 0/0 sensor-fault artifacts the original dashboard had.
        if s["hum"] < 35:
            db.insert_alert(node_id, "low_humidity", f"{node_id} ground humidity low: {s['hum']:.1f}%", "warning")
        if s["water"] < 100:
            db.insert_alert(node_id, "low_water", f"{node_id} water level low: {s['water']:.0f}mm", "warning")
        if s["temp"] > 32:
            db.insert_alert(node_id, "high_temp", f"{node_id} ground temp elevated: {s['temp']:.1f}\u00b0C", "warning")

    # Simulated camera AI detections — clearly flagged simulated=1 everywhere downstream
    for cam_id in ["CH01", "CH02", "CH03", "CH04"]:
        roll = random.random()
        if roll < 0.0015:
            label, conf = "SMOKE_SUSPECTED", round(random.uniform(55, 82), 1)
            db.insert_alert(cam_id, "camera_detection", f"{cam_id} flagged possible smoke (simulated CV, {conf}% conf)", "critical")
        else:
            label, conf = "CLEAR", round(random.uniform(96.5, 99.8), 1)
        db.insert_camera_detection(cam_id, label, conf, simulated=1)


def _loop(interval_seconds):
    global _running
    while _running:
        try:
            _tick()
        except Exception as e:
            print(f"[simulator] tick error: {e}")
        time.sleep(interval_seconds)


def start(interval_seconds=15):
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_loop, args=(interval_seconds,), daemon=True)
    _thread.start()
    print(f"[simulator] started (interval={interval_seconds}s) — remove/disable once real hardware is connected")


def stop():
    global _running
    _running = False
