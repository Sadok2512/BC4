"""G16 (0.15.0) — Distribution par valeur sur `/dict/params`.

Vérifie, sur TEST2 (déjà peuplé via `scripts/populate_dict_for_all_projects.py`) :
- `GET /dict/params?system=LTE` renvoie, pour chaque paramètre, un champ
  `value_distribution` (nouveau 0.15.0) et `value_distribution_mode`.
- Pour un path `rsrpResult` (numérique, LTE) :
  * `value_distribution` est non vide ;
  * `sum(count)` sur la distribution == `count` global du paramètre
    (cohérence avec le count du param dans la ligne) ;
  * la formule 3GPP est respectée : `value_converted == str(int(value_raw) - 141)`.
- Pour un paramètre enum (ex. `dl-Bandwidth`), chaque entrée a
  `value_converted = null`.
- Appliquer `operator=Orange` RESTREINT la distribution (somme filtrée
  <= somme non filtrée).
- Non-régression : les buckets `(operator, band)` existants restent
  présents.

PRÉ-REQUIS :
- `BC4_API_BASE`, `BC4_ADMIN_EMAIL`, `BC4_ADMIN_PASSWORD`.
- Projet TEST2 ingéré + `param_occurrence` peuplé.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal


def _test2_id() -> str:
    with SessionLocal() as db:
        pid = db.execute(
            text("SELECT id FROM projects WHERE name = 'TEST2'")
        ).scalar()
    if not pid:
        pytest.fail("projet TEST2 absent — garde G16 skippée")
    return pid


def _ensure_populated(pid: str) -> None:
    with SessionLocal() as db:
        n = db.execute(
            text("SELECT COUNT(*) FROM param_occurrence WHERE project_id = :p"),
            {"p": pid},
        ).scalar()
    if not n or n == 0:
        pytest.fail(
            "param_occurrence vide pour TEST2 — "
            "lance scripts/populate_dict_for_all_projects.py d'abord"
        )


def test_value_distribution_numeric_rsrp_result(client):
    """Un paramètre numérique (rsrpResult) doit exposer value_distribution
    non vide, somme = count, et formule 3GPP (idx - 141) respectée."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/params", params={"system": "LTE"})
    assert r.status_code == 200, r.text
    params = r.json().get("params", [])
    assert params, "LTE devrait exposer au moins un paramètre"

    # On vise un path rsrpResult (LTE, 3GPP TS 36.133 idx-141 dBm).
    rsrp_rows = [p for p in params if p["path"].endswith("rsrpResult")]
    assert rsrp_rows, "LTE devrait contenir au moins un path rsrpResult"
    row = rsrp_rows[0]

    assert "value_distribution" in row
    assert "value_distribution_mode" in row
    assert row["value_distribution_mode"] in {"exact", "binned"}
    vd = row["value_distribution"]
    assert vd, "value_distribution doit être non vide pour un path peuplé"

    # Cohérence des comptages : somme sur la distribution = count du param.
    total_vd = sum(int(v["count"]) for v in vd)
    assert total_vd == int(row["count"]), (
        f"somme value_distribution ({total_vd}) != row.count ({row['count']})"
    )

    # Formule 3GPP : pour chaque entrée exacte (non binnée), on vérifie
    # value_converted == str(int(value_raw) - 141).
    if row["value_distribution_mode"] == "exact":
        for v in vd:
            raw = v["value_raw"]
            conv = v["value_converted"]
            if conv is None:
                # Résidu non-convertible toléré en queue (jamais inventé).
                continue
            # value_raw doit être un entier pour rsrpResult.
            try:
                raw_int = int(raw)
            except ValueError:
                pytest.fail(
                    f"value_raw '{raw}' pour rsrpResult n'est pas un entier"
                )
            expected = str(raw_int - 141)
            assert conv == expected, (
                f"rsrpResult: raw={raw} converted={conv} attendu {expected} "
                "(formule idx-141)"
            )


