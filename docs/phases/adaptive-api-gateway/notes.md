# Adaptive API Gateway — the `/adapt-slo` guide

> **This supersedes `docs/phases/phase-2/`.** Same challenge, same endpoint: that
> folder holds the earlier `/adapt` guide, which covered only the adaptation
> half. This one adds SLO metrics and, on one point, **contradicts** it — see
> "What changed" below. The implementation stays in `app/routers/phase2.py`
> because that module already owns `POST /solve`.

- **PDF:** `statement.pdf` in this folder, printed from
  <https://adaptive-api-gateway-be2304567894.herokuapp.com/adapt-slo> (3 pages)
- **`statement-full.md`:** the same guide from
  `/static/adapt-slo.md` — **the authoritative version**. The PDF is printed
  from `/static/adapt-slo-amb.md`, the deliberately *ambiguous* variant (2,027
  bytes against 3,612), which omits both rule sections entirely. Everything in
  "The rules, verbatim" below comes from the full file and is not in the PDF.
- **Endpoints required:** `POST /solve` — already exists, now returns a second
  key
- **Submitted to controller:** no
- **Score:**

## What changed from the `/adapt` guide

| | `/adapt` (phase-2) | `/adapt-slo` (this one) |
|---|---|---|
| request payload | `adaptInput` only | `adaptInput` + `heartbeats` + `sloQuery` |
| response | `{adaptOutput}` | `{adaptOutput, sloOutput}` |
| unknown/missing priority | **0** (our guess — the old guide said nothing) | **2**, stated explicitly |

The priority default is a real correction, not an addition: phase-2 chose 0 in
the absence of any rule, and the full guide now says 2. Phase 2 was never
submitted, so nothing scored depends on the old behaviour.

## The rules, verbatim (full guide only)

### Part 1: Adaptation Rules

> - `adaptInput.user.id` -> `adaptOutput.id`
> - `adaptInput.user.fullName` -> `adaptOutput.name`
> - `adaptInput.action` -> lowercase string in `adaptOutput.action`
> - `adaptInput.metadata.priority` mapping: `LOW` -> `1`, `MEDIUM` -> `2`, `HIGH` -> `3`
>
> Robustness expectations:
> - Ignore unknown fields.
> - **If priority is missing or unrecognized, default to `2`.**
> - The output should be deterministic for the same logical input.

### Part 2: SLO Rules

> Filtering rules:
> - Keep only heartbeats whose `service` matches `sloQuery.service`.
> - If `sloQuery.since` exists, keep only heartbeats where `timestamp >= since`;
>   otherwise keep all.
> - **Ignore duplicate heartbeats that share the same `(service, timestamp)` pair.**
> - Handle out-of-order input correctly.
>
> Metrics:
> - `availability = OK_count / total_count`
> - `p95LatencyMs = nearest-rank p95 latency of the relevant rows`
>
> If no rows remain after filtering, return `availability: 0.0`, `p95LatencyMs: 0`.

### Success criteria

> - `POST /solve` exists and responds with HTTP 200,
> - the response contains **both** `adaptOutput` and `sloOutput`,
> - the adaptation mapping is correct,
> - the priority defaults and lowercasing behave as expected,
> - the SLO availability and p95 calculations are correct.

## The worked example, verbatim

Request:

```json
{ "payload": "ewoJImFkYXB0SW5wdXQiOiB7...fQ==" }
```

(the full base64 is the `SAMPLE_PAYLOAD` constant in `tests/test_phase2.py`;
a test decodes it and asserts it matches the JSON below, so a transcription
slip cannot pass silently)

Decodes to:

```json
{
    "adaptInput": {
        "user": { "id": "U42", "fullName": "Jane Doe" },
        "action": "CREATE",
        "metadata": { "priority": "HIGH" }
    },
    "heartbeats": [
        { "service": "auth", "timestamp": 1710000123, "latencyMs": 120, "status": "OK" },
        { "service": "auth", "timestamp": 1710000125, "latencyMs": 180, "status": "FAIL" },
        { "service": "auth", "timestamp": 1710000121, "latencyMs": 95,  "status": "OK" }
    ],
    "sloQuery": { "service": "auth", "since": 1710000123 }
}
```

Must return:

```json
{
    "adaptOutput": { "id": "U42", "name": "Jane Doe", "action": "create", "priority": 3 },
    "sloOutput":   { "availability": 0.5, "p95LatencyMs": 180 }
}
```

### Why the example pins two things the prose leaves open

**`since` is inclusive.** Of the three heartbeats, `1710000121` is before
`since` and drops out. That leaves `1710000123` (OK) and `1710000125` (FAIL) —
one OK of two, `availability = 0.5`, exactly as printed. Read `>` instead of
`>=` and only the FAIL row survives: `availability` would be `0.0`.

**Nearest-rank, not interpolation.** The surviving latencies are `[120, 180]`.
Nearest-rank p95 is `ceil(0.95 x 2) = 2`, the 2nd smallest, `180` — the printed
answer. Linear interpolation (numpy's default) gives `177`, and taking the
lower rank gives `120`. Both are ruled out by the example, and only nearest-rank
always returns a latency that was actually observed.

## What we shipped

`app/routers/phase2.py` gains `sloOutput`; the adaptation half is unchanged
except for the priority default.

- **`sloOutput` is always present**, even when nothing matches, because the
  success criteria say the response contains both keys and the guide defines
  the empty case (`0.0` / `0`) precisely so that it always can.
- Filtering is service match -> `since` -> de-duplicate on `(service, timestamp)`,
  keeping the **first** row seen. Order of input never matters: filtering and
  both metrics are order-independent, and the example's heartbeats are already
  out of order (123, 125, 121).
- `availability` is returned unrounded. The example is exactly `0.5`; rounding
  would be inventing a precision the guide does not state.

## Assumptions we made

- **Duplicate `(service, timestamp)` keeps the first row in input order.** The
  guide says to ignore duplicates but not which to keep. It only matters when
  two rows share a timestamp and disagree on `status` or `latencyMs`.
- **A numeric `priority` passes through unchanged** (`5` -> `5`). The guide's
  default of 2 is for "missing or unrecognized"; a number is already a
  priority, not an unrecognised word. Only `LOW`/`MEDIUM`/`HIGH` are mapped —
  the phase-2 guesses (`CRITICAL` -> 4, `URGENT` -> 4, `NONE` -> 0) are
  **removed**, because the guide makes every unlisted word a 2.
- **`status` is compared case-insensitively**, and anything that is not `OK`
  counts against availability. The guide shows only `OK` and `FAIL`.
- **A missing `sloQuery.service` matches every heartbeat** rather than none.
  With no service named there is nothing to filter on, and returning the
  zero-row answer would throw away data the caller sent.
- **A heartbeat missing `latencyMs` still counts toward availability** but
  contributes no latency; one missing `status` counts as not-OK.
- **`availability` is unrounded**; `p95LatencyMs` is returned as an `int` when
  the observed latency is integral, matching the example's `180`.
- **The response keeps the guide's key order** (`adaptOutput`, then
  `sloOutput`; `availability`, then `p95LatencyMs`) in case the evaluator
  compares JSON text rather than parsed objects.

## Clarifications from challenge developers

- Q: With no `sloQuery` at all, should the response still carry `sloOutput`
  with the zero-row defaults, or omit the key? We always include it. → A: …
- Q: When two heartbeats share `(service, timestamp)` but differ on `status`,
  which one wins? → A: …
- Q: Is `availability` compared exactly or within a tolerance? We return it
  unrounded (`1/3` -> `0.3333333333333333`). → A: …

## Failed test cases and what fixed them

- (none yet — not run against the grader)
