"""Ghost Chains Phase 3 — "Value Signal". See docs/phases/ghost-chains/phase-3/notes.md.

Unlike Phase 2, this statement *does* commit to an ordering: of its four worked
examples, "Example 1 should receive the lowest risk score of the four" and
"Example 3 should receive the highest", with 2 and 4 "not directly comparable".
That ordering is the spine of this file — it is the only place in three phases where
the statement tells us outright how two scenarios must rank.

The rest pins what the Core Principle asks for: value is read *inside structurally
inferred flow segments*, never aggregated across unrelated branches, and a stream
whose amounts say nothing must score exactly what Phases 1 and 2 gave it.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.ghost_value import ValueTrail
from app.main import app
from app.routers import phase3

client = TestClient(app)

BASE = datetime.fromisoformat("2026-06-08T12:00:00+00:00")

# entity names from the statement's examples
M, A, C, H, S, O, N = (
    "meridian_holdings",
    "apex_logistics",
    "cascade_payments",
    "horizon_capital",
    "sterling_bridge",
    "oakridge_imports",
    "nimbus_trading",
)
IOS, ANDROID = "dev_ios_7f3a91", "dev_android_c2e4b8"
IP, IP2 = "10.0.0.1", "10.0.0.2"


@pytest.fixture(autouse=True)
def clean_state():
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    yield
    client.post("/ghost-chains/reset", json={"clearTransactions": True})


def at(minutes: float) -> str:
    return (BASE + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def send(transactions):
    return client.post("/ghost-chains/transactions", json={"transactions": transactions})


def stream(steps, prefix):
    """Stream (sender, receiver, amount[, minutes][, extra]) steps one per request,
    from a clean state; return every risk score. Minutes default to one per step, the
    statement's examples being given as ordered sequences without timestamps."""
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    scores = []
    for i, step in enumerate(steps):
        sender, receiver, amount = step[0], step[1], step[2]
        minutes = step[3] if len(step) > 3 else i
        extra = step[4] if len(step) > 4 else {}
        body = {
            "txId": f"{prefix}_{i}",
            "fromUserId": sender,
            "toUserId": receiver,
            "amount": amount,
            "createdAt": at(minutes),
        }
        body.update(extra)
        r = send([body])
        assert r.status_code == 200, r.text
        scores.append(r.json()["transactions"][0]["riskScore"])
    return scores


def last(steps, prefix):
    return stream(steps, prefix)[-1]


def flatten(steps, amount=100.0):
    """The same structure and identity with every amount made identical — the trail
    of amounts then says nothing at all."""
    return [
        (s[0], s[1], amount) + tuple(s[3:]) for s in steps
    ]


# --- the statement's four worked examples ----------------------------------

EXAMPLE_1 = [  # Consistent Value Decay
    (M, A, 10000),
    (A, C, 9910),
    (C, H, 9820.81),
    (H, N, 9732.42),
]
EXAMPLE_2 = [  # Competing Flow Hypotheses
    (M, A, 10000),
    (A, C, 9800),
    (A, S, 5000),
    (C, H, 9700),
    (S, O, 4900),
]
EXAMPLE_3 = [  # Value Trajectory Reversal
    (M, A, 10000),
    (A, C, 9950),
    (C, H, 9800),
    (H, N, 9950),
]
EXAMPLE_4 = [  # Convergence of Separate Value Paths
    (M, A, 10000),
    (A, C, 9800),
    (A, S, 5000),
    (C, H, 9700),
    (S, H, 4950),
]


def worked_examples():
    return (
        last(EXAMPLE_1, "v1"),
        last(EXAMPLE_2, "v2"),
        last(EXAMPLE_3, "v3"),
        last(EXAMPLE_4, "v4"),
    )


def test_example_1_consistent_decay_scores_lowest_of_the_four():
    """"Example 1 should receive the lowest risk score of the four. Consistent value
    decay along a single path represents the characteristic layering pattern rather
    than a deviation from it.\""""
    one, two, three, four = worked_examples()
    assert one < two
    assert one < three
    assert one < four


def test_example_3_value_reversal_scores_highest_of_the_four():
    """"Example 3 should receive the highest risk score of the four. A value
    trajectory reversal against structural continuity is a direct contradiction.\""""
    one, two, three, four = worked_examples()
    assert three > one
    assert three > two
    assert three > four


