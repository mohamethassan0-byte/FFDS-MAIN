# FFDS Backend

Real backend for the Forest Fire Detection System dashboard. Pure Python
standard library — **no `pip install` required**.

## Run it

```
cd ffds_backend
python3 app.py
```

You should see:

```
[weather_fwi] started (interval=900s)
[simulator] started (interval=15s) — remove/disable once real hardware is connected
[app] FFDS backend running at http://localhost:8420
```

Then open `ffds-pro.html` in your browser (or double-click it). It talks to
`http://localhost:8420` automatically. If the backend isn't running, the
dashboard shows **"BACKEND OFFLINE"** instead of pretending everything's fine.

## What's real vs. simulated right now

| Piece | Status |
|---|---|
| Weather (temp/humidity/wind/rain/pressure) | **Real** — fetched server-side from Open-Meteo |
| Fire Weather Index (FFMC/DMC/DC/ISI/BUI/FWI) | **Real** — full Canadian FWI system with persistent day-to-day state |
| Air quality (PM10/PM2.5) | **Real** — Open-Meteo air quality API, fetched client-side |
| Satellite fire hotspots | **Real** — NASA GIBS/FIRMS thermal anomaly imagery, keyless |
| CH-01, CH-02 camera images | **Real** — official NPS webcams (Look Rock, Purchase Knob), refresh ~15min |
| Ground sensor readings (temp/humidity/CO2/water level) | **Simulated** — stands in for hardware, same code path |
| Camera AI flame/smoke detection | **Simulated stub** — not analyzing real image frames yet |
| CH-03, CH-04 cameras | **Placeholder** — no confirmed public feed found for these |

## Connecting real hardware later

When your Arduino/Raspberry Pi nodes are ready:

1. Set `SIMULATOR_ENABLED = False` in `app.py`
2. Have each device `POST` JSON to `http://<server-ip>:8420/api/ingest`:

```json
{
  "node_id": "N01",
  "ground_temp": 28.4,
  "ground_humidity": 47.2,
  "co2": 265.0,
  "water_level": 415.0,
  "ground_movement": 0.01
}
```

That's it. The dashboard already reads from the same database table —
no frontend changes needed.

## Files

- `app.py` — HTTP server + REST API (start here)
- `db.py` — SQLite schema and queries
- `fwi.py` — Canadian Fire Weather Index calculations (Van Wagner 1987)
- `simulator.py` — fake sensor data generator (disable when hardware arrives)
- `weather_fwi.py` — fetches real weather, updates FWI daily
- `ffds.db` — created automatically on first run (SQLite file)

## Known limitations (be upfront about these in your report)

- FWI uses current weather as a proxy for "noon" weather since a single
  API call can't give historical noon readings — a minor simplification.
- The AI flame/smoke detection is a labeled stub, not a real model. Wiring
  in an actual CV model (e.g. YOLOv8 on the camera frames) is the natural
  next step.
- NPS webcam images refresh ~15 minutes — real snapshots, not video.
