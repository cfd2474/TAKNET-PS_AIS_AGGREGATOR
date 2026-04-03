"""Optional UDP fan-out of NMEA/AIVDM lines copied from feeder → ais-core path.

Designed for aggregators that accept UDP (e.g. AIS Friends: ais.aisfriends.com:PORT).
One datagram per line, newline-terminated payload (common convention).

Environment (ais-proxy container):
  AIS_UDP_FORWARD_ENABLED   — true/1/yes/on to enable (default off).
  AIS_UDP_FORWARD_TARGETS — comma-separated host:port, e.g.
                            ais.aisfriends.com:11884
  AIS_UDP_FORWARD_DNS_TTL_S — re-resolve hostnames every N seconds (default 300).
"""

from __future__ import annotations

import asyncio
import os
import re
import socket
import threading
import time
from typing import Callable, List, Optional, Tuple

_AIVDM = re.compile(rb"AIVD[MO]", re.IGNORECASE)


def _env_truthy(key: str, default: bool = False) -> bool:
    v = (os.environ.get(key) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _parse_targets(raw: str) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            continue
        host, _, port_s = part.rpartition(":")
        host = host.strip()
        try:
            port = int(port_s.strip())
        except ValueError:
            continue
        if host and 1 <= port <= 65535:
            out.append((host, port))
    return out


def _resolve_all(hosts_ports: List[Tuple[str, int]]) -> list:
    """Resolved sockaddrs for sendto (IPv4 or IPv6 tuples from getaddrinfo)."""
    addrs: list = []
    for host, port in hosts_ports:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
            # IPv4 only: single AF_INET DGRAM socket for all targets.
            for fam, _, _, _, sa in infos:
                if fam == socket.AF_INET:
                    addrs.append(sa)
                    break
        except OSError:
            pass
    return addrs


class LineDemuxer:
    """Buffer a byte stream and invoke callback for each \\n-terminated line."""

    __slots__ = ("_buf", "_on_line")

    def __init__(self, on_line: Callable[[bytes], None]):
        self._buf = bytearray()
        self._on_line = on_line

    def feed(self, data: bytes) -> None:
        if not data:
            return
        self._buf.extend(data)
        while True:
            i = self._buf.find(b"\n")
            if i < 0:
                break
            line = bytes(self._buf[:i])
            del self._buf[: i + 1]
            line = line.rstrip(b"\r")
            if line and _AIVDM.search(line):
                self._on_line(line)


class UDPForwarderPool:
    """Thread-safe UDP sends; DNS refresh in background."""

    __slots__ = ("_lock", "_sock", "_targets_spec", "_resolved", "_ttl", "_last_resolve")

    def __init__(self, targets_spec: List[Tuple[str, int]], dns_ttl_s: float):
        self._lock = threading.Lock()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._sock.setblocking(True)
        except OSError:
            pass
        self._targets_spec = targets_spec
        self._ttl = max(30.0, dns_ttl_s)
        self._last_resolve = 0.0
        self._resolved: list = []
        self._refresh_resolved()

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def _refresh_resolved(self) -> None:
        self._resolved = _resolve_all(self._targets_spec)
        self._last_resolve = time.monotonic()
        if not self._resolved:
            print("[ais-proxy-udp] WARNING: no UDP targets resolved; check AIS_UDP_FORWARD_TARGETS / DNS")

    def send_nmea_line(self, line: bytes) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_resolve > self._ttl:
                self._refresh_resolved()
            if not self._resolved:
                return
            payload = line + b"\n"
            for addr in self._resolved:
                try:
                    self._sock.sendto(payload, addr)
                except OSError as err:
                    print(f"[ais-proxy-udp] sendto {addr!r}: {err}")


_pool: Optional[UDPForwarderPool] = None
_pool_lock = threading.Lock()
_pool_init_failed: bool = False


def get_udp_forward_pool() -> Optional[UDPForwarderPool]:
    """Lazy singleton from environment."""
    global _pool, _pool_init_failed
    with _pool_lock:
        if _pool is not None:
            return _pool
        if _pool_init_failed:
            return None
        if not _env_truthy("AIS_UDP_FORWARD_ENABLED", False):
            return None
        raw = (os.environ.get("AIS_UDP_FORWARD_TARGETS") or "").strip()
        targets = _parse_targets(raw)
        if not targets:
            _pool_init_failed = True
            print("[ais-proxy-udp] AIS_UDP_FORWARD_ENABLED but AIS_UDP_FORWARD_TARGETS empty")
            return None
        try:
            ttl = float(os.environ.get("AIS_UDP_FORWARD_DNS_TTL_S", "300"))
        except ValueError:
            ttl = 300.0
        _pool = UDPForwarderPool(targets, ttl)
        print(f"[ais-proxy-udp] forwarding AIVDM/AIVDO lines to {targets!r}")
        return _pool


def make_line_demuxer() -> Optional[LineDemuxer]:
    pool = get_udp_forward_pool()
    if not pool:
        return None

    def on_line(line: bytes) -> None:
        pool.send_nmea_line(line)

    return LineDemuxer(on_line)


async def pipe_to_upstream_with_udp_tee(
    reader: asyncio.StreamReader,
    upstream_w: asyncio.StreamWriter,
    demux: Optional[LineDemuxer],
) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            if demux is not None:
                demux.feed(chunk)
            upstream_w.write(chunk)
            await upstream_w.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            upstream_w.close()
            await upstream_w.wait_closed()
        except Exception:
            pass
