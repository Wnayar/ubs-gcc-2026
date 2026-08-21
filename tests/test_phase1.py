from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_statement_example():
    # verbatim from statement.pdf: {"value": 5} -> {"result": 25}, 200 OK
    r = client.post("/square", json={"value": 5})
    assert r.status_code == 200
    assert r.json() == {"result": 25}


def test_int_stays_int():
    r = client.post("/square", json={"value": 12})
    assert r.text == '{"result":144}'


def test_float():
    r = client.post("/square", json={"value": 2.5})
    assert r.status_code == 200
    assert r.json() == {"result": 6.25}


def test_negative():
    r = client.post("/square", json={"value": -4})
    assert r.status_code == 200
    assert r.json() == {"result": 16}


def test_missing_value_rejected():
    r = client.post("/square", json={})
    assert r.status_code == 422


def test_non_numeric_rejected():
    r = client.post("/square", json={"value": "five"})
    assert r.status_code == 422
