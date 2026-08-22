"""Ghost Chains Phase 2 — "Identity Signal".

Phase 2 adds no endpoints and no mechanical requirements. It activates the two
optional fields Phase 1 already accepted and ignored, `ipAddress` and `deviceId`,
as evidence about *where a transaction sits in the active graph*:

    "Transactions that look unrelated on the graph may share a network address or
     device -- a hint of common control. A single shared attribute can be
     coincidence (office Wi-Fi, cloud NAT). When identity lines up with structural
     flow -- or the same identity appears across disconnected components -- treat
     it as a stronger combined signal."

This module holds all of it. It maintains its own window-bounded index and turns a
transaction into one evidence value in [0, 1]; `app/routers/phase3.py` owns the
structural bands and decides how much that evidence is allowed to move a score.
Keeping the two apart is deliberate: the Phase 1 model is worth 369/400 and every
signal in it was paid for in failed evaluations, so Phase 2 does not touch it.

The whole design is written up in docs/phases/ghost-chains/phase-2/notes.md.
"""
from __future__ import annotations

import math
from heapq import heappop, heappush
from typing import Callable, Iterable

# the statement's two identity dimensions, treated as independent
ATTRIBUTES = ("ipAddress", "deviceId")

# How stale identity evidence is allowed to get. Phase 1's TAU_TRAIL: an identifier
# seen on the leg that fed this sender twenty minutes ago says much more about the
# flow than one from this morning.
TAU_IDENTITY = 3 * 3600.0

K_ALIGN = 2.0  # saturation of "how many entities on this flow already used it"
K_GROUPS = 1.0  # saturation of "how many disconnected components share it"

W_ALIGN = 0.45  # identity lines up with structural flow
W_PAIR = 0.30  # both ends of this very transfer have used it
W_CROSS = 0.55  # the same identity turns up in unrelated components
W_SHIFT = 0.15  # the leg that fed the sender carried a *different* value
# Absence is evidence only in proportion to how strongly the surrounding flow was
# carrying the identifier ("weigh absence against the surrounding structure"), and
# always ranks below a flow that keeps it: the statement calls agreement a "stronger
# combined signal" outright, while absence merely "can be a signal".
DROP_SHARE = 0.75
DROP_OWN_USE = 1.0  # the sender itself used to initiate with it, and stopped
DROP_INHERITED = 0.85  # only the incoming leg carried it

MAX_GROUPED = 32  # cap the component grouping; identity values touch few entities
# An address hundreds of entities initiate from is infrastructure, not coordination
# — the statement names cloud NAT itself. Beyond this it stops counting as reuse
# across components, which also bounds the per-transaction work.
MAX_SHARED = 256


def saturate(value: float, k: float) -> float:
    """Map an unbounded count into [0, 1), the same form Phase 1 uses."""
    return value / (value + k) if value > 0 else 0.0


def freshness(age: float) -> float:
    return math.exp(-max(age, 0.0) / TAU_IDENTITY)


