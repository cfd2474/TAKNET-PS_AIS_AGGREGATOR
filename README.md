# TAKNET-PS AIS Aggregator

Distributed **AIS** (marine vessel tracking) aggregation stack, aligned with the architecture of [TAKNET-PS ADS-B Aggregator](https://github.com/cfd2474/TAKNET-PS_Aggregator): ingress proxy with feeder classification, a core merge/decode path, a map-oriented JSON feed, Flask dashboard, public REST API, and nginx on the front.

Local reference copy of the ADS-B project: `../TAKNET-PS_Aggregator` (same machine layout as this repo).

---

## Architecture mapping (ADS-B → AIS)

| Role | ADS-B stack | AIS stack (this project) |
|------|-------------|---------------------------|
| Feeder ingress | `beast-proxy` — TCP Beast, NetBird/GeoIP, SQLite, optional claim line | **`ais-proxy`** — TCP NMEA/AIVDM (text lines), same classification + DB pattern, optional `TAKNET_FEEDER_CLAIM` prefix |
| Core processing | `readsb` — net-only Beast in, SBS/Beast out | **`ais-core`** — multi-source NMEA ingest, decode (AIVDM/AIVDO), dedupe by MMSI, time windows |
| Map / live JSON | `tar1090` → `aircraft.json` | **`ais-map`** (or static + JSON) → `vessels.json` (GeoJSON or tar1090-like array) |
| Optional merge | `aircraft-merger` | **`vessel-merger`** — local + remote AIS feeds, prefer local |
| Dashboard | Flask `web/` | **`web/`** — same patterns: auth, feeders, health, updates |
| Public API | `api-server` `/v2/` | **`api-server`** — `/v2/` style endpoints over `vessels.json` |
| Edge | `nginx` | **`nginx`** — `/`, `/api/`, `/v2/`, `/ais/` map paths |
| VPN | NetBird / Tailscale CIDR | Same `.env` variables; classify feeder source IP the same way |

**Not ported 1:1:** MLAT and ADSBHub are aviation-specific. AIS may later add satellite AIS (Spire, etc.) as optional inbound feeds, analogous to ADSBHub.

---

## Data plane (AIS)

- Feeders send **NMEA 0183** sentences over TCP (common conventions: port **10110**, or custom). Payloads are typically `!AIVDM` / `!AIVDO` fragments.
- **`ais-proxy`** accepts feeder TCP connections, records sessions in SQLite, optionally reads one or more ASCII metadata lines (claim key), then forwards the byte stream to **`ais-core`**.
- **`ais-core`** reassembles multi-part AIVDM messages, decodes with a library such as [libais](https://github.com/bosth/libais)-based tooling or **`pyais`**, maintains a **MMSI-keyed** track table, and exposes a periodic JSON snapshot for the map and API.

---

## Repository layout (target)

```
TAKNET-PS_AIS_AGGREGATOR/
├── docker-compose.yml
├── env.example
├── install.sh                 # optional: mirror ADS-B installer pattern
├── ais-proxy/               # Python async TCP → ais-core (like beast-proxy)
├── ais-core/                # decode + merge + vessels.json
├── vessel-merger/           # optional: local + external AIS
├── web/                     # Flask dashboard
├── api-server/              # public REST
├── nginx/
└── README.md
```

---

## Next implementation steps

1. **Copy operational patterns** from `../TAKNET-PS_Aggregator`: `beast-proxy` → `ais-proxy` (replace Beast framing with line-oriented NMEA forwarding), reuse `vpn_resolver` / `geoip` / SQLite schema ideas with `feeders` / `connections` tables adapted for AIS.
2. **Implement `ais-core`** with a single multi-writer message bus (asyncio) and MMSI deduplication.
3. **Define `vessels.json`** schema (stable for map + API); version it (e.g. `schema_version`).
4. **Wire `web/`** and **`nginx`** from the ADS-B project with routes renamed (`/tar1090/` → `/ais/` or similar).
5. **Add `taknet-ais` CLI** matching `taknet-agg` ergonomics (`start`, `logs`, `update`).

---

## License / ops

Match licensing and deployment assumptions with your ADS-B aggregator; use the same NetBird feeder onboarding story with AIS TCP targets documented for feeder operators.
