from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_square():
    r = client.post("/square", json={"number": 7})
    assert r.status_code == 200
    assert r.json() == {"result": 49.0}


def test_square_rejects_garbage():
    r = client.post("/square", json={"number": "not-a-number"})
    assert r.status_code == 422


def test_request_log_captures_traffic():
    client.post("/square", json={"number": 2})
    r = client.get("/debug/requests")
    assert r.status_code == 200
    assert any(e["path"] == "/square" for e in r.json())
