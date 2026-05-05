#!/usr/bin/env bash
set -euo pipefail

CYAN='\033[0;36m'; BOLD='\033[1m'; YELLOW='\033[1;33m'; RESET='\033[0m'

DOCKER="docker"
if ! docker info &>/dev/null 2>&1; then
    if sudo docker info &>/dev/null 2>&1; then
        DOCKER="sudo docker"
    fi
fi

if $DOCKER compose version &>/dev/null 2>&1; then
    COMPOSE="$DOCKER compose"
else
    COMPOSE="${DOCKER%docker}docker-compose"
fi

echo ""
echo -e "${BOLD}${CYAN}── ProvenQuant Trader Status ───────────────${RESET}"
echo ""

$COMPOSE ps

echo ""
echo -e "${BOLD}${CYAN}── Paper Balance ───────────────────────────${RESET}"
if $COMPOSE ps backend 2>/dev/null | grep -q "running\|Up"; then
    $COMPOSE exec -T backend python tasks.py paper-balance 2>/dev/null || echo -e "${YELLOW}  (backend not ready yet)${RESET}"
else
    echo -e "${YELLOW}  Backend is not running. Run ./setup.sh first.${RESET}"
fi
echo ""
