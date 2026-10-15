"""G3: NR branch populated for Paris Q1, empty NR state for Rennes LTE."""

from tests.conftest import PARIS, RENNES


def _nr_counts(tree: dict) -> int:
    total = 0
    for b in tree["branches"]:
        if b["techno"] == "NR":
            for c in b["channels"]:
                for m in c["messages"]:
                    total += m["count"]
    return total


def test_paris_nr_populated(client):
    r = client.get(f"/projects/{PARIS}/dict/tree")
    assert r.status_code == 200
    assert _nr_counts(r.json()) > 0, "Paris 2026 Q1 doit exposer des observations NR"


def test_rennes_nr_empty(client):
    r = client.get(f"/projects/{RENNES}/dict/tree")
    assert r.status_code == 200
    tree = r.json()
    technos = {b["techno"] for b in tree["branches"]}
    assert technos == {"LTE", "NR"}, "Les deux branches techno doivent exister (invariant Zod)"
    assert _nr_counts(tree) == 0, "Rennes LTE (sans NR) doit avoir count=0 sur NR"
