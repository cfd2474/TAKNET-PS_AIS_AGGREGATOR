#!/usr/bin/env bash
# =============================================================================
# TAKNET-PS AIS Aggregator — Installer
# Target: Rocky Linux 8.x / 9.x, AlmaLinux, RHEL-family (same as ADS-B stack).
# Debian/Ubuntu: install Docker Engine + compose plugin first, then run this script.
#
# Install methods:
#   curl -sSL https://raw.githubusercontent.com/OWNER/TAKNET-PS_AIS_AGGREGATOR/main/install.sh | sudo bash
#   git clone https://github.com/OWNER/TAKNET-PS_AIS_AGGREGATOR.git && cd TAKNET-PS_AIS_AGGREGATOR && sudo bash install.sh
#
# Edit REPO_URL below if your GitHub org/user differs.
# =============================================================================
set -euo pipefail

REPO_URL="${TAKNET_AIS_REPO_URL:-https://github.com/cfd2474/TAKNET-PS_AIS_AGGREGATOR.git}"
INSTALL_DIR="${TAKNET_AIS_INSTALL_DIR:-/opt/taknet-ais-aggregator}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo ""
echo "=========================================="
echo "  TAKNET-PS AIS Aggregator — Installer"
echo "=========================================="
echo ""

[[ $EUID -ne 0 ]] && err "Run as root: curl ... | sudo bash  OR  sudo bash install.sh"

# ── Base packages (clone / tooling) ───────────────────────────────────────
_install_pkg() {
    local p="$1"
    if command -v dnf &>/dev/null; then
        dnf install -y "$p" 2>/dev/null && return 0
    fi
    if command -v yum &>/dev/null; then
        yum install -y "$p" 2>/dev/null && return 0
    fi
    if command -v apt-get &>/dev/null; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$p" 2>/dev/null && return 0
    fi
    return 1
}

for pkg in git curl jq tar rsync; do
    if ! command -v "$pkg" &>/dev/null; then
        info "Installing $pkg..."
        _install_pkg "$pkg" || warn "Could not install $pkg via package manager — install manually"
    fi
done
command -v git &>/dev/null || err "git is required"
command -v curl &>/dev/null || err "curl is required"

# ── Source: local git checkout, installed tree, or fresh clone ─────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
CLEANUP_DIR=""

if [[ -f "$SCRIPT_DIR/docker-compose.yml" ]] && [[ "$SCRIPT_DIR" != "/root" ]] && [[ "$SCRIPT_DIR" != "/tmp" ]]; then
    SOURCE_DIR="$SCRIPT_DIR"
    ok "Running from local repo: $SOURCE_DIR"
elif [[ -f "$INSTALL_DIR/docker-compose.yml" ]]; then
    SOURCE_DIR="$INSTALL_DIR"
    ok "Running from installed tree: $SOURCE_DIR"
else
    command -v git &>/dev/null || err "git not found — install git then re-run"
    info "Cloning from Git ($REPO_URL)..."
    CLEANUP_DIR="$(mktemp -d)"
    git clone --depth 1 "$REPO_URL" "$CLEANUP_DIR/repo"
    SOURCE_DIR="$CLEANUP_DIR/repo"
    ok "Cloned to $SOURCE_DIR"
fi

VERSION="$(cat "$SOURCE_DIR/VERSION" 2>/dev/null || echo "unknown")"
info "Version: v${VERSION}"

# ── Docker ──────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    if command -v dnf &>/dev/null; then
        info "Installing Docker (dnf)..."
        dnf install -y dnf-utils 2>/dev/null || true
        dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null || true
        dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        systemctl enable --now docker
        ok "Docker installed"
    else
        err "Docker not found. On Debian/Ubuntu install Docker Engine + compose plugin, then re-run: https://docs.docker.com/engine/install/"
    fi
else
    ok "Docker already installed ($(docker --version 2>/dev/null | awk '{print $3}' || echo ok))"
fi

docker compose version &>/dev/null || err "docker compose plugin not found (install docker-compose-plugin)"

# ── Deploy files ─────────────────────────────────────────────────────────────
info "Deploying to ${INSTALL_DIR}..."
mkdir -p "$INSTALL_DIR"

if command -v rsync &>/dev/null; then
    rsync -a --exclude='.git' "$SOURCE_DIR/" "$INSTALL_DIR/"
else
    shopt -s dotglob nullglob
    cp -a "$SOURCE_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true
    shopt -u dotglob nullglob
    rm -rf "$INSTALL_DIR/.git" 2>/dev/null || true
fi
ok "Files deployed"

mkdir -p "$INSTALL_DIR/var/network-feeds-status"
chmod 755 "$INSTALL_DIR/var" 2>/dev/null || true

# ── .env ────────────────────────────────────────────────────────────────────
if [[ -f "$INSTALL_DIR/.env" ]]; then
    grep -q '^INSTALL_DIR=' "$INSTALL_DIR/.env" 2>/dev/null || echo "INSTALL_DIR=$INSTALL_DIR" >> "$INSTALL_DIR/.env"
    ok "Existing .env preserved"
elif [[ -f "$INSTALL_DIR/env.example" ]]; then
    cp "$INSTALL_DIR/env.example" "$INSTALL_DIR/.env"
    echo "INSTALL_DIR=$INSTALL_DIR" >> "$INSTALL_DIR/.env"
    warn "Created .env from env.example — edit $INSTALL_DIR/.env (set SECRET_KEY, NETBIRD_*, etc.)"
else
    cat > "$INSTALL_DIR/.env" << ENVEOF
