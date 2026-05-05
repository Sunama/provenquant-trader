#!/usr/bin/env bash
# ProvenQuant Trader — one-command setup for first-time users
set -euo pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BLUE}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
step()    { echo -e "\n${BOLD}${CYAN}▶ $*${RESET}"; }
ask()     { echo -e "${YELLOW}$*${RESET}"; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║      ProvenQuant Trader — Setup          ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${RESET}"
echo ""

# ── 1. Check Docker ───────────────────────────────────────────────────────────
step "Checking requirements"

if ! command -v docker &>/dev/null; then
    error "Docker is not installed."
    echo "  Please install Docker Desktop from: https://www.docker.com/products/docker-desktop/"
    exit 1
fi

# Detect whether sudo is needed to run Docker
# Try without sudo first; fall back to sudo if permission is denied.
DOCKER="docker"
if ! docker info &>/dev/null; then
    if sudo docker info &>/dev/null 2>&1; then
        DOCKER="sudo docker"
        warn "Docker requires sudo on this machine — all docker commands will use sudo"
    else
        error "Docker daemon is not running."
        echo "  Please start Docker Desktop (or run: sudo systemctl start docker) and try again."
        exit 1
    fi
fi

# Prefer 'docker compose' (v2) plugin over legacy 'docker-compose' (v1)
if $DOCKER compose version &>/dev/null 2>&1; then
    COMPOSE="$DOCKER compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE="${DOCKER%docker}docker-compose"   # keeps sudo prefix if present
else
    error "Docker Compose is not available."
    echo "  Please install Docker Desktop (it includes Compose)."
    exit 1
fi

success "Docker $(docker --version | awk '{print $3}' | tr -d ',')"

# ── 2. Create .env if missing ─────────────────────────────────────────────────
step "Configuration"

if [ -f ".env" ]; then
    success ".env already exists — skipping"
else
    info "Creating .env from template…"
    cp .env.template .env

    # Generate random secrets so users don't have to
    gen_secret() { openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32; }

    SERVER_SECRET=$(gen_secret)
    POSTGRES_PASSWORD=$(gen_secret)
    TRADER_POSTGRES_PASSWORD=$(gen_secret)
    REDIS_PASSWORD=$(gen_secret)
    RABBITMQ_PASSWORD=$(gen_secret)

    # Substitute generated values into .env
    sed -i "s/^SERVER_SECRET=.*/SERVER_SECRET=${SERVER_SECRET}/" .env
    sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${POSTGRES_PASSWORD}/" .env
    sed -i "s/^TRADER_POSTGRES_PASSWORD=.*/TRADER_POSTGRES_PASSWORD=${TRADER_POSTGRES_PASSWORD}/" .env
    sed -i "s/^REDIS_PASSWORD=.*/REDIS_PASSWORD=${REDIS_PASSWORD}/" .env
    sed -i "s/^RABBITMQ_PASSWORD=.*/RABBITMQ_PASSWORD=${RABBITMQ_PASSWORD}/" .env

    success ".env created with random secrets"

    echo ""
    ask "  Optional: enter your ProvenQuant API key (press Enter to skip):"
    read -r PQKEY
    if [ -n "$PQKEY" ]; then
        sed -i "s/^PROVENQUANT_API_KEY=.*/PROVENQUANT_API_KEY=${PQKEY}/" .env
        success "ProvenQuant API key saved"
    else
        info "Running in standalone mode (no ProvenQuant integration)"
    fi
fi

# ── 3. Build images ───────────────────────────────────────────────────────────
step "Building Docker images (this may take a few minutes on first run)"

$COMPOSE build --quiet
success "Images built"

# ── 4. Start services ─────────────────────────────────────────────────────────
step "Starting services"

$COMPOSE up -d postgres redis rabbitmq
info "Waiting for Postgres to be ready…"

MAX_WAIT=60
WAITED=0
until $COMPOSE exec -T postgres pg_isready -U postgres &>/dev/null; do
    sleep 2
    WAITED=$((WAITED + 2))
    if [ $WAITED -ge $MAX_WAIT ]; then
        error "Postgres did not become ready within ${MAX_WAIT}s"
        $COMPOSE logs postgres | tail -20
        exit 1
    fi
    echo -n "."
done
echo ""
success "Postgres is ready"

$COMPOSE up -d
success "All services started"

# ── 5. Run migrations ─────────────────────────────────────────────────────────
step "Setting up database"

info "Waiting for backend to be ready…"
sleep 5

$COMPOSE exec -T backend alembic upgrade head
success "Database migrations applied"

# ── 6. Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║   ✓  ProvenQuant Trader is running!      ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}API${RESET}    → http://localhost:8001"
echo -e "  ${BOLD}Docs${RESET}   → http://localhost:8001/api/openapi.json"
echo -e "  ${BOLD}Flower${RESET} → http://localhost:5556  (task monitor)"
echo ""
echo -e "  ${BOLD}To start trading with the example RSI strategy:${RESET}"
echo -e "  ${CYAN}$COMPOSE exec backend python tasks.py start-trader --strategy strategies.example_rsi.RSIStrategy${RESET}"
echo ""
echo -e "  ${BOLD}To check your paper balance:${RESET}"
echo -e "  ${CYAN}$COMPOSE exec backend python tasks.py paper-balance${RESET}"
echo ""
echo -e "  ${BOLD}To stop everything:${RESET}"
echo -e "  ${CYAN}$COMPOSE down${RESET}"
echo ""
