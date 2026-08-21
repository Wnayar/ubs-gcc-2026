# Kan Chiong Delivery Driver — Solution Notes

A build-up from "what was Dijkstra again" to the full algorithm.

---

## 0. TL;DR

**Time-dependent Dijkstra over `(node, time)` states, bounded by the last obstruction's end time, closed out with a plain static Dijkstra.**

Three things make it not-vanilla-Dijkstra:
1. Edge cost depends on *when* you enter it → time-dependent.
2. `speed_factor = 0.0` means arriving **earlier can be worse** → the node alone is no longer a valid Dijkstra state; you need `(node, time)`.
3. No waiting at nodes → "waiting" must be simulated by driving in circles, so cycles are legal and sometimes optimal.

---

## 1. Dijkstra refresher

Goal: shortest path from `S` to `T` in a graph with **non-negative** edge weights.

```python
dist = {v: INF for v in V}; dist[S] = 0
pq = [(0, S)]                          # min-heap keyed by distance
while pq:
    d, v = heappop(pq)
    if d > dist[v]: continue           # stale entry, skip
    for (u, w) in neighbors(v):
        if d + w < dist[u]:
            dist[u] = d + w
            heappush(pq, (dist[u], u))
```

**Why it works:** when you pop the smallest unsettled distance, nothing left in the queue can improve it — every remaining path is already ≥ that value and edges only add non-negative weight. So the first pop of a node is final. Settle once, never revisit. `O((V+E) log V)`.

**The assumption to remember:** *the best-known value at a node is a complete summary of that node.* Everything below is about that assumption failing.

---

## 2. Time-dependent Dijkstra

Now edge weight is a function of departure time: `w(e, t)`. Instead of tracking *distance*, track **earliest arrival time**.

```python
arr[S] = start_time
# relax:  arr[u] = min(arr[u], arrive(e, arr[v]))
```

Does Dijkstra still work? Only if the network is **FIFO** (also called *non-overtaking*):

> Departing later never gets you there earlier. `arrive(e, t)` is non-decreasing in `t`.

Physically: if I leave a road 10 minutes after you, I can't pass you, because we're both subject to the same traffic at the same moments.

If FIFO holds, everything about Dijkstra survives — settle each node once on its earliest arrival, done.

**Speed factors alone are FIFO.** A 0.5 zone slows everyone equally; nobody overtakes.

---

## 3. Where this problem breaks FIFO

`speed_factor = 0.0` + "no waiting at nodes" = a hard on/off gate. From Example 3:

```
reach [1,0] at 08:30:10  →  edge_1 is blocked  →  dead end
reach [1,0] at 08:30:50  →  edge_1 is open     →  arrive in 10s
```

Arriving **earlier is strictly worse**. `arrive(t)` jumps from `∞` to finite as `t` increases — not monotone, not FIFO.

Consequence: earliest-arrival-per-node is no longer a sufficient summary. Plain Dijkstra settles `[1,0]` at 08:30:10, finds every outgoing move blocked, and never reconsiders → reports unreachable. Wrong.

**Fix: expand the state space.** The state is the pair:

```
state = (node, arrival_time)
```

The same node at two different times is two different states. This is a **time-expanded graph**. Dijkstra is still correct on it (priority = arrival time, transitions never decrease time), it just has more vertices.

---

## 4. Termination — why cycling doesn't run forever

Left alone, "drive in circles to burn time" is an infinite state space. Two things bound it:

**(a) Dedupe on the exact state.** A `(node, t)` pair you've already expanded is skipped. This is also what saves you from `base_duration_sec = 0` edges (allowed by the constraints!), which would otherwise loop forever at zero time cost.

**(b) The obstruction horizon.** Let

```
T_end = max(end_time over all obstructions)
```

After `T_end` the graph is **completely static** — every edge is just `base_duration_sec`. So:

1. Precompute plain Dijkstra from the **destination** on the base graph → `h[v]` = obstruction-free travel time from `v` to the destination.
2. Only ever search states with `t < T_end`.
3. The moment a state has `t >= T_end`, don't expand it. Its best possible finish is exactly `t + h[v]` — record that as a candidate answer and move on.

Now cycling is bounded by `(T_end − start_time) / min_positive_edge_duration`.

**Bonus:** if every `speed_factor <= 1`, that same `h[v]` is an **admissible heuristic** (it can never overestimate), so you can run this as A* and prune aggressively: drop any state where `t + h[v] >= best_known`. If factors above 1.0 are possible, use `base / max_factor` as the heuristic weight instead.

---

## 5. The edge cost function

The fiddly bit. You don't divide once — you **integrate progress through the windows**.

Model: the edge needs `base` seconds of *progress*. At factor `f` you accumulate progress at rate `f` per real second.

