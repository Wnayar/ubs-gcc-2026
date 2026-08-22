"""Ghost Chains Phase 1 — see docs/phases/phase-3/notes.md.

The statement is explicit that absolute scores need not match a reference: what is
scored is the *ranking* and structural coherence. So these tests assert the
orderings the statement demands, plus the one absolute value it pins (an isolated
transaction scores 0.0), plus the protocol rules.
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

EXAMPLE_1 = [(M, A)]
EXAMPLE_2 = [(M, A), (A, C)]
EXAMPLE_3 = [(M, A), (M, H), (A, S), (H, S)]
EXAMPLE_4 = [(M, A), (A, C), (C, O), (O, A)]
EXAMPLE_5 = [(M, A), (A, C), (C, M), (A, N), (N, M)]


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


def run_example(pairs, prefix="ex"):
    """Stream a sequence one transaction per request; return the last risk score."""
    scores = []
    for i, (sender, receiver) in enumerate(pairs):
        r = send([tx(f"{prefix}_{i}", sender, receiver, minutes=i)])
        assert r.status_code == 200, r.text
        scores.append(r.json()["transactions"][0]["riskScore"])
    return scores[-1]


# --- endpoints -------------------------------------------------------------


def test_health():
    r = client.get("/ghost-chains/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_reset_echoes_request():
    r = client.post("/ghost-chains/reset", json={"clearTransactions": True})
    assert r.status_code == 200
    assert r.json() == {"clearTransactions": True}


def test_statement_batch_example():
    # verbatim from statement.pdf page 4 — two isolated transactions, both 0.0
    r = send(
        [
            {
                "txId": "tx_meridian_001",
                "fromUserId": "meridian_holdings",
                "toUserId": "apex_logistics",
                "amount": 370.0,
                "createdAt": "2026-06-08T12:00:00Z",
            },
            {
                "txId": "tx_cascade_014",
                "fromUserId": "cascade_payments",
                "toUserId": "horizon_capital",
                "amount": 100.0,
                "createdAt": "2026-06-08T12:01:00Z",
            },
        ]
    )
    assert r.status_code == 200
    assert r.json() == {
        "transactions": [
            {"txId": "tx_meridian_001", "riskScore": 0.0},
            {"txId": "tx_cascade_014", "riskScore": 0.0},
        ]
    }


def test_response_preserves_input_order():
    ids = [f"ord_{i}" for i in range(6)]
    r = send([tx(t, f"s{i}", f"r{i}", minutes=i) for i, t in enumerate(ids)])
    assert [e["txId"] for e in r.json()["transactions"]] == ids


# --- the five worked examples ---------------------------------------------


@pytest.fixture
def example_scores():
    scores = {}
    for name, pairs in [
        ("ex1", EXAMPLE_1),
        ("ex2", EXAMPLE_2),
        ("ex3", EXAMPLE_3),
        ("ex4", EXAMPLE_4),
        ("ex5", EXAMPLE_5),
    ]:
        client.post("/ghost-chains/reset", json={"clearTransactions": True})
        scores[name] = run_example(pairs, prefix=name)
    return scores


def test_example_1_is_lowest_of_the_five(example_scores):
    # statement: "Example 1 should receive the lowest risk score of the five."
    assert example_scores["ex1"] < min(
        example_scores[k] for k in ("ex2", "ex3", "ex4", "ex5")
    )


def test_isolated_transaction_scores_zero(example_scores):
    assert example_scores["ex1"] == 0.0


def test_extension_scores_above_isolated(example_scores):
    assert example_scores["ex2"] > example_scores["ex1"]


def test_convergence_sits_between_extension_and_return(example_scores):
    # "stronger than simple extension, but not necessarily as suspicious as a
    # return path"
    assert example_scores["ex2"] < example_scores["ex3"] < example_scores["ex4"]


def test_return_is_meaningfully_above_extension(example_scores):
    # statement: "meaningfully higher"
    assert example_scores["ex4"] - example_scores["ex2"] >= 0.1


def test_multi_loop_is_meaningfully_above_single_return(example_scores):
    # "Two independent return paths converging on the same node represent a
    # stronger structural signal than a single return."
    assert example_scores["ex5"] - example_scores["ex4"] >= 0.05


def test_all_scores_in_range(example_scores):
    assert all(0.0 <= s <= 1.0 for s in example_scores.values())


# --- streaming rules -------------------------------------------------------


def test_identical_duplicate_txid_returns_original_score_and_does_not_mutate():
    first = send([tx("dup_1", M, A, minutes=0)]).json()["transactions"][0]["riskScore"]
    again = send([tx("dup_1", M, A, minutes=0)]).json()["transactions"][0]["riskScore"]
    assert again == first
    # if the duplicate had been applied as a second edge, this extension would see
    # a different graph; compare against a clean run of the same two-edge sequence
    after_dup = send([tx("dup_2", A, C, minutes=1)]).json()["transactions"][0]["riskScore"]
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    send([tx("clean_1", M, A, minutes=0)])
    clean = send([tx("clean_2", A, C, minutes=1)]).json()["transactions"][0]["riskScore"]
    assert after_dup == clean


def test_duplicate_txid_with_different_payload_returns_original_score():
    first = send([tx("same_id", M, A, minutes=0)]).json()["transactions"][0]["riskScore"]
    r = send([tx("same_id", C, O, minutes=5, amount=999.0)])
    assert r.status_code == 200
    assert r.json()["transactions"][0]["riskScore"] == first


def test_reset_clears_graph_state():
    send([tx("r_1", M, A, minutes=0)])
    with_history = send([tx("r_2", A, C, minutes=1)]).json()["transactions"][0]["riskScore"]
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    fresh = send([tx("r_3", A, C, minutes=1)]).json()["transactions"][0]["riskScore"]
    assert with_history > fresh == 0.0


def test_identical_input_after_reset_scores_identically():
    first = run_example(EXAMPLE_5, prefix="det_a")
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    second = run_example(EXAMPLE_5, prefix="det_b")
    assert first == second


def test_reset_false_does_not_clear():
    send([tx("keep_1", M, A, minutes=0)])
    r = client.post("/ghost-chains/reset", json={"clearTransactions": False})
    assert r.status_code == 200
    assert r.json() == {"clearTransactions": False}
    kept = send([tx("keep_2", A, C, minutes=1)]).json()["transactions"][0]["riskScore"]
    assert kept > 0.0


# --- lookback window -------------------------------------------------------


def test_expired_transaction_does_not_influence_scoring():
    send([tx("old_1", M, A, minutes=0)])
    # 24h + 1 minute later the first edge is outside the window, so this is an
    # isolated transaction again
    r = send([tx("old_2", A, C, minutes=24 * 60 + 1)])
    assert r.json()["transactions"][0]["riskScore"] == 0.0


def test_edge_exactly_at_window_boundary_is_still_active():
    send([tx("edge_1", M, A, minutes=0)])
    r = send([tx("edge_2", A, C, minutes=24 * 60)])
    assert r.json()["transactions"][0]["riskScore"] > 0.0


def test_transaction_just_inside_window_still_counts():
    send([tx("in_1", M, A, minutes=0)])
    r = send([tx("in_2", A, C, minutes=24 * 60 - 1)])
    assert r.json()["transactions"][0]["riskScore"] > 0.0


# --- tolerance of optional / unknown / bad input ---------------------------


def test_optional_fields_present_are_accepted():
    r = send(
        [tx("opt_1", M, A, minutes=0, ipAddress="203.0.113.7", deviceId="dev-9")]
    )
    assert r.status_code == 200


def test_unknown_fields_are_ignored():
    # forward compatibility: later phases add fields; do not reject them
    r = send([tx("unk_1", M, A, minutes=0, somethingFromPhase4={"nested": 1})])
    assert r.status_code == 200
    assert r.json()["transactions"][0]["txId"] == "unk_1"


def test_empty_transaction_list_is_ok():
    r = send([])
    assert r.status_code == 200
    assert r.json() == {"transactions": []}


def test_missing_required_field_rejected():
    r = send([{"txId": "bad_1", "fromUserId": M, "amount": 1.0, "createdAt": at(0)}])
    assert r.status_code == 422


def test_unparseable_timestamp_rejected():
    r = send([tx("bad_2", M, A) | {"createdAt": "not-a-timestamp"}])
    assert r.status_code == 422


def test_non_numeric_amount_rejected():
    r = send([tx("bad_3", M, A) | {"amount": "a lot"}])
    assert r.status_code == 422


def test_missing_transactions_key_rejected():
    r = client.post("/ghost-chains/transactions", json={})
    assert r.status_code == 422


def test_self_transfer_does_not_fail():
    r = send([tx("self_1", M, M, minutes=0)])
    assert r.status_code == 200
    assert 0.0 <= r.json()["transactions"][0]["riskScore"] <= 1.0


def test_repeated_edge_does_not_fail():
    send([tx("rep_1", M, A, minutes=0)])
    r = send([tx("rep_2", M, A, minutes=1)])
    assert r.status_code == 200
    assert 0.0 <= r.json()["transactions"][0]["riskScore"] <= 1.0


# --- earlier phases --------------------------------------------------------


def test_earlier_phases_still_work():
    assert client.post("/square", json={"value": 5}).json() == {"result": 25}
    assert client.get("/health").json()["status"] == "ok"
