"""G20 (0.21.0) — `value_matrix` sur `/dict/params`.

Vérifie, sur TEST2 (déjà peuplé via `scripts/populate_dict_for_all_projects.py`) :
- `GET /dict/params?system=LTE` renvoie, pour chaque paramètre, un champ
  `value_matrix` (nouveau 0.21.0).
- Pour `rsrpResult` (numérique, LTE) :
  * `value_matrix` est non vide ;
  * `sum(cell.count)` sur la matrice == `count` global du paramètre ;
  * la formule 3GPP est respectée pour chaque cellule :
    `value_converted == str(int(value_raw) - 141)`.
- Au moins un paramètre expose une cellule `operator="non attribué"` ou
  `band="non attribué"` (TEST2 a ~30.5% d'occurrences NULL — un sous-
  ensemble substantiel doit remonter).
- Appliquer `operator=Orange` restreint le `value_matrix` à des cellules
  avec `operator == "Orange"` exclusivement (filtre strict, pas
  d'invention d'opérateurs).
- Non-régression : les buckets `(operator, band)` existants restent
  présents et incluent maintenant un bucket « non attribué » quand il
  y a des NULL (changement 0.21.0).

PRÉ-REQUIS :
- `BC4_API_BASE`, `BC4_ADMIN_EMAIL`, `BC4_ADMIN_PASSWORD`.
- Projet TEST2 ingéré + `param_occurrence` peuplé.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal


UNASSIGNED = "non attribué"


def _test2_id() -> str:
    with SessionLocal() as db:
        pid = db.execute(
            text("SELECT id FROM projects WHERE name = 'TEST2'")
        ).scalar()
    if not pid:
        pytest.skip("projet TEST2 absent — garde G20 skippée")
    return pid


def _ensure_populated(pid: str) -> None:
    with SessionLocal() as db:
        n = db.execute(
            text("SELECT COUNT(*) FROM param_occurrence WHERE project_id = :p"),
            {"p": pid},
        ).scalar()
    if not n or n == 0:
        pytest.skip(
            "param_occurrence vide pour TEST2 — "
            "lance scripts/populate_dict_for_all_projects.py d'abord"
        )


def test_value_matrix_present_and_coherent_rsrp_result(client):
    """Un paramètre peuplé (rsrpResult) doit exposer un `value_matrix`
    non vide, cohérent (somme = count) et sans inversion de formule."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/params", params={"system": "LTE"})
    assert r.status_code == 200, r.text
    params = r.json().get("params", [])
    assert params, "LTE devrait exposer au moins un paramètre"

    rsrp_rows = [p for p in params if p["path"].endswith("rsrpResult")]
    assert rsrp_rows, "LTE devrait contenir au moins un path rsrpResult"
    row = rsrp_rows[0]

    assert "value_matrix" in row, "value_matrix doit être présent (0.21.0)"
    vm = row["value_matrix"]
    assert vm, "value_matrix doit être non vide pour rsrpResult peuplé"

    # Cohérence : somme sur la matrice = count du param.
    total_vm = sum(int(c["count"]) for c in vm)
    assert total_vm == int(row["count"]), (
        f"somme value_matrix ({total_vm}) != row.count ({row['count']})"
    )

    # Toutes les cellules ont les 5 clés obligatoires + operator/band str.
    for cell in vm:
        assert set(cell.keys()) >= {
            "value_raw",
            "value_converted",
            "operator",
            "band",
            "count",
        }
        assert isinstance(cell["operator"], str) and cell["operator"], (
            f"operator doit être une string non vide (non null), vu {cell!r}"
        )
        assert isinstance(cell["band"], str) and cell["band"], (
            f"band doit être une string non vide (non null), vu {cell!r}"
        )

    # Formule 3GPP : rsrpResult → value_converted = str(int(value_raw) - 141).
    for cell in vm:
        raw = cell["value_raw"]
        conv = cell["value_converted"]
        if conv is None:
            # Résidu non-convertible toléré en queue (jamais inventé).
            continue
        try:
            raw_int = int(raw)
        except ValueError:
            pytest.fail(
                f"value_raw '{raw}' pour rsrpResult n'est pas un entier"
            )
        expected = str(raw_int - 141)
        assert conv == expected, (
            f"rsrpResult cell: raw={raw} converted={conv} attendu {expected} "
            "(formule idx-141 — non-régression G16)"
        )