def test_examples_1_and_3_are_separated_by_value_alone():
    """Examples 1 and 3 are the *same graph* — four hops M -> A -> C -> H -> N, same
    entities, same order, same timings. Only the amounts differ. Whatever separates
    them therefore has to come from the value signal and nothing else."""
    assert [step[:2] for step in EXAMPLE_1] == [step[:2] for step in EXAMPLE_3]
    assert last(flatten(EXAMPLE_1), "s1") == last(flatten(EXAMPLE_3), "s2")
    assert last(EXAMPLE_3, "s3") > last(EXAMPLE_1, "s4")


def test_consistent_decay_adds_no_value_evidence():
    """A trail that confirms the pattern is not evidence against it: Example 1 scores
    exactly what the same chain scores with every amount identical."""
    assert last(EXAMPLE_1, "c1") == last(flatten(EXAMPLE_1), "c2")


def test_examples_2_and_4_sit_between_the_two_extremes():
    """"Examples 2 and 4 test value continuity under qualitatively different
    conditions -- divergence and convergence respectively -- and are not directly
    comparable in risk." So they are pinned against 1 and 3, never against each other."""
    one, two, three, four = worked_examples()
    assert one < two < three
    assert one < four < three


# --- the Core Principle: value lives inside structural segments ------------


def test_a_reversal_needs_a_flow_to_reverse():
    """"amount forms a value signal inside structurally inferred flow segments." A
    large amount between two entities nothing else touches is not evidence of
    anything -- there is no trail for it to contradict."""
    assert last([(M, A, 10_000_000)], "r1") == 0.0
    assert last([(M, A, 1), (C, H, 10_000_000)], "r2") == 0.0


def test_value_is_not_aggregated_across_unrelated_branches():
    """"Do not blindly aggregate amounts across unrelated branches without structural
    segmentation." Sterling Bridge -> Oakridge Imports is scored on the trail that
    reaches Sterling Bridge; what the *other* branch out of Apex Logistics carried
    cannot change it."""
    other_branch_huge = [
        (M, A, 10000),
        (A, C, 9800),
        (A, S, 5000),
        (C, H, 9700),
        (S, O, 4900),
    ]
    other_branch_tiny = [
        (M, A, 10000),
        (A, C, 3),  # the sibling branch now carries almost nothing
        (A, S, 5000),
        (C, H, 1),
        (S, O, 4900),
    ]
    assert last(other_branch_huge, "b1") == last(other_branch_tiny, "b2")


def test_a_bigger_reversal_outranks_a_smaller_one():
    """Any reversal is a contradiction; a larger one is a larger contradiction."""
    chain = [(M, A, 10000), (A, C, 9900), (C, H, 9800)]
    slight = last(chain + [(H, N, 9850)], "m1")  # +0.5%
    gross = last(chain + [(H, N, 30000)], "m2")
    flat = last(chain + [(H, N, 9700)], "m3")
    assert gross > slight > flat


def test_a_rounding_artefact_is_not_a_reversal():
    """"Exceeds the preceding step" has to mean something: amounts carry fees and
    rounding, and a hop that arrives a hundredth of a percent higher has not reversed
    a trajectory. The statement's own reversals are 1.0-1.6% excesses."""
    chain = [(M, A, 10000), (A, C, 9900), (C, H, 9800)]
    artefact = last(chain + [(H, N, 9800.05)], "a1")  # +0.0005%
    real = last(chain + [(H, N, 9898)], "a2")  # +1.0%, the statement's own scale
    assert artefact < real


def test_an_incoherent_trail_outranks_a_coherent_one():
    """"Along an inferred flow, the trail of amounts can confirm or contradict a
    pattern." Two hops keeping 99% each are one flow; a hop keeping half followed by
    a hop keeping 98% is two hypotheses about where the value went."""
    coherent = last([(M, A, 10000), (A, S, 9900), (S, O, 9801)], "i1")
    incoherent = last([(M, A, 10000), (A, S, 5000), (S, O, 4900)], "i2")
    assert incoherent > coherent


