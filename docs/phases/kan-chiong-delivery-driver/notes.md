# Kan Chiong Delivery Driver

- **PDF:** `statement.pdf` in this folder (re-downloaded 2026-08-22 11:06 — this
  version contains Example 3 "No Waiting + Cycling", which settles the cycling
  question the first implementation fought the grader over; that implementation
  was deleted and this folder restarted from scratch)
- **Endpoints required:** `POST /kan-cheong-delivery-driver` (statement titles the
  challenge "Kan Chiong" but spells the path "kan-cheong" — path copied verbatim)
- **Submitted to controller:** no
- **Score:**
- `graded-runs/` holds a captured grader request/response (run 5, 2026-08-22 02:41Z)
  from the *previous* implementation — kept for batch-size/perf reference only; its
  response reflects the old disputed semantics, so it is NOT a correctness oracle.

## The problem

Time-dependent fastest route on a city road network. Per case: `start_coordinate`,
`end_coordinate`, `start_time` (ISO-8601), `nodes` ([x,y] integer pairs), `edges`
(`edge_id`, `node1`, `node2`, `base_duration_sec` int in [0, 999]) and
`obstructions` (`edge_id`, `edge.from`/`edge.to`, `start_time`, `end_time`,
`speed_factor`). Return fastest `total_duration_sec`, `arrival_time`, and the
ordered `path` of traversed edge_ids — or `null`/`null`/`[]` if unreachable.

Rules from the statement:

- Edges are **bidirectional**, same base duration both ways.
- Obstructions are **directional**: they apply only when both `edge_id` and the
  `edge.from -> edge.to` direction match the traversal.
- **No waiting at nodes.** **Cycles are allowed** (a node may be revisited).
- If an obstruction becomes active during traversal, only the remaining
  untraveled portion is affected by the new `speed_factor`.
- `speed_factor = 0.0` means that directed traversal is **blocked while active**.

### Batch + timeout + scoring

- One POST carries a map `{case_id: case_input}`; reply with `{case_id: case_output}`
  for **every** id in the request. Cases are independent; any order.
- **10 s hard budget for the whole batch** — a timeout scores the entire batch 0,
  no partial credit for cases already solved. So: never let the request time out;
  answering a case wrongly loses only that case.
- Per case all-or-nothing; larger cases (more nodes/edges/obstructions) are worth
  more points.

### Semantics derived from the examples

