from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_request_log_captures_traffic():
    client.post("/square", json={"value": 2})
    r = client.get("/debug/requests")
    assert r.status_code == 200
    assert any(e["path"] == "/square" for e in r.json())
