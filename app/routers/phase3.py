"""Phase 3 (our folder numbering) — Ghost Chains, the challenge's Phase 1.

"Follow the Money": a streaming AML risk scorer over a rolling 24-hour directed
graph of entities. The score of a transaction is how much the edge it adds
increases the graph's capacity to support recurring flow — new or shortened paths,
convergence of routes, and above all return paths that close loops.

The full derivation, the five worked examples and every assumption are in
docs/phases/phase-3/notes.md.
"""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from heapq import heappop, heappush
from typing import Iterable, Mapping

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/ghost-chains", tags=["ghost-chains-phase-1"])

WINDOW = timedelta(hours=24)  # active lookback; a tx is active while age <= WINDOW
BFS_CAP = 50_000  # guard against a pathological stream stalling the instance
MAX_REMEMBERED_SCORES = 200_000  # idempotency memory, bounded

# Component weights sum to 1.0, so the score is in [0, 1] by construction. The
# loop/return terms only apply when the edge closes a cycle, which is why a return
# path outranks convergence, and convergence outranks a plain extension.
W_REACH, W_SHORTEN, W_CONVERGE, W_LOOP, W_RETURN = 0.22, 0.08, 0.22, 0.28, 0.20
K_REACH, K_SHORTEN, K_CONVERGE, K_LOOP, K_RETURN = 3.0, 2.0, 2.0, 2.0, 1.0


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


class GhostGraph:
    """Rolling directed multigraph of entities, with incremental scoring."""

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self.out: dict[str, dict[str, int]] = {}
        self.inn: dict[str, dict[str, int]] = {}
        self.expiry: list[tuple[float, str, str, str]] = []  # heap by createdAt
        self.scores: dict[str, float] = {}
        self.clock: datetime | None = None

    # --- graph maintenance ------------------------------------------------

    @staticmethod
    def _link(side: dict[str, dict[str, int]], a: str, b: str) -> None:
        row = side.setdefault(a, {})
        row[b] = row.get(b, 0) + 1

    @staticmethod
    def _unlink(side: dict[str, dict[str, int]], a: str, b: str) -> None:
        row = side.get(a)
        if not row or b not in row:
            return
        row[b] -= 1
        if row[b] <= 0:
            del row[b]
        if not row:
            del side[a]

    def _add_edge(self, sender: str, receiver: str) -> None:
        self._link(self.out, sender, receiver)
        self._link(self.inn, receiver, sender)

    def _drop_edge(self, sender: str, receiver: str) -> None:
        self._unlink(self.out, sender, receiver)
        self._unlink(self.inn, receiver, sender)

    def _expire(self, now: datetime) -> None:
        """Drop everything created strictly more than WINDOW before `now`."""
        cutoff = (now - WINDOW).timestamp()
        while self.expiry and self.expiry[0][0] < cutoff:
            _, _, sender, receiver = heappop(self.expiry)
            self._drop_edge(sender, receiver)

    def _bfs(self, side: Mapping[str, dict[str, int]], start: str) -> dict[str, int]:
        """Distances from `start` following `side` (self.out = forward, self.inn = reverse)."""
        seen = {start: 0}
        queue: deque[str] = deque([start])
        while queue:
            node = queue.popleft()
            step = seen[node] + 1
            for neighbour in side.get(node, ()):
                if neighbour not in seen:
                    seen[neighbour] = step
                    if len(seen) >= BFS_CAP:
                        return seen
                    queue.append(neighbour)
        return seen

    # --- scoring ----------------------------------------------------------

    def structural_score(self, sender: str, receiver: str) -> float:
        """How much would edge sender->receiver raise the graph's recurring-flow capacity?

        Measured against the graph as it stands *before* the edge is added.
        """
        if sender == receiver:
            return 0.0  # a self-transfer connects nothing new (notes.md)

        to_sender = self._bfs(self.inn, sender)  # who can reach the sender
        to_receiver = self._bfs(self.inn, receiver)
        from_receiver = self._bfs(self.out, receiver)  # who the receiver can reach
        from_sender = self._bfs(self.out, sender)

        ancestors_s, ancestors_r = set(to_sender), set(to_receiver)
        descendants_r, descendants_s = set(from_receiver), set(from_sender)

        # entities that reach the sender but could not reach the receiver, crossed
        # with entities the receiver reaches but the sender could not: the pairs
        # this edge newly connects. Minus one for the trivial (sender, receiver).
        reach = len(ancestors_s - ancestors_r) * len(descendants_r - descendants_s) - 1

        # the edge is a genuine shortcut for anyone who could already reach the receiver
        shorten = sum(
            1
            for node, distance in to_sender.items()
            if node in to_receiver and distance + 1 < to_receiver[node]
        )

        edge_exists = receiver in self.out.get(sender, ())
        # entities that could already reach the receiver and now gain a second,
        # distinct route to it. A repeated edge is no new route at all.
        converge = 0 if edge_exists else len(ancestors_s & ancestors_r)

        signal = (
            W_REACH * _saturate(reach, K_REACH)
            + W_SHORTEN * _saturate(shorten, K_SHORTEN)
            + W_CONVERGE * _saturate(converge, K_CONVERGE)
        )

        if sender in descendants_r:  # the receiver already reached the sender: a loop
            # the strongly connected component the edge produces, derived without a
            # further traversal: reachable from the receiver AND reaching it
            component = (descendants_r | {receiver}) & (ancestors_r | ancestors_s)
            returns = sum(1 for node in self.inn.get(receiver, ()) if node in component)
            if not edge_exists and sender in component:
                returns += 1  # the edge being added is itself a return route
            signal += W_LOOP * _saturate(len(component) - 1, K_LOOP)
            # two independent return routes converging on one node outrank a single
            # return — this is what separates the statement's example 5 from 4
            signal += W_RETURN * _saturate(returns - 1, K_RETURN)

        return round(min(1.0, max(0.0, signal)), 6)

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
        # event time, not wall clock, and it never runs backwards
        if self.clock is None or created > self.clock:
            self.clock = created
        self._expire(self.clock)

        risk = self.structural_score(transaction.fromUserId, transaction.toUserId)

        if created >= self.clock - WINDOW:  # inside the window: it joins the graph
            self._add_edge(transaction.fromUserId, transaction.toUserId)
            heappush(
                self.expiry,
                (
                    created.timestamp(),
                    transaction.txId,
                    transaction.fromUserId,
                    transaction.toUserId,
                ),
            )

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
