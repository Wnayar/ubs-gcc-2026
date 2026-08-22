"""Phase 3 (our folder numbering) — Ghost Chains, the challenge's Phase 1.

"Follow the Money": a streaming AML risk scorer over a rolling 24-hour directed
graph of entities.

The graph is *temporal*. A path only counts if money could actually have travelled
it: edge timestamps must not decrease along the direction of flow. Scoring a
transaction on paths that ignore time credits round trips that never happened —
the first version of this router did exactly that, and the evaluator reported
STRUCTURAL_DEVIATION and TEMPORAL_DEVIATION both High.

The full derivation and every assumption are in docs/phases/phase-3/notes.md.
"""
from __future__ import annotations

import asyncio
import bisect
import math
from datetime import datetime, timedelta, timezone
from heapq import heappop, heappush

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/ghost-chains", tags=["ghost-chains-phase-1"])

WINDOW = timedelta(hours=24).total_seconds()  # active lookback, inclusive
MAX_REMEMBERED_SCORES = 200_000  # idempotency memory, bounded
NEG_INF = float("-inf")

# Recency: money that moved recently weighs more than money that moved this
# morning, and a round trip that closes fast is tighter than one that dawdles.
TAU_TRAIL = 3 * 3600.0
TAU_HOLD = 2 * 3600.0

# The statement names its signals in increasing order of interest: money that
# "travels onward", "fans into the same destination", or "-- especially -- loops
# back through entities you have already seen", with two independent return routes
# stronger still. Each is a band; the continuous signals only move a transaction
# *within* its band. Structural Consistency is scored on behaving coherently across
# related scenarios, so that ordering has to hold in a busy graph too, not merely
# in the statement's five isolated examples.
TIER_ONWARD = 0.08  # the sender was itself paid recently: flow travelling onward
TIER_FAN = 0.30  # several routes converge on the receiver
TIER_RETURN = 0.55  # funds have come back round to the sender
TIER_MULTI = 0.78  # two or more independent return routes meet at the receiver
TIER_TOP = 1.0

K_TRAIL, K_FAN, K_ROUTES = 3.0, 3.0, 1.0


class Transaction(BaseModel):
    # unknown fields are ignored by default — later phases add optional fields and
    # the statement forbids rejecting transactions that carry unrecognised ones
    txId: str
    fromUserId: str
    toUserId: str
    amount: float
    createdAt: datetime
    ipAddress: str | None = None
    deviceId: str | None = None


class ScoreResult(BaseModel):
    txId: str
    riskScore: float


class TransactionsRequest(BaseModel):
    transactions: list[Transaction]


class TransactionsResponse(BaseModel):
    transactions: list[ScoreResult]


class ResetRequest(BaseModel):
    clearTransactions: bool = True


class ResetResponse(BaseModel):
    clearTransactions: bool


def _saturate(value: float, k: float) -> float:
    """Map an unbounded count into [0, 1), 0 at 0 and flattening as it grows."""
    return value / (value + k) if value > 0 else 0.0


def _decay(age: float, tau: float) -> float:
    """1.0 for something that just happened, fading towards 0 with age."""
    return math.exp(-max(age, 0.0) / tau)


def _band(floor: float, ceiling: float, refine: float) -> float:
    """Place a score inside its structural band, refined by the continuous signals."""
    refine = min(1.0, max(0.0, refine))
    return round(floor + (ceiling - floor) * refine, 6)