def test_one_hop_alone_is_not_an_incoherent_trail():
    """"A single amount means little alone." With only one retention ratio there is
    nothing for it to disagree with, so a first onward hop carries no value signal
    however much of the prior amount it keeps."""
    assert last([(M, A, 10000), (A, C, 4000)], "o1") == last(
        [(M, A, 10000), (A, C, 10000)], "o2"
    )


# --- the cross-signal examples (no expected ordering is given) --------------

CROSS_P1_P2 = [  # cycle closed on a different device
    (M, A, 100, 0, {"deviceId": IOS}),
    (A, C, 100, 1, {"deviceId": IOS}),
    (C, H, 100, 2, {"deviceId": ANDROID}),
    (H, M, 100, 3, {"deviceId": ANDROID}),
]
CROSS_P1_P3 = [  # return path whose amount exceeds the leg that fed it
    (M, A, 10000),
    (A, C, 9800),
    (C, H, 9700),
    (H, A, 9850),
]
CROSS_P2_P3 = [  # convergence that changes address and raises the amount
    (M, A, 10000, 0, {"ipAddress": IP}),
    (C, H, 10000, 1, {"ipAddress": IP}),
    (A, N, 9800, 2, {"ipAddress": IP}),
    (H, N, 10100, 3, {"ipAddress": IP2}),
]


@pytest.mark.parametrize(
    "name,steps",
    [("p1p2", CROSS_P1_P2), ("p1p3", CROSS_P1_P3), ("p2p3", CROSS_P2_P3)],
)
def test_cross_signal_examples_process_and_stay_in_range(name, steps):
    scores = stream(steps, name)
    assert all(0.0 <= score <= 1.0 for score in scores)


def test_cross_signal_value_and_structure_combine_on_a_return_path():
    """"Structural and value observations are simultaneously present for the final
    transaction": the same return path scores higher when its amount reverses than
    when it decays."""
    reversing = last(CROSS_P1_P3, "x1")
    decaying = last(CROSS_P1_P3[:3] + [(H, A, 9600)], "x2")
    assert reversing > decaying


def test_cross_signal_identity_and_value_combine_at_a_convergence():
    """"Structural, identity, and value observations are each present for the final
    transaction." Removing either non-structural signal must lower the score."""
    everything = last(CROSS_P2_P3, "y1")
    without_value = last(flatten(CROSS_P2_P3, 10000), "y2")
    without_identity = last([step[:4] for step in CROSS_P2_P3], "y3")
    assert everything > without_value
    assert everything > without_identity


# --- earlier phases must be untouched --------------------------------------


def test_a_stream_of_identical_amounts_scores_exactly_as_phase_1_did():
    """A Phase 3 evaluation re-tests every Phase 1 and Phase 2 requirement. Phases 1
    and 2 ignored `amount` entirely, so a stream whose amounts carry no progression
    must still produce their scores bit-for-bit.

    These are the current model's numbers (decay-free band placement, identity
    contained inside its band), shared with
    `tests/test_ghost_chains_phase2.py::PHASE_1_BASELINE`.
    """
    baseline = {
        "example_3": [0.0, 0.0, 0.11818, 0.362097],
        "example_4": [0.0, 0.11834, 0.141292, 0.732918],
        "example_5": [0.0, 0.11834, 0.728354, 0.118021, 0.889452],
        "hf_temporal_A": [0.0, 0.109691, 0.596019],
        "hf_struct_recip": [0.0, 0.69762],
    }
    runs = {
        "example_3": [(M, A, 100, 0), (M, H, 100, 1), (A, S, 100, 2), (H, S, 100, 3)],
        "example_4": [(M, A, 100, 0), (A, C, 100, 1), (C, O, 100, 2), (O, A, 100, 3)],
        "example_5": [
            (M, A, 100, 0), (A, C, 100, 1), (C, M, 100, 2),
            (A, N, 100, 3), (N, M, 100, 4),
        ],
        "hf_temporal_A": [
            ("A1", "A2", 100, 0), ("A2", "A3", 100, 60), ("A3", "A1", 100, 23 * 60),
        ],
        "hf_struct_recip": [("E2", "E3", 100, 0), ("E3", "E2", 100, 60)],
    }
    for name, steps in runs.items():
        assert stream(steps, name) == baseline[name], name


