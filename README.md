# TAKNET-PS AIS Aggregator

Distributed **AIS** (marine vessel tracking) aggregation stack. The **`web/`** dashboard is recreated from [TAKNET-PS Aggregator](https://github.com/cfd2474/TAKNET-PS_Aggregator) with the same **routes, JSON APIs, services, and UI sections**, adapted for **vessels** (`vessels.json` / `VESSELS_JSON_URL`) instead of **aircraft** (`aircraft.json`).

---

## Architecture (parity with ADS-B stack)

| ADS-B role | AIS equivalent |
|------------|----------------|
| `beast-proxy` | **`ais-proxy`** — NMEA TCP from feeders; optional UDP copy to third parties (e.g. AIS Friends) |
| `readsb` + `tar1090` | **`ais-core`** — decode + **`/data/vessels.json`** |
| `mlat-server` | *(not used for AIS)* |
| `aircraft-merger` + network hub | **`vessel-merger`** + **`aisstream-connector`** (AISstream.io) + future AIShub / etc. |
| outbound feeder | Optional push to third-party aggregators |
| Flask **`web/`** | **Same** — dashboard, inputs, config, outputs, API, tunnel |
| `api-server` (`/v2/`) | **`api-server`** *(add when ready)* |
| `nginx` | **`nginx`** *(optional front edge)* |

---

## Dashboard sections (same features as ADS-B aggregator)

| Area | Routes / behavior |
|------|-------------------|
| **Auth** | `/login`, `/register`, `/pending`, `/profile`, `/forgot-password`, `/reset-password/<token>` |
| **Dashboard** | `/`, `/dashboard` — stats, feeder breakdown, system health, network-feed status, activity |
| **Inputs** | `/inputs/feeders`, `/inputs/feeder/<id>` — feeder registry & detail |
| **Map** | `/map` — Leaflet: **Combined (network)** (`VESSELS_JSON_URL` / merger) vs **Direct (feeders)** (`DIRECT_VESSELS_JSON_URL` → ais-core); legend colors by `source` |
| **Statistics** | `/stats` — graphs slot (embed when ready) |
| **Outputs** | `/outputs`, CoT proxy pages — JSON / CoT outputs (schema shared with ADS-B) |
| **Config** | `/config` — VPN, services (Docker), health, diagnostics, updates, **users** |
| **API (dashboard)** | `/api/*` — status, feeders, `/api/aircraft.json` (combined), `/api/vessels-direct.json` (feeders), docker, VPN, updates, settings, outputs, diagnostics |
| **About** | `/about` |
| **Feeder tunnel** | `/feeder` WebSocket paths — when `feeder_tunnel` module loads |

Environment highlights:

- **`VESSELS_JSON_URL`** — merged JSON for the **Combined** map and dashboard counts (default: **`vessel-merger`** — `ais-core` feeders + **AISstream**). Set to `http://ais-core:4001/data/vessels.json` only if you want to disable the merger. Legacy **`AIRCRAFT_JSON_URL`** is still read as a fallback key for the same setting.
- **`DIRECT_VESSELS_JSON_URL`** — ais-core **feeder-only** JSON for the **Direct** map (default `http://<READSB_HOST>:4001/data/vessels.json`).
- **`SITE_LAT`** / **`SITE_LON`** — default map center on `/map`.
- **`GITHUB_REPO`** — OTA updates clone target (default `cfd2474/TAKNET-PS_AIS_AGGREGATOR`).
- **`NETWORK_FEEDS_STATUS_PATH`** — shared directory for connector status files (`feed.json`, `receive.json`). Legacy **`ADSBHUB_STATUS_PATH`** is still read as a fallback for the same path.
- **`NETWORK_FEED_OUTBOUND_ENABLED`** / **`NETWORK_FEED_INBOUND_ENABLED`** — toggles for Config → Services (legacy **`ADSBHUB_FEED_ENABLED`** / **`ADSBHUB_RECEIVE_ENABLED`** still honored if the new keys are unset).
- **AISstream.io** — [WebSocket API](https://aisstream.io/documentation): subscribe with **`APIKey`** + **`BoundingBoxes`** (required) within 3 seconds of connecting to **`wss://stream.aisstream.io/v0/stream`**. This stack runs **`aisstream-connector`** (ingest) and **`vessel-merger`** (merge with `ais-core`). Set **`AISSTREAM_API_KEY`** in `.env` (or Config → Services), align **`SITE_LAT`/`SITE_LON`** with your area, and optionally set **`AISSTREAM_BOUNDING_BOXES`** (JSON array of corner pairs) or **`AISSTREAM_BBOX_SPAN_DEG`** (default ±6° around site). Rebuild/restart **`aisstream-connector`** and **`vessel-merger`** after changing the key or bbox. **Combined** map uses **`VESSELS_JSON_URL`** (merger); **Direct** stays feeder-only via **`DIRECT_VESSELS_JSON_URL`**.
- **`AISHUB_POLL_URL`** — optional AIShub poll URL for a future connector.
- **aiscatcher.org exchange** — same variables as [docker-shipfeeder / Feeding AIS Aggregator Services](https://github.com/sdr-enthusiasts/docker-shipfeeder?tab=readme-ov-file#feeding-ais-aggregator-services): **`AISCATCHER_SHAREDATA`** (`true`/`false`), optional **`AISCATCHER_FEEDER_KEY`** (UUID from [aiscatcher.org](https://www.aiscatcher.org/) join), optional **`AISCATCHER_SHAREKEY`** (reserved for future exchange options). Config → Services persists these to `.env`. Merged vessel rows should use `source` containing `aiscatcher` so outputs and CoT treat them as network traffic.
- **AIS Friends (API v1)** — bidirectional HTTP/API integration per [AIS Friends API v1 documentation](https://www.aisfriends.com/docs/api/v1): **`AISFRIENDS_API_V1_ENABLED`**, **`AISFRIENDS_API_KEY`**, optional **`AISFRIENDS_API_BASE_URL`**, optional **`AISFRIENDS_STATION_ID`** (persisted from Config → Services). Tag merged rows with `source` containing **`aisfriends`** for network filtering.
- **AIS Friends (UDP upload)** — after registration they ask you to send your AIS feed by **UDP** to **`ais.aisfriends.com`** on the **port assigned in email** (e.g. **11884**). **`ais-proxy`** can forward **`!AIVDM` / `!AIVDO`** lines from the same TCP feeder stream: set **`AIS_UDP_FORWARD_ENABLED=true`** and **`AIS_UDP_FORWARD_TARGETS=ais.aisfriends.com:11884`** (comma-separated `host:port` for multiple targets). Rebuild/restart **`ais-proxy`** after changing these. Alternatively, use **[docker-shipfeeder](https://github.com/sdr-enthusiasts/docker-shipfeeder?tab=readme-ov-file#feeding-ais-aggregator-services)** with **`AISFRIENDS_UDP_PORT`** if you prefer a parallel SDR path.

---

## Data plane

- Feeders send **NMEA 0183** over TCP (often **10110**): `!AIVDM` / `!AIVDO`.
- **`ais-proxy`** → **`ais-core`** → **`vessels.json`** for feeder traffic; **`aisstream-connector`** pulls AISstream.io via WebSocket; **`vessel-merger`** combines both for **`VESSELS_JSON_URL`** (optional UDP fan-out from **`ais-proxy`** before **`ais-core`**).

---

## Repository layout

```
TAKNET-PS_AIS_AGGREGATOR/
├── docker-compose.yml
├── env.example
├── RELEASES.json
├── VERSION
├── var/                         # host health + network-feed status (mounted to dashboard /app/var)
├── ais-proxy/
├── ais-core/
├── aisstream-connector/        # AISstream.io WebSocket → local vessels.json
├── vessel-merger/              # merges ais-core + aisstream JSON for Combined map
├── web/                         # full Flask app (parity with ADS-B web)
├── api-server/                 # optional public REST
├── nginx/
└── README.md
```

---

## Install (bash from Git or curl)

**Requires:** root, Git, curl, Docker Engine + `docker compose` plugin. On Rocky/Alma/RHEL the script can install Docker via dnf; on Debian/Ubuntu install Docker first from [Docker’s docs](https://docs.docker.com/engine/install/).

```bash
# From a clone (recommended)
git clone https://github.com/cfd2474/TAKNET-PS_AIS_AGGREGATOR.git
cd TAKNET-PS_AIS_AGGREGATOR
sudo bash install.sh
```

```bash
# One-liner (set REPO URL to your fork if needed)
curl -sSL https://raw.githubusercontent.com/cfd2474/TAKNET-PS_AIS_AGGREGATOR/main/install.sh | sudo bash
```

Override clone URL or install path without editing the script:

```bash
sudo TAKNET_AIS_REPO_URL=https://github.com/you/TAKNET-PS_AIS_AGGREGATOR.git \
     TAKNET_AIS_INSTALL_DIR=/opt/taknet-ais-aggregator \
     bash install.sh
```

After install: **`taknet-ais status`**, **`taknet-ais logs`**, **`taknet-ais update`**.

---

## Operations

- **Dashboard:** `WEB_PORT` (default **5000**). Default admin: **`admin`** / **`password`** — change immediately.
- **Database:** SQLite `DB_PATH` (`/data/ais_aggregator.db`), shared volume **`ais-db-data`** with **`ais-proxy`** when SQLite is enabled there.
- **Docker:** Dashboard mounts **`/var/run/docker.sock`** (read/write) for **Services** and **Config → Updates**.
- **Secrets:** `SECRET_KEY`, Resend (`RESEND_*`), NetBird (`NETBIRD_*`), etc. in `.env`.
- **Web UI updates (docker:cli):** **`INSTALL_DIR`** in `.env` must be the **absolute host path** to the install root (default **`/opt/taknet-ais-aggregator`**). Compose bind-mounts `${INSTALL_DIR}/.env`, `var/`, `VERSION`, and `RELEASES.json` into the dashboard and passes the same path to the update job. If `INSTALL_DIR` was **`/app`**, Docker bind-mounts the **host’s** `/app`, so `docker compose` finds no project files and exits **1**. For a clone outside `/opt/...`, set **`INSTALL_DIR`** to that directory’s absolute path before `docker compose up`.

---

## Next steps

1. Harden **`ais-proxy`** (SQLite, VPN classification, claim line).
2. Add **`vessel-merger`** and network connectors; point **`VESSELS_JSON_URL`** at the merger.
3. Add **`api-server`** + **`nginx`** for public `/v2/` and TLS.
4. Replace **map** template with a real **Leaflet/MapLibre** view over **`vessels.json`**.