- `speed_factor` **divides speed** (traversal accumulates `base_duration_sec`
  units of progress at `speed_factor` units per real second). Example 1 proves
  it: e0+e1(sf 0.5)+e2+e3 would cost 60+120+40+50 = 270 (the e2 obstruction is
  the *opposite* direction, so it doesn't apply), losing to e0+e4+e3 = 230, the
  expected answer. If sf multiplied duration, the first route would cost 210 and
  win — contradiction.
- Blocked entry: an arc whose blocking (sf = 0) window is active at the departure
  instant cannot be entered (Example 4 → null). Window activity treated as
  `start_time <= t < end_time`: in Example 3 arriving at the node exactly at a
  window's `start_time` (08:30:10) is blocked.
- Because entry can be blocked and waiting at nodes is forbidden, the network is
  **non-FIFO**: arriving earlier can be strictly worse. Cycling nearby edges is
  the statement's sanctioned substitute for waiting — Example 3's expected path
  is `edge_0` five times (out-back-out-back-out, reaching the middle node at
  +10 s/+30 s while blocked, +50 s when clear) then `edge_1`, total 60 s.
- Search state must therefore be `(node, arrival_time)`, never node alone, and
  the answer is the earliest arrival at the destination node.

## Worked examples (verbatim, all turned into tests)

1. **Batch example** (pages 1–2): two single-edge cases sharing one request.
   `case_1` (no obstruction) → `{"total_duration_sec": 60, "arrival_time":
   "2026-06-10T08:31:00Z", "path": ["edge_0"]}` (the PDF's response line is
   width-truncated at `["edg`, but the 60 s single edge makes it unambiguous);
   `case_2` (edge blocked 08:00–09:00, depart 08:30) → nulls + `[]`.
2. **Example 1** (5 nodes, sf 0.5 on e1 forward, sf 0.0 on e2 *reverse*) →
   230 s, `2026-06-10T08:33:50Z`, `["edge_0", "edge_4", "edge_3"]`.
3. **Example 2**: same network, `end_coordinate` [3,3] is not a node →
   unreachable → nulls + `[]`.
4. **Example 3 (No Waiting + Cycling)**: e1 blocked 08:30:10–08:30:20 and
   08:30:30–08:30:40; direct e2 slowed to sf 0.2 (20/0.2 = 100 s) → cycle e0
   five times then e1: 60 s, `2026-06-10T08:31:00Z`,
   `["edge_0","edge_0","edge_0","edge_0","edge_0","edge_1"]`.
5. **Example 4 (No Waiting + Blocked at Start)**: only edge out of start is
   blocked at departure → nulls + `[]`.

## Implementation

`app/routers/kan_chiong.py`, tests in `tests/test_kan_chiong.py`.

- Dijkstra over `(node, time)` states keyed by arrival time; first pop of the
  destination is optimal because every arc's arrival function is ≥ departure
  time. Exact arithmetic: times are `Fraction` seconds since `start_time`
  (speed factors go through `Fraction(str(sf))`, so 0.2 is exactly 1/5 and
  20/0.2 is exactly 100 — float would give 100.00000000000001).
- Traversal simulation walks the arc's obstruction-window breakpoints:
  progress accumulates at the active speed factor (1 when no window is active);
  sf = 0 active at the departure instant ⇒ arc not enterable; sf = 0 becoming
  active mid-edge ⇒ progress stalls until the window ends, then resumes.
- Cycling makes the state space infinite in principle; it is tamed by (a) exact
  dedup on `(node, time)`, (b) once `t >=` the last obstruction end the network
  is FIFO again, so only the earliest post-horizon state per node is expanded,
  and (c) a wall-clock deadline (~8.5 s minus elapsed, shared by the batch).
- Batch handling: body is `dict[str, Any]` (422 only for a non-object body);
  each case is validated and solved inside try/except — a malformed or crashing
  case answers nulls instead of poisoning the batch. Cases are solved smallest
  first so a huge case can't starve many small ones; anything unfinished at the
  deadline answers nulls (0 for those cases, but the batch survives).

## Assumptions we made

- **Overlapping obstructions** on the same directed arc: statement is silent; we
  apply the most restrictive (minimum) active `speed_factor`.
- **Window boundaries**: active on `start_time <= t < end_time` (start-inclusive
  is proven by Example 3; end-exclusive — entering exactly at `end_time` is
  allowed — is our reading of "while active", untested by the examples).
- **Stalling mid-edge is legal**: "no waiting" is stated only *at nodes*, and the
  remaining-portion rule explicitly contemplates a new speed factor (including
  0.0) taking effect mid-traversal, so we let progress stop on the edge until
  the window ends. If the intended reading is "never enter an edge you can't
  finish unobstructed", routes through such edges would differ.
- **Output number shapes — THE open risk**: examples only show integer seconds;
  we emit ints when the exact result is integral, else a float (e.g.
  `139.66666666666666`), and `arrival_time` as `...SSZ` with fractional seconds
  only when non-integral (e.g. `...:19.666667Z`, microsecond precision). The
  deleted implementation FLOORED fractional durations instead — 83/1000 cases
  in the run-5 capture are affected — and we don't know which shape the grader
  accepts. Check the first graded run's `/debug/requests` for exactly this.
- **Unknown/missing nodes**: a start or end coordinate not in `nodes` (Example 2)
  is unreachable; `start == end` returns 0 s, `arrival_time = start_time`, `[]`.
- `speed_factor > 1` **is real and is honoured as a speed-up**: the run-5 grader
  capture contains factors 1.5 and 2.0, and honouring them (progress at rate
  1.5×/2×) reproduces the old implementation's answers on those cases exactly.
  The default rate 1 applies only when no window is active — it is not a cap.
  Obstructions whose `edge.from`/`edge.to` match neither orientation of their
  edge are ignored.

## Replay against the run-5 grader capture (2026-08-22)

Replaying `graded-runs/run5-...-request.json.gz` (1000 cases, biggest ~1800
elements) through this implementation: **0.61 s** for the whole batch (budget
10 s), every case answered. Versus the old implementation's recorded response:
zero disagreements on paths or on integral durations; the only differences are
the 83 fractional-duration cases (old floored, we emit exact — see the
assumption above). Real grader inputs also exercise: `+08:00`/`-08:00`
timezone offsets, zero-length obstruction windows, duplicate parallel edges
between the same node pair, and speed factors up to 2.0 — the speed-up case has
a dedicated test; the rest are verified by the replay's agreement with the
recorded answers.

## Clarifications from challenge developers

- Q: … → A: …

## Failed test cases and what fixed them

-
