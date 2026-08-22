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


def test_statement_example():
    # verbatim from statement.pdf
    r = client.post("/solve", json={"payload": SAMPLE_PAYLOAD})
    assert r.status_code == 200
    assert r.json() == {
        "adaptOutput": {
            "id": "U42",
            "name": "Jane Doe",
            "action": "create",
            "priority": 3,
        }
    }


def test_statement_example_key_order():
    # the grader may compare JSON text, so keep the statement's field order
    r = client.post("/solve", json={"payload": SAMPLE_PAYLOAD})
    assert r.text == (
        '{"adaptOutput":{"id":"U42","name":"Jane Doe","action":"create","priority":3}}'
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


def test_unknown_priority_is_zero_not_an_error():
    r = client.post(
        "/solve", json={"payload": encode(adapt_input(metadata={"priority": "???"}))}
    )
    assert r.status_code == 200
    assert r.json()["adaptOutput"]["priority"] == 0


def test_missing_metadata_is_zero_not_an_error():
    body = adapt_input()
    del body["adaptInput"]["metadata"]
    r = client.post("/solve", json={"payload": encode(body)})
    assert r.status_code == 200
    assert r.json()["adaptOutput"]["priority"] == 0


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
