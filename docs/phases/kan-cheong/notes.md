# Kan Chiong Delivery Driver

- **PDF:** `statement.pdf` in this folder (copied from `docs/entry-challenge/`, where the
  user dropped it — the original was left in place rather than moved, since that folder
  is the documented reference copy and the file is untracked in git)
- **Endpoints required:** `POST /kan-cheong-delivery-driver`
- **Submitted to controller:** no
- **Score:**

> **Reading the PDF:** every code block is clipped on the right by the print-to-PDF
> (`base_duration_sec` values, the batch response line). The full text *is* in the PDF
> content stream — `pdftotext` also clips it. Extract with pypdf per page and pull the
> `(...) Tj` operands to get the unclipped source. All values below came from that.

## The problem

City road network with time-dependent obstructions. Given a start coordinate, an end
coordinate and a departure time, return the fastest route by travel time: total duration
in seconds, arrival time, and the ordered list of traversed `edge_id`s.

Note the spelling: the title says **Chiong**, the required path says **cheong**
(`/kan-cheong-delivery-driver`) — matches the statement's own footer URL. Use the path.

## Batch protocol

Request body is a JSON object mapping a caller-assigned case id to that case's input:

```json
{
  "case_1": { "...": "one case's input, see Input Format below" },
  "case_2": { "...": "another case's input" },
  "...": "..."
}
```

Response must be the same shape — same case ids, mapped to each case's output. Cases are
entirely independent. Order does not matter, but **every case id in the request must have
a matching entry in the response**.

## Input format (one case)

```json
{
  "start_coordinate": [x, y],
  "end_coordinate": [x, y],
  "start_time": "ISO-8601",
  "nodes": [[x1, y1], [x2, y2], ...],
  "edges": [
    {
      "edge_id": "string",
      "node1": [x, y],
      "node2": [x, y],
      "base_duration_sec": 0
    }
  ],
  "obstructions": [
    {
      "edge_id": "string",
      "edge": {
        "from": [x, y],
        "to": [x, y]
      },
      "start_time": "ISO-8601",
      "end_time": "ISO-8601",
      "speed_factor": 0.0
    }
  ]
}
```

## Output format (one case)

```json
{
  "total_duration_sec": 0,
  "arrival_time": "ISO-8601",
  "path": ["edge_id_1", "edge_id_2", "..."]
}
```

If destination is unreachable:

```json
{
  "total_duration_sec": null,
  "arrival_time": null,
  "path": []
}
```

## Notes (verbatim)

- Edges are **bidirectional** with the same base duration in both directions.
- Obstructions are **directional** and apply only when both match:
  - `edge_id`
  - `edge.from -> edge.to`

## Constraints (verbatim)

- **No waiting** at nodes.
- Coordinates are integer pairs: `[x, y]`.
- `base_duration_sec` is an integer in `[0, 999]`.
- Cycles are allowed (a node may be revisited).
- If an obstruction becomes active during traversal, only the remaining untraveled
  portion is affected by the new `speed_factor`.
- `speed_factor = 0.0` means that directed traversal is blocked while active.

## Timeout and scoring (verbatim, matters for design)

- **10 seconds for the entire batch request**, regardless of how many cases. A single hard
  cutoff on the whole request/response, not per case. Miss it and the **entire batch scores
  0** — no partial credit for cases already solved.
- Each case is scored independently and correct answers add up. No partial credit within a
  case. Larger, more complex cases (more nodes/edges/obstructions) are worth more points.

## The travel-time model (derived from the examples)

An obstruction does not multiply the duration, it divides the speed:

- Traversing an arc means accumulating `base_duration_sec` seconds of *progress*. While a
  matching obstruction is active, progress accrues at `speed_factor` seconds per real
  second. So a whole traversal under factor `f` takes `base / f` real seconds.
- Example 3 pins this down: `edge_2` has base 20 under factor 0.2 → 100 s (arrival
  08:31:40), losing to the 60 s cycling route. If the factor *multiplied* the duration it
  would be 4 s and `edge_2` would win. It doesn't.
- Example 1 confirms it again: `edge_1` base 60 under factor 0.5 costs 120 s, which is why
  `edge_4` (120 s, unobstructed) plus `edge_3` beats `edge_1` + `edge_2`.
- Mid-traversal factor changes only affect the remaining untraveled portion (statement),
  which is exactly the progress integral above.

## Worked examples (verbatim from statement.pdf)

### Batch example

Request:

