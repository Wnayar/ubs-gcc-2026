#!/usr/bin/env bash
# Wake a Render free-plan service and prove it is ready for a grader run.
#
#   ./scripts/warm.sh https://<service>.onrender.com [expected-commit]
#
# Free services spin down after ~15 idle minutes and take ~50 s to wake, but the
# SHOWDOWN coordinator allows 5 s per /move and forfeits a leg after five
# failures in a row. A cold service therefore scores a clean 0 on every leg
# without a single hand being played. Run this immediately before submitting.
set -u
BASE="${1:?usage: warm.sh <base-url> [expected-commit]}"
WANT="${2:-}"

echo "waking $BASE ..."
START=$(date +%s)
for i in $(seq 1 40); do
  BODY=$(curl -s --max-time 90 "$BASE/health" 2>/dev/null)
  CODE=$?
  if [ $CODE -eq 0 ] && [ -n "$BODY" ]; then
    T=$(curl -s -o /dev/null -w '%{time_total}' --max-time 90 "$BASE/health")
    COMMIT=$(printf '%s' "$BODY" | sed -n 's/.*"commit":"\([^"]*\)".*/\1/p')
    echo "  awake after $(( $(date +%s) - START ))s — commit $COMMIT, /health in ${T}s"
    # a warm dyno answers in well under a second; keep pinging until it does
    if awk "BEGIN{exit !($T < 1.0)}"; then
      if [ -n "$WANT" ] && [ "${COMMIT:0:${#WANT}}" != "$WANT" ]; then
        echo "  WARNING: serving $COMMIT, expected $WANT — this service is building a different branch"
        exit 2
      fi
      echo "  READY — submit now, and do not leave it idle for 15 minutes"
      exit 0
    fi
  fi
  sleep 5
done
echo "  FAILED to wake $BASE — check the Render dashboard before submitting"
exit 1
