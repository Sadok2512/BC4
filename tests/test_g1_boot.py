"""G1: migrations applied + API up + /health OK."""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.14.0"
