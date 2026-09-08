#!/usr/bin/env bash
# Run from the project root. Stops and removes containers/networks (and the clab lab if present).
cd "$(dirname "$0")/.."
docker compose down -v --remove-orphans
docker compose -f docker-compose.clab.yml down --remove-orphans 2>/dev/null || true
echo "cleaned up"
