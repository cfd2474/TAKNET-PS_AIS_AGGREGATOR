# TAKNET-PS AIS Aggregator

Distributed **AIS** (marine vessel tracking) aggregation stack: ingress proxy with feeder classification, a core decode path, merged network feeds, a map-oriented JSON feed, Flask dashboard, public REST API, and nginx on the front.

---

## Architecture

| Role | Component |
|------|-----------|
| Feeder ingress | **`ais-proxy`** — TCP NMEA/AIVDM, NetBird/GeoIP, SQLite (when wired), optional `TAKNET_FEEDER_CLAIM` prefix |
| Core processing | **`ais-core`** — NMEA ingest, AIVDM/AIVDO decode (`pyais`), MMSI-keyed tracks |
| Map / live JSON | **`ais-map`** or dashboard embed → **`vessels.json`** |
| Optional merge | **`vessel-merger`** — local + AISstream / AIShub-style feeds, prefer local MMSI |
| Dashboard | Flask **`web/`** — auth, feeders, health, updates |
| Public API | **`api-server`** — REST over merged `vessels.json` |
| Edge | **`nginx`** — `/`, `/api/`, `/v2/`, map paths |
| VPN | NetBird (or Tailscale) CIDR classification for feeder IPs |

Optional inbound network feeds (e.g. satellite AIS) can follow the same merge pattern as other remote sources.

---

## Data plane

- Feeders send **NMEA 0183** over TCP (often port **10110**). Payloads are typically `!AIVDM` / `!AIVDO`.
- **`ais-proxy`** accepts feeder TCP connections, optionally metadata lines (claim key), then forwards the stream to **`ais-core`**.
- **`ais-core`** decodes messages, maintains MMSI-keyed state, and serves **`/data/vessels.json`** for downstream services.

---

## Repository layout (target)

```
TAKNET-PS_AIS_AGGREGATOR/
├── docker-compose.yml
├── env.example
├── install.sh
├── ais-proxy/
├── ais-core/
├── vessel-merger/
├── web/
├── api-server/
├── nginx/
└── README.md
```

---

## Next implementation steps

1. Extend **`ais-proxy`** with SQLite, VPN/GeoIP classification, and feeder claim handling.
2. Harden **`ais-core`** (multi-part AIVDM, rate limits) and stabilize **`vessels.json`** (`schema_version`).
3. Implement **`vessel-merger`** and network connectors (AISstream, AIShub API).
4. Add **`web/`** and **`nginx`** routes for the AIS map and management UI.
5. Add **`taknet-ais`** CLI for operations (`start`, `logs`, `update`).

---

## Operations

Document NetBird (or VPN) hostnames and the AIS TCP port for feeder operators. Keep secrets in `.env` only.
