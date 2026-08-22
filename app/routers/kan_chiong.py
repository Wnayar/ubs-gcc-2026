"""Kan Chiong Delivery Driver (docs/phases/kan-chiong-delivery-driver/).

Fastest route through a road network whose directed edge traversals are slowed
or blocked during time windows. One POST carries a whole batch of independent
cases under a single 10 s budget; a timeout zeroes the entire batch, so the
solver works against a wall-clock deadline and answers nulls for anything it
could not finish rather than ever letting the request time out.

Semantics (derived in notes.md from the statement's examples):

* `speed_factor` divides speed: traversing an arc accumulates
  `base_duration_sec` units of progress at `speed_factor` units per real
  second (Example 1 rules out the duration-multiplier reading).
* An arc whose blocking (speed_factor 0) window is active at the departure
  instant cannot be entered; windows are active on `start <= t < end`
  (Example 3 blocks arrival exactly at a window's start). A window that
  activates mid-traversal applies to the remaining portion only — for 0.0
  that means stalling on the edge until the window ends.
* No waiting at nodes, but cycles are allowed, so cycling substitutes for
  waiting (Example 3's expected path rides the same edge five times). Blocked
  entry makes the network non-FIFO — arriving earlier can be strictly worse —
  so the search state is (node, time), never node alone.

All arithmetic is exact: times are Fraction seconds from the case's
start_time, and speed factors go through Fraction(str(...)) so a JSON 0.2 is
exactly 1/5 (20 / 0.2 must be 100, not 100.00000000000001).
"""
from __future__ import annotations

import heapq
import time
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["kan-chiong"])

# The grader allows 10 s for the whole batch; keep headroom for the network
# round trip and JSON (de)serialisation.
BATCH_BUDGET_SEC = 8.5
# Memory backstop for the (node, time) state space on adversarial cases.
MAX_STATES = 400_000

ZERO = Fraction(0)
ONE = Fraction(1)

NULL_ANSWER = {"total_duration_sec": None, "arrival_time": None, "path": []}


Coord = tuple[int, int]


class Edge(BaseModel):
    edge_id: str
    node1: Coord
    node2: Coord
    base_duration_sec: int = Field(ge=0)


class ObstructionDirection(BaseModel):
    from_: Coord = Field(alias="from")
    to: Coord


class Obstruction(BaseModel):
    edge_id: str
    edge: ObstructionDirection
    start_time: datetime
    end_time: datetime
    speed_factor: float


class Case(BaseModel):
    start_coordinate: Coord
    end_coordinate: Coord
    start_time: datetime
    nodes: list[Coord]
    edges: list[Edge]
    obstructions: list[Obstruction]


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _offset(dt: datetime, t0: datetime) -> Fraction:
    """Exact seconds from t0 to dt."""
    delta = _utc(dt) - t0
    return Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 1_000_000)


def _exact(speed_factor: float) -> Fraction:
    # str() of a float is the shortest round-tripping decimal, so a JSON "0.2"
    # comes back as exactly 1/5 rather than the nearest binary double.
    return Fraction(str(speed_factor))


class Arc:
    """One direction of an edge, with the obstruction windows that apply to it."""

    __slots__ = ("to", "edge_id", "base", "windows", "bounds")

    def __init__(self, to: Coord, edge_id: str, base: Fraction,
                 windows: list[tuple[Fraction, Fraction, Fraction]]):
        self.to = to
        self.edge_id = edge_id
        self.base = base
        self.windows = windows
        # every instant at which the active speed factor can change
        self.bounds = sorted({b for ws, we, _ in windows for b in (ws, we)})

    def rate_at(self, t: Fraction) -> Fraction:
        # Overlapping obstructions: the most restrictive active factor wins.
        # A lone active factor may exceed 1 — grader batches contain 1.5 and
        # 2.0 speed-ups, honoured as given — so 1 applies only when no window
        # is active, not as a cap.
        rate = None
        for ws, we, sf in self.windows:
            if ws <= t < we and (rate is None or sf < rate):
                rate = sf
        return ONE if rate is None else rate

    def traverse(self, t: Fraction) -> Fraction | None:
        """Arrival time when departing at t, or None if entry is blocked."""
        if self.rate_at(t) == 0:
            return None
        remaining = self.base
        if remaining == 0:
            return t
        cur = t
        for i in range(bisect_right(self.bounds, t), len(self.bounds)):
            bound = self.bounds[i]
            rate = self.rate_at(cur)
            if rate > 0:
                needed = remaining / rate
                if needed <= bound - cur:
                    return cur + needed
                remaining -= rate * (bound - cur)
            # rate 0 mid-edge: stall until the next boundary
            cur = bound
        rate = self.rate_at(cur)
        if rate <= 0:  # can't happen (all windows have ended), but never divide by 0
            return None
        return cur + remaining / rate


