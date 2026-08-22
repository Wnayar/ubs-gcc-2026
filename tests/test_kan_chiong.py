"""Kan Chiong Delivery Driver — statement examples and edge cases.

Every worked example from docs/phases/kan-chiong-delivery-driver/statement.pdf is
reproduced verbatim as a test. The non-statement tests at the bottom pin down the
semantics derived in notes.md (window boundaries, mid-edge speed changes, exact
fraction arithmetic, per-case robustness).
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

URL = "/kan-cheong-delivery-driver"

NULL_ANSWER = {"total_duration_sec": None, "arrival_time": None, "path": []}


def solve_one(case: dict) -> dict:
    """Send a single case through the batch endpoint and return its answer."""
    r = client.post(URL, json={"case": case})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"case"}
    return body["case"]


# --- Batch example (statement pages 1-2) -----------------------------------

def test_batch_example():
    request = {
        "case_1": {
            "start_coordinate": [0, 0],
            "end_coordinate": [1, 0],
            "start_time": "2026-06-10T08:30:00Z",
            "nodes": [[0, 0], [1, 0]],
            "edges": [
                {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60}
            ],
            "obstructions": [],
        },
        "case_2": {
            "start_coordinate": [0, 0],
            "end_coordinate": [1, 0],
            "start_time": "2026-06-10T08:30:00Z",
            "nodes": [[0, 0], [1, 0]],
            "edges": [
                {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60}
            ],
            "obstructions": [
                {
                    "edge_id": "edge_0",
                    "edge": {"from": [0, 0], "to": [1, 0]},
                    "start_time": "2026-06-10T08:00:00Z",
                    "end_time": "2026-06-10T09:00:00Z",
                    "speed_factor": 0.0,
                }
            ],
        },
    }
    r = client.post(URL, json=request)
    assert r.status_code == 200
    assert r.json() == {
        "case_1": {
            "total_duration_sec": 60,
            "arrival_time": "2026-06-10T08:31:00Z",
            "path": ["edge_0"],
        },
        "case_2": NULL_ANSWER,
    }


# --- Examples 1 & 2 share this network -------------------------------------

EXAMPLE_1_2_NETWORK = {
    "start_time": "2026-06-10T08:30:00Z",
    "nodes": [[0, 0], [1, 0], [2, 0], [2, 1], [3, 1]],
    "edges": [
        {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60},
        {"edge_id": "edge_1", "node1": [1, 0], "node2": [2, 0], "base_duration_sec": 60},
        {"edge_id": "edge_2", "node1": [2, 0], "node2": [2, 1], "base_duration_sec": 40},
        {"edge_id": "edge_3", "node1": [2, 1], "node2": [3, 1], "base_duration_sec": 50},
        {"edge_id": "edge_4", "node1": [1, 0], "node2": [2, 1], "base_duration_sec": 120},
    ],
    "obstructions": [
        {
            "edge_id": "edge_1",
            "edge": {"from": [1, 0], "to": [2, 0]},
            "start_time": "2026-06-10T08:00:00Z",
            "end_time": "2026-06-10T09:00:00Z",
            "speed_factor": 0.5,
        },
        {
            "edge_id": "edge_2",
            "edge": {"from": [2, 1], "to": [2, 0]},
            "start_time": "2026-06-10T08:15:00Z",
            "end_time": "2026-06-10T08:45:00Z",
            "speed_factor": 0.0,
        },
    ],
}


def test_example_1_obstruction_makes_detour_faster():
    case = {"start_coordinate": [0, 0], "end_coordinate": [3, 1], **EXAMPLE_1_2_NETWORK}
    assert solve_one(case) == {
        "total_duration_sec": 230,
        "arrival_time": "2026-06-10T08:33:50Z",
        "path": ["edge_0", "edge_4", "edge_3"],
    }


def test_example_2_end_not_in_network_is_unreachable():
    case = {"start_coordinate": [0, 0], "end_coordinate": [3, 3], **EXAMPLE_1_2_NETWORK}
    assert solve_one(case) == NULL_ANSWER


# --- Example 3 (No Waiting + Cycling) --------------------------------------

def test_example_3_cycles_in_place_of_waiting():
    case = {
        "start_coordinate": [0, 0],
        "end_coordinate": [2, 0],
        "start_time": "2026-06-10T08:30:00Z",
        "nodes": [[0, 0], [1, 0], [2, 0]],
        "edges": [
            {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 10},
            {"edge_id": "edge_1", "node1": [1, 0], "node2": [2, 0], "base_duration_sec": 10},
            {"edge_id": "edge_2", "node1": [0, 0], "node2": [2, 0], "base_duration_sec": 20},
        ],
        "obstructions": [
            {
                "edge_id": "edge_1",
                "edge": {"from": [1, 0], "to": [2, 0]},
                "start_time": "2026-06-10T08:30:10Z",
                "end_time": "2026-06-10T08:30:20Z",
                "speed_factor": 0.0,
            },
            {
                "edge_id": "edge_1",
                "edge": {"from": [1, 0], "to": [2, 0]},
                "start_time": "2026-06-10T08:30:30Z",
                "end_time": "2026-06-10T08:30:40Z",
                "speed_factor": 0.0,
            },
            {
                "edge_id": "edge_2",
                "edge": {"from": [0, 0], "to": [2, 0]},
                "start_time": "2026-06-10T08:30:00Z",
                "end_time": "2026-06-10T08:32:00Z",
                "speed_factor": 0.2,
            },
        ],
    }
    assert solve_one(case) == {
        "total_duration_sec": 60,
        "arrival_time": "2026-06-10T08:31:00Z",
        "path": ["edge_0", "edge_0", "edge_0", "edge_0", "edge_0", "edge_1"],
    }


# --- Example 4 (No Waiting + Blocked at Start) ------------------------------

def test_example_4_blocked_at_start_is_unreachable():
    case = {
        "start_coordinate": [0, 0],
        "end_coordinate": [1, 0],
        "start_time": "2026-06-10T08:30:00Z",
        "nodes": [[0, 0], [1, 0]],
        "edges": [
            {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60}
        ],
        "obstructions": [
            {
                "edge_id": "edge_0",
                "edge": {"from": [0, 0], "to": [1, 0]},
                "start_time": "2026-06-10T08:00:00Z",
                "end_time": "2026-06-10T09:00:00Z",
                "speed_factor": 0.0,
            }
        ],
    }
    assert solve_one(case) == NULL_ANSWER


# --- Semantics pinned down beyond the statement's examples ------------------

def simple_case(**overrides) -> dict:
    """One 60 s edge from [0,0] to [1,0], departing 08:30."""
    case = {
        "start_coordinate": [0, 0],
        "end_coordinate": [1, 0],
        "start_time": "2026-06-10T08:30:00Z",
        "nodes": [[0, 0], [1, 0]],
        "edges": [
            {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60}
        ],
        "obstructions": [],
    }
    case.update(overrides)
    return case


def obstruction(start: str, end: str, sf: float, *, frm=(0, 0), to=(1, 0)) -> dict:
    return {
        "edge_id": "edge_0",
        "edge": {"from": list(frm), "to": list(to)},
        "start_time": start,
        "end_time": end,
        "speed_factor": sf,
    }


def test_start_equals_end_is_a_zero_second_trip():
    case = simple_case(end_coordinate=[0, 0])
    assert solve_one(case) == {
        "total_duration_sec": 0,
        "arrival_time": "2026-06-10T08:30:00Z",
        "path": [],
    }


def test_edges_are_bidirectional():
    case = simple_case(start_coordinate=[1, 0], end_coordinate=[0, 0])
    answer = solve_one(case)
    assert answer["total_duration_sec"] == 60
    assert answer["path"] == ["edge_0"]


def test_reverse_direction_obstruction_does_not_apply():
    # Block only the [1,0] -> [0,0] direction; we travel [0,0] -> [1,0].
    case = simple_case(
        obstructions=[obstruction("2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z", 0.0,
                                  frm=(1, 0), to=(0, 0))]
    )
    assert solve_one(case)["total_duration_sec"] == 60


def test_entry_at_exact_window_end_is_allowed():
    case = simple_case(
        obstructions=[obstruction("2026-06-10T08:00:00Z", "2026-06-10T08:30:00Z", 0.0)]
    )
    assert solve_one(case) == {
        "total_duration_sec": 60,
        "arrival_time": "2026-06-10T08:31:00Z",
        "path": ["edge_0"],
    }


def test_entry_at_exact_window_start_is_blocked():
    case = simple_case(
        obstructions=[obstruction("2026-06-10T08:30:00Z", "2026-06-10T08:31:00Z", 0.0)]
    )
    assert solve_one(case) == NULL_ANSWER


def test_slowdown_starting_mid_traversal_hits_only_the_remainder():
    # 30 s of progress at full speed, then the remaining 30 units at half speed
    # take 60 s: 90 s in total.
    case = simple_case(
        obstructions=[obstruction("2026-06-10T08:30:30Z", "2026-06-10T09:00:00Z", 0.5)]
    )
    assert solve_one(case) == {
        "total_duration_sec": 90,
        "arrival_time": "2026-06-10T08:31:30Z",
        "path": ["edge_0"],
    }


def test_block_starting_mid_traversal_stalls_the_edge():
    # 30 s of progress, stalled from 08:30:30 to 08:31:00, then the last 30 s.
    case = simple_case(
        obstructions=[obstruction("2026-06-10T08:30:30Z", "2026-06-10T08:31:00Z", 0.0)]
    )
    assert solve_one(case) == {
        "total_duration_sec": 90,
        "arrival_time": "2026-06-10T08:31:30Z",
        "path": ["edge_0"],
    }


def test_decimal_speed_factor_stays_exact():
    # 20 s edge at speed factor 0.2 must be exactly 100 s, not 100.00000000000001
    # (0.2 is not representable in binary floating point).
    case = simple_case(
        edges=[{"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 20}],
        obstructions=[obstruction("2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z", 0.2)],
    )
    assert solve_one(case) == {
        "total_duration_sec": 100,
        "arrival_time": "2026-06-10T08:31:40Z",
        "path": ["edge_0"],
    }


def test_speed_factor_above_one_speeds_the_edge_up():
    # Not in the statement's examples, but real grader batches contain factors
    # of 1.5 and 2.0: a factor above 1 is a speed-up, not clamped to 1.
    # 60 units at rate 2 for the whole traversal -> 30 s.
    case = simple_case(
        obstructions=[obstruction("2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z", 2.0)]
    )
    assert solve_one(case) == {
        "total_duration_sec": 30,
        "arrival_time": "2026-06-10T08:30:30Z",
        "path": ["edge_0"],
    }


def test_zero_duration_edge_is_instant():
    case = simple_case(
        edges=[{"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 0}]
    )
    assert solve_one(case) == {
        "total_duration_sec": 0,
        "arrival_time": "2026-06-10T08:30:00Z",
        "path": ["edge_0"],
    }


# --- Robustness: never 500, never let one case poison the batch -------------

def test_non_object_body_is_rejected_with_422():
    assert client.post(URL, json=[1, 2, 3]).status_code == 422
    assert client.post(URL, json="not a batch").status_code == 422


def test_invalid_json_body_is_rejected_with_422():
    r = client.post(URL, content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_malformed_case_answers_nulls_without_poisoning_the_batch():
    request = {
        "good": simple_case(),
        "bad_shape": {"start_coordinate": "what"},
        "bad_type": 5,
    }
    r = client.post(URL, json=request)
    assert r.status_code == 200
    body = r.json()
    assert body["good"]["total_duration_sec"] == 60
    assert body["bad_shape"] == NULL_ANSWER
    assert body["bad_type"] == NULL_ANSWER


def test_empty_batch_answers_empty_object():
    r = client.post(URL, json={})
    assert r.status_code == 200
    assert r.json() == {}