def test_flat_amounts_produce_no_value_evidence_at_all():
    """The drift-proof half of the guarantee above: whatever the structural model is
    tuned to, a trail whose amounts never change has nothing to confirm or contradict,
    so `ValueTrail` must stay silent on every shape the earlier phases are scored on."""
    trail = ValueTrail()
    when = 0.0
    for sender, receiver in [(M, A), (A, C), (C, H), (H, N), (M, H), (H, S)]:
        assert trail.evidence(sender, 100.0, when) == (0.0, 0.0)
        trail.record(sender, receiver, when, 100.0)
        when += 60.0


def test_value_evidence_never_lowers_a_structural_score():
    """Value only ever adds, exactly as identity does: the Phase 1 post-mortems
    measured under-scoring a hot transaction at ~4x the cost of over-scoring a cold
    one, and the statement only ever says to "assign a higher risk score when value
    evidence increases combined suspicion"."""
    structures = [
        [(M, A, 0), (A, C, 1)],                                   # extension
        [(M, A, 0), (M, H, 1), (A, S, 2), (H, S, 3)],             # convergence
        [(M, A, 0), (A, C, 1), (C, O, 2), (O, A, 3)],             # return
        [(M, A, 0), (A, C, 1), (C, M, 2), (A, N, 3), (N, M, 4)],  # multi-loop
    ]
    for index, edges in enumerate(structures):
        flat = [(s[0], s[1], 100.0, s[2]) for s in edges]
        varied = [(s[0], s[1], 100.0 + 37 * i, s[2]) for i, s in enumerate(edges)]
        bare, valued = last(flat, f"n{index}"), last(varied, f"w{index}")
        assert valued >= bare, edges
        assert 0.0 <= valued <= 1.0


def test_self_transfer_stays_at_zero_whatever_it_carries():
    scores = stream([(M, A, 10000, 0), ("E1", "E1", 999999, 1)], "z1")
    assert scores[-1] == 0.0


# --- state follows the lookback window -------------------------------------


def test_value_evidence_expires_with_the_window():
    """An amount from 25 hours ago is not part of any flow any more: the trail it
    belonged to has left the graph, so the later hop has nothing to contradict."""
    aged = stream(
        [(M, A, 10000, 0), (A, C, 5000, 1), (C, H, 9000, 25 * 60)], "e1"
    )
    assert aged[-1] == 0.0


def test_reset_clears_value_state():
    stream([(M, A, 10000, 0), (A, C, 5000, 1)], "e2")
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    r = send([{
        "txId": "e3", "fromUserId": C, "toUserId": H,
        "amount": 9000, "createdAt": at(2),
    }])
    assert r.json()["transactions"][0]["riskScore"] == 0.0


def test_duplicate_txid_with_a_new_amount_returns_the_original_score():
    stream([(M, A, 10000, 0), (A, C, 9900, 1)], "d1")
    first = send([{
        "txId": "dup", "fromUserId": C, "toUserId": H,
        "amount": 9800, "createdAt": at(2),
    }])
    original = first.json()["transactions"][0]["riskScore"]
    again = send([{
        "txId": "dup", "fromUserId": C, "toUserId": H,
        "amount": 99999, "createdAt": at(2),
    }])
    assert again.json()["transactions"][0]["riskScore"] == original


def test_value_from_a_later_leg_cannot_score_an_earlier_one():
    """A transaction is scored on what was known at *its* moment. A leg that fed the
    sender at 12:20 is not a trail its 12:05 transfer can have contradicted."""
    out_of_order = [(M, A, 10000, 0), (M, A, 100, 20), (A, C, 9900, 5)]
    assert last(out_of_order, "t1") == last(
        [(M, A, 10000, 0), (M, A, 10000, 20), (A, C, 10000, 5)], "t2"
    )


def test_batched_transactions_build_the_value_trail_in_order():
    """"Multiple transactions in a single request must be processed sequentially in
    order" -- so the amount on the first is part of the trail scoring the third."""
    batch = [
        {"txId": "s0", "fromUserId": M, "toUserId": A, "amount": 10000,
         "createdAt": at(0)},
        {"txId": "s1", "fromUserId": A, "toUserId": C, "amount": 5000,
         "createdAt": at(1)},
        {"txId": "s2", "fromUserId": C, "toUserId": H, "amount": 4900,
         "createdAt": at(2)},
    ]
    r = send(batch)
    assert r.status_code == 200
    scores = [item["riskScore"] for item in r.json()["transactions"]]
    assert scores == stream(
        [(M, A, 10000, 0), (A, C, 5000, 1), (C, H, 4900, 2)], "s3"
    )


