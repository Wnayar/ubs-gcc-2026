"""Ghost Chains Phase 2 — "Identity Signal". See docs/phases/ghost-chains/phase-2/notes.md.

The statement says outright that its four examples "show how evidence changes -- they
do not define a strict risk ordering between scenarios", so these tests assert the
relations it *does* state: identity agreement reinforces structure, reuse across
disconnected components is a hint rather than proof, a dropped identifier on a
carrying flow is itself a signal, and the two attributes are independent dimensions.

They also pin the thing a Phase 2 evaluation re-tests: with no identity fields in the
stream, every score must be exactly what Phase 1 returned.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app

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
IP = "10.0.0.1"

# Phase 1 scores of the 369-point build, captured before Phase 2 was written. A
# stream carrying no identity fields must still produce exactly these.
#
# `example_5[2]` and `hf_temporal_A[2]` were briefly higher (0.728354 / 0.596019)
# while the dedicated-cycle exemption was shipped; run 9 scored 368 with it and run
# 8 scored 368 without, so it bought nothing, and these are the 369 numbers again.
PHASE_1_BASELINE = {
    "example_1": [0.0],
    "example_2": [0.0, 0.11774],
    "example_3": [0.0, 0.0, 0.116985, 0.360534],
    "example_4": [0.0, 0.11774, 0.140565, 0.73052],
    "example_5": [0.0, 0.11774, 0.725981, 0.116235, 0.887572],
    "hf_temporal_A": [0.0, 0.081431, 0.300193],
    "hf_temporal_B": [0.0, 0.081431, 0.010033],
    "hf_struct_self": [0.0],
    "hf_struct_recip": [0.0, 0.584907],
}


@pytest.fixture(autouse=True)
def clean_state():
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    yield
    client.post("/ghost-chains/reset", json={"clearTransactions": True})


def at(minutes: float) -> str:
    return (BASE + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def tx(tx_id, sender, receiver, minutes=0, amount=100.0, **extra):
    body = {
        "txId": tx_id,
        "fromUserId": sender,
        "toUserId": receiver,
        "amount": amount,
        "createdAt": at(minutes),
    }
    body.update(extra)
    return body


def send(transactions):
    return client.post("/ghost-chains/transactions", json={"transactions": transactions})


def stream(steps, prefix):
    """Stream (sender, receiver, minutes, extra) steps one per request, from a clean
    state; return every risk score."""
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    scores = []
    for i, step in enumerate(steps):
        sender, receiver, minutes = step[0], step[1], step[2]
        extra = step[3] if len(step) > 3 else {}
        r = send([tx(f"{prefix}_{i}", sender, receiver, minutes=minutes, **extra)])
        assert r.status_code == 200, r.text
        scores.append(r.json()["transactions"][0]["riskScore"])
    return scores


def last(steps, prefix):
    return stream(steps, prefix)[-1]


def strip_identity(steps):
    """The same structure with every identity attribute removed."""
    return [(s[0], s[1], s[2]) for s in steps]


# --- the statement's four examples -----------------------------------------

EXAMPLE_1 = [
    (M, A, 0, {"deviceId": IOS}),
    (A, C, 1, {"deviceId": IOS}),
    (C, H, 2, {"deviceId": IOS}),
]
EXAMPLE_2 = [
    (M, A, 0, {"deviceId": IOS}),
    (A, C, 1, {"deviceId": IOS}),
    (A, S, 2, {"deviceId": IOS}),
    (C, O, 3, {"deviceId": ANDROID}),
]
EXAMPLE_3 = [
    (M, A, 0, {"deviceId": IOS}),
    (A, C, 1, {"deviceId": IOS}),
    (C, H, 2, {"deviceId": ANDROID}),
    (H, N, 3, {"deviceId": ANDROID}),
]
EXAMPLE_4 = [
    (M, A, 0, {"ipAddress": IP}),
    (C, H, 1, {"ipAddress": IP}),
    (O, S, 2, {"ipAddress": IP}),
]


def test_example_1_consistent_identity_reinforces_structure():
    """"Structural and identity observations reinforce each other within this segment.\""""
    with_identity = last(EXAMPLE_1, "e1")
    without = last(strip_identity(EXAMPLE_1), "e1n")
    assert with_identity > without


def test_example_2_new_device_on_a_branch_is_weaker_than_a_consistent_one():
    """A branch that introduces a new device carries less identity evidence than one
    that continues the flow's device -- but is not *less* suspicious than a branch
    with no identity information at all."""
    divergent = last(EXAMPLE_2, "e2")
    consistent = last(
        EXAMPLE_2[:3] + [(C, O, 3, {"deviceId": IOS})], "e2c"
    )
    silent = last(strip_identity(EXAMPLE_2), "e2n")
    assert consistent > divergent >= silent