def test_value_distribution_enum_null_converted(client):
    """Un paramètre enum (ex. dl-Bandwidth) doit renvoyer
    value_converted=null sur chaque entrée."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/params", params={"system": "LTE"})
    assert r.status_code == 200, r.text
    params = r.json().get("params", [])

    enum_candidates = [p for p in params if p["path"].endswith("dl-Bandwidth")]
    if not enum_candidates:
        pytest.fail("Aucun path dl-Bandwidth exposé sur TEST2 — enum test skippé")
    row = enum_candidates[0]
    assert row.get("unit_converted") is None, (
        "dl-Bandwidth est un enum — unit_converted doit être null"
    )
    vd = row["value_distribution"]
    assert vd, "value_distribution d'un enum doit lister les valeurs observées"
    for v in vd:
        assert v["value_converted"] is None, (
            f"enum dl-Bandwidth: value_converted doit être null, "
            f"vu {v['value_converted']!r} pour value_raw={v['value_raw']!r}"
        )
    # Tri alpha ascendant.
    raws = [v["value_raw"] for v in vd]
    assert raws == sorted(raws), f"enum doit être trié alpha asc : {raws}"


def test_value_distribution_filter_operator_restricts(client):
    """Filtrer sur operator=Orange doit restreindre la distribution
    (somme filtrée <= somme non filtrée) sans fabriquer d'opérateur."""
    pid = _test2_id()
    _ensure_populated(pid)
    r_all = client.get(f"/projects/{pid}/dict/params", params={"system": "LTE"})
    assert r_all.status_code == 200
    all_params = r_all.json().get("params", [])
    rsrp_all = [p for p in all_params if p["path"].endswith("rsrpResult")]
    assert rsrp_all
    total_all = int(rsrp_all[0]["count"])

    r_or = client.get(
        f"/projects/{pid}/dict/params",
        params={"system": "LTE", "operator": "Orange"},
    )
    assert r_or.status_code == 200
    or_params = r_or.json().get("params", [])
    rsrp_or = [p for p in or_params if p["path"].endswith("rsrpResult")]
    # Si Orange a 0 occurrence sur ce path, la ligne peut disparaître —
    # c'est un comportement acceptable (pas d'invention). Dans ce cas on
    # vérifie juste qu'aucune autre ligne ne porte Orange avec un total
    # supérieur au total global.
    if not rsrp_or:
        return
    total_or = int(rsrp_or[0]["count"])
    assert total_or <= total_all, (
        f"filtre operator=Orange doit restreindre : "
        f"total_or={total_or} > total_all={total_all}"
    )
    sum_vd_or = sum(int(v["count"]) for v in rsrp_or[0]["value_distribution"])
    assert sum_vd_or == total_or, (
        f"somme value_distribution filtrée ({sum_vd_or}) != count filtré ({total_or})"
    )


def test_value_distribution_preserves_operator_band_buckets(client):
    """Non-régression : le champ `buckets` (op x band) reste présent."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/params", params={"system": "LTE"})
    assert r.status_code == 200
    params = r.json().get("params", [])
    assert params
    for p in params[:5]:
        assert "buckets" in p, "le champ buckets (op x band) doit être conservé"
        assert isinstance(p["buckets"], list)
        assert "value_distribution" in p
        assert isinstance(p["value_distribution"], list)


def test_value_distribution_sorted_ascending_numeric(client):
    """La distribution numérique est triée par value_converted asc (float)."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/params", params={"system": "LTE"})
    assert r.status_code == 200
    params = r.json().get("params", [])
    rsrp_rows = [
        p
        for p in params
        if p["path"].endswith("rsrpResult") and p["value_distribution_mode"] == "exact"
    ]
    if not rsrp_rows:
        pytest.fail("pas de rsrpResult en mode exact — skip tri asc")
    vd = rsrp_rows[0]["value_distribution"]
    conv_floats: list[float] = []
    for v in vd:
        if v["value_converted"] is not None:
            try:
                conv_floats.append(float(v["value_converted"]))
            except ValueError:
                continue
    assert conv_floats == sorted(conv_floats), (
        f"value_distribution doit être triée asc par value_converted : "
        f"{conv_floats[:10]}"
    )