```python
def arrive(arc, t0):
    """Arrival time entering `arc` at t0, or None if it can't be entered."""
    t, remaining = t0, arc.base        # remaining un-driven base-seconds
    while remaining > 0:
        f = active_factor(arc, t)      # 1.0 if nothing active
        if f == 0:
            if t == t0:
                return None            # cannot ENTER a blocked arc
            t = block_end(arc, t)      # caught mid-edge: stall it out
            continue
        t_next = next_factor_change(arc, t)   # next window start/end after t
        span   = t_next - t
        need   = remaining / f
        if need <= span:
            return t + need            # finish inside this window
        remaining -= span * f          # consumed span*f base-seconds
        t = t_next
    return t
```

Sanity check against the spec's example: 30s edge, factor drops to 0.5 after 10s → first 10s burns 10 base-seconds, 20 remain at rate 0.5 → 40s more → **50s total**. ✓

### Two rules that are easy to get backwards

**Blocked at entry ⇒ the arc is unusable.** Not "enter and stall." Proof: in Example 3, entering-and-stalling would give 40s, but the official answer is 60s. Example 4 confirms it — the only outgoing move is blocked at departure and the answer is `null`.

**Windows are `[start, end)`** — start inclusive, end exclusive. Example 3 blocks at exactly 08:30:10.

**Obstructions are directional.** Match on the *ordered triple* `(edge_id, from, to)`. An edge is bidirectional; an obstruction applies to one direction only. Build the graph as **two directed arcs per edge**, each with its own sorted window list.

---

## 6. The full algorithm

```python
INF = float('inf')

h     = dijkstra_from(dest_node)                       # static base graph
T_end = max((o.end_time for o in obstructions), default=start_time)

best, best_state = INF, None
parent = {}                                            # (node,t) -> (prev_node, prev_t, edge_id)
seen   = {(start_node, start_time)}
pq     = [(start_time, start_node)]

while pq:
    t, v = heappop(pq)
    if t >= best:                    # queue is monotone in t → nothing left can win
        break
    if v == dest_node:
        best, best_state = t, (v, t); break
    if t >= T_end:                   # static tail — plain Dijkstra finishes it
        if h[v] < INF and t + h[v] < best:
            best, best_state = t + h[v], ('STATIC', v, t)
        continue
    for arc in out_arcs(v):
        t2 = arrive(arc, t)
        if t2 is None:                 continue      # blocked at entry
        if t2 + h[arc.to] >= best:     continue      # A* prune
        if (arc.to, t2) in seen:       continue      # already expanded this state
        seen.add((arc.to, t2))
        parent[(arc.to, t2)] = (v, t, arc.edge_id)
        heappush(pq, (t2, arc.to))
```

Then walk `parent` backwards to rebuild the `edge_id` list. If the winner came from the static tail, append the static Dijkstra path from that node to the destination.

Unreachable → `best` stays `INF` → emit `{"total_duration_sec": null, "arrival_time": null, "path": []}`.

**Complexity:** `O(States · deg · log States)` where `States` = distinct reachable `(node, time)` pairs before `T_end`. The A* prune and the horizon cut are what keep that number sane.

---

## 7. Traps

**Float time keys.** `20 / 0.2` can land on `99.99999999999999`. Your `(node, t)` dedupe set then never matches and the search explodes. Use `fractions.Fraction` for all time arithmetic (exact, and `speed_factor` parses cleanly from the JSON decimal), or quantize to microseconds before using `t` as a key.

**Don't add a "wait at node" edge.** Tempting, and wrong — it would make Example 3 return 30s instead of 60s.

**Start node = destination node.** Answer is 0s, empty path. Handle before the loop.

**Coordinates as keys.** Nodes are `[x, y]` lists — convert to tuples before hashing.

---

## 8. Spec gaps — pick a behavior, document the assumption

1. **Overlapping obstructions on the same arc.** Multiply the factors, or take the min? Take the **min** (most restrictive) so a `0.0` always dominates.
2. **A `0.0` window starting while you're mid-edge.** `remaining / 0` is infinite. I stall until the window ends and then resume — that's the natural reading of "only the remaining untraveled portion is affected" as a continuous rule, and it's what the code above does. The alternative is declaring the traversal invalid.

---

## 9. Checklist

- [ ] Parse to tuples; two directed arcs per edge
- [ ] Index obstructions by `(edge_id, from, to)`, windows sorted by start
- [ ] `arrive()` — integrate, refuse entry on `f == 0`, `[start, end)`
- [ ] Static Dijkstra from destination → `h`
- [ ] Time-expanded Dijkstra + `seen` dedupe + horizon cut + A* prune
- [ ] Reconstruct path, append static tail if used
- [ ] Exact time arithmetic (`Fraction`)
- [ ] `null` response for unreachable
- [ ] Verify against all 4 PDF examples: **230s / null / 60s / null**