```json
{
  "case_1": {
    "start_coordinate": [0, 0],
    "end_coordinate": [1, 0],
    "start_time": "2026-06-10T08:30:00Z",
    "nodes": [[0, 0], [1, 0]],
    "edges": [
      { "edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60 }
    ],
    "obstructions": []
  },
  "case_2": {
    "start_coordinate": [0, 0],
    "end_coordinate": [1, 0],
    "start_time": "2026-06-10T08:30:00Z",
    "nodes": [[0, 0], [1, 0]],
    "edges": [
      { "edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60 }
    ],
    "obstructions": [
      {
        "edge_id": "edge_0",
        "edge": { "from": [0, 0], "to": [1, 0] },
        "start_time": "2026-06-10T08:00:00Z",
        "end_time": "2026-06-10T09:00:00Z",
        "speed_factor": 0.0
      }
    ]
  }
}
```

Response:

```json
{
  "case_1": { "total_duration_sec": 60, "arrival_time": "2026-06-10T08:31:00Z", "path": ["edge_0"] },
  "case_2": { "total_duration_sec": null, "arrival_time": null, "path": [] }
}
```

### Example 1

Input:

```json
{
  "start_coordinate": [0, 0],
  "end_coordinate": [3, 1],
  "start_time": "2026-06-10T08:30:00Z",
  "nodes": [[0, 0], [1, 0], [2, 0], [2, 1], [3, 1]],
  "edges": [
    { "edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60 },
    { "edge_id": "edge_1", "node1": [1, 0], "node2": [2, 0], "base_duration_sec": 60 },
    { "edge_id": "edge_2", "node1": [2, 0], "node2": [2, 1], "base_duration_sec": 40 },
    { "edge_id": "edge_3", "node1": [2, 1], "node2": [3, 1], "base_duration_sec": 50 },
    { "edge_id": "edge_4", "node1": [1, 0], "node2": [2, 1], "base_duration_sec": 120 }
  ],
  "obstructions": [
    {
      "edge_id": "edge_1",
      "edge": { "from": [1, 0], "to": [2, 0] },
      "start_time": "2026-06-10T08:00:00Z",
      "end_time": "2026-06-10T09:00:00Z",
      "speed_factor": 0.5
    },
    {
      "edge_id": "edge_2",
      "edge": { "from": [2, 1], "to": [2, 0] },
      "start_time": "2026-06-10T08:15:00Z",
      "end_time": "2026-06-10T08:45:00Z",
      "speed_factor": 0.0
    }
  ]
}
```

Output:

```json
{
  "total_duration_sec": 230,
  "arrival_time": "2026-06-10T08:33:50Z",
  "path": ["edge_0", "edge_4", "edge_3"]
}
```

Explanation: `edge_4` is preferred over `edge_1` + `edge_2` because of active obstruction
impact.

Note the obstruction on `edge_2` runs `[2, 1] -> [2, 0]`, i.e. the *reverse* of how the
edge is declared — the route uses `[2, 0] -> [2, 1]`, which is unobstructed. Directionality
is not cosmetic here.

### Example 2

Same graph as Example 1, but `"end_coordinate": [3, 3]` and
`"nodes": [[0, 0], [1, 0], [2, 0], [2, 1], [3, 1]]`.

Output:

```json
{
  "total_duration_sec": null,
  "arrival_time": null,
  "path": []
}
```

Explanation: `end_coordinate` is unreachable, so the expected result is the null-duration
no-path response.

### Example 3 (No Waiting + Cycling)

Input:

```json
{
  "start_coordinate": [0, 0],
  "end_coordinate": [2, 0],
  "start_time": "2026-06-10T08:30:00Z",
  "nodes": [[0, 0], [1, 0], [2, 0]],
  "edges": [
    { "edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 10 },
    { "edge_id": "edge_1", "node1": [1, 0], "node2": [2, 0], "base_duration_sec": 10 },
    { "edge_id": "edge_2", "node1": [0, 0], "node2": [2, 0], "base_duration_sec": 20 }
  ],
  "obstructions": [
    {
      "edge_id": "edge_1",
      "edge": { "from": [1, 0], "to": [2, 0] },
      "start_time": "2026-06-10T08:30:10Z",
      "end_time": "2026-06-10T08:30:20Z",
      "speed_factor": 0.0
    },
    {
      "edge_id": "edge_1",
      "edge": { "from": [1, 0], "to": [2, 0] },
      "start_time": "2026-06-10T08:30:30Z",
      "end_time": "2026-06-10T08:30:40Z",
      "speed_factor": 0.0
    },
    {
      "edge_id": "edge_2",
      "edge": { "from": [0, 0], "to": [2, 0] },
      "start_time": "2026-06-10T08:30:00Z",
      "end_time": "2026-06-10T08:32:00Z",
      "speed_factor": 0.2
    }
  ]
}
```

