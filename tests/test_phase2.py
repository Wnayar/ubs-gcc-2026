import base64
import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# verbatim from statement.pdf (full string taken from the page's markdown source —
# the PDF clips it visually)
SAMPLE_PAYLOAD = (
    "ewoJImFkYXB0SW5wdXQiOiB7CgkJInVzZXIiOiB7CgkJCSJpZCI6ICJVNDIiLAoJCQkiZnVsbE5hbW"
    "UiOiAiSmFuZSBEb2UiCgkJfSwKCQkiYWN0aW9uIjogIkNSRUFURSIsCgkJIm1ldGFkYXRhIjogewoJ"
    "CQkicHJpb3JpdHkiOiAiSElHSCIKCQl9Cgl9Cn0="
)


def encode(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def adapt_input(**over):
    payload = {
        "user": {"id": "U42", "fullName": "Jane Doe"},
        "action": "CREATE",
        "metadata": {"priority": "HIGH"},
    }
    payload.update(over)
    return {"adaptInput": payload}


# The /adapt-slo guide's payload: the same adaptInput plus heartbeats and a
# sloQuery. Verbatim from docs/phases/adaptive-api-gateway/statement-full.md.
SLO_PAYLOAD = (
    "ewoJImFkYXB0SW5wdXQiOiB7CgkJInVzZXIiOiB7CgkJCSJpZCI6ICJVNDIiLAoJCQkiZnVsbE5hbW"
    "UiOiAiSmFuZSBEb2UiCgkJfSwKCQkiYWN0aW9uIjogIkNSRUFURSIsCgkJIm1ldGFkYXRhIjogewoJ"
    "CQkicHJpb3JpdHkiOiAiSElHSCIKCQl9Cgl9LAoJImhlYXJ0YmVhdHMiOiBbCgkJewoJCQkic2Vydm"
    "ljZSI6ICJhdXRoIiwKCQkJInRpbWVzdGFtcCI6IDE3MTAwMDAxMjMsCgkJCSJsYXRlbmN5TXMiOiAx"
    "MjAsCgkJCSJzdGF0dXMiOiAiT0siCgkJfSwKCQl7CgkJCSJzZXJ2aWNlIjogImF1dGgiLAoJCQkidG"
    "ltZXN0YW1wIjogMTcxMDAwMDEyNSwKCQkJImxhdGVuY3lNcyI6IDE4MCwKCQkJInN0YXR1cyI6ICJG"
    "QUlMIgoJCX0sCgkJewoJCQkic2VydmljZSI6ICJhdXRoIiwKCQkJInRpbWVzdGFtcCI6IDE3MTAwMD"
    "AxMjEsCgkJCSJsYXRlbmN5TXMiOiA5NSwKCQkJInN0YXR1cyI6ICJPSyIKCQl9CgldLAoJInNsb1F1"
    "ZXJ5IjogewoJCSJzZXJ2aWNlIjogImF1dGgiLAoJCSJzaW5jZSI6IDE3MTAwMDAxMjMKCX0KfQ=="
)


def heartbeat(service="auth", timestamp=1710000123, latency=120, status="OK"):
    return {
        "service": service,
        "timestamp": timestamp,
        "latencyMs": latency,
        "status": status,
    }


def slo(payload_heartbeats, query):
    body = adapt_input()
    body["heartbeats"] = payload_heartbeats
    body["sloQuery"] = query
    r = client.post("/solve", json={"payload": encode(body)})
    assert r.status_code == 200, r.text
    return r.json()["sloOutput"]


def test_slo_statement_example():
    # verbatim from the /adapt-slo guide
    r = client.post("/solve", json={"payload": SLO_PAYLOAD})
    assert r.status_code == 200
    assert r.json() == {
        "adaptOutput": {
            "id": "U42",
            "name": "Jane Doe",
            "action": "create",
            "priority": 3,
        },
        "sloOutput": {"availability": 0.5, "p95LatencyMs": 180},
    }


def test_slo_sample_payload_decodes_as_the_guide_claims():
    # guards the constant above against transcription errors
    decoded = json.loads(base64.b64decode(SLO_PAYLOAD))
    assert decoded["sloQuery"] == {"service": "auth", "since": 1710000123}
    assert [h["timestamp"] for h in decoded["heartbeats"]] == [
        1710000123,
        1710000125,
        1710000121,
    ]


def test_slo_statement_example_key_order():
    # the grader may compare JSON text, so keep the guide's field order
    r = client.post("/solve", json={"payload": SLO_PAYLOAD})
    assert r.text == (
        '{"adaptOutput":{"id":"U42","name":"Jane Doe","action":"create","priority":3},'
        '"sloOutput":{"availability":0.5,"p95LatencyMs":180}}'
    )


def test_statement_example():
    # the earlier /adapt guide's payload: adaptInput only, no heartbeats. The
    # success criteria say the response carries both keys, and the guide defines
    # the no-rows answer, so sloOutput is present and zeroed.
    r = client.post("/solve", json={"payload": SAMPLE_PAYLOAD})
    assert r.status_code == 200
    assert r.json() == {
        "adaptOutput": {
            "id": "U42",
            "name": "Jane Doe",
            "action": "create",
            "priority": 3,
        },
        "sloOutput": {"availability": 0.0, "p95LatencyMs": 0},
    }


def test_statement_example_key_order():
    # the grader may compare JSON text, so keep the statement's field order
    r = client.post("/solve", json={"payload": SAMPLE_PAYLOAD})
    assert r.text == (
        '{"adaptOutput":{"id":"U42","name":"Jane Doe","action":"create","priority":3},'
        '"sloOutput":{"availability":0.0,"p95LatencyMs":0}}'
    )


def test_sample_payload_decodes_as_the_statement_claims():
    # guards the constant above against transcription errors
    assert json.loads(base64.b64decode(SAMPLE_PAYLOAD)) == adapt_input()


def test_priority_ladder():
    for word, expected in [("LOW", 1), ("MEDIUM", 2), ("HIGH", 3)]:
        r = client.post(
            "/solve",
            json={"payload": encode(adapt_input(metadata={"priority": word}))},
        )
        assert r.status_code == 200, word
        assert r.json()["adaptOutput"]["priority"] == expected, word


def test_priority_is_case_insensitive():
    r = client.post(
        "/solve", json={"payload": encode(adapt_input(metadata={"priority": "high"}))}
    )
    assert r.json()["adaptOutput"]["priority"] == 3


def test_numeric_priority_passes_through():
    r = client.post(
        "/solve", json={"payload": encode(adapt_input(metadata={"priority": 7}))}
    )
    assert r.json()["adaptOutput"]["priority"] == 7


def test_unrecognised_priority_defaults_to_two():
    # The /adapt guide said nothing and we guessed 0. The full /adapt-slo guide
    # is explicit: "If priority is missing or unrecognized, default to 2."
    for word in ("???", "CRITICAL", "URGENT", "NONE", ""):
        r = client.post(
            "/solve", json={"payload": encode(adapt_input(metadata={"priority": word}))}
        )
        assert r.status_code == 200, word
        assert r.json()["adaptOutput"]["priority"] == 2, word


def test_missing_priority_defaults_to_two():
    body = adapt_input()
    del body["adaptInput"]["metadata"]
    r = client.post("/solve", json={"payload": encode(body)})
    assert r.status_code == 200
    assert r.json()["adaptOutput"]["priority"] == 2


def test_action_is_lowercased():
    r = client.post("/solve", json={"payload": encode(adapt_input(action="DELETE"))})
    assert r.json()["adaptOutput"]["action"] == "delete"


def test_urlsafe_base64_accepted():
    # the '?' in this id lands on a '/' in the standard alphabet and a '_' in the
    # url-safe one, so this genuinely exercises the url-safe path
    body = adapt_input(user={"id": "U42?", "fullName": "Jane Doe"})
    raw = json.dumps(body).encode()
    assert "/" in base64.b64encode(raw).decode()
    assert "_" in base64.urlsafe_b64encode(raw).decode()
    r = client.post("/solve", json={"payload": base64.urlsafe_b64encode(raw).decode()})
    assert r.status_code == 200
    assert r.json()["adaptOutput"]["id"] == "U42?"


def test_unpadded_base64_accepted():
    r = client.post(
        "/solve", json={"payload": encode(adapt_input()).rstrip("=")}
    )
    assert r.status_code == 200
    assert r.json()["adaptOutput"]["name"] == "Jane Doe"


def test_whitespace_around_payload_tolerated():
    r = client.post("/solve", json={"payload": "\n  " + SAMPLE_PAYLOAD + "  \n"})
    assert r.status_code == 200
    assert r.json()["adaptOutput"]["id"] == "U42"


def test_plain_json_payload_accepted():
    r = client.post("/solve", json={"payload": json.dumps(adapt_input())})
    assert r.status_code == 200
    assert r.json()["adaptOutput"]["priority"] == 3


def test_object_payload_accepted():
    r = client.post("/solve", json={"payload": adapt_input()})
    assert r.status_code == 200
    assert r.json()["adaptOutput"]["name"] == "Jane Doe"


def test_v1_first_and_last_name_bridged():
    body = adapt_input(user={"userId": "U9", "firstName": "Jane", "lastName": "Doe"})
    r = client.post("/solve", json={"payload": encode(body)})
    assert r.status_code == 200
    assert r.json()["adaptOutput"] == {
        "id": "U9",
        "name": "Jane Doe",
        "action": "create",
        "priority": 3,
    }


def test_top_level_priority_bridged():
    body = adapt_input()
    del body["adaptInput"]["metadata"]
    body["adaptInput"]["priority"] = "LOW"
    r = client.post("/solve", json={"payload": encode(body)})
    assert r.json()["adaptOutput"]["priority"] == 1


def test_missing_payload_rejected():
    r = client.post("/solve", json={})
    assert r.status_code == 422


def test_non_string_payload_rejected():
    r = client.post("/solve", json={"payload": 12345})
    assert r.status_code == 422


def test_undecodable_payload_rejected():
    r = client.post("/solve", json={"payload": "!!!not base64!!!"})
    assert r.status_code == 422


def test_base64_of_non_json_rejected():
    r = client.post(
        "/solve", json={"payload": base64.b64encode(b"hello there").decode()}
    )
    assert r.status_code == 422


def test_missing_adapt_input_rejected():
    r = client.post("/solve", json={"payload": encode({"somethingElse": {}})})
    assert r.status_code == 422


def test_missing_action_rejected():
    body = adapt_input()
    del body["adaptInput"]["action"]
    r = client.post("/solve", json={"payload": encode(body)})
    assert r.status_code == 422


def test_non_string_action_rejected():
    r = client.post("/solve", json={"payload": encode(adapt_input(action=7))})
    assert r.status_code == 422


def test_empty_body_rejected():
    r = client.post("/solve", content=b"", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_phase1_still_works():
    # iron rule 1: never break an earlier phase
    r = client.post("/square", json={"value": 5})
    assert r.status_code == 200
    assert r.json() == {"result": 25}


# --- Part 2: SLO rules (the /adapt-slo guide) -------------------------------


def test_since_is_inclusive():
    """The example proves it: dropping the row at exactly `since` would make
    availability 0.0, and the guide prints 0.5."""
    out = slo(
        [
            heartbeat(timestamp=1710000123, latency=120, status="OK"),
            heartbeat(timestamp=1710000125, latency=180, status="FAIL"),
            heartbeat(timestamp=1710000121, latency=95, status="OK"),
        ],
        {"service": "auth", "since": 1710000123},
    )
    assert out == {"availability": 0.5, "p95LatencyMs": 180}


def test_no_since_keeps_every_row_for_that_service():
    out = slo(
        [
            heartbeat(timestamp=1710000121, latency=95, status="OK"),
            heartbeat(timestamp=1710000123, latency=120, status="OK"),
            heartbeat(timestamp=1710000125, latency=180, status="FAIL"),
        ],
        {"service": "auth"},
    )
    assert out["availability"] == 2 / 3
    assert out["p95LatencyMs"] == 180


def test_only_the_queried_service_counts():
    out = slo(
        [
            heartbeat(service="auth", timestamp=1, latency=10, status="OK"),
            heartbeat(service="billing", timestamp=2, latency=9000, status="FAIL"),
        ],
        {"service": "auth"},
    )
    assert out == {"availability": 1.0, "p95LatencyMs": 10}


def test_duplicate_service_timestamp_pairs_are_ignored():
    """"Ignore duplicate heartbeats that share the same (service, timestamp)"."""
    out = slo(
        [
            heartbeat(timestamp=1, latency=100, status="OK"),
            heartbeat(timestamp=1, latency=900, status="FAIL"),  # duplicate key
            heartbeat(timestamp=2, latency=200, status="OK"),
        ],
        {"service": "auth"},
    )
    assert out == {"availability": 1.0, "p95LatencyMs": 200}


def test_out_of_order_input_gives_the_same_answer():
    rows = [
        heartbeat(timestamp=5, latency=500, status="FAIL"),
        heartbeat(timestamp=1, latency=100, status="OK"),
        heartbeat(timestamp=3, latency=300, status="OK"),
    ]
    forwards = slo(rows, {"service": "auth"})
    backwards = slo(list(reversed(rows)), {"service": "auth"})
    assert forwards == backwards
    assert forwards["availability"] == 2 / 3


def test_no_rows_after_filtering_is_zero_zero():
    """The guide's own default, and why sloOutput can always be present."""
    assert slo([heartbeat(service="auth")], {"service": "billing"}) == {
        "availability": 0.0,
        "p95LatencyMs": 0,
    }
    assert slo([], {"service": "auth"}) == {"availability": 0.0, "p95LatencyMs": 0}
    assert slo([heartbeat(timestamp=1)], {"service": "auth", "since": 99}) == {
        "availability": 0.0,
        "p95LatencyMs": 0,
    }


def test_p95_is_nearest_rank_not_interpolated():
    """Twenty rows 10..200: nearest-rank p95 is ceil(0.95 * 20) = 19th = 190.
    Linear interpolation would give 199.5, which is not a latency anyone saw."""
    rows = [heartbeat(timestamp=i, latency=i * 10) for i in range(1, 21)]
    out = slo(rows, {"service": "auth"})
    assert out["p95LatencyMs"] == 190
    assert out["availability"] == 1.0


def test_p95_of_a_single_row_is_that_row():
    assert slo([heartbeat(latency=42)], {"service": "auth"})["p95LatencyMs"] == 42


def test_availability_counts_anything_not_ok_as_down():
    out = slo(
        [
            heartbeat(timestamp=1, status="OK"),
            heartbeat(timestamp=2, status="FAIL"),
            heartbeat(timestamp=3, status="DEGRADED"),
            heartbeat(timestamp=4, status="ok"),  # case-insensitive
        ],
        {"service": "auth"},
    )
    assert out["availability"] == 0.5


def test_slo_output_is_present_even_with_no_heartbeats_at_all():
    r = client.post("/solve", json={"payload": encode(adapt_input())})
    assert r.status_code == 200
    assert r.json()["sloOutput"] == {"availability": 0.0, "p95LatencyMs": 0}


def test_malformed_heartbeats_do_not_500():
    for rows in ("not a list", [1, 2, 3], [{"service": "auth"}], [None]):
        body = adapt_input()
        body["heartbeats"] = rows
        body["sloQuery"] = {"service": "auth"}
        r = client.post("/solve", json={"payload": encode(body)})
        assert r.status_code == 200, rows
        assert "sloOutput" in r.json(), rows


def test_malformed_slo_query_does_not_500():
    for query in ("nope", 7, [], {"service": 5}, {"since": "soon"}):
        body = adapt_input()
        body["heartbeats"] = [heartbeat()]
        body["sloQuery"] = query
        r = client.post("/solve", json={"payload": encode(body)})
        assert r.status_code == 200, query
        assert "sloOutput" in r.json(), query
