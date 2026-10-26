"""G1: migrations applied + API up + /health OK."""
import re


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    # 0.82.2 — version compared par regex SemVer, pas par litéral figé
    # (évite de breaker ce test à chaque bump).
    assert re.fullmatch(r'\d+\.\d+\.\d+', body["version"]), body["version"]
    assert "decoder_version" in body
