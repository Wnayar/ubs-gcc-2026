"""Ghost Chains Phase 3 — "Value Signal".

Phase 3 adds no endpoints and no mechanical requirements. It activates the one
required field Phase 1 and Phase 2 deliberately ignored, `amount`:

    "Layering often pushes value along a chain where each hop keeps most of the
     prior amount. A single amount means little alone; along an inferred flow, the
     trail of amounts can confirm or contradict a pattern."

    "`amount` forms a value signal inside structurally inferred flow segments. Do
     not blindly aggregate amounts across unrelated branches without structural
     segmentation."

The statement is unusually explicit about which direction this cuts. Its Example 1
is a textbook layering chain — four hops each keeping 99.1% of the last — and it is
required to score *lowest* of the four, because "consistent value decay along a
single path represents the characteristic layering pattern rather than a deviation
from it". Example 3 is the same graph with one amount raised, and is required to
score *highest*. So the value signal does not score layering; it scores the trail of
amounts **contradicting** the layering it sits inside.

This module holds all of it. It keeps its own window-bounded index of the amount on
every leg, walks the inferred flow segment feeding a transaction, and turns the
resulting retention ratios into one evidence value in [0, 1]. `app/routers/phase3.py`
owns the structural bands and decides how far that evidence may move a score.

The whole design is written up in docs/phases/ghost-chains/phase-3/notes.md.
"""
from __future__ import annotations

import bisect
import math
from heapq import heappop, heappush

# How far back along the inferred flow the value trail is read. The statement's
# examples build segments of two and three hops; reading much further makes the
# coherence measure a statement about the whole graph's history rather than about
# the flow this transaction belongs to.
MAX_SEGMENT = 6

# A reversal is a qualitative event -- "the amount ... exceeds the preceding step,
# reversing the prior reduction along the same path" -- so any excess at all carries
# most of the weight and its size only refines it. The statement's own reversals are
# 1.0-1.6% excesses, so the refinement has to be sensitive at that scale.
W_REVERSAL = 0.85
REVERSAL_FLOOR = 0.55
K_EXCESS = 0.05

# The trail failing to confirm a single progression is the weaker half of the signal:
# it is what separates the statement's branching examples (a hop keeping half, then a
# hop keeping 98%) from its single consistent chain, without ever approaching what an
# outright reversal is worth.
W_INCOHERENCE = 0.22

# What counts as "exceeds the preceding step". Amounts carry fees and rounding, and a
# hop that comes back a hundredth of a percent higher is an artefact, not a reversed
# trajectory. The statement's own reversals are 1.0-1.6% excesses, so this sits two
# orders of magnitude below the smallest thing it asks us to detect.
REVERSAL_TOLERANCE = 1e-4


def saturate(value: float, k: float) -> float:
    """Map an unbounded magnitude into [0, 1), the same form Phases 1 and 2 use."""
    if not math.isfinite(value):
        return 1.0 if value > 0 else 0.0
    return value / (value + k) if value > 0 else 0.0


def usable(amount: float) -> bool:
    """Can this amount take part in a retention ratio?

    A zero, negative, infinite or NaN amount is still a perfectly good graph edge —
    the statement forbids failing on it and Phase 1 scores it exactly as before —
    but there is no progression to read from it, so it ends the value trail rather
    than poisoning the arithmetic of every transaction downstream of it.
    """
    return amount > 0.0 and math.isfinite(amount)


