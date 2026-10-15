"""G4: conformance of 3GPP conversion to conversion_rule.

Non-régression on a numeric param: verify the fiche carries the exact
scale/offset/unit/decimals/ref expected by 3GPP TS 36.133 §9.1.4 for
`lte-mr-rsrp`, and that the dominant conversion string respects the
decimals/unit of the rule.
"""

from tests.conftest import PARIS


def test_lte_rsrp_rule(client):
    r = client.get(
        f"/projects/{PARIS}/dict/param",
        params={"param_id": "lte-mr-rsrp", "group_by": "operator"},
    )
    assert r.status_code == 200
    body = r.json()
    rule = body["fiche"]["conversion_rule"]
    assert rule is not None
    assert rule["scale"] == 1
    assert rule["offset"] == -140
    assert rule["unit"] == "dBm"
    assert rule["decimals"] == 0
    assert "36.133" in rule["ref"]

    dom = body["fiche"]["dominant"]
    assert dom["value"] is not None
    # Conversion: v * 1 + (-140), formatted "<int> dBm" (comma for decimals already)
    expected = int(dom["value"]) + (-140)
    assert f"{expected} dBm" in dom["conversion"].replace(",", "")


def test_nr_rsrp_rule(client):
    r = client.get(
        f"/projects/{PARIS}/dict/param",
        params={"param_id": "nr-mr-rsrp", "group_by": "operator"},
    )
    assert r.status_code == 200
    rule = r.json()["fiche"]["conversion_rule"]
    assert rule["offset"] == -157
    assert rule["unit"] == "dBm"
    assert "38.133" in rule["ref"]