def test_example_3_identity_shift_mid_flow_sits_below_an_unbroken_identity():
    """The structural path is unbroken but the identity evidence changes partway:
    both observations are valid and are weighed together."""
    shifted = last(EXAMPLE_3, "e3")
    unbroken = last(
        [(M, A, 0, {"deviceId": IOS}), (A, C, 1, {"deviceId": IOS}),
         (C, H, 2, {"deviceId": IOS}), (H, N, 3, {"deviceId": IOS})], "e3c"
    )
    silent = last(strip_identity(EXAMPLE_3), "e3n")
    assert unbroken > shifted >= silent


def test_example_4_shared_identity_across_disconnected_components_is_a_hint():
    """Three unrelated transfers share one address: a cross-structural relationship
    invisible from the graph, but it "does not independently establish risk"."""
    scores = stream(EXAMPLE_4, "e4")
    assert scores[0] == 0.0  # first sighting: nothing to share with yet
    assert scores[2] > 0.0  # third component makes it a signal
    # ...but weaker than ordinary structural flow, let alone a return
    assert scores[2] < last([(M, A, 0), (A, C, 1)], "e4f")


def test_example_4_a_single_shared_attribute_is_coincidence():
    """"A single shared attribute can be coincidence (office Wi-Fi, cloud NAT)."\""""
    two_components = stream(EXAMPLE_4[:2], "e4a")
    assert two_components[1] == last(strip_identity(EXAMPLE_4[:2]), "e4b")


# --- missing identity ------------------------------------------------------

CARRYING_CHAIN = [
    (M, A, 0, {"deviceId": IOS}),
    (A, C, 1, {"deviceId": IOS}),
]


def test_dropped_identifier_on_a_connected_flow_is_a_signal():
    """"Dropping a network address or device identifier mid-path is a way to break
    the trail."\""""
    dropped = last(CARRYING_CHAIN + [(C, H, 2)], "d1")
    silent = last(strip_identity(CARRYING_CHAIN) + [(C, H, 2)], "d2")
    assert dropped > silent


def test_dropped_identifier_stays_below_a_flow_that_keeps_it():
    kept = last(CARRYING_CHAIN + [(C, H, 2, {"deviceId": IOS})], "d3")
    dropped = last(CARRYING_CHAIN + [(C, H, 2)], "d4")
    assert kept > dropped


def test_missing_identity_on_an_unrelated_transaction_is_normal():
    """The suspicious case is a *consistent flow* that stops carrying its identity;
    an unrelated transfer with no identity is ordinary and must score as before."""
    unrelated = stream(CARRYING_CHAIN + [(O, S, 2)], "d5")[-1]
    assert unrelated == 0.0


def test_absence_of_one_attribute_does_not_erase_the_other():
    """A leg that keeps its device but drops its address still carries evidence."""
    both = [
        (M, A, 0, {"deviceId": IOS, "ipAddress": IP}),
        (A, C, 1, {"deviceId": IOS, "ipAddress": IP}),
    ]
    half = last(both + [(C, H, 2, {"deviceId": IOS})], "h1")
    silent = last(strip_identity(both) + [(C, H, 2)], "h2")
    assert half > silent


# --- independent dimensions ------------------------------------------------


def test_two_agreeing_attributes_beat_one():
    """"When both are present, treat them as independent dimensions."\""""
    device_only = last(
        [(M, A, 0, {"deviceId": IOS}), (A, C, 1, {"deviceId": IOS}),
         (C, H, 2, {"deviceId": IOS})], "i1"
    )
    both = last(
        [(M, A, 0, {"deviceId": IOS, "ipAddress": IP}),
         (A, C, 1, {"deviceId": IOS, "ipAddress": IP}),
         (C, H, 2, {"deviceId": IOS, "ipAddress": IP})], "i2"
    )
    assert both > device_only


def test_identity_evidence_never_lowers_a_structural_score():
    """Identity only ever adds: the Phase 1 post-mortems measured under-scoring a
    hot transaction at ~4x the cost of over-scoring a cold one."""
    structures = [
        [(M, A, 0), (A, C, 1)],                                  # extension
        [(M, A, 0), (M, H, 1), (A, S, 2), (H, S, 3)],            # convergence
        [(M, A, 0), (A, C, 1), (C, O, 2), (O, A, 3)],            # return
        [(M, A, 0), (A, C, 1), (C, M, 2), (A, N, 3), (N, M, 4)],  # multi-loop
    ]
    for index, steps in enumerate(structures):
        bare = last(steps, f"n{index}")
        tagged = last(
            [(s[0], s[1], s[2], {"deviceId": IOS, "ipAddress": IP}) for s in steps],
            f"t{index}",
        )
        assert tagged >= bare, steps
        assert 0.0 <= tagged <= 1.0


