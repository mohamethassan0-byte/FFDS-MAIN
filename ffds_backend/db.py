"""
FFDS — SQLite data layer.
Pure standard library (sqlite3). No external dependencies.
"""
import sqlite3
import os
import time
import json

DB_PATH = os.path.join(os.path.dirname(__file__), "ffds.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS nodes (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        lat REAL, lon REAL,
        kind TEXT NOT NULL  -- 'ground_sensor' | 'camera'
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        node_id TEXT NOT NULL,
        ts REAL NOT NULL,
        ground_temp REAL,
        ground_humidity REAL,
        co2 REAL,
        water_level REAL,
        ground_movement REAL,
        source TEXT DEFAULT 'simulated'  -- 'simulated' | 'hardware'
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_readings_node_ts ON readings(node_id, ts)")

    c.execute("""
    CREATE TABLE IF NOT EXISTS weather_daily (
        date TEXT PRIMARY KEY,
        temp REAL, rh REAL, wind_kmh REAL, rain_24h_mm REAL,
        pressure_hpa REAL, cloud_pct REAL, wind_dir_deg REAL
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS fwi_daily (
        date TEXT PRIMARY KEY,
        ffmc REAL, dmc REAL, dc REAL, isi REAL, bui REAL, fwi REAL,
        risk_level TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        node_id TEXT,
        type TEXT NOT NULL,
        message TEXT NOT NULL,
        severity TEXT NOT NULL,  -- 'info' | 'warning' | 'critical'
        acknowledged INTEGER DEFAULT 0
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS camera_detections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT NOT NULL,
        ts REAL NOT NULL,
        label TEXT NOT NULL,      -- 'CLEAR' | 'SMOKE_SUSPECTED' | 'FLAME_SUSPECTED'
        confidence REAL NOT NULL,
        simulated INTEGER DEFAULT 1
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        type TEXT NOT NULL,
        message TEXT NOT NULL
    )""")

    conn.commit()

    # Seed nodes if empty
    existing = c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    if existing == 0:
        nodes = [
            ("N01", "NODE-01", 35.6474, -83.5397, "ground_sensor"),   # near Look Rock
            ("N02", "NODE-02", 35.5836, -83.0928, "ground_sensor"),   # near Purchase Knob
            ("CH01", "CH-01", 35.6474, -83.5397, "camera"),           # Look Rock
            ("CH02", "CH-02", 35.5836, -83.0928, "camera"),           # Purchase Knob
            ("CH03", "CH-03", 35.6117, -83.4895, "camera"),           # Newfound Gap (planned)
            ("CH04", "CH-04", 35.6367, -83.3593, "camera"),           # Twin Creeks (planned)
        ]
        c.executemany("INSERT INTO nodes (id, name, lat, lon, kind) VALUES (?,?,?,?,?)", nodes)
        conn.commit()

    conn.close()


def insert_reading(node_id, ground_temp, ground_humidity, co2, water_level, ground_movement, source="simulated", ts=None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO readings (node_id, ts, ground_temp, ground_humidity, co2, water_level, ground_movement, source) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (node_id, ts or time.time(), ground_temp, ground_humidity, co2, water_level, ground_movement, source)
    )
    conn.commit()
    conn.close()


def latest_readings():
    conn = get_conn()
    rows = conn.execute("""
        SELECT r.* FROM readings r
        INNER JOIN (
            SELECT node_id, MAX(ts) as max_ts FROM readings GROUP BY node_id
        ) latest ON r.node_id = latest.node_id AND r.ts = latest.max_ts
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def history(node_id, since_ts):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM readings WHERE node_id=? AND ts>=? ORDER BY ts ASC",
        (node_id, since_ts)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def recent_snapshot_log(limit=25):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM readings ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_alert(node_id, type_, message, severity):
    conn = get_conn()
    conn.execute(
        "INSERT INTO alerts (ts, node_id, type, message, severity) VALUES (?,?,?,?,?)",
        (time.time(), node_id, type_, message, severity)
    )
    conn.commit()
    conn.close()


def recent_alerts(limit=20, unacknowledged_only=False):
    conn = get_conn()
    q = "SELECT * FROM alerts"
    if unacknowledged_only:
        q += " WHERE acknowledged=0"
    q += " ORDER BY ts DESC LIMIT ?"
    rows = conn.execute(q, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def acknowledge_alert(alert_id):
    conn = get_conn()
    conn.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()


def get_nodes(kind=None):
    conn = get_conn()
    if kind:
        rows = conn.execute("SELECT * FROM nodes WHERE kind=?", (kind,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM nodes").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_camera_detection(camera_id, label, confidence, simulated=1):
    conn = get_conn()
    conn.execute(
        "INSERT INTO camera_detections (camera_id, ts, label, confidence, simulated) VALUES (?,?,?,?,?)",
        (camera_id, time.time(), label, confidence, simulated)
    )
    conn.commit()
    conn.close()


def latest_camera_detections():
    conn = get_conn()
    rows = conn.execute("""
        SELECT d.* FROM camera_detections d
        INNER JOIN (
            SELECT camera_id, MAX(ts) as max_ts FROM camera_detections GROUP BY camera_id
        ) latest ON d.camera_id = latest.camera_id AND d.ts = latest.max_ts
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_weather_daily(date, temp, rh, wind_kmh, rain_24h_mm, pressure_hpa=None, cloud_pct=None, wind_dir_deg=None):
    conn = get_conn()
    conn.execute("""
        INSERT INTO weather_daily (date, temp, rh, wind_kmh, rain_24h_mm, pressure_hpa, cloud_pct, wind_dir_deg)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET temp=excluded.temp, rh=excluded.rh,
            wind_kmh=excluded.wind_kmh, rain_24h_mm=excluded.rain_24h_mm,
            pressure_hpa=excluded.pressure_hpa, cloud_pct=excluded.cloud_pct, wind_dir_deg=excluded.wind_dir_deg
    """, (date, temp, rh, wind_kmh, rain_24h_mm, pressure_hpa, cloud_pct, wind_dir_deg))
    conn.commit()
    conn.close()


def get_weather_daily(date):
    conn = get_conn()
    row = conn.execute("SELECT * FROM weather_daily WHERE date=?", (date,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_fwi_daily(date, ffmc, dmc, dc, isi, bui, fwi, risk_level):
    conn = get_conn()
    conn.execute("""
        INSERT INTO fwi_daily (date, ffmc, dmc, dc, isi, bui, fwi, risk_level) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET ffmc=excluded.ffmc, dmc=excluded.dmc, dc=excluded.dc,
            isi=excluded.isi, bui=excluded.bui, fwi=excluded.fwi, risk_level=excluded.risk_level
    """, (date, ffmc, dmc, dc, isi, bui, fwi, risk_level))
    conn.commit()
    conn.close()


def get_fwi_daily(date):
    conn = get_conn()
    row = conn.execute("SELECT * FROM fwi_daily WHERE date=?", (date,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_fwi():
    conn = get_conn()
    row = conn.execute("SELECT * FROM fwi_daily ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def get_fwi_history(days=7):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM fwi_daily ORDER BY date DESC LIMIT ?", (days,)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def insert_event(type_, message):
    conn = get_conn()
    conn.execute("INSERT INTO events (ts, type, message) VALUES (?,?,?)", (time.time(), type_, message))
    conn.commit()
    conn.close()


def recent_events(limit=20):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
