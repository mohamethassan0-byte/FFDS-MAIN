"""
Server-side weather fetch + daily FWI update.

Runs on the backend (not the browser) because the FWI system needs
persistent day-to-day state (yesterday's FFMC/DMC/DC) that a stateless
static page can't hold. Uses urllib only — no third-party HTTP client
required.
"""
import json
import threading
import time
import urllib.request
from datetime import datetime, timezone

import db
import fwi

LAT, LON = 35.6532, -83.5070  # Great Smoky Mountains NP (Gatlinburg, TN area)
OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,surface_pressure,cloud_cover,wind_direction_10m"
    "&daily=precipitation_sum"
    "&timezone=America%2FNew_York"
)


def fetch_current_weather():
    req = urllib.request.Request(OPEN_METEO_URL, headers={"User-Agent": "FFDS-Backend/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    cur = data["current"]
    rain_today = data["daily"]["precipitation_sum"][0] if data.get("daily", {}).get("precipitation_sum") else 0.0
    return {
        "temp": cur["temperature_2m"],
        "rh": cur["relative_humidity_2m"],
        "wind_kmh": cur["wind_speed_10m"],
        "rain_24h_mm": rain_today or 0.0,
        "pressure_hpa": cur.get("surface_pressure"),
        "cloud_pct": cur.get("cloud_cover"),
        "wind_dir_deg": cur.get("wind_direction_10m"),
    }


def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def yesterday_codes(today):
    """Find the most recent prior day's FWI codes, or system startup defaults."""
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM fwi_daily WHERE date < ? ORDER BY date DESC LIMIT 1", (today,)
    ).fetchone()
    conn.close()
    if row:
        return {"ffmc": row["ffmc"], "dmc": row["dmc"], "dc": row["dc"]}
    return {"ffmc": fwi.STARTUP_FFMC, "dmc": fwi.STARTUP_DMC, "dc": fwi.STARTUP_DC}


def update_once():
    try:
        wx = fetch_current_weather()
    except Exception as e:
        print(f"[weather_fwi] fetch failed: {e}")
        db.insert_event("weather_fetch_error", str(e))
        return None

    date = today_str()
    db.upsert_weather_daily(date, wx["temp"], wx["rh"], wx["wind_kmh"], wx["rain_24h_mm"],
                             wx.get("pressure_hpa"), wx.get("cloud_pct"), wx.get("wind_dir_deg"))

    prev = yesterday_codes(date)
    month = datetime.now(timezone.utc).month
    result = fwi.compute_daily(prev, wx["temp"], wx["rh"], wx["wind_kmh"], wx["rain_24h_mm"], month=month)
    db.upsert_fwi_daily(date, result["ffmc"], result["dmc"], result["dc"],
                         result["isi"], result["bui"], result["fwi"], result["risk_level"])
    print(f"[weather_fwi] {date}: FWI={result['fwi']} ({result['risk_level']}) "
          f"T={wx['temp']}C RH={wx['rh']}% wind={wx['wind_kmh']}km/h rain={wx['rain_24h_mm']}mm")
    return {**wx, **result, "date": date}


def _loop(interval_seconds):
    while True:
        update_once()
        time.sleep(interval_seconds)


def start(interval_seconds=900):
    """Update immediately, then every `interval_seconds` (default 15 min).
    Recomputing repeatedly within the same UTC day just refreshes today's
    row with the latest weather — the FWI carries state day-to-day via
    yesterday_codes(), not by re-running old days."""
    t = threading.Thread(target=_loop, args=(interval_seconds,), daemon=True)
    t.start()
    print(f"[weather_fwi] started (interval={interval_seconds}s)")