def test_identity_lift_is_bounded_by_the_structural_band():
    """Identity amplifies structure, it does not replace it: no identity evidence
    can lift ordinary onward flow past a genuine multi-loop."""
    onward = last(
        [(M, A, 0, {"deviceId": IOS, "ipAddress": IP}),
         (A, C, 1, {"deviceId": IOS, "ipAddress": IP})], "b1"
    )
    multi_loop = last(
        [(M, A, 0), (A, C, 1), (C, M, 2), (A, N, 3), (N, M, 4)], "b2"
    )
    assert onward < multi_loop


def test_identity_can_never_move_a_transaction_out_of_its_band():
    """The strong form, and the reason Phase 1 survives a Phase 2 evaluation: a
    fully corroborated identity signal on the weakest member of a band still ranks
    below the weakest member of the band above, whatever the graph looks like.

    A lift that could cross a band would demote every structurally hotter transfer
    that carries no identifier -- and Phase 1 measured under-scoring a hot
    transaction at ~4x the cost of over-scoring a cold one.
    """
    from app.routers.phase3 import BANDS, _band_ceiling

    structures = {
        "isolated": [(O, S, 0)],
        "onward": [(M, A, 0), (A, C, 1)],
        "convergence": [(M, A, 0), (M, H, 1), (A, S, 2), (H, S, 3)],
        "return": [(M, A, 0), (A, C, 1), (C, O, 2), (O, A, 3)],
        "multi_loop": [(M, A, 0), (A, C, 1), (C, M, 2), (A, N, 3), (N, M, 4)],
    }
    for name, steps in structures.items():
        bare = last(steps, f"c{name}")
        tagged = last(
            [(s[0], s[1], s[2], {"deviceId": IOS, "ipAddress": IP}) for s in steps],
            f"cid{name}",
        )
        assert bare <= tagged < _band_ceiling(bare), name
        assert _band_ceiling(bare) in BANDS, name


def test_identity_only_evidence_ranks_below_every_real_flow():
    """"Shared identity across disconnected components ... does not independently
    establish risk": with no structure at all it gets the band below onward flow,
    above a genuinely isolated pair and below the weakest real chain."""
    from app.routers.phase3 import TIER_ONWARD

    cross_component = stream(EXAMPLE_4, "z1")[-1]
    weakest_flow = last(strip_identity([(M, A, 0), (A, C, 1)]), "z2")
    assert 0.0 < cross_component < TIER_ONWARD <= weakest_flow


# --- identity state follows the lookback window ----------------------------


def test_identity_evidence_expires_with_the_window():
    aged = stream(
        [(M, A, 0, {"ipAddress": IP}),
         (C, H, 1, {"ipAddress": IP}),
         (O, S, 25 * 60, {"ipAddress": IP})], "x1"
    )
    assert aged[-1] == 0.0


def test_reset_clears_identity_state():
    stream(EXAMPLE_4[:2], "x2")
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    r = send([tx("x3", O, S, minutes=2, ipAddress=IP)])
    assert r.json()["transactions"][0]["riskScore"] == 0.0


def test_duplicate_txid_with_new_identity_returns_the_original_score():
    first = send([tx("dup", M, A, minutes=0, deviceId=IOS)])
    original = first.json()["transactions"][0]["riskScore"]
    again = send([tx("dup", M, A, minutes=0, deviceId=ANDROID, ipAddress=IP)])
    assert again.json()["transactions"][0]["riskScore"] == original
    # and the replay must not have registered a second identity anywhere
    assert last([(C, H, 1, {"ipAddress": IP}), (O, S, 2, {"ipAddress": IP})], "dup2") == 0.0


# --- Phase 1 must be untouched ---------------------------------------------


def test_identity_free_stream_matches_phase_1_baseline():
    """A Phase 2 evaluation re-tests every Phase 1 requirement. With no identity
    fields present, scores must be bit-for-bit the 369-point build's."""
    runs = {
        "example_1": [(M, A, 0)],
        "example_2": [(M, A, 0), (A, C, 1)],
        "example_3": [(M, A, 0), (M, H, 1), (A, S, 2), (H, S, 3)],
        "example_4": [(M, A, 0), (A, C, 1), (C, O, 2), (O, A, 3)],
        "example_5": [(M, A, 0), (A, C, 1), (C, M, 2), (A, N, 3), (N, M, 4)],
        "hf_temporal_A": [("A1", "A2", 0), ("A2", "A3", 60), ("A3", "A1", 23 * 60)],
        "hf_temporal_B": [("B1", "B2", 0), ("B2", "B3", 60), ("B3", "B1", 24 * 60)],
        "hf_struct_self": [("E1", "E1", 0)],
        "hf_struct_recip": [("E2", "E3", 0), ("E3", "E2", 60)],
    }
    for name, steps in runs.items():
        assert stream(steps, name) == PHASE_1_BASELINE[name], name