INSTALL_DIR=$INSTALL_DIR
TZ=America/Los_Angeles
SITE_NAME=TAKNET-PS AIS Aggregator
WEB_PORT=5000
AIS_FEEDER_PORT=10110
AIS_CORE_HOST=ais-core
AIS_CORE_PORT=4000
NETBIRD_ENABLED=true
NETBIRD_API_URL=https://netbird.yourdomain.com
NETBIRD_API_TOKEN=
NETBIRD_CIDR=100.64.0.0/10
GEOIP_ENABLED=true
SECRET_KEY=change-me
GITHUB_REPO=cfd2474/TAKNET-PS_AIS_AGGREGATOR
VESSELS_JSON_URL=http://ais-core:4001/data/vessels.json
RESEND_ENABLED=false
RESEND_API_KEY=
RESEND_FROM_EMAIL=noreply@notify.tak-solutions.com
RESEND_ADMIN_EMAILS=
ENVEOF
    warn "Created minimal .env — edit $INSTALL_DIR/.env"
fi

# ── Firewall (firewalld) ────────────────────────────────────────────────────
if command -v firewall-cmd &>/dev/null && systemctl is-active --quiet firewalld 2>/dev/null; then
    info "Opening firewall ports (TCP)..."
    # shellcheck disable=SC1090
    set -a && source "$INSTALL_DIR/.env" 2>/dev/null && set +a || true
    for port in "${WEB_PORT:-5000}" "${AIS_FEEDER_PORT:-10110}"; do
        firewall-cmd --permanent --add-port="${port}/tcp" 2>/dev/null || true
    done
    firewall-cmd --reload 2>/dev/null || true
    ok "Firewall updated"
else
    warn "firewalld not active — open WEB_PORT and AIS_FEEDER_PORT manually if needed"
fi

# ── CLI: taknet-ais ───────────────────────────────────────────────────────────
cat > /usr/local/bin/taknet-ais << CLIEOF
#!/usr/bin/env bash
set -e
INSTALL_DIR="$INSTALL_DIR"
cd "\$INSTALL_DIR" || { echo "Error: \$INSTALL_DIR not found"; exit 1; }

REPO_URL="$REPO_URL"

case "\${1:-help}" in
    start)
        docker compose up -d --build
        ;;
    stop)
        docker compose down
        ;;
    restart)
        docker compose restart \${2:-}
        ;;
    status)
        echo "=== TAKNET-PS AIS Aggregator ==="
        echo "Version: \$(cat VERSION 2>/dev/null || echo unknown)"
        echo ""
        docker compose ps
        ;;
    logs)
        docker compose logs \${2:---tail=50} \${3:-}
        ;;
    update)
        OLD_VERSION=\$(cat VERSION 2>/dev/null || echo "unknown")
        echo "Pulling latest from Git..."
        TMPDIR=\$(mktemp -d)
        git clone --depth 1 "\$REPO_URL" "\$TMPDIR/repo"
        if command -v rsync &>/dev/null; then
            rsync -a --exclude='.git' "\$TMPDIR/repo/" "\$INSTALL_DIR/"
        else
            shopt -s dotglob nullglob
            cp -a "\$TMPDIR/repo"/* "\$INSTALL_DIR/" 2>/dev/null || true
            shopt -u dotglob nullglob
        fi
        rm -rf "\$INSTALL_DIR/.git" "\$TMPDIR"
        bash "\$INSTALL_DIR/install.sh" 2>/dev/null || true
        docker compose pull 2>/dev/null || true
        docker compose up -d --build
        NEW_VERSION=\$(cat VERSION 2>/dev/null || echo "unknown")
        echo "Updated from v\$OLD_VERSION to v\$NEW_VERSION"
        ;;
    rebuild)
        docker compose up -d --build --force-recreate
        ;;
    help|*)
        echo "Usage: taknet-ais <command> [args]"
        echo ""
        echo "Commands:"
        echo "  start      Start all services"
        echo "  stop       Stop all services"
        echo "  restart    Restart all or one service: taknet-ais restart dashboard"
        echo "  status     Show version and container status"
        echo "  logs       docker compose logs (optional service name)"
        echo "  update     Clone latest from Git, re-run install.sh, rebuild"
        echo "  rebuild    Force recreate all containers"
        ;;
esac
CLIEOF
chmod +x /usr/local/bin/taknet-ais
ok "CLI installed: taknet-ais"

# ── Compose up ─────────────────────────────────────────────────────────────
info "Building and starting containers..."
cd "$INSTALL_DIR"
for cname in taknet-ais-dashboard taknet-ais-proxy taknet-ais-core taknet-aisstream-connector taknet-vessel-merger; do
    docker rm -f "$cname" 2>/dev/null || true
done
docker compose up -d --build

[[ -n "${CLEANUP_DIR:-}" ]] && rm -rf "$CLEANUP_DIR"

# shellcheck disable=SC1090
set -a && source "$INSTALL_DIR/.env" 2>/dev/null && set +a || true
IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost)"

echo ""
echo "=========================================="
echo -e "  ${GREEN}TAKNET-PS AIS Aggregator v${VERSION} — Installed${NC}"
echo "=========================================="
echo ""
echo "  Dashboard:      http://${IP}:${WEB_PORT:-5000}"
echo "  AIS feeder TCP: ${IP}:${AIS_FEEDER_PORT:-10110}  (NMEA / AIVDM)"
echo ""
echo "  CLI:     taknet-ais status"
echo "  Config:  $INSTALL_DIR/.env"
echo "  Update:  taknet-ais update"
echo ""
