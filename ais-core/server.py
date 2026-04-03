"""AIS core: TCP NMEA from ais-proxy, decode AIVDM, serve local vessels.json."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from pyais import decode

LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "4000"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "4001"))

STATE = {
    "vessels_by_mmsi": {},
    "messages": 0,
    "now": 0.0,
}
STATE_LOCK = threading.Lock()


def _vessel_record(decoded) -> dict | None:
    """Extract a normalized vessel dict from a pyais decoded message."""
    mmsi = getattr(decoded, "mmsi", None)
    if mmsi is None:
        return None
    lat = getattr(decoded, "lat", None)
    lon = getattr(decoded, "lon", None)
    out = {
        "mmsi": int(mmsi),
        "source": "local",
    }
    if lat is not None and lon is not None:
        try:
            out["lat"] = float(lat)
            out["lon"] = float(lon)
        except (TypeError, ValueError):
            pass
    cog = getattr(decoded, "course", None)
    if cog is None:
        cog = getattr(decoded, "cog", None)
    if cog is not None:
        try:
            out["cog"] = float(cog)
        except (TypeError, ValueError):
            pass
    sog = getattr(decoded, "speed", None)
    if sog is None:
        sog = getattr(decoded, "sog", None)
    if sog is not None:
        try:
            out["sog"] = float(sog)
        except (TypeError, ValueError):
            pass
    name = getattr(decoded, "shipname", None) or getattr(decoded, "name", None)
    if name:
        s = str(name).strip("@")
        if s:
            out["name"] = s[:20]
    return out


def _decode_line(line: bytes) -> None:
    """Decode one NMEA line; update STATE on success."""
    try:
        s = line.decode("utf-8", errors="ignore").strip()
    except Exception:
        return
    if not s or "AIVDM" not in s and "AIVDO" not in s:
        return
    try:
        decoded = decode(s)
    except Exception:
        return
    if isinstance(decoded, (list, tuple)):
        for d in decoded:
            _apply_decoded(d)
        return
    if decoded is not None:
        _apply_decoded(decoded)


def _apply_decoded(decoded) -> None:
    rec = _vessel_record(decoded)
    if not rec:
        return
    mmsi = rec["mmsi"]
    ts = time.time()
    rec["last_seen"] = ts
    if "lat" not in rec or "lon" not in rec:
        with STATE_LOCK:
            prev = STATE["vessels_by_mmsi"].get(mmsi)
            if prev:
                merged = {**prev, **rec}
                STATE["vessels_by_mmsi"][mmsi] = merged
            else:
                STATE["vessels_by_mmsi"][mmsi] = rec
            STATE["messages"] += 1
            STATE["now"] = ts
        return
    with STATE_LOCK:
        prev = STATE["vessels_by_mmsi"].get(mmsi, {})
        merged = {**prev, **rec}
        STATE["vessels_by_mmsi"][mmsi] = merged
        STATE["messages"] += 1
        STATE["now"] = ts


def _feed_line_buffer(data: bytes, carry: bytearray) -> None:
    carry.extend(data)
    while True:
        if b"\n" not in carry:
            break
        line, _sep, rest = carry.partition(b"\n")
        del carry[:]
        carry.extend(rest)
        if line.endswith(b"\r"):
            line = line[:-1]
        if line:
            _decode_line(line)


async def consume_feeder(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    n = 0
    buf = bytearray()
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            n += len(data)
            _feed_line_buffer(data, buf)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        who = peer[0] if peer else "?"
        print(f"[ais-core] closed upstream from proxy {who}, bytes={n}")


async def handle_upstream(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
):
    asyncio.create_task(consume_feeder(reader, writer))


class VesselsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/") == "/data/vessels.json" or self.path.rstrip("/") == "/vessels.json":
            with STATE_LOCK:
                vessels = list(STATE["vessels_by_mmsi"].values())
                now = STATE["now"] or time.time()
                messages = STATE["messages"]
            body = json.dumps(
                {
                    "schema_version": 1,
                    "vessels": vessels,
                    "now": now,
                    "messages": messages,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def _run_http():
    server = HTTPServer((LISTEN_HOST, HTTP_PORT), VesselsHandler)
    print(f"[ais-core] HTTP vessels at http://{LISTEN_HOST}:{HTTP_PORT}/data/vessels.json")
    server.serve_forever()


async def main():
    threading.Thread(target=_run_http, daemon=True).start()
    server = await asyncio.start_server(handle_upstream, LISTEN_HOST, LISTEN_PORT)
    print(f"[ais-core] NMEA TCP on {LISTEN_HOST}:{LISTEN_PORT}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
