"""Regression tests against the real graded stream.

`docs/phases/ghost-chains/logs/2026-08-22-graded-runs.json` is what the evaluator
actually sent us on 2026-08-22, pulled off the branch service before a redeploy
could wipe it: run 1 is the Phase 1 evaluation (no identity fields anywhere) and
run 2 the Phase 2 one (ipAddress on 55 of 109, deviceId on 67). Both scored ~368.

Everything asserted here is a *property* rather than a score, because the reference
scores are not disclosed -- but the properties are the ones each shipped decision
is betting on, and they are now checked against the grader's own data instead of a
stream we invented.
"""
import json
from heapq import heappush
from pathlib import Path

import pytest

from app.routers import phase3

ARCHIVE = (Path(__file__).resolve().parent.parent
           / "docs/phases/ghost-chains/logs/2026-08-22-graded-runs.json")
BANDS = (phase3.TIER_ONWARD, phase3.TIER_FAN, phase3.TIER_RETURN,
         phase3.TIER_MULTI, phase3.TIER_TOP)


def band(score: float) -> int:
    return sum(1 for edge in BANDS if score >= edge)


def replay(transactions, decay_free, value=True):
    """Score a captured run offline, returning (txId, structural, promoted, final).

    Mirrors GhostGraph.process rather than calling it, so band placement is visible
    separately at each step: `structural` is Phase 1, `promoted` is after Phase 3's
    value reversal (the only cross-band signal), and `final` is after identity and an
    incoherent trail have ordered it inside that band. `value=False` scores the run
    as Phases 1 and 2 alone did.
    """
    original = phase3.DECAY_FREE_BANDS
    phase3.DECAY_FREE_BANDS = decay_free
    try:
        graph = phase3.GhostGraph()
        scored = []
        for item in transactions:
            t = phase3.Transaction(**{k: item[k] for k in (
                "txId", "fromUserId", "toUserId", "amount", "createdAt",
                "ipAddress", "deviceId")})
            when = t.createdAt.timestamp()
            if graph.clock is None or when > graph.clock:
                graph.clock = when
            graph._expire(graph.clock)
            if t.fromUserId == t.toUserId:
                structural = promoted = final = 0.0
            else:
                context = graph._context(t.fromUserId, t.toUserId, when)
                structural = graph.structural_score(t.fromUserId, t.toUserId, when, context)
                reversal, incoherence = graph.value.evidence(
                    t.fromUserId, t.amount, when) if value else (0.0, 0.0)
                identity = graph.identity.evidence(
                    t.fromUserId, t.toUserId, when, t.identities(),
                    set(context[0]) | set(context[1]) | set(context[2]),
                    graph._neighbours)
                promoted = graph.value_promoted(structural, reversal)
                weak = 1.0 - (1.0 - identity) * (1.0 - incoherence)
                ceiling = phase3._band_ceiling(promoted)
                final = round(min(1.0, promoted + (ceiling - promoted)
                                  * phase3.BAND_SHARE * weak), 6)
            graph._link(graph.out, t.fromUserId, t.toUserId, when)
            graph._link(graph.inn, t.toUserId, t.fromUserId, when)
            heappush(graph.expiry, (when, t.txId, t.fromUserId, t.toUserId))
            graph.identity.record(t.fromUserId, t.toUserId, when, t.identities())
            graph.value.record(t.fromUserId, t.toUserId, when, t.amount)
            scored.append((t.txId, structural, promoted, final))
        return scored
    finally:
        phase3.DECAY_FREE_BANDS = original


@pytest.fixture(scope="module")
def graded():
    return {run["phase"]: run["transactions"] for run in json.loads(ARCHIVE.read_text())["runs"]}


def test_the_phase_1_stream_carried_no_identity_at_all(graded):
    """Worth pinning as data: it is why the identity model went three evaluations
    without ever firing on a graded transaction, and why Phase 1's score is purely
    the structural model."""
    assert len(graded[1]) == 109
    assert not any(t["ipAddress"] or t["deviceId"] for t in graded[1])


def test_the_phase_2_stream_did_carry_identity(graded):
    assert sum(1 for t in graded[2] if t["ipAddress"]) == 55
    assert sum(1 for t in graded[2] if t["deviceId"]) == 67


@pytest.mark.parametrize("phase", [1, 2])
@pytest.mark.parametrize("decay_free", [False, True])
def test_every_graded_transaction_scores_in_range(graded, phase, decay_free):
    assert all(0.0 <= f <= 1.0 for _, _, _, f in replay(graded[phase], decay_free))


def test_identity_never_moves_a_graded_transaction_out_of_its_band(graded):
    """The Phase 2 lever. The headroom lift this replaced crossed 7 bands on this
    exact stream; containment must cross none.

    Measured from the *promoted* score, because Phase 3 gave one signal — and only
    one — permission to change a band: a value reversal. Everything identity and an
    incoherent trail do still has to stay inside whatever band that leaves.
    """
    crossed = [t for t, _, promoted, final in replay(graded[2], phase3.DECAY_FREE_BANDS)
               if band(final) != band(promoted)]
    assert crossed == []


def test_identity_only_ever_raises_a_graded_score(graded):
    assert all(final >= promoted >= structural
               for _, structural, promoted, final
               in replay(graded[2], phase3.DECAY_FREE_BANDS))


@pytest.mark.parametrize("phase", [1, 2])
def test_the_value_signal_is_upward_only_on_the_graded_stream(phase, graded):
    """Phase 3's lever, held to exactly the standard the decay-free change was.

    `amount` is a *required* field, so unlike identity — which never appeared in the
    Phase 1 evaluation at all — the value signal fires on the real graded stream:
    reversal on 36 of 109 there, an incoherent trail on 56. That is far too much to
    ship on the strength of four worked examples, so the property the four-to-one
    penalty asymmetry actually needs is pinned here instead: it may promote, it may
    never demote.
    """
    without = replay(graded[phase], phase3.DECAY_FREE_BANDS, value=False)
    with_value = replay(graded[phase], phase3.DECAY_FREE_BANDS, value=True)
    demoted = [(t, a, b) for (t, _, _, a), (_, _, _, b) in zip(without, with_value)
               if b < a - 1e-9]
    assert demoted == []
    raised = sum(1 for (_, _, _, a), (_, _, _, b) in zip(without, with_value)
                 if b > a + 1e-9)
    assert raised > 0


def test_only_a_value_reversal_ever_crosses_a_band(graded):
    """Structure chooses the band; Phase 3 lets exactly one signal overrule that."""
    for phase in (1, 2):
        for txid, structural, promoted, final in replay(
                graded[phase], phase3.DECAY_FREE_BANDS):
            if band(final) != band(structural):
                assert promoted > structural, txid


@pytest.mark.parametrize("phase", [1, 2])
def test_dropping_the_decay_is_upward_only_on_the_graded_stream(graded, phase):
    """The Phase 1 lever, and the whole reason it is safe to spend a run on.

    Under-scoring a reference-hot transaction was measured at ~4x the cost of
    over-scoring a cold one, so a change that only ever raises scores risks the
    cheap direction. If a future edit makes this demote anything, that reasoning no
    longer covers it.
    """
    decayed = replay(graded[phase], decay_free=False)
    free = replay(graded[phase], decay_free=True)
    demoted = [(t, a, b) for (t, _, _, a), (_, _, _, b) in zip(decayed, free) if b < a - 1e-9]
    assert demoted == []
    raised = sum(1 for (_, _, _, a), (_, _, _, b) in zip(decayed, free) if b > a + 1e-9)
    assert raised >= 90 if phase == 1 else raised > 0
