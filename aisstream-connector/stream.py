"""AISstream.io WebSocket client — positions into vessels.json (ais-core compatible).

Per https://aisstream.io/documentation — subscribe within 3s of connect with APIKey + BoundingBoxes.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

import websockets

WS_URL = "wss://stream.aisstream.io/v0/stream"
HTTP_HOST = os.environ.get("AISSTREAM_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("AISSTREAM_HTTP_PORT", "4002"))
API_KEY = (os.environ.get("AISSTREAM_API_KEY") or "").strip()

# Optional JSON array: [[[lat1,lon1],[lat2,lon2]], ...] — see AISstream docs
_RAW_BOXES = (os.environ.get("AISSTREAM_BOUNDING_BOXES") or "").strip()

SITE_LAT = float(os.environ.get("SITE_LAT", "33.8753"))
SITE_LON = float(os.environ.get("SITE_LON", "-117.5664"))
# Default ±6° (~400 nm) around map center; override with AISSTREAM_BOUNDING_BOXES for exact area
_SPAN = float(os.environ.get("AISSTREAM_BBOX_SPAN_DEG", "6"))

STATE_LOCK = threading.Lock()
STATE: Dict[str, Any] = {
    "vessels_by_mmsi": {},
    "messages": 0,
    "now": 0.0,
    "ws_error": "",
    "ws_connected": False,
}


def _default_bounding_boxes() -> list:
    la1, lo1 = SITE_LAT - _SPAN, SITE_LON - _SPAN
    la2, lo2 = SITE_LAT + _SPAN, SITE_LON + _SPAN
    return [[[la1, lo1], [la2, lo2]]]


def _parse_bounding_boxes() -> list:
    if _RAW_BOXES:
        try:
            data = json.loads(_RAW_BOXES)
            if isinstance(data, list) and data:
                return data
        except json.JSONDecodeError:
            pass
    return _default_bounding_boxes()


def _subscription_message() -> dict:
    msg = {
        "APIKey": API_KEY,
        "BoundingBoxes": _parse_bounding_boxes(),
        "FilterMessageTypes": [
            "PositionReport",
            "StandardClassBPositionReport",
            "ExtendedClassBPositionReport",
            "ShipStaticData",
            "StaticDataReport",
        ],
    }
    return msg


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _message_inner(message: dict) -> dict:
    """Extract typed AIS payload; tolerate key naming drift in AISstream beta API."""
    mt = message.get("MessageType") or ""
    box = message.get("Message") or {}
    if not isinstance(box, dict):
        return {}
    if mt and isinstance(box.get(mt), dict):
        return box[mt]
    for v in box.values():
        if isinstance(v, dict):
            return v
    return {}


def _apply_position_message(message: dict) -> None:
    mt = message.get("MessageType") or ""
    meta = message.get("MetaData") or {}
    inner = _message_inner(message)

    mmsi = meta.get("MMSI") or inner.get("UserID")
    if mmsi is None:
        return
    try:
        mmsi_i = int(mmsi)
    except (TypeError, ValueError):
        return

    lat = _num(meta.get("latitude") or meta.get("Latitude"))
    lon = _num(meta.get("longitude") or meta.get("Longitude"))
    if lat is None:
        lat = _num(inner.get("Latitude"))
    if lon is None:
        lon = _num(inner.get("Longitude"))

    rec: Dict[str, Any] = {
        "mmsi": mmsi_i,
        "source": "aisstream",
        "last_seen": time.time(),
    }
    if lat is not None and lon is not None:
        rec["lat"] = lat
        rec["lon"] = lon
    cog = _num(inner.get("Cog") or inner.get("Course"))
    if cog is not None:
        rec["cog"] = cog
    sog = _num(inner.get("Sog") or inner.get("Speed"))
    if sog is not None:
        rec["sog"] = sog
    name = meta.get("ShipName") or inner.get("Name")
    if name:
        s = str(name).strip("@ \x00")
        if s:
            rec["name"] = s[:32]

    with STATE_LOCK:
        prev = STATE["vessels_by_mmsi"].get(mmsi_i, {})
        merged = {**prev, **rec}
        STATE["vessels_by_mmsi"][mmsi_i] = merged
        STATE["messages"] = int(STATE["messages"]) + 1
        STATE["now"] = time.time()


def _apply_static_message(message: dict) -> None:
    meta = message.get("MetaData") or {}
    inner = _message_inner(message)

    mmsi = meta.get("MMSI") or inner.get("UserID")
    if mmsi is None:
        return
    try:
        mmsi_i = int(mmsi)
    except (TypeError, ValueError):
        return

    name = meta.get("ShipName") or inner.get("Name")
    if not name:
        return
    s = str(name).strip("@ \x00")
    if not s:
        return

    with STATE_LOCK:
        prev = STATE["vessels_by_mmsi"].get(mmsi_i, {"mmsi": mmsi_i, "source": "aisstream"})
        prev["name"] = s[:32]
        prev["last_seen"] = time.time()
        STATE["vessels_by_mmsi"][mmsi_i] = prev
        STATE["messages"] = int(STATE["messages"]) + 1
        STATE["now"] = time.time()


def _handle_ws_payload(text: str) -> None:
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return
    if isinstance(message, dict) and "error" in message:
        with STATE_LOCK:
            STATE["ws_error"] = str(message.get("error", "error"))
        return

    mt = message.get("MessageType")
    if mt in ("ShipStaticData", "StaticDataReport"):
        _apply_static_message(message)
        return
    if mt in (
        "PositionReport",
        "StandardClassBPositionReport",
        "ExtendedClassBPositionReport",
        "LongRangeAisBroadcastMessage",
    ):
        _apply_position_message(message)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p = self.path.rstrip("/")
        if p in ("/data/vessels.json", "/vessels.json"):
            with STATE_LOCK:
                vessels = list(STATE["vessels_by_mmsi"].values())
                now = STATE["now"] or time.time()
                messages = int(STATE["messages"])
                err = STATE.get("ws_error") or ""
                connected = bool(STATE.get("ws_connected"))
            body = json.dumps(
                {
                    "schema_version": 1,
                    "vessels": vessels,
                    "now": now,
                    "messages": messages,
                    "source": "aisstream-connector",
                    "aisstream_ws_connected": connected,
                    "aisstream_ws_error": err,
                }
            ).encode("utf-8")
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


def _run_http():
    server = HTTPServer((HTTP_HOST, HTTP_PORT), _Handler)
    print(f"[aisstream-connector] HTTP http://{HTTP_HOST}:{HTTP_PORT}/data/vessels.json")
    server.serve_forever()


async def _ws_loop():
    if not API_KEY:
        with STATE_LOCK:
            STATE["ws_error"] = "AISSTREAM_API_KEY is not set"
        print("[aisstream-connector] AISSTREAM_API_KEY empty — serving empty vessels until key is set")
        await asyncio.Event().wait()
        return

    while True:
        with STATE_LOCK:
            STATE["ws_error"] = ""
            STATE["ws_connected"] = False
        try:
            async with websockets.connect(
                WS_URL,
                ping_interval=20,
                ping_timeout=60,
                close_timeout=10,
            ) as ws:
                sub = json.dumps(_subscription_message())
                await ws.send(sub)
                with STATE_LOCK:
                    STATE["ws_connected"] = True
                    STATE["ws_error"] = ""
                print("[aisstream-connector] subscribed to AISstream (BoundingBoxes + filters)")
                async for raw in ws:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    _handle_ws_payload(raw)
        except Exception as e:
            with STATE_LOCK:
                STATE["ws_connected"] = False
                STATE["ws_error"] = str(e)[:500]
            print(f"[aisstream-connector] websocket error: {e!r}, reconnecting in 10s")
            await asyncio.sleep(10)


def main():
    threading.Thread(target=_run_http, daemon=True).start()
    if not API_KEY:
        print("[aisstream-connector] Set AISSTREAM_API_KEY in .env and restart this container.")
        while True:
            time.sleep(3600)
        return
    asyncio.run(_ws_loop())


if __name__ == "__main__":
    main()