def test_self_transfer_with_identity_still_scores_zero():
    scores = stream(
        [(M, A, 0, {"deviceId": IOS}), ("E1", "E1", 1, {"deviceId": IOS})], "s1"
    )
    assert scores[-1] == 0.0


# --- tolerating junk in the optional fields --------------------------------


@pytest.mark.parametrize(
    "value", [None, "", "   ", 12345, 10.5, True, {"a": 1}, [1, 2], "10.0.0.1"]
)
def test_identity_fields_never_break_processing(value):
    r = send([tx("j1", M, A, minutes=0, ipAddress=value, deviceId=value)])
    assert r.status_code == 200, r.text
    score = r.json()["transactions"][0]["riskScore"]
    assert 0.0 <= score <= 1.0


def test_blank_identity_is_treated_as_absent():
    blank = stream(
        [(M, A, 0, {"ipAddress": ""}), (C, H, 1, {"ipAddress": ""}),
         (O, S, 2, {"ipAddress": ""})], "j2"
    )
    assert blank[-1] == 0.0


def test_identity_on_an_unknown_extra_field_is_ignored():
    r = send([tx("j3", M, A, minutes=0, macAddress="aa:bb:cc", sessionId="abc")])
    assert r.status_code == 200
    assert r.json()["transactions"][0]["riskScore"] == 0.0


def test_earlier_phases_still_work():
    assert client.get("/health").status_code == 200
    assert client.post("/square", json={"value": 5}).json()["result"] == 25


# --- ordering and infrastructure -------------------------------------------


def test_identity_within_a_single_batch_counts_sequentially():
    """"Multiple transactions in a single request must be processed sequentially in
    order" -- so identity registered by the first is evidence about the third."""
    batch = [
        tx("s1", M, A, minutes=0, deviceId=IOS),
        tx("s2", A, C, minutes=1, deviceId=IOS),
        tx("s3", C, H, minutes=2, deviceId=IOS),
    ]
    r = send(batch)
    assert r.status_code == 200
    scores = [item["riskScore"] for item in r.json()["transactions"]]
    assert scores[2] > last(strip_identity(EXAMPLE_1), "s4")


def test_identity_from_a_later_leg_cannot_score_an_earlier_one():
    """A late-arriving transaction is scored on what was known at *its* moment: a
    leg that fed the sender at 12:20 is not a trail its 12:05 transfer can have
    dropped. Scoring on evidence from the future is the mistake that had Phase 1
    reporting TEMPORAL_DEVIATION for three evaluations."""
    out_of_order = [
        (M, A, 0, {"deviceId": IOS}),
        (M, A, 20, {"deviceId": IOS}),
        (A, C, 5),  # arrives last, but happened in between
    ]
    assert last(out_of_order, "o1") == last(strip_identity(out_of_order), "o2")


def test_an_address_shared_by_hundreds_of_entities_is_infrastructure():
    """Cloud NAT is named in the statement as the coincidence case: reuse stops
    counting as coordination once it is shared by the whole world."""
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    crowd = [
        tx(f"nat_{i}", f"user_{i}", f"peer_{i}", minutes=i, ipAddress=IP)
        for i in range(300)
    ]
    assert send(crowd).status_code == 200
    r = send([tx("nat_last", O, S, minutes=300, ipAddress=IP)])
    assert r.json()["transactions"][0]["riskScore"] == 0.0


def test_a_dropped_identifier_weighs_the_trail_it_broke():
    """"Weigh absence against the surrounding structure rather than treating every
    missing field as suspicious": a long, consistently-tagged flow that stops
    carrying its device says far more than one leg that never really carried it."""
    long_trail = [
        (M, A, 0, {"deviceId": IOS}),
        (A, C, 1, {"deviceId": IOS}),
        (C, H, 2, {"deviceId": IOS}),
        (H, N, 3),
    ]
    short_trail = [(M, A, 0, {"deviceId": IOS}), (A, C, 1)]

    def identity_delta(steps, prefix):
        return last(steps, prefix) - last(strip_identity(steps), prefix + "n")

    assert identity_delta(long_trail, "w1") > identity_delta(short_trail, "w2") > 0
