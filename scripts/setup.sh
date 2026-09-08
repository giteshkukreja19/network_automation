#!/usr/bin/env bash
# Run from the project root:  ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== Docker =="; docker info --format 'Engine {{.ServerVersion}} on {{.OSType}}/{{.Architecture}}'
echo "== Python =="; python3 --version
python3 -c 'import sys; assert sys.version_info >= (3,11), "need Python >= 3.11"'
[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }
echo "== Host venv (only needed to run the tests) =="
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r backend/requirements.txt -r controller/requirements.txt pytest httpx
echo "== Building images (first build downloads Alpine/FRR packages; a few minutes) =="
docker compose build
echo "setup complete -> next: ./scripts/start.sh"
