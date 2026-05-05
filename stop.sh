#!/usr/bin/env bash
set -euo pipefail

CYAN='\033[0;36m'; BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RESET='\033[0m'

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

echo -e "\n${BOLD}${CYAN}▶ Stopping ProvenQuant Trader…${RESET}"
$COMPOSE down
echo -e "\n${GREEN}All services stopped.${RESET}\n"
