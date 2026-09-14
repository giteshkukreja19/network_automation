#!/usr/bin/env bash
# Run from the project root.   ./scripts/start.sh          (Implementation B, default)
#                              ./scripts/start.sh clab     (Implementation A, cEOS - see README)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
if [ "${1:-}" = "clab" ]; then
  echo "Deploy Containerlab first (README section 7), then:"
  docker compose -f docker-compose.clab.yml up -d --build
else
  docker compose up -d --build
fi
echo -n "waiting for dashboard"
for i in $(seq 1 60); do
  curl -fsS http://127.0.0.1:5000/healthz >/dev/null 2>&1 && { echo " - up"; echo "Open http://localhost:5000"; exit 0; }
  echo -n "."; sleep 2
done
echo; echo "dashboard did not become healthy; run: docker compose logs"; exit 1
