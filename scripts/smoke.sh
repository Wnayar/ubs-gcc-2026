#!/usr/bin/env bash
# Smoke-test a running instance.
#   ./scripts/smoke.sh                                # local
#   ./scripts/smoke.sh https://<service>.onrender.com # deployed
set -u
BASE="${1:-http://localhost:8000}"

check() {
  local desc="$1"; shift
  echo "== $desc"
  curl -sS -w '\n   -> HTTP %{http_code} in %{time_total}s\n' "$@"
  echo
}

check "health" "$BASE/health"
check "square" -X POST "$BASE/square" -H 'Content-Type: application/json' -d '{"number": 12}'
check "square bad input" -X POST "$BASE/square" -H 'Content-Type: application/json' -d '{"number": "x"}'