def clean(value: object) -> str | None:
    """Identity fields are decorative to the required schema, so nothing in them may
    cause a transaction to fail. Numbers become strings; blanks, nulls and anything
    structured count as *absent*, which is a state the statement requires us to
    handle anyway."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip() or None
    return None


class IdentityIndex:
    """Who has initiated transactions with which identifiers, inside the window.

    Every record expires with the transaction that carried it, on the same half-open
    24-hour window as the graph: an address shared with a transaction that has aged
    out is not shared any more.
    """

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        # (attribute, value) -> initiating entity -> how many live transactions
        self.initiators: dict[tuple[str, str], dict[str, int]] = {}
        # (attribute, entity) -> (when, value or None) for the latest leg in / out
        self.inbound: dict[tuple[str, str], tuple[float, str | None]] = {}
        self.outbound: dict[tuple[str, str], tuple[float, str | None]] = {}
        self.expiry: list[tuple[float, int, str, str, str, str]] = []
        self.cutoff = float("-inf")
        self._seq = 0

    def _push(self, when: float, kind: str, attr: str, first: str, second: str) -> None:
        self._seq += 1
        heappush(self.expiry, (when, self._seq, kind, attr, first, second))

    # --- maintenance -------------------------------------------------------

    def expire(self, cutoff: float) -> None:
        """Drop everything at or before `cutoff` — the graph's own window edge."""
        self.cutoff = cutoff
        while self.expiry and self.expiry[0][0] <= cutoff:
            when, _, kind, attr, first, second = heappop(self.expiry)
            if kind == "use":
                row = self.initiators.get((attr, first))
                if row is None:
                    continue
                if row.get(second, 0) <= 1:
                    row.pop(second, None)
                else:
                    row[second] -= 1
                if not row:
                    del self.initiators[(attr, first)]
                continue
            side = self.inbound if kind == "in" else self.outbound
            record = side.get((attr, first))
            if record is not None and record[0] == when:
                del side[(attr, first)]

    def record(
        self, sender: str, receiver: str, when: float, identities: dict[str, str | None]
    ) -> None:
        """Register a transaction that has already been scored."""
        for attr in ATTRIBUTES:
            value = identities.get(attr)
            if value is not None:
                row = self.initiators.setdefault((attr, value), {})
                row[sender] = row.get(sender, 0) + 1
                self._push(when, "use", attr, value, sender)
            # absence is recorded too: it is what makes a *later* leg's absence
            # ordinary rather than a dropped trail
            self.inbound[(attr, receiver)] = (when, value)
            self._push(when, "in", attr, receiver, "")
            self.outbound[(attr, sender)] = (when, value)
            self._push(when, "out", attr, sender, "")

    # --- evidence ----------------------------------------------------------

    def _live(
        self, side: dict[str, tuple[float, str | None]], attr: str, entity: str, when: float
    ) -> tuple[float, str | None] | None:
        record = side.get((attr, entity))
        if record is None or record[0] > when or record[0] <= self.cutoff:
            return None  # nothing, in the future, or aged out of the window
        return record

    def _groups(
        self, entities: Iterable[str], neighbours: Callable[[str], Iterable[str]]
    ) -> int:
        """How many *disconnected* groups these entities fall into, walking the
        window graph. Three unrelated transfers sharing an address are three
        components; one busy office subnet is one."""
        pool = set(sorted(entities)[:MAX_GROUPED])
        groups = 0
        while pool:
            stack = [pool.pop()]
            groups += 1
            while stack:
                for nxt in neighbours(stack.pop()):
                    if nxt in pool:
                        pool.discard(nxt)
                        stack.append(nxt)
        return groups

    def _value_evidence(
        self,
        attr: str,
        value: str,
        sender: str,
        receiver: str,
        related: set[str],
        neighbours: Callable[[str], Iterable[str]],
    ) -> float:
        """How much this identifier says about a transfer sitting where this one sits."""
        row = self.initiators.get((attr, value))
        if not row:
            return 0.0  # first sighting: an identifier alone means nothing

        # identity lining up with the flow this transfer belongs to (walk whichever
        # side is smaller — a shared address can have far more users than this
        # transfer has relatives, or the other way round)
        if len(row) <= len(related):
            aligned = sum(1 for entity in row if entity != sender and entity in related)
        else:
            aligned = sum(1 for entity in related if entity != sender and entity in row)
        # both ends of this very transfer have initiated with it: common control
        pair = 1.0 if sender in row and receiver in row else 0.0
        # ...and the same identifier over in components this flow cannot reach.
        # Scored on groups *minus one*, so the second component on its own is worth
        # nothing: "a single shared attribute can be coincidence".
        if len(row) > MAX_SHARED:
            groups = 0  # shared infrastructure: coincidence by weight of numbers
        else:
            elsewhere = [
                entity
                for entity in row
                if entity not in related and entity != sender and entity != receiver
            ]
            groups = self._groups(elsewhere, neighbours) if elsewhere else 0
        return (
            W_ALIGN * saturate(aligned, K_ALIGN)
            + W_PAIR * pair
            + W_CROSS * saturate(groups - 1, K_GROUPS)
        )

    def _attribute_evidence(
        self,
        attr: str,
        value: str | None,
        sender: str,
        receiver: str,
        when: float,
        related: set[str],
        neighbours: Callable[[str], Iterable[str]],
    ) -> float:
        prior = self._live(self.inbound, attr, sender, when)  # the leg that fed us

        if value is None:
            # "Missing identity on a connected path": suspicious only when the flow
            # feeding this sender was carrying the attribute and this leg stops.
            if prior is None or prior[1] is None:
                return 0.0  # nothing was being carried — missing fields are normal
            carried = self._value_evidence(
                attr, prior[1], sender, receiver, related, neighbours
            )
            if carried <= 0.0:
                return 0.0
            own = self._live(self.outbound, attr, sender, when)
            strength = DROP_OWN_USE if own is not None and own[1] == prior[1] else DROP_INHERITED
            return DROP_SHARE * strength * carried * freshness(when - prior[0])

        evidence = self._value_evidence(attr, value, sender, receiver, related, neighbours)
        if prior is not None and prior[1] is not None and prior[1] != value:
            # the identifier changed at this hop: the structural path is intact but
            # one identity cluster no longer explains it
            evidence += W_SHIFT * freshness(when - prior[0])
        return min(1.0, evidence)

    def evidence(
        self,
        sender: str,
        receiver: str,
        when: float,
        identities: dict[str, str | None],
        related: set[str],
        neighbours: Callable[[str], Iterable[str]],
    ) -> float:
        """Combined identity evidence in [0, 1] for a transfer about to be scored.

        The two attributes are combined as independent dimensions, exactly as the
        statement asks: neither can saturate the other, and both agreeing is worth
        more than either alone.
        """
        remaining = 1.0
        for attr in ATTRIBUTES:
            remaining *= 1.0 - self._attribute_evidence(
                attr, identities.get(attr), sender, receiver, when, related, neighbours
            )
            if remaining <= 0.0:
                return 1.0
        return 1.0 - remaining
