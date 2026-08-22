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
check "square" -X POST "$BASE/square" -H 'Content-Type: application/json' -d '{"value": 12}'
check "square bad input" -X POST "$BASE/square" -H 'Content-Type: application/json' -d '{"value": "x"}'
check "ghost-chains health" "$BASE/ghost-chains/health"
check "ghost-chains reset" -X POST "$BASE/ghost-chains/reset" \
  -H 'Content-Type: application/json' -d '{"clearTransactions": true}'
check "ghost-chains transactions (statement example)" \
  -X POST "$BASE/ghost-chains/transactions" -H 'Content-Type: application/json' -d '{
    "transactions": [
      {"txId": "smoke_1", "fromUserId": "meridian_holdings", "toUserId": "apex_logistics",
       "amount": 370.0, "createdAt": "2026-06-08T12:00:00Z"},
      {"txId": "smoke_2", "fromUserId": "apex_logistics", "toUserId": "cascade_payments",
       "amount": 100.0, "createdAt": "2026-06-08T12:01:00Z"},
      {"txId": "smoke_3", "fromUserId": "cascade_payments", "toUserId": "meridian_holdings",
       "amount": 100.0, "createdAt": "2026-06-08T12:02:00Z"}
    ]
  }'
# leave no smoke-test state behind in the graph the grader will use
check "ghost-chains reset (cleanup)" -X POST "$BASE/ghost-chains/reset" \
  -H 'Content-Type: application/json' -d '{"clearTransactions": true}'

check "mcp tools/list (the address tool-box tries first)" \
  -X POST "$BASE/mcp/" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
check "mcp calculate" \
  -X POST "$BASE/mcp" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/call",
       "params": {"name": "calculate", "arguments": {"expression": "2 + 2"}}}'

# SHOWDOWN: the guide's own worked example. Holding a 3 against a community 5 and
# facing 18 into 32 — the reply should be {"action":"fold"}, and must never be a
# non-200 (a bad response is substituted with check; five in a row forfeit).
check "showdown /move" -X POST "$BASE/move" -H 'Content-Type: application/json' -d '{
  "match_id":"smoke","round":"post_reveal","your_number":3,"community_number":5,
  "your_seat":0,"button_seat":1,"your_stack":185,"starting_stack":200,
  "hand_number":6,"total_hands":100,"small_blind":1,"big_blind":2,
  "pot":32,"to_call":18,"min_raise_to":36,"max_raise_to":185,
  "legal_actions":["fold","call","raise"],
  "players":[{"seat":0,"name":"you","bet_this_round":0,"stack":185,"chip_delta":-8},
             {"seat":1,"name":"Gaston","bet_this_round":18,"stack":183,"chip_delta":8}],
  "current_hand_actions":[],"recent_hands":[]}'
check "showdown /move garbage body" -X POST "$BASE/move" -H 'Content-Type: application/json' -d 'not json'