class ValueTrail:
    """The amount on every leg inside the window, indexed by receiving entity.

    Records expire with the transactions that carried them, on the graph's own
    half-open 24-hour window: an amount that has aged out is not part of any flow
    any more, exactly as its edge is no longer part of the graph.
    """

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        # receiver -> legs (when, seq, amount, sender), kept sorted by arrival
        self.inbound: dict[str, list[tuple[float, int, float, str]]] = {}
        self.expiry: list[tuple[float, int, str]] = []
        self._seq = 0

    # --- maintenance -------------------------------------------------------

    def expire(self, cutoff: float) -> None:
        """Drop everything at or before `cutoff` — the graph's own window edge."""
        while self.expiry and self.expiry[0][0] <= cutoff:
            when, seq, receiver = heappop(self.expiry)
            legs = self.inbound.get(receiver)
            if legs is None:
                continue
            index = bisect.bisect_left(legs, (when, seq, -1.0, ""))
            if index < len(legs) and legs[index][:2] == (when, seq):
                del legs[index]
            if not legs:
                del self.inbound[receiver]

    def record(self, sender: str, receiver: str, when: float, amount: float) -> None:
        """Register a transaction that has already been scored."""
        self._seq += 1
        bisect.insort(
            self.inbound.setdefault(receiver, []), (when, self._seq, amount, sender)
        )
        heappush(self.expiry, (when, self._seq, receiver))

    # --- the inferred flow segment ----------------------------------------

    def _latest(self, entity: str, ceiling: float):
        """The most recent leg that had arrived at `entity` by `ceiling`."""
        legs = self.inbound.get(entity)
        if not legs:
            return None
        index = bisect.bisect_right(legs, (ceiling, float("inf"), 0.0, "")) - 1
        return legs[index] if index >= 0 else None

    def segment(self, sender: str, when: float) -> list[float]:
        """The amounts along the flow segment feeding `sender`, oldest first.

        Walks back one leg at a time, each hop strictly no later than the one it
        feeds, so the segment is a path money could actually have travelled — the
        same temporal discipline the structural score uses. Following only the
        latest leg into each entity is what "structural segmentation" means here:
        the trail is one inferred path, never the sum of unrelated branches.
        """
        amounts: list[float] = []
        node, ceiling = sender, when
        seen = {node}
        while len(amounts) < MAX_SEGMENT:
            leg = self._latest(node, ceiling)
            if leg is None:
                break
            _, _, amount, upstream = leg
            if not usable(amount) or upstream in seen:
                break  # no ratio to form, or the trail has doubled back
            amounts.append(amount)
            seen.add(upstream)
            node, ceiling = upstream, leg[0]
        amounts.reverse()
        return amounts

    # --- evidence ----------------------------------------------------------

    def evidence(self, sender: str, amount: float, when: float) -> float:
        """How far this transfer's amount contradicts the flow segment it extends.

        Zero whenever there is nothing to contradict: no inferred segment feeding
        the sender, or a trail whose retention is uniform and not reversed. A
        stream in which every amount is the same therefore produces no value signal
        at all, and Phases 1 and 2 score exactly as they did.
        """
        if not usable(amount):
            return 0.0  # nothing that can be read as value carried onward
        trail = self.segment(sender, when)
        if not trail:
            return 0.0

        amounts = trail + [amount]
        ratios = [amounts[i] / amounts[i - 1] for i in range(1, len(amounts))]

        # "The amount ... exceeds the preceding step ..., reversing the prior
        # reduction along the same path" — value growing along a structurally
        # continuous flow is a direct contradiction of what the flow looks like.
        final = ratios[-1]
        reversal = 0.0
        if final > 1.0 + REVERSAL_TOLERANCE:
            reversal = W_REVERSAL * (
                REVERSAL_FLOOR
                + (1.0 - REVERSAL_FLOOR) * saturate(final - 1.0, K_EXCESS)
            )

        # ...and whether the trail confirms a single progression at all. One hop
        # keeping 99% behind another keeping 99% is one flow; a hop keeping half
        # followed by a hop keeping 98% is two hypotheses about where the value went.
        incoherence = 0.0
        if len(ratios) >= 2:
            widest, tightest = max(ratios), min(ratios)
            incoherence = W_INCOHERENCE * ((widest - tightest) / widest)

        # independent dimensions, as Phase 2 combines its two attributes: a reversal
        # and an incoherent trail say different things, and neither saturates the other
        return min(1.0, 1.0 - (1.0 - reversal) * (1.0 - incoherence))