class GhostGraph:
    """Rolling temporal graph of entity transfers, scored incrementally."""

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        # sender -> receiver -> sorted timestamps of the transfers between them
        self.out: dict[str, dict[str, list[float]]] = {}
        self.inn: dict[str, dict[str, list[float]]] = {}
        self.expiry: list[tuple[float, str, str, str]] = []
        self.scores: dict[str, float] = {}
        self.clock: float | None = None

    # --- graph maintenance ------------------------------------------------

    @staticmethod
    def _link(side: dict[str, dict[str, list[float]]], a: str, b: str, when: float) -> None:
        bisect.insort(side.setdefault(a, {}).setdefault(b, []), when)

    @staticmethod
    def _unlink(side: dict[str, dict[str, list[float]]], a: str, b: str, when: float) -> None:
        row = side.get(a)
        times = row.get(b) if row else None
        if not times:
            return
        index = bisect.bisect_left(times, when)
        if index < len(times) and times[index] == when:
            del times[index]
        if not times:
            del row[b]
        if not row:
            del side[a]

    def _expire(self, now: float) -> None:
        """Drop everything created strictly more than WINDOW before `now`."""
        cutoff = now - WINDOW
        while self.expiry and self.expiry[0][0] < cutoff:
            when, _, sender, receiver = heappop(self.expiry)
            self._unlink(self.out, sender, receiver, when)
            self._unlink(self.inn, receiver, sender, when)

    # --- temporal traversal ------------------------------------------------

    def _earliest_arrival(self, source: str, ceiling: float):
        """Where money leaving `source` could have got to, and how soon.

        Follows edges whose timestamps do not decrease along the path, so every
        node reached is one funds could genuinely have flowed to.
        """
        arrival = {source: NEG_INF}
        hops = {source: 0}
        queue: list[tuple[float, int, str]] = [(NEG_INF, 0, source)]
        while queue:
            when, hop, node = heappop(queue)
            if when > arrival[node]:
                continue  # already reached sooner by another route
            for nxt, times in self.out.get(node, {}).items():
                index = bisect.bisect_left(times, when)
                if index >= len(times):
                    continue
                step = times[index]
                if step > ceiling or step >= arrival.get(nxt, math.inf):
                    continue
                arrival[nxt] = step
                hops[nxt] = hop + 1
                heappush(queue, (step, hop + 1, nxt))
        return arrival, hops

    def _latest_departure(self, target: str, ceiling: float) -> dict[str, float]:
        """Who could have fed `target` by `ceiling`, and how late they let go."""
        departure = {target: ceiling}
        queue: list[tuple[float, str]] = [(-ceiling, target)]
        while queue:
            negated, node = heappop(queue)
            when = -negated
            if when < departure[node]:
                continue
            for prev, times in self.inn.get(node, {}).items():
                index = bisect.bisect_right(times, when) - 1
                if index < 0:
                    continue
                step = times[index]
                if step <= departure.get(prev, NEG_INF):
                    continue
                departure[prev] = step
                heappush(queue, (-step, prev))
        return departure

    # --- scoring ----------------------------------------------------------

    def structural_score(self, sender: str, receiver: str, when: float) -> float:
        """How much does this transfer raise the graph's capacity for recurring flow?"""
        if sender == receiver:
            return 0.0  # a self-transfer connects nothing (notes.md)

        upstream = self._latest_departure(sender, when)
        feeding_receiver = self._latest_departure(receiver, when)
        onward, hops = self._earliest_arrival(receiver, when)

        # the money trail arriving at the sender: how much traceable flow this
        # transfer carries onward, discounted by how stale each hop is
        trail = sum(
            _decay(when - moved, TAU_TRAIL)
            for node, moved in upstream.items()
            if node != sender
        )
        # distinct counterparties already paying into this receiver
        fan_sources = [
            other for other in self.inn.get(receiver, {}) if other != sender
        ]
        fan = sum(
            _decay(when - self.inn[receiver][other][-1], TAU_TRAIL)
            for other in fan_sources
        )
        # entities upstream of *both* ends: they could already reach the receiver
        # and this transfer hands them a second, distinct route to it
        shared = (set(upstream) & set(feeding_receiver)) - {sender, receiver}
        converge = sum(_decay(when - upstream[node], TAU_TRAIL) for node in shared)

        arrival = onward.get(sender)
        if arrival is not None:
            # funds left the receiver, moved through the network in time order and
            # reached the sender: this transfer closes a genuine round trip
            tight = _decay(when - arrival, TAU_HOLD)  # how fast it bounced back
            short = 2.0 / (hops[sender] + 1)  # how few hops the cycle takes
            routes = 1  # the transfer being scored is one return route
            for other, times in self.inn.get(receiver, {}).items():
                if other == sender:
                    continue
                reached = onward.get(other)
                if reached is None:
                    continue
                index = bisect.bisect_left(times, reached)
                if index < len(times) and times[index] <= when:
                    routes += 1  # an independent return route into the receiver
            if routes >= 2:
                return _band(
                    TIER_MULTI,
                    TIER_TOP,
                    0.40 * _saturate(routes - 2, K_ROUTES) + 0.30 * tight + 0.30 * short,
                )
            return _band(
                TIER_RETURN,
                TIER_MULTI,
                0.50 * tight + 0.30 * short + 0.20 * _saturate(trail, K_TRAIL),
            )

        # count, not decayed weight: one common origin with a second route to the
        # receiver is the statement's convergence example, however recent it is
        if shared or len(fan_sources) >= 2:
            # money fanning into one destination, or a second route reaching it
            return _band(
                TIER_FAN,
                TIER_RETURN,
                0.55 * _saturate(converge, K_FAN)
                + 0.45 * _saturate(fan, K_FAN),
            )

        if trail > 0.0 or fan_sources:
            # ordinary onward movement along a chain
            return _band(
                TIER_ONWARD,
                TIER_FAN,
                0.70 * _saturate(trail, K_TRAIL) + 0.30 * _saturate(fan, K_FAN),
            )

        return 0.0  # nothing has connected to either end yet

    # --- streaming --------------------------------------------------------

    def process(self, transaction: Transaction) -> float:
        # txId is the idempotency key: a repeat returns the original score and
        # changes nothing, whether or not the rest of the payload matches
        remembered = self.scores.get(transaction.txId)
        if remembered is not None:
            return remembered

        created = transaction.createdAt
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        when = created.timestamp()
        # event time, not wall clock, and it never runs backwards
        if self.clock is None or when > self.clock:
            self.clock = when
        self._expire(self.clock)

        sender, receiver = transaction.fromUserId, transaction.toUserId
        risk = self.structural_score(sender, receiver, when)

        if when >= self.clock - WINDOW:  # inside the window: it joins the graph
            self._link(self.out, sender, receiver, when)
            self._link(self.inn, receiver, sender, when)
            heappush(self.expiry, (when, transaction.txId, sender, receiver))

        self.scores[transaction.txId] = risk
        while len(self.scores) > MAX_REMEMBERED_SCORES:
            del self.scores[next(iter(self.scores))]
        return risk


GRAPH = GhostGraph()
_LOCK = asyncio.Lock()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/reset", response_model=ResetResponse)
async def reset(request: ResetRequest) -> ResetResponse:
    async with _LOCK:
        if request.clearTransactions:
            GRAPH.clear()
    return ResetResponse(clearTransactions=request.clearTransactions)


@router.post("/transactions", response_model=TransactionsResponse)
async def transactions(request: TransactionsRequest) -> TransactionsResponse:
    async with _LOCK:  # state mutation stays serialised under concurrent load
        results = [
            ScoreResult(txId=item.txId, riskScore=GRAPH.process(item))
            for item in request.transactions  # sequential, order preserved
        ]
    return TransactionsResponse(transactions=results)
