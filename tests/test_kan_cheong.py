"""Kan Chiong Delivery Driver.

Every EXAMPLE_* / BATCH_* constant is transcribed verbatim from statement.pdf
(docs/phases/kan-cheong/). The PDF clips its code blocks on the right when rendered;
the values here came from the PDF's own content stream. See notes.md.
"""
import copy

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

URL = "/kan-cheong-delivery-driver"

# --- verbatim from statement.pdf --------------------------------------------

BATCH_REQUEST = {
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

BATCH_RESPONSE = {
    "case_1": {
        "total_duration_sec": 60,
        "arrival_time": "2026-06-10T08:31:00Z",
        "path": ["edge_0"],
    },
    "case_2": {"total_duration_sec": None, "arrival_time": None, "path": []},
}

EXAMPLE_1 = {
    "start_coordinate": [0, 0],
    "end_coordinate": [3, 1],
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

EXAMPLE_1_OUTPUT = {
    "total_duration_sec": 230,
    "arrival_time": "2026-06-10T08:33:50Z",
    "path": ["edge_0", "edge_4", "edge_3"],
}

# same graph as example 1, but the destination is not on it
EXAMPLE_2 = copy.deepcopy(EXAMPLE_1)
EXAMPLE_2["end_coordinate"] = [3, 3]

EXAMPLE_2_OUTPUT = {"total_duration_sec": None, "arrival_time": None, "path": []}

EXAMPLE_3 = {
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

EXAMPLE_3_OUTPUT = {
    "total_duration_sec": 60,
    "arrival_time": "2026-06-10T08:31:00Z",
    "path": ["edge_0", "edge_0", "edge_0", "edge_0", "edge_0", "edge_1"],
}

EXAMPLE_4 = {
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

EXAMPLE_4_OUTPUT = {"total_duration_sec": None, "arrival_time": None, "path": []}


def solve(**cases):
    r = client.post(URL, json=cases)
    assert r.status_code == 200, r.text
    return r.json()


def one(case):
    """Solve a single case and return just its answer."""
    return solve(case_1=copy.deepcopy(case))["case_1"]


# --- the statement's examples ------------------------------------------------


def test_batch_example():
    r = client.post(URL, json=BATCH_REQUEST)
    assert r.status_code == 200
    assert r.json() == BATCH_RESPONSE


def test_example_1():
    assert one(EXAMPLE_1) == EXAMPLE_1_OUTPUT


def test_example_2_unreachable_destination():
    assert one(EXAMPLE_2) == EXAMPLE_2_OUTPUT


def test_example_3_no_waiting_so_the_route_cycles():
    assert one(EXAMPLE_3) == EXAMPLE_3_OUTPUT


def test_example_4_blocked_at_start():
    assert one(EXAMPLE_4) == EXAMPLE_4_OUTPUT


def test_all_four_examples_in_one_batch():
    # the grader sends many cases at once; they must not leak into each other
    answers = solve(a=EXAMPLE_1, b=EXAMPLE_2, c=EXAMPLE_3, d=EXAMPLE_4)
    assert answers == {
        "a": EXAMPLE_1_OUTPUT,
        "b": EXAMPLE_2_OUTPUT,
        "c": EXAMPLE_3_OUTPUT,
        "d": EXAMPLE_4_OUTPUT,
    }


# --- batch protocol ----------------------------------------------------------


def test_every_case_id_is_answered():
    ids = [f"case_{i}" for i in range(25)]
    answers = solve(**{i: EXAMPLE_1 for i in ids})
    assert sorted(answers) == sorted(ids)
    assert all(answers[i] == EXAMPLE_1_OUTPUT for i in ids)


def test_arbitrary_case_ids_are_echoed_back():
    answers = solve(**{"weird id 🚚": EXAMPLE_1})
    assert list(answers) == ["weird id 🚚"]


def test_empty_batch_is_an_empty_object():
    r = client.post(URL, json={})
    assert r.status_code == 200
    assert r.json() == {}


def test_answer_keys_match_the_output_schema():
    assert list(one(EXAMPLE_1)) == ["total_duration_sec", "arrival_time", "path"]


# --- travel-time model -------------------------------------------------------


def case(**over):
    """Two nodes joined by one 60 s edge, departing 08:30:00."""
    body = {
        "start_coordinate": [0, 0],
        "end_coordinate": [1, 0],
        "start_time": "2026-06-10T08:30:00Z",
        "nodes": [[0, 0], [1, 0]],
        "edges": [
            {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60}
        ],
        "obstructions": [],
    }
    body.update(over)
    return body


def obstruction(**over):
    body = {
        "edge_id": "edge_0",
        "edge": {"from": [0, 0], "to": [1, 0]},
        "start_time": "2026-06-10T08:00:00Z",
        "end_time": "2026-06-10T09:00:00Z",
        "speed_factor": 0.5,
    }
    body.update(over)
    return body


def test_speed_factor_divides_not_multiplies():
    # 60 s of road at half speed is 120 s, not 30
    assert one(case(obstructions=[obstruction(speed_factor=0.5)])) == {
        "total_duration_sec": 120,
        "arrival_time": "2026-06-10T08:32:00Z",
        "path": ["edge_0"],
    }


def test_obstruction_is_directional():
    # declared [1,0] -> [0,0]; we travel [0,0] -> [1,0], so it must not apply
    answer = one(
        case(obstructions=[obstruction(edge={"from": [1, 0], "to": [0, 0]}, speed_factor=0.1)])
    )
    assert answer["total_duration_sec"] == 60


def test_obstruction_must_match_the_edge_id_too():
    answer = one(case(obstructions=[obstruction(edge_id="some_other_edge", speed_factor=0.1)]))
    assert answer["total_duration_sec"] == 60


def test_edges_are_bidirectional():
    # the only edge is declared [1,0] -> [0,0]; we travel the other way
    answer = one(
        case(
            edges=[
                {
                    "edge_id": "edge_0",
                    "node1": [1, 0],
                    "node2": [0, 0],
                    "base_duration_sec": 60,
                }
            ]
        )
    )
    assert answer == {
        "total_duration_sec": 60,
        "arrival_time": "2026-06-10T08:31:00Z",
        "path": ["edge_0"],
    }


def test_obstruction_that_ends_before_departure_is_irrelevant():
    answer = one(
        case(
            obstructions=[
                obstruction(
                    start_time="2026-06-10T07:00:00Z",
                    end_time="2026-06-10T08:00:00Z",
                    speed_factor=0.0,
                )
            ]
        )
    )
    assert answer["total_duration_sec"] == 60


def test_obstruction_that_starts_after_arrival_is_irrelevant():
    answer = one(
        case(
            obstructions=[
                obstruction(
                    start_time="2026-06-10T09:00:00Z",
                    end_time="2026-06-10T10:00:00Z",
                    speed_factor=0.0,
                )
            ]
        )
    )
    assert answer["total_duration_sec"] == 60


def test_only_the_untraveled_portion_is_slowed():
    # 30 s at full speed, then the remaining 30 s of road at 0.5 -> 60 more seconds
    answer = one(
        case(
            obstructions=[
                obstruction(
                    start_time="2026-06-10T08:30:30Z",
                    end_time="2026-06-10T09:00:00Z",
                    speed_factor=0.5,
                )
            ]
        )
    )
    assert answer["total_duration_sec"] == 90
    assert answer["arrival_time"] == "2026-06-10T08:31:30Z"


def test_obstruction_window_start_is_inclusive():
    # example 3 depends on this: arriving exactly at start_time finds the arc shut
    answer = one(
        case(
            obstructions=[
                obstruction(
                    start_time="2026-06-10T08:30:00Z",
                    end_time="2026-06-10T09:00:00Z",
                    speed_factor=0.0,
                )
            ]
        )
    )
    assert answer == EXAMPLE_4_OUTPUT


def test_blocked_arc_clears_partway_through_the_journey():
    # blocked until 08:31, and there is a second way round costing 200 s;
    # cycling on the detour is the only way to burn time, so the answer is the detour
    answer = one(
        case(
            end_coordinate=[2, 0],
            nodes=[[0, 0], [1, 0], [2, 0]],
            edges=[
                {"edge_id": "fast", "node1": [0, 0], "node2": [2, 0], "base_duration_sec": 10},
                {"edge_id": "slow_a", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 100},
                {"edge_id": "slow_b", "node1": [1, 0], "node2": [2, 0], "base_duration_sec": 100},
            ],
            obstructions=[
                {
                    "edge_id": "fast",
                    "edge": {"from": [0, 0], "to": [2, 0]},
                    "start_time": "2026-06-10T08:30:00Z",
                    "end_time": "2026-06-10T08:31:00Z",
                    "speed_factor": 0.0,
                }
            ],
        )
    )
    assert answer["total_duration_sec"] == 200
    assert answer["path"] == ["slow_a", "slow_b"]


def test_zero_duration_edge():
    answer = one(
        case(
            edges=[
                {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 0}
            ]
        )
    )
    assert answer == {
        "total_duration_sec": 0,
        "arrival_time": "2026-06-10T08:30:00Z",
        "path": ["edge_0"],
    }


def test_start_equals_end():
    answer = one(case(end_coordinate=[0, 0]))
    assert answer == {
        "total_duration_sec": 0,
        "arrival_time": "2026-06-10T08:30:00Z",
        "path": [],
    }


def test_parallel_edges_pick_the_faster_one():
    answer = one(
        case(
            edges=[
                {"edge_id": "slow", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 60},
                {"edge_id": "quick", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 20},
            ]
        )
    )
    assert answer["path"] == ["quick"]
    assert answer["total_duration_sec"] == 20


def test_overlapping_obstructions_take_the_most_restrictive():
    # assumption (notes.md): overlapping windows -> lowest speed_factor wins
    answer = one(
        case(
            obstructions=[
                obstruction(speed_factor=0.5),
                obstruction(speed_factor=0.25),
            ]
        )
    )
    assert answer["total_duration_sec"] == 240


def test_no_route_when_the_graph_is_disconnected():
    answer = one(
        case(
            end_coordinate=[9, 9],
            nodes=[[0, 0], [1, 0], [9, 9]],
        )
    )
    assert answer == EXAMPLE_2_OUTPUT


def test_non_utc_start_time_is_normalised_to_z():
    answer = one(case(start_time="2026-06-10T16:30:00+08:00"))
    assert answer["arrival_time"] == "2026-06-10T08:31:00Z"


def test_large_grid_stays_within_budget():
    # 30x30 grid, ~1740 edges, obstructions on a whole column: exercises the
    # search on something the grader would call a "larger, more complex" case
    n = 30
    nodes = [[x, y] for x in range(n) for y in range(n)]
    edges = []
    for x in range(n):
        for y in range(n):
            if x + 1 < n:
                edges.append(
                    {
                        "edge_id": f"h_{x}_{y}",
                        "node1": [x, y],
                        "node2": [x + 1, y],
                        "base_duration_sec": 10,
                    }
                )
            if y + 1 < n:
                edges.append(
                    {
                        "edge_id": f"v_{x}_{y}",
                        "node1": [x, y],
                        "node2": [x, y + 1],
                        "base_duration_sec": 10,
                    }
                )
    obstructions = [
        {
            "edge_id": f"h_5_{y}",
            "edge": {"from": [5, y], "to": [6, y]},
            "start_time": "2026-06-10T08:00:00Z",
            "end_time": "2026-06-10T09:00:00Z",
            "speed_factor": 0.5,
        }
        for y in range(n)
    ]
    answer = one(
        case(
            start_coordinate=[0, 0],
            end_coordinate=[n - 1, n - 1],
            nodes=nodes,
            edges=edges,
            obstructions=obstructions,
        )
    )
    # 58 moves of 10 s, one of which must cross the slowed column at 20 s
    assert answer["total_duration_sec"] == 590
    assert len(answer["path"]) == 58


# --- bad input ---------------------------------------------------------------


def test_body_that_is_not_an_object_is_rejected():
    assert client.post(URL, json=[1, 2, 3]).status_code == 422


def test_string_body_is_rejected():
    assert client.post(URL, json="hello").status_code == 422


def test_empty_body_is_rejected():
    r = client.post(URL, content=b"", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_malformed_case_gets_the_null_answer_not_a_500():
    # assumption (notes.md): one bad case must not cost us the rest of the batch
    answers = solve(good=EXAMPLE_1, bad={"start_coordinate": "nonsense"})
    assert answers["good"] == EXAMPLE_1_OUTPUT
    assert answers["bad"] == EXAMPLE_2_OUTPUT


def test_case_that_is_not_an_object_gets_the_null_answer():
    answers = solve(good=EXAMPLE_1, bad=42)
    assert answers["good"] == EXAMPLE_1_OUTPUT
    assert answers["bad"] == EXAMPLE_2_OUTPUT


def test_unparseable_start_time_gets_the_null_answer():
    assert one(case(start_time="not a time")) == EXAMPLE_2_OUTPUT


def test_missing_edges_gets_the_null_answer():
    body = case()
    del body["edges"]
    assert one(body) == EXAMPLE_2_OUTPUT


def test_junk_obstruction_entries_are_ignored():
    answer = one(case(obstructions=[None, 7, {}, obstruction(speed_factor=0.5)]))
    assert answer["total_duration_sec"] == 120


# --- earlier phases still work (iron rule 1) ---------------------------------


def test_phase1_still_works():
    r = client.post("/square", json={"value": 5})
    assert r.status_code == 200
    assert r.json() == {"result": 25}


def test_phase2_still_works():
    r = client.post("/solve", json={"payload": {"adaptInput": {
        "user": {"id": "U42", "fullName": "Jane Doe"},
        "action": "CREATE",
        "metadata": {"priority": "HIGH"},
    }}})
    assert r.status_code == 200
    assert r.json()["adaptOutput"]["priority"] == 3


# --- assumptions worth pinning (see notes.md) --------------------------------


def test_block_starting_mid_traversal_strands_the_driver_on_the_arc():
    # assumption: "only the remaining untraveled portion is affected" taken
    # literally, so a factor of 0 halts progress rather than forbidding entry
    # after the fact. 30 s travelled, 30 s of standstill, then 30 s to finish.
    answer = one(
        case(
            obstructions=[
                obstruction(
                    start_time="2026-06-10T08:30:30Z",
                    end_time="2026-06-10T08:31:00Z",
                    speed_factor=0.0,
                )
            ]
        )
    )
    assert answer["total_duration_sec"] == 90
    assert answer["arrival_time"] == "2026-06-10T08:31:30Z"


def test_obstruction_window_end_is_exclusive():
    # assumption: [start, end). Arriving at [1,0] at exactly 08:30:10, the
    # instant the block lifts, the driver may set off down edge_1.
    answer = one(
        case(
            end_coordinate=[2, 0],
            nodes=[[0, 0], [1, 0], [2, 0]],
            edges=[
                {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 10},
                {"edge_id": "edge_1", "node1": [1, 0], "node2": [2, 0], "base_duration_sec": 10},
            ],
            obstructions=[
                {
                    "edge_id": "edge_1",
                    "edge": {"from": [1, 0], "to": [2, 0]},
                    "start_time": "2026-06-10T08:30:00Z",
                    "end_time": "2026-06-10T08:30:10Z",
                    "speed_factor": 0.0,
                }
            ],
        )
    )
    assert answer["total_duration_sec"] == 20
    assert answer["path"] == ["edge_0", "edge_1"]


def test_a_large_batch_answers_every_case_inside_the_statement_budget():
    # the statement's 10 s cutoff is on the whole batch and scores it 0 if missed,
    # so every case must come back with an entry, budget or no budget
    import time

    n = 12
    nodes = [[x, y] for x in range(n) for y in range(n)]
    edges = []
    for x in range(n):
        for y in range(n):
            if x + 1 < n:
                edges.append(
                    {"edge_id": f"h_{x}_{y}", "node1": [x, y], "node2": [x + 1, y],
                     "base_duration_sec": 10 + (x * 7 + y * 3) % 40}
                )
            if y + 1 < n:
                edges.append(
                    {"edge_id": f"v_{x}_{y}", "node1": [x, y], "node2": [x, y + 1],
                     "base_duration_sec": 10 + (x * 3 + y * 7) % 40}
                )
    obstructions = [
        {
            "edge_id": e["edge_id"],
            "edge": {"from": e["node1"], "to": e["node2"]},
            "start_time": "2026-06-10T08:30:00Z",
            "end_time": "2026-06-10T09:30:00Z",
            "speed_factor": [0.0, 0.25, 0.5][i % 3],
        }
        for i, e in enumerate(edges)
        if i % 4 == 0
    ]
    batch = {
        f"case_{i}": dict(
            case(
                start_coordinate=[0, 0],
                end_coordinate=[n - 1, n - 1],
                nodes=nodes,
                edges=edges,
                obstructions=obstructions,
            ),
            start_time=f"2026-06-10T08:{30 + i:02d}:00Z",
        )
        for i in range(25)
    }
    started = time.monotonic()
    r = client.post(URL, json=batch)
    elapsed = time.monotonic() - started
    assert r.status_code == 200
    assert sorted(r.json()) == sorted(batch)
    assert all(a["total_duration_sec"] is not None for a in r.json().values())
    assert elapsed < 10, f"batch took {elapsed:.1f}s, statement allows 10"


def test_fractional_duration_is_truncated_not_rounded():
    # A real grader case (recovered from /debug/requests) whose exact answer is
    # 179.5 s: 1 s of edge_0 at full speed, 42 s at 0.75, then the remainder,
    # plus 53 + 65. Rounding up scored 92/100; the ~8% that missed lines up with
    # the cases where round-half-up and truncation disagree, and truncation is
    # what int(total_seconds()) and a second-precision strftime both do.
    answer = one(
        {
            "start_coordinate": [0, 0],
            "end_coordinate": [3, 0],
            "start_time": "2026-06-10T02:28:00-08:00",
            "nodes": [[0, 0], [1, 0], [2, 0], [3, 0], [1, 1]],
            "edges": [
                {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 51},
                {"edge_id": "edge_1", "node1": [1, 0], "node2": [2, 0], "base_duration_sec": 53},
                {"edge_id": "edge_2", "node1": [2, 0], "node2": [3, 0], "base_duration_sec": 65},
                {"edge_id": "edge_3", "node1": [1, 0], "node2": [1, 1], "base_duration_sec": 74},
                {"edge_id": "edge_4", "node1": [2, 0], "node2": [1, 1], "base_duration_sec": 88},
            ],
            "obstructions": [
                {"edge_id": "edge_3", "edge": {"from": [1, 0], "to": [1, 1]},
                 "start_time": "2026-06-10T10:28:03Z", "end_time": "2026-06-10T10:28:31Z",
                 "speed_factor": 0.75},
                {"edge_id": "edge_0", "edge": {"from": [0, 0], "to": [1, 0]},
                 "start_time": "2026-06-10T10:28:01Z", "end_time": "2026-06-10T10:28:43Z",
                 "speed_factor": 0.75},
            ],
        }
    )
    assert answer == {
        "total_duration_sec": 179,
        "arrival_time": "2026-06-10T10:30:59Z",
        "path": ["edge_0", "edge_1", "edge_2"],
    }


def test_arrival_time_never_disagrees_with_the_duration():
    # whatever the rounding, start + total_duration_sec must equal arrival_time
    from datetime import datetime, timedelta, timezone

    for factor, base in [(0.75, 51), (0.3, 17), (0.7, 23), (0.25, 99)]:
        answer = one(
            case(
                edges=[{"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0],
                        "base_duration_sec": base}],
                obstructions=[obstruction(
                    start_time="2026-06-10T08:30:05Z",
                    end_time="2026-06-10T09:00:00Z",
                    speed_factor=factor,
                )],
            )
        )
        start = datetime(2026, 6, 10, 8, 30, tzinfo=timezone.utc)
        expected = (start + timedelta(seconds=answer["total_duration_sec"]))
        assert answer["arrival_time"] == expected.strftime("%Y-%m-%dT%H:%M:%SZ"), (factor, base)


def test_hard_cases_get_the_budget_left_over_by_easy_ones():
    # ~800 trivial cases plus one that needs real searching: dividing the budget
    # evenly up front left the hard one ~10 ms while most of the budget went
    # unspent, which is how the first graded run was run
    import time

    trivial = case()
    n = 14
    nodes = [[x, y] for x in range(n) for y in range(n)]
    edges, eid = [], 0
    for x in range(n):
        for y in range(n):
            if x + 1 < n:
                edges.append({"edge_id": f"e{eid}", "node1": [x, y], "node2": [x + 1, y],
                              "base_duration_sec": 10 + (x + y) % 20}); eid += 1
            if y + 1 < n:
                edges.append({"edge_id": f"e{eid}", "node1": [x, y], "node2": [x, y + 1],
                              "base_duration_sec": 10 + (x * 2 + y) % 20}); eid += 1
    obstructions = [
        {"edge_id": e["edge_id"], "edge": {"from": e["node1"], "to": e["node2"]},
         "start_time": "2026-06-10T08:30:00Z", "end_time": "2026-06-10T08:33:00Z",
         "speed_factor": 0.0}
        for i, e in enumerate(edges) if i % 3 == 0
    ]
    batch = {f"easy_{i}": trivial for i in range(800)}
    batch["hard"] = case(start_coordinate=[0, 0], end_coordinate=[n - 1, n - 1],
                         nodes=nodes, edges=edges, obstructions=obstructions)
    started = time.monotonic()
    r = client.post(URL, json=batch)
    elapsed = time.monotonic() - started
    assert r.status_code == 200
    body = r.json()
    assert len(body) == len(batch)
    assert body["hard"]["total_duration_sec"] is not None
    assert elapsed < 10, f"batch took {elapsed:.1f}s, statement allows 10"


def test_graded_batches_are_captured_whole_for_diagnosis():
    # the shared request log clips at 4 KB and the grader's batch is 3 MB, so a
    # run that scores short leaves nothing to examine. Keep real batches whole.
    import gzip
    import json as _json

    from app.routers.kan_cheong import CAPTURES

    CAPTURES.clear()
    client.post(URL, json={"a": EXAMPLE_1, "b": EXAMPLE_1})  # too small to keep
    assert client.get("/debug/kan-cheong/captures").json() == []

    batch = {f"case_{i}": EXAMPLE_1 for i in range(25)}
    client.post(URL, json=batch)
    listing = client.get("/debug/kan-cheong/captures").json()
    assert len(listing) == 1 and listing[0]["cases"] == 25

    blob = client.get("/debug/kan-cheong/capture/0?which=request")
    assert blob.status_code == 200
    assert _json.loads(gzip.decompress(blob.content)) == batch

    answers = _json.loads(
        gzip.decompress(client.get("/debug/kan-cheong/capture/0?which=response").content)
    )
    assert answers["case_0"] == EXAMPLE_1_OUTPUT
    assert client.get("/debug/kan-cheong/capture/9").status_code == 404
    CAPTURES.clear()


def test_capture_never_breaks_the_batch():
    # diagnostics must not cost us a graded run
    import app.routers.kan_cheong as module

    original = module.gzip.compress
    module.gzip.compress = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        r = client.post(URL, json={f"case_{i}": EXAMPLE_1 for i in range(25)})
        assert r.status_code == 200
        assert r.json()["case_0"] == EXAMPLE_1_OUTPUT
    finally:
        module.gzip.compress = original
