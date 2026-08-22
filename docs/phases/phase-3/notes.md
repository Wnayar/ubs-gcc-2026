# Phase 3 (our folder) — Ghost Chains, the challenge's **Phase 1** ("Follow the Money")

> Folder numbering is ours and sequential; this is Ghost Chains **Phase 1 of 3**.
> Ghost Chains Phases 2 and 3 unlock later in the event and will become our
> phase-4 / phase-5 folders.

- **PDF:** `statement.pdf` in this folder (from
  <https://ghost-chains-0fdb9aeda564.herokuapp.com/phase/1>, 10 pages)
- **Endpoints required:** `GET /ghost-chains/health`, `POST /ghost-chains/reset`,
  `POST /ghost-chains/transactions`
- **Submitted to controller:** no
- **Score:**

## Event and scoring rules (page 1–2)

- Three **cumulative** phases: a Phase 2 evaluation re-tests Phase 1, a Phase 3
  evaluation re-tests Phases 1 and 2. Never break earlier behaviour.
- Two scored dimensions: **Detection Quality** (do we rank more suspicious
  transactions above less suspicious ones) and **Structural Consistency** (do we
  behave coherently across structurally related scenarios). The statement warns
  outright: "Systems built on principled graph models are expected to outperform
  implementations tuned to specific patterns." → build the model, don't fit the
  five examples.
- **Absolute scores do not need to match a reference.** Only the ranking matters.
- **Earliness bonus** for evaluating early within a phase's window → get a working
  system registered and evaluated as soon as it is green.
- Diagnostics on disagreement: an array of observation categories with a severity,
  e.g. `STRUCTURAL_DEVIATION: Moderate, TEMPORAL_DEVIATION: Low`. Phase 1 can emit
  only `STRUCTURAL_DEVIATION` and `TEMPORAL_DEVIATION`. No absolute scores are
  disclosed. If no disagreement, no diagnostic payload.

## Endpoints (pages 2–4)

### `GET /ghost-chains/health`
```json
{ "status": "ok" }
```

### `POST /ghost-chains/reset`
Request and response are both:
```json
{ "clearTransactions": true }
```
Behaviour: clear all transaction state, graph construction, caches and derived
structures — "restore the system to a clean initial state equivalent to startup."

### `POST /ghost-chains/transactions`
Request fields — `transactions`: array of objects with

| field | required | meaning |
|---|---|---|
| `txId` | yes | unique string id |
| `fromUserId` | yes | sending entity ("user" = any identity: account, legal entity, counterparty) |
| `toUserId` | yes | receiving entity |
| `amount` | yes | number |
| `createdAt` | yes | ISO 8601 timestamp |
| `ipAddress` | no | omitted when unknown |
| `deviceId` | no | omitted when unknown |

"Optional fields may be absent on any transaction; this must not cause processing
to fail." Response — `transactions`: array of `{txId, riskScore}` where
`riskScore` ∈ [0.0, 1.0].

Behaviour: score each transaction immediately as it is processed; process a batch
**sequentially in order**; **preserve input ordering** in the response.

## Examples from the statement (verbatim)

Request (page 4):
```json
{
  "transactions": [
    { "txId": "tx_meridian_001", "fromUserId": "meridian_holdings", "toUserId": "apex_logistics",
      "amount": 370.0, "createdAt": "2026-06-08T12:00:00Z" },
    { "txId": "tx_cascade_014", "fromUserId": "cascade_payments", "toUserId": "horizon_capital",
      "amount": 100.0, "createdAt": "2026-06-08T12:01:00Z" }
  ]
}
```
Response (page 4):
```json
{
  "transactions": [
    { "txId": "tx_meridian_001", "riskScore": 0.0 },
    { "txId": "tx_cascade_014", "riskScore": 0.0 }
  ]
}
```
→ two structurally isolated transactions both score **exactly 0.0**. This is the
only place the statement pins an absolute value, and our model reproduces it.

## State and execution model (pages 5–6)

- **Streaming:** score using only information available at that point; update state
  incrementally, no reprocessing of history.
- **Lookback window W = 24 hours.** Only transactions created in the most recent 24
  hours are active. Expired ones must be removed from graph state and must not
  influence scoring. "Be precise about boundary conditions."
- **Ordering:** in-request order is processing order; across requests, arrival order
  defines state evolution.
- **Idempotency:** each `txId` is unique. A duplicate `txId` with an identical
  payload returns the original score and makes no state change. "Consider what
  should happen if the payload differs." (left to us — see assumptions)
- Scores are **relative** suspiciousness in [0,1], not calibrated probabilities.
  Identical inputs after a reset must produce identical outputs.
- **Forward compatibility:** later phases add optional fields. Ignore unknown or
  absent fields gracefully; never reject a transaction for unrecognised attributes.
- **Performance:** continuous streaming, memory bounded by the active window.

## The Phase 1 model — "Follow the Money" (pages 7–10)

Core principle, verbatim: "Each incoming transaction updates a directed graph of
entities. Risk score reflects how the transaction changes the graph's **structural
signal**: the combined effect of **new or shortened paths** between entities, not
any single graph feature. A higher risk score corresponds to a greater increase in
the graph's **capacity to support recurring flow**." Edge cases the examples do not
cover (degenerate or repeated edges) are explicitly left to us.

### The five worked examples (last transaction of each is the one scored)

| # | name | sequence | interpretation |
|---|---|---|---|
| 1 | Isolated | M→A | no pattern yet |
| 2 | Extension | M→A, **A→C** | funds move onward to a new counterparty |
| 3 | Convergence | M→A, M→H, A→S, **H→S** | two paths from M arrive at the same destination |
| 4 | Return | M→A, A→C, C→O, **O→A** | funds return to a counterparty upstream of the sender |
| 5 | Multi-Loop | M→A, A→C, C→M, A→N, **N→M** | two independent return routes converge on M |

(M = Meridian Holdings, A = Apex Logistics, C = Cascade Payments, H = Horizon
Capital, S = Sterling Bridge, O = Oakridge Imports, N = Nimbus Trading.)

### Required ordering (page 10, verbatim constraints)

- Example 1 receives the **lowest** score of the five.
- Example 4 is **meaningfully higher** than Example 2.
- Example 5 is **meaningfully higher** than Example 4 — "two independent return
  paths converging on the same node represent a stronger structural signal than a
  single return."
- Convergence (3) is "stronger than simple extension, but not necessarily as
  suspicious as a return path" → 2 < 3 < 4.

### Our model

For an incoming edge `u → v`, all measured against the graph **before** the edge is
added (BFS from/to `u` and `v` gives ancestors `A_u`, `A_v` and descendants `D_u`,
`D_v` with distances):

| component | definition | what it captures |
|---|---|---|
| `reach` | `\|A_u \ A_v\| × \|D_v \ D_u\| − 1` | newly connected entity pairs, minus the trivial `(u,v)` pair itself |
| `shorten` | `#{x : d(x,u) + 1 < d(x,v)}` | the edge is a genuine shortcut to `v` |
| `converge` | `\|A_u ∩ A_v\|` | entities that could already reach `v` and now gain a second, distinct route |
| `loop` | `\|SCC(v)\| − 1` when `v` already reached `u` | size of the recurring-flow structure the edge closes |
| `returns` | in-edges of `v` from inside `SCC(v)` − 1 | **independent** return routes converging on `v` (what separates ex. 5 from ex. 4) |

Each is squashed by `x/(x+k)` (0 at 0, saturating) and combined with fixed weights
summing to 1.0, so the score is in [0,1] by construction:
`0.22·reach + 0.08·shorten + 0.22·converge + 0.28·loop + 0.20·returns`, the last two
only when the edge closes a loop. `SCC(v)` after insertion is derived without extra
traversal as `(D_v ∪ {v}) ∩ (A_v ∪ A_u)`.

Scores this produces for the five examples: **0.0 < 0.055 < 0.073 < 0.36 < 0.488** —
every required inequality holds, example 1 is exactly 0.0 as the sample response
shows, and the 4→2 and 5→4 gaps are large.

## Assumptions we made

- **"Now" is event time, not wall clock.** The window is anchored to the greatest
  `createdAt` seen so far (monotonic), not `datetime.now()` — the sample data is
  dated 2026-06-08, so wall-clock expiry would drop everything instantly.
- **Window boundary: inclusive.** A transaction is active while
  `now − createdAt ≤ 24h`; it expires strictly past 24h. "Within the most recent 24
  hours" reads as the closed interval. One constant flips this if the grader
  reports `TEMPORAL_DEVIATION`.
- **Out-of-order arrivals** are scored against the window anchored at the newest
  timestamp seen; the clock never moves backwards.
- **Duplicate `txId` with a *different* payload** → we return the original score and
  make no state change, i.e. `txId` is the idempotency key. The statement invites a
  choice here; this one can never corrupt graph state and never fails.
- **Self-transfer (`fromUserId == toUserId`)** → 0.0. A degenerate 1-node loop adds
  no connectivity between distinct entities.
- **Repeated edge** (same pair, new `txId`) → the structural delta terms fall to 0;
  only the recurring-flow terms remain, so a repeat inside a loop still scores
  above an isolated repeat. Rationale: it adds no new structure but does exercise
  an existing one. Repetition-as-value-signal is Ghost Chains Phase 3's theme.
- **`clearTransactions: false`** → we do not clear and echo `false` back. `true` or
  absent → clear and echo `true`.
- **Malformed transactions** (missing required field, unparseable `createdAt`) →
  422 for the request; never a 500. Unknown extra fields are ignored, per the
  forward-compatibility rule.
- **Traversal cap:** each BFS is capped at 50 000 visited nodes so a pathological
  stream cannot stall the free-plan instance. Never reached at realistic sizes.
- Scores are rounded to 6 decimals for stable, comparable output.

## Measured throughput (this laptop, random-graph worst case)

| active graph | cost |
|---|---|
| 200 entities / ~2 000 live edges | 0.30 ms per transaction |
| 1 000 entities / ~5 000 live edges | 0.97 ms per transaction |
| 2 000 entities / ~17 000 live edges | 3.30 ms per transaction |

Four BFS per transaction over the active window. Random edges are the worst case
(one giant strongly connected component); clustered real traffic is cheaper. On the
Render free instance assume several times slower — a stream of a few thousand
transactions is comfortable, tens of thousands in a single request is not. If an
evaluation ever times out, the ready mitigation is a hop-limited BFS (cap at ~6
hops), which bounds the work per transaction at the cost of ignoring very long
chains; it is a one-constant change in `app/routers/phase3.py`.

## Clarifications from challenge developers

- Q: Is a transaction created exactly 24h before the current one still active? → A: …
- Q: Duplicate `txId` with a differing payload — original score, or an error? → A: …
- Q: Should a self-transfer or a repeated identical edge carry any structural
  signal? → A: …
- Q: Is "now" for the lookback window the newest `createdAt` seen, or wall clock? → A: …

## Failed test cases and what fixed them

-