def _build_adjacency(case: Case, t0: datetime) -> dict[Coord, list[Arc]]:
    per_arc: dict[tuple[str, Coord, Coord], list[tuple[Fraction, Fraction, Fraction]]] = {}
    edges_by_id: dict[str, list[Edge]] = {}
    for edge in case.edges:
        edges_by_id.setdefault(edge.edge_id, []).append(edge)

    for obs in case.obstructions:
        ws = _offset(obs.start_time, t0)
        we = _offset(obs.end_time, t0)
        if ws >= we:
            continue
        window = (ws, we, _exact(obs.speed_factor))
        for edge in edges_by_id.get(obs.edge_id, ()):
            frm, to = obs.edge.from_, obs.edge.to
            # directional: only the matching orientation of the edge is affected
            if (frm, to) in ((edge.node1, edge.node2), (edge.node2, edge.node1)):
                per_arc.setdefault((edge.edge_id, frm, to), []).append(window)

    adjacency: dict[Coord, list[Arc]] = {}
    for edge in case.edges:
        base = Fraction(edge.base_duration_sec)
        for frm, to in ((edge.node1, edge.node2), (edge.node2, edge.node1)):
            windows = per_arc.get((edge.edge_id, frm, to), [])
            adjacency.setdefault(frm, []).append(Arc(to, edge.edge_id, base, windows))
    return adjacency


def _format_answer(t0: datetime, arrival: Fraction, path: list[str]) -> dict[str, Any]:
    if arrival.denominator == 1:
        arrival_dt = t0 + timedelta(seconds=int(arrival))
        arrival_iso = arrival_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        duration: int | float = int(arrival)
    else:
        arrival_dt = t0 + timedelta(microseconds=round(arrival * 1_000_000))
        arrival_iso = arrival_dt.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0") + "Z"
        duration = float(arrival)
    return {"total_duration_sec": duration, "arrival_time": arrival_iso, "path": path}


def _solve(case: Case, deadline: float) -> dict[str, Any] | None:
    """Earliest-arrival search over (node, time) states.

    Returns the answer dict, or None when unreachable / out of budget (the
    caller answers nulls either way). Optimality: every arc's arrival is >= its
    departure time, so popping states in arrival order makes the first pop of
    the destination minimal. Cycling keeps the pre-horizon state space large
    but finite; once t passes the last obstruction end the network is FIFO
    again, so only the earliest post-horizon state per node is expanded.
    """
    start = case.start_coordinate
    end = case.end_coordinate
    t0 = _utc(case.start_time)
    if start == end:
        return _format_answer(t0, ZERO, [])

    adjacency = _build_adjacency(case, t0)
    horizon = max((arc.bounds[-1] for arcs in adjacency.values() for arc in arcs
                   if arc.bounds), default=ZERO)

    heap: list[tuple[Fraction, int, Coord]] = [(ZERO, 0, start)]
    seq = 1
    seen: set[tuple[Coord, Fraction]] = {(start, ZERO)}
    parent: dict[tuple[Coord, Fraction], tuple[Coord, Fraction, str]] = {}
    expanded_post_horizon: set[Coord] = set()
    pops = 0

    while heap:
        t, _, node = heapq.heappop(heap)
        pops += 1
        if pops % 256 == 0 and (time.monotonic() > deadline or len(seen) > MAX_STATES):
            return None
        if node == end:
            path: list[str] = []
            key = (node, t)
            while key in parent:
                prev_node, prev_t, edge_id = parent[key]
                path.append(edge_id)
                key = (prev_node, prev_t)
            path.reverse()
            return _format_answer(t0, t, path)
        if t >= horizon:
            if node in expanded_post_horizon:
                continue
            expanded_post_horizon.add(node)
        for arc in adjacency.get(node, ()):
            arrival = arc.traverse(t)
            if arrival is None:
                continue
            if arrival >= horizon and arc.to in expanded_post_horizon:
                continue
            key = (arc.to, arrival)
            if key in seen:
                continue
            seen.add(key)
            parent[key] = (node, t, arc.edge_id)
            heapq.heappush(heap, (arrival, seq, arc.to))
            seq += 1
    return None


def _case_size(raw: Any) -> int:
    if not isinstance(raw, dict):
        return 0
    return sum(len(raw.get(k, ())) for k in ("nodes", "edges", "obstructions")
               if isinstance(raw.get(k), list))


@router.post("/kan-cheong-delivery-driver")
def kan_cheong_delivery_driver(batch: dict[str, Any]) -> dict[str, Any]:
    """Solve a batch of independent routing cases within the 10 s budget.

    Small cases are solved first so one huge case can't starve the rest of the
    batch; a case that is malformed, crashes, or runs out of budget answers
    nulls — each case is all-or-nothing, but the batch must always come back.
    """
    deadline = time.monotonic() + BATCH_BUDGET_SEC
    answers = {case_id: dict(NULL_ANSWER) for case_id in batch}
    for case_id in sorted(batch, key=lambda c: _case_size(batch[c])):
        if time.monotonic() > deadline:
            break
        try:
            case = Case.model_validate(batch[case_id])
            answer = _solve(case, deadline)
            if answer is not None:
                answers[case_id] = answer
        except Exception:
            pass  # malformed case: keep the null answer, don't poison the batch
    return answers