def test_value_matrix_contains_non_attribue_somewhere(client):
    """TEST2 porte ~30% d'occurrences `operator=NULL` (events sans SIB1 avant
    + sans match freq/pci). Elles doivent apparaître explicitement sous
    `operator="non attribué"` OU `band="non attribué"` quelque part.

    Observation : sur TEST2 les NULL sont concentrés côté NR (events NR
    sans SIB1 LTE précédent + sans match freq/pci NR catalogué). On
    scanne donc les deux systèmes et on exige qu'au moins un paramètre
    expose un bucket NULL — un vide total serait un bug du COALESCE.
    """
    pid = _test2_id()
    _ensure_populated(pid)

    found = False
    for system in ("LTE", "NR"):
        r = client.get(f"/projects/{pid}/dict/params", params={"system": system})
        assert r.status_code == 200
        params = r.json().get("params", [])
        for p in params:
            for cell in p.get("value_matrix", []):
                if cell["operator"] == UNASSIGNED or cell["band"] == UNASSIGNED:
                    found = True
                    break
            if found:
                break
        if found:
            break

    assert found, (
        "Aucune cellule 'non attribué' trouvée dans value_matrix (LTE + NR) "
        "— le COALESCE n'a pas été appliqué dans la requête SQL "
        "(bug : les 30% d'occurrences NULL sont silencieusement omises)."
    )


def test_value_matrix_filter_operator_strict(client):
    """Filtrer sur operator=Orange → value_matrix ne contient PLUS QUE des
    cellules avec operator=='Orange'. Jamais un bucket inventé ailleurs."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(
        f"/projects/{pid}/dict/params",
        params={"system": "LTE", "operator": "Orange"},
    )
    assert r.status_code == 200
    params = r.json().get("params", [])
    for p in params:
        for cell in p.get("value_matrix", []):
            assert cell["operator"] == "Orange", (
                f"filtre operator=Orange: cellule {cell!r} n'est pas Orange — "
                "fuite ou invention"
            )


def test_value_matrix_sum_matches_distribution(client):
    """Cohérence croisée : somme(value_matrix.count) == somme(value_distribution.count)
    (même périmètre, agrégations différentes sur la même donnée)."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/params", params={"system": "LTE"})
    assert r.status_code == 200
    params = r.json().get("params", [])
    checked = 0
    for p in params:
        vm = p.get("value_matrix", [])
        vd = p.get("value_distribution", [])
        # On ne compare que les paths en mode "exact" — en mode binné,
        # value_distribution regroupe les valeurs, value_matrix garde
        # value_raw brut, donc les cardinalités diffèrent mais la SOMME
        # DES COUNTS doit rester égale.
        if not vm or not vd:
            continue
        sum_vm = sum(int(c["count"]) for c in vm)
        sum_vd = sum(int(c["count"]) for c in vd)
        assert sum_vm == sum_vd, (
            f"[{p['path']}] somme value_matrix ({sum_vm}) != "
            f"somme value_distribution ({sum_vd}) — divergence de périmètre"
        )
        checked += 1
    assert checked > 0, "Aucun paramètre n'a pu être vérifié (vm/vd vides)"


def test_value_matrix_preserves_buckets_non_breaking(client):
    """Non-régression : le champ `buckets` (op × band) reste exposé pour
    les clients qui l'utilisaient avant 0.21.0."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/params", params={"system": "LTE"})
    assert r.status_code == 200
    params = r.json().get("params", [])
    assert params
    for p in params[:5]:
        assert "buckets" in p, "le champ buckets (op × band) doit être conservé"
        assert isinstance(p["buckets"], list)
        assert "value_matrix" in p
        assert isinstance(p["value_matrix"], list)


def test_buckets_now_include_non_attribue_when_nulls(client):
    """0.21.0 — Les buckets (op × band) exposent maintenant un bucket
    'non attribué' (operator et/ou band) quand des occurrences NULL
    existent (c'était silencieusement omis avant 0.21.0).

    Scan LTE + NR (sur TEST2 les NULL sont côté NR)."""
    pid = _test2_id()
    _ensure_populated(pid)
    found = False
    for system in ("LTE", "NR"):
        r = client.get(f"/projects/{pid}/dict/params", params={"system": system})
        assert r.status_code == 200
        params = r.json().get("params", [])
        for p in params:
            for b in p.get("buckets", []):
                if b.get("operator") == UNASSIGNED or b.get("band") == UNASSIGNED:
                    found = True
                    break
            if found:
                break
        if found:
            break
    assert found, (
        "Aucun bucket 'non attribué' dans buckets[] (LTE + NR) — alignement "
        "0.21.0 raté (les events NULL doivent apparaître dans buckets ET "
        "value_matrix)."
    )
