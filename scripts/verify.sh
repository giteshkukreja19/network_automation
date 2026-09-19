#!/usr/bin/env bash
# Run from the project root after start.sh. Exits non-zero if ANY check fails.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
chk() { if eval "$2" >/dev/null 2>&1; then echo "PASS  $1"; else echo "FAIL  $1"; fail=1; fi; }
chk "Docker Engine running"            "docker info"
chk "Flask dashboard HTTP 200"         "curl -fsS -o /dev/null http://127.0.0.1:5000/"
chk "FastAPI controller HTTP 200"      "curl -fsS -o /dev/null http://127.0.0.1:8000/health"
chk "Router SSH port answers (2222)"   "nc -z -w3 127.0.0.1 2222"
chk "Switch SSH port answers (2223)"   "nc -z -w3 127.0.0.1 2223"
echo "--- live integration tests (Netmiko, NAPALM, config + readback) ---"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
$PY -m pytest -m integration -v || fail=1
[ $fail -eq 0 ] && echo "ALL CHECKS PASSED" || { echo "SOME CHECKS FAILED"; exit 1; }