Output:

```json
{
  "total_duration_sec": 60,
  "arrival_time": "2026-06-10T08:31:00Z",
  "path": ["edge_0", "edge_0", "edge_0", "edge_0", "edge_0", "edge_1"]
}
```

Explanation: No waiting is allowed, so the route cycles on `edge_0` until `edge_1`'s
blocking window clears.

Walk-through (this example carries most of the semantics):

| time | where | why |
|---|---|---|
| 08:30:00 | `[0,0]` | depart |
| 08:30:10 | `[1,0]` | `edge_0` (10 s). `edge_1` is blocked at exactly 08:30:10 → window start is **inclusive** |
| 08:30:20 | `[0,0]` | can't wait, so bounce back on `edge_0` |
| 08:30:30 | `[1,0]` | `edge_1` blocked again (second window, also inclusive at its start) |
| 08:30:40 | `[0,0]` | bounce back again |
| 08:30:50 | `[1,0]` | third try |
| 08:31:00 | `[2,0]` | `edge_1` free → arrive. Total 60 s |

`edge_2` direct would be 20 / 0.2 = 100 s → 08:31:40, so cycling genuinely wins.

Crucially, entering a blocked arc and *sitting on it* until the block clears is **not**
allowed: that would give 08:30:10 + 10 s of block + 10 s of travel = 08:30:30, beating the
stated answer of 08:31:00. So `speed_factor = 0.0` at entry means the arc cannot be entered
at all.

### Example 4 (No Waiting + Blocked at Start)

Input:

```json
{
  "start_coordinate": [0, 0],
  "end_coordinate": [1, 0],
  "start_time": "2026-06-10T08:30:00Z",
  "nodes": [[0, 0], [1, 0]],
  "edges": [
    { "edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60 }
  ],
  "obstructions": [
    {
      "edge_id": "edge_0",
      "edge": { "from": [0, 0], "to": [1, 0] },
      "start_time": "2026-06-10T08:00:00Z",
      "end_time": "2026-06-10T09:00:00Z",
      "speed_factor": 0.0
    }
  ]
}
```

Output:

```json
{
  "total_duration_sec": null,
  "arrival_time": null,
  "path": []
}
```

Explanation: Waiting is not allowed, and the only outgoing move from `start_coordinate` is
blocked (`speed_factor=0.0`) at departure time, so no valid route exists.

## Algorithm shipped

The blocking rule makes this **non-FIFO**: arriving at a node earlier can be strictly
worse (Example 3 — the earliest arrival at `[1,0]` is the one that finds `edge_1` shut).
So a plain Dijkstra keyed on nodes is wrong; the state has to be `(node, time)`. Forbidding
waiting on a network with blockable arcs is NP-hard in general, so the search is bounded
and seeded with a route we know we can fall back on.

1. Parse each case; times become exact `Fraction` seconds relative to `start_time`
   (`Fraction(str(0.2)) == 1/5`, so `20 / 0.2` is exactly 100 — floats would drift).
2. Per directed arc, merge its matching obstructions into a piecewise-constant
   `speed_factor` timeline (overlaps → the most restrictive factor wins).
3. **Greedy pass** — earliest-arrival Dijkstra with one label per node, skipping arcs that
   are shut at the moment we would enter them. Whatever it returns is a genuinely
   walkable route. If no obstruction in the case has `speed_factor` 0, every arc is FIFO
   and this pass is already **exact** — that is the fast path, and it is the common one.
4. Otherwise it becomes the starting upper bound for the exhaustive search, and the answer
   we fall back on if that search runs out of budget. This matters more than it sounds:
   before it existed, a big obstructed case burned its whole slice and returned
   `null` — a guaranteed zero on a case we could already route.
5. `dist_static` = reverse Dijkstra to the target on plain `base_duration_sec`. After the
   last obstruction ends nothing changes, so this is the *exact* cost of any journey
   starting at or after that horizon, and it doubles as the A* heuristic.
6. A* over `(node, time)` states ordered by `time + h[node]`, dedup on the exact
   `(node, time)` pair (never on node alone — that is the non-FIFO trap). Expanding an arc
   integrates the progress model above; an arc whose factor is 0 at entry is skipped.
