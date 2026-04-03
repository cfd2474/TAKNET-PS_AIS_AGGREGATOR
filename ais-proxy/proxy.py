"""TAKNET-PS AIS TCP proxy — NMEA/AIVDM from feeders → ais-core.

Mirrors the beast-proxy pattern: one asyncio connection to ais-core per feeder
session. Optional ASCII prefix lines before NMEA (claim key) can be added
next to match TAKNET_FEEDER_CLAIM behavior from the ADS-B stack.
"""

import asyncio
import os

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "10110"))
AIS_CORE_HOST = os.environ.get("AIS_CORE_HOST", "ais-core")
AIS_CORE_PORT = int(os.environ.get("AIS_CORE_PORT", "4000"))


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def handle_client(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
):
    peer = writer.get_extra_info("peername")
    ip = peer[0] if peer else "?"
    print(f"[ais-proxy] feeder connected from {ip}")

    upstream_r = upstream_w = None
    try:
        upstream_r, upstream_w = await asyncio.open_connection(
            AIS_CORE_HOST, AIS_CORE_PORT
        )
        print(f"[ais-proxy] {ip} → {AIS_CORE_HOST}:{AIS_CORE_PORT}")
        await asyncio.gather(
            pipe(reader, upstream_w),
            pipe(upstream_r, writer),
        )
    except (ConnectionRefusedError, OSError) as e:
        print(f"[ais-proxy] upstream unavailable: {e}")
    finally:
        if not writer.is_closing():
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        print(f"[ais-proxy] disconnected {ip}")


async def main():
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    print(
        f"[ais-proxy] listening on {LISTEN_HOST}:{LISTEN_PORT} → "
        f"{AIS_CORE_HOST}:{AIS_CORE_PORT}"
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