# --- amounts that cannot form a ratio --------------------------------------


@pytest.mark.parametrize("amount", [0, 0.0, -50.0, 1e-300, 1e308])
def test_degenerate_amounts_never_break_processing(amount):
    """`amount` is required, so it cannot simply be absent — but nothing about a
    zero, negative or enormous amount may produce a NaN score or a 500."""
    scores = stream([(M, A, 10000, 0), (A, C, amount, 1), (C, H, 9000, 2)], "g1")
    for score in scores:
        assert 0.0 <= score <= 1.0
        assert score == score  # not NaN


def test_a_non_positive_amount_carries_no_value_signal():
    """There is no retention ratio to read from a zero or negative transfer, so it
    ends the trail rather than inventing evidence from it."""
    assert last([(M, A, 10000, 0), (A, C, 0, 1), (C, H, 9000, 2)], "g2") == last(
        [(M, A, 100, 0), (A, C, 100, 1), (C, H, 100, 2)], "g3"
    )


def test_non_numeric_amount_is_still_rejected():
    r = send([{
        "txId": "g4", "fromUserId": M, "toUserId": A,
        "amount": "a lot", "createdAt": at(0),
    }])
    assert r.status_code == 422


def test_earlier_phases_still_work():
    assert client.get("/health").status_code == 200
    assert client.post("/square", json={"value": 5}).json()["result"] == 25
    assert client.get("/ghost-chains/health").json() == {"status": "ok"}


@pytest.mark.parametrize("gap", [0, 1, 5, 15, 30, 60, 120, 240])
def test_the_required_ordering_survives_the_sequences_being_spread_out(gap):
    """The statement gives its examples as ordered sequences with no timestamps, so
    the ordering has to hold however tightly or loosely the grader spaces them —
    including four transactions sharing one instant.

    It holds out to four-hourly spacing. Beyond roughly eight hours a gap the 24-hour
    window has expired the head of each chain and the scenario is no longer the
    scenario; see notes.md, "Where the required ordering stops holding"."""

    def spaced(steps, prefix):
        return last([(s[0], s[1], s[2], i * gap) for i, s in enumerate(steps)], prefix)

    one = spaced(EXAMPLE_1, f"q{gap}a")
    two = spaced(EXAMPLE_2, f"q{gap}b")
    three = spaced(EXAMPLE_3, f"q{gap}c")
    four = spaced(EXAMPLE_4, f"q{gap}d")
    assert one == min(one, two, three, four)
    assert three == max(one, two, three, four)


@pytest.mark.parametrize("decay_free", [True, False])
@pytest.mark.parametrize("gap", [0, 1, 5, 15, 30])
def test_the_required_ordering_holds_whichever_way_the_decay_flag_is_set(decay_free, gap):
    """`DECAY_FREE_BANDS` is Phase 1's open lever, and the graded feedback
    `TEMPORAL_DEVIATION: High` may yet send it back to False. Phase 3 must not be
    what stops that: the statement's required ordering holds under both settings.

    The spacings it survives do differ — decay-free holds out to 240 minutes, the
    decaying build to 30, because decay erodes Example 2's already-shorter trail
    fastest. Only the range common to both is pinned here; the wider decay-free range
    is pinned by `test_the_required_ordering_survives_the_sequences_being_spread_out`.
    """
    original = phase3.DECAY_FREE_BANDS
    phase3.DECAY_FREE_BANDS = decay_free
    try:
        def spaced(steps, prefix):
            return last([(s[0], s[1], s[2], i * gap) for i, s in enumerate(steps)], prefix)

        one = spaced(EXAMPLE_1, f"f{decay_free}{gap}a")
        two = spaced(EXAMPLE_2, f"f{decay_free}{gap}b")
        three = spaced(EXAMPLE_3, f"f{decay_free}{gap}c")
        four = spaced(EXAMPLE_4, f"f{decay_free}{gap}d")
        assert one == min(one, two, three, four)
        assert three == max(one, two, three, four)
    finally:
        phase3.DECAY_FREE_BANDS = original