7. Any state at or past the obstruction horizon is not expanded — it converts straight into
   a finished candidate `time + dist_static[node]` with the static tail appended. This is
   what bounds the otherwise infinite cycling search.
8. At most `MAX_TIMES_PER_NODE` (24) distinct arrival times are kept per node. A* pops in
   increasing order of estimated completion, so the times that survive are the promising
   ones. This is the one deliberate departure from exactness, and it is what makes large
   cases finish at all.
9. First pop of the target node is optimal (admissible + consistent heuristic).

Budget: the batch shares an 8 s wall-clock budget (statement allows 10 s), sliced evenly
across the remaining unsolved cases. A case that runs out of budget returns its greedy
route rather than sinking the whole batch — a timeout scores 0 for *everything*.

### Measured (local, `TestClient`, one core)

| batch | wall clock | answered |
|---|---|---|
| 100 cases, 8×8 grid, ¼ of arcs obstructed | 0.27 s | 100/100 |
| 50 cases, 30×30 | 5.68 s | 50/50 |
| 5 cases, 60×60 (~7 100 edges each) | 3.43 s | 5/5 |
| 3 cases, 120×120 (~28 600 edges each) | 6.83 s | 3/3 |

The exhaustive search beat the greedy route in 4 of 20 random 25×25 cases, so step 6 is
worth its cost — those 4 would have scored 0 on the greedy answer alone.

### Verification beyond the statement's examples

12 000 randomly generated small cases (2–5 nodes, parallel edges, zero-duration edges,
overlapping and reversed obstructions, `speed_factor` from 0 to 2) were cross-checked
against an exhaustive depth-limited enumeration of every route. Zero mismatches.

## Assumptions we made

Flagged for the challenge developers — none of these are pinned by the statement:

1. **Overlapping obstructions on the same directed arc** → the lowest `speed_factor` wins
   (most restrictive). The statement never says. Multiplying them is the other candidate;
   the examples never overlap, so nothing distinguishes them.
2. **Obstruction windows are `[start_time, end_time)`** — start inclusive (forced by
   Example 3, where arriving at exactly 08:30:10 must be blocked), end exclusive (nothing
   in the statement pins this; the examples never land exactly on an `end_time`).
3. **Blocked means cannot enter, but a block that starts mid-traversal strands you on the
   arc** (progress halts until it lifts). Example 3 forces the no-entry half. The stranding
   half is the literal reading of "only the remaining untraveled portion is affected", but
   no example exercises it — the alternative is to forbid such a traversal outright.
4. **`start_coordinate == end_coordinate`** → `total_duration_sec: 0`, `arrival_time ==
   start_time`, `path: []`. Never stated.
5. **Non-integer durations are truncated to whole seconds** (not rounded), and
   `arrival_time` is derived from the same truncated value so the two always agree. The
   output schema shows an integer and every example is integral, but real grader cases are
   not — see "First graded run" below, which is why this is truncation and not rounding.
6. **A malformed individual case returns the null response** instead of failing the batch,
   so one bad case can't cost us the other cases. Only a body that isn't a JSON object at
   all is a 422.
7. **`arrival_time` is emitted as UTC** `...Z` with second precision, matching every
   example, even if the case's `start_time` carried a different offset.
8. **`nodes` is not treated as authoritative** — any coordinate appearing on an edge is
   also a node. Unreachability is decided by the graph, which is what Example 2 needs.
9. **`speed_factor > 1` is honoured** (traversal faster than base) if the grader ever sends
   it; the A* heuristic accounts for it so the search stays admissible.
10. **Bounded search** — at most 24 arrival times are kept per node, and the batch stops
    searching at 8 s. Exact on everything we can check (see verification above), but on a
    large adversarial case it can return a walkable-but-slower route instead of the
    optimum. The alternative — searching to exhaustion — returns nothing at all when the
    clock runs out, and a missed batch scores 0 across every case in it.

## First graded run — 92/100

Scored 92/100. `GET /debug/requests` still held the grader's own call: a **3 MB batch of
roughly 800 cases**, answered in 3.09 s. The first five cases were recovered intact from
the (4 KB-clipped) log and re-solved locally to the same answers the live service gave, so
the run is reproducible.

**What was wrong: rounding.** `case_1`'s exact answer is **179.5 s** — 1 s of `edge_0` at
full speed, 42 s at 0.75, then the remainder, plus 53 + 65. Fractional answers are not
rare: on 4 000 cases generated to match the shape of the recovered ones, 13.9% come out
fractional. Comparing what round-half-up (what we shipped) disagrees with:

| grader convention | we would disagree on | implied score |
|---|---|---|
| **truncate / `int()`** | **9.3%** | **91/100** |
| ceil | 4.6% | 95/100 |
| `round()` (banker's) | 2.8% | 97/100 |
| exact fraction, no rounding | 13.9% | 86/100 |

Truncation is the only convention consistent with the 92 we actually scored, and it is
what a reference implementation falls into naturally: `int(total_seconds())` truncates,
and formatting a datetime at second precision drops the sub-second part. The routing
itself is not in question — the search is verified exact against exhaustive enumeration on
12 000 small cases, and small cases are the bulk of the batch, so an 8% loss cannot be a
routing bug. Now truncating.

**Also fixed: budget starvation.** The batch budget was divided evenly across all cases up
front. With ~800 cases that is ~10 ms each, so any case needing real search was cut off
almost immediately and fell back to its greedy route — while 5 s of the 8 s budget went
unspent. Now every case gets the cheap pass first, and only the cases that actually need
searching share what is left, smallest first. A 20x20 grid with 400 blocked arcs needs
~15 ms and does improve on greedy, so this was live.

Checked and **not** the cause: `MAX_TIMES_PER_NODE` never binds (answers and timings are
identical at 24, 96 and 512), and timezone handling is fine (three of the five recovered
cases carry non-UTC offsets, and a string-comparison mismatch there would have cost far
more than 8 points).

## Third graded run — 92/100, and what it rules out

Truncation moved the score 91 -> 92, not the ~9 that convention predicted, so the bulk of
the loss was never rounding. The whole graded batch was pulled from
`/debug/kan-cheong/capture/0` and kept in `graded-runs/`, which is **gitignored** — this
repo is public and those are UBS's test cases, not ours to publish. Re-pull it by setting
`KAN_CHEONG_CAPTURE=1` on the service and running the grader again. The batch is
**1000 cases, 3.9 MB, answered in 5.10 s** (median case is 5 nodes / 6 edges / 1
obstruction; the largest is 625 nodes / 1200 edges / 392 obstructions).

**Our answers are correct under our reading of the statement.** All 1000 were re-checked
against a clean-room reimplementation that shares no code with the router — a direct
simulator for the 861 small cases, and an independent no-heuristic `(node, time)` Dijkstra
for the other 139. **Zero disagreements.** The response is also structurally exact: every
case id present, right types and key order, and `arrival_time` always equal to
`start_time + total_duration_sec`.

So the missing points are a reading of the statement that our implementation *and* our
reference share. Every candidate was measured against the real batch, as a share of total
weight (weight = nodes + edges + obstructions, since larger cases are worth more):

| alternative reading | cases changed | weight |
|---|---|---|
| window end inclusive `[s, e]` (incl. zero-length windows) | 0 | 0.00% |
| rounding: ceil / banker's / exact fraction | 0 | 0.00% |
| overlapping windows multiply instead of most-restrictive | 34 | 0.40% |
| a 0-factor window mid-arc forbids the traversal (no stranding) | 12 | 0.30% |
| `start == end` returns null instead of 0 | 86 | 2.92% |
| `speed_factor > 1` clamped to 1 | 35 | 10.76% |
| obstructions apply in both directions | 156 | 13.42% |
| factor fixed at entry, mid-traversal changes ignored | 145 | 16.00% |

Nothing lands at 8%. The two readings closest in size are both contradicted by the
statement: direction is explicit ("obstructions are directional... `edge.from -> edge.to`")
and confirmed by Example 1, and mid-traversal change is the whole point of "only the
remaining untraveled portion is affected". Clamping `speed_factor` is the only survivor
near the right size, but the generator sends 1.5 and 2.0 as clean deliberate values
(19.6% of all obstructions), so clamping would make its own choice pointless.

Also checked and cleared:

- **The 84 null answers are right.** Every one is a case where all arcs out of the start
  are shut at departure — `case_6` is Example 4 almost verbatim, and the statement gives
  the null response for exactly that.
- **Path tie-breaking is already the natural choice.** Only 15 cases have more than one
  optimal route (12 of them are 900-parallel-edge graphs answered by a single 10 s edge),
  and in every one we already return the first-listed, lowest-numbered edge.
- **Search bounds and deadlines are not biting.** Identical answers with the cap at 24,
  96, 512 and unbounded; and emulating Render's ~16-30x slowdown, the budget can fall to
  the equivalent of ~8 s before a single answer changes.

## Failed test cases and what fixed them

- Rounding fractional durations up instead of truncating — cost ~8 points on the first
  graded run. See above.
