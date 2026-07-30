"""
FFDS Backend — Forest Fire Detection System API server.

Zero external dependencies: pure Python standard library
(http.server + sqlite3 + urllib). Run with:

    python3 app.py

Serves REST API on http://localhost:8420

Endpoints:
  GET  /api/health
  GET  /api/nodes                      -> node list + latest reading each
  GET  /api/nodes/{id}/history?hours=24
  GET  /api/readings/log?limit=25      -> recent snapshot log (all nodes)
  GET  /api/fwi/current
  GET  /api/fwi/history?days=7
  GET  /api/alerts?limit=20
  POST /api/alerts/{id}/acknowledge
  GET  /api/cameras                    -> latest simulated AI detection per camera
  POST /api/siren                      -> log a manual siren trigger event
  GET  /api/events?limit=20
  POST /api/ingest                     -> REAL HARDWARE ENDPOINT (see below)

--- FOR FUTURE HARDWARE INTEGRATION ---
When real Arduino/Raspberry Pi nodes are ready, disable the simulator
(SIMULATOR_ENABLED = False below) and have each device POST JSON to
/api/ingest in this shape:

  {
    "node_id": "N01",
    "ground_temp": 28.4,
    "ground_humidity": 47.2,
    "co2": 265.0,
    "water_level": 415.0,
    "ground_movement": 0.01
  }

That's it — the rest of the dashboard (charts, alerts, snapshot log)
already reads from the same `readings` table and needs no changes.
"""
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import db
import simulator
import weather_fwi

PORT = 8420
SIMULATOR_ENABLED = True   # set False once real hardware is POSTing to /api/ingest


def json_default(o):
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet; comment out to see request logs

    def _send(self, code, payload):
        body = json.dumps(payload, default=json_default).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            if path == "/api/health":
                return self._send(200, {"status": "ok", "ts": time.time()})

            if path == "/api/nodes":
                nodes = db.get_nodes()
                latest = {r["node_id"]: r for r in db.latest_readings()}
                cams = {d["camera_id"]: d for d in db.latest_camera_detections()}
                out = []
                for n in nodes:
                    entry = dict(n)
                    if n["kind"] == "ground_sensor":
                        entry["latest_reading"] = latest.get(n["id"])
                    elif n["kind"] == "camera":
                        entry["latest_detection"] = cams.get(n["id"])
                    out.append(entry)
                return self._send(200, {"nodes": out})

            m = re.match(r"^/api/nodes/([A-Za-z0-9]+)/history$", path)
            if m:
                node_id = m.group(1)
                hours = float(qs.get("hours", ["24"])[0])
                since = time.time() - hours * 3600
                return self._send(200, {"node_id": node_id, "history": db.history(node_id, since)})

            if path == "/api/readings/log":
                limit = int(qs.get("limit", ["25"])[0])
                return self._send(200, {"log": db.recent_snapshot_log(limit)})

            if path == "/api/fwi/current":
                latest = db.get_latest_fwi()
                if not latest:
                    return self._send(503, {"error": "FWI not yet computed — server just started, try again shortly"})
                return self._send(200, latest)

            if path == "/api/weather/current":
                conn = db.get_conn()
                row = conn.execute("SELECT * FROM weather_daily ORDER BY date DESC LIMIT 1").fetchone()
                conn.close()
                if not row:
                    return self._send(503, {"error": "weather not yet fetched — try again shortly"})
                return self._send(200, dict(row))

            if path == "/api/fwi/history":
                days = int(qs.get("days", ["7"])[0])
                return self._send(200, {"history": db.get_fwi_history(days)})

            if path == "/api/alerts":
                limit = int(qs.get("limit", ["20"])[0])
                unack = qs.get("unacknowledged", ["false"])[0] == "true"
                return self._send(200, {"alerts": db.recent_alerts(limit, unack)})

            if path == "/api/cameras":
                cams = db.get_nodes(kind="camera")
                latest = {d["camera_id"]: d for d in db.latest_camera_detections()}
                for c in cams:
                    c["latest_detection"] = latest.get(c["id"])
                return self._send(200, {"cameras": cams})

            if path == "/api/events":
                limit = int(qs.get("limit", ["20"])[0])
                return self._send(200, {"events": db.recent_events(limit)})

            return self._send(404, {"error": "not found"})

        except Exception as e:
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode()) if raw else {}
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid JSON body"})

        try:
            m = re.match(r"^/api/alerts/(\d+)/acknowledge$", path)
            if m:
                db.acknowledge_alert(int(m.group(1)))
                return self._send(200, {"ok": True})

            if path == "/api/siren":
                db.insert_event("manual_siren", "Manual siren activated by operator")
                return self._send(200, {"ok": True, "ts": time.time()})

            if path == "/api/ingest":
                # Real hardware endpoint — see module docstring
                required = ["node_id", "ground_temp", "ground_humidity", "co2", "water_level"]
                missing = [k for k in required if k not in body]
                if missing:
                    return self._send(400, {"error": f"missing fields: {missing}"})
                db.insert_reading(
                    body["node_id"], body["ground_temp"], body["ground_humidity"],
                    body["co2"], body["water_level"], body.get("ground_movement", 0.0),
                    source="hardware",
                )
                return self._send(201, {"ok": True})

            return self._send(404, {"error": "not found"})

        except Exception as e:
            return self._send(500, {"error": str(e)})


def main():
    db.init_db()
    weather_fwi.start(interval_seconds=900)  # real weather -> real FWI, every 15 min
    if SIMULATOR_ENABLED:
        simulator.start(interval_seconds=15)
    else:
        print("[app] simulator disabled — waiting for hardware POSTs to /api/ingest")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[app] FFDS backend running at http://localhost:{PORT}")
    print(f"[app] try: curl http://localhost:{PORT}/api/nodes")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[app] shutting down")
        simulator.stop()


if __name__ == "__main__":
    main()
