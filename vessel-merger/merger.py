"""Merge ais-core vessels.json + aisstream-connector vessels.json for Combined map."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

AIS_CORE_URL = (os.environ.get("AIS_CORE_URL") or "http://ais-core:4001").rstrip("/")
AISSTREAM_URL = (os.environ.get("AISSTREAM_URL") or "http://aisstream-connector:4002").rstrip("/")
HTTP_HOST = os.environ.get("MERGER_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("MERGER_HTTP_PORT", "4003"))
FETCH_TIMEOUT = float(os.environ.get("MERGER_FETCH_TIMEOUT", "5"))


def _fetch_json(base: str) -> dict:
    url = base + "/data/vessels.json"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def merge() -> dict:
    core = {}
    stream = {}
    try:
        core = _fetch_json(AIS_CORE_URL)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as e:
        core = {"error_upstream": f"ais-core: {e}", "vessels": []}
    try:
        stream = _fetch_json(AISSTREAM_URL)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as e:
        stream = {"error_upstream": f"aisstream: {e}", "vessels": []}

    by_mmsi: dict = {}
    for v in core.get("vessels") or []:
        if not isinstance(v, dict):
            continue
        m = v.get("mmsi")
        if m is None:
            continue
        try:
            mi = int(m)
        except (TypeError, ValueError):
            continue
        by_mmsi[mi] = dict(v)

    for v in stream.get("vessels") or []:
        if not isinstance(v, dict):
            continue
        m = v.get("mmsi")
        if m is None:
            continue
        try:
            mi = int(m)
        except (TypeError, ValueError):
            continue
        if mi in by_mmsi:
            continue
        # AISstream-only traffic (no feeder report for this MMSI)
        by_mmsi[mi] = dict(v)

    now = time.time()
    return {
        "schema_version": 1,
        "vessels": list(by_mmsi.values()),
        "now": now,
        "messages": int(core.get("messages") or 0) + int(stream.get("messages") or 0),
        "merged_from": {"ais_core": AIS_CORE_URL, "aisstream": AISSTREAM_URL},
    }


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p = self.path.rstrip("/")
        if p in ("/data/vessels.json", "/vessels.json"):
            data = merge()
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def main():
    server = HTTPServer((HTTP_HOST, HTTP_PORT), _Handler)
    print(
        f"[vessel-merger] http://{HTTP_HOST}:{HTTP_PORT}/data/vessels.json "
        f"← {AIS_CORE_URL} + {AISSTREAM_URL}"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
