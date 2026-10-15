"""G14 (0.13.0) — Dictionnaire complet RRC LTE+NR.

Vérifie, sur le projet TEST2 (déjà ingéré, 19 380 events RRC) :
- `param_occurrence` est peuplé (count > 0).
- `/dict/tree` expose les branches LTE *et* NR non vides.
- `/dict/params?system=LTE&message=SystemInformationBlockType1` renvoie
  des paramètres dont au moins un (`q-RxLevMin` ou similaire) porte un
  `value_converted` non null (preuve que la table 3GPP s'applique).
- `/dict/param/map?path=…&system=LTE` renvoie `len(points) > 0`.
- Aucun path DENY (`ue-Identity|s-TMSI|dedicatedNAS|…`) ne figure dans
  `/dict/params` ni dans la base `param_occurrence`.

PRÉ-REQUIS :
- `BC4_API_BASE`, `BC4_ADMIN_EMAIL`, `BC4_ADMIN_PASSWORD`
- Le projet TEST2 doit exister et avoir été peuplé par
  `scripts/populate_dict_for_all_projects.py` au moins une fois (sinon
  le test skip la partie `param_occurrence` et crie).
"""
from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from app.db import SessionLocal


def _test2_id() -> str:
    with SessionLocal() as db:
        pid = db.execute(
            text("SELECT id FROM projects WHERE name = 'TEST2'")
        ).scalar()
    if not pid:
        pytest.skip("projet TEST2 absent — garde G13 skippée (non-régression ciblée)")
    return pid


def test_param_occurrence_populated():
    pid = _test2_id()
    with SessionLocal() as db:
        n = db.execute(
            text("SELECT COUNT(*) FROM param_occurrence WHERE project_id = :p"),
            {"p": pid},
        ).scalar()
    assert n and n > 0, (
        f"param_occurrence vide pour TEST2 — "
        f"lance scripts/populate_dict_for_all_projects.py d'abord"
    )


def test_dict_tree_has_lte_and_nr(client):
    pid = _test2_id()
    r = client.get(f"/projects/{pid}/dict/tree")
    assert r.status_code == 200, r.text
    body = r.json()
    branches = body.get("branches", [])
    systems = {b["system"]: int(b.get("count", 0)) for b in branches}
    assert "LTE" in systems and systems["LTE"] > 0, (
        f"TEST2 doit exposer une branche LTE non vide : {systems}"
    )
    assert "NR" in systems and systems["NR"] > 0, (
        f"TEST2 doit exposer une branche NR non vide : {systems}"
    )


def test_dict_params_sib1_has_q_rx_lev_min_converted(client):
    pid = _test2_id()
    r = client.get(
        f"/projects/{pid}/dict/params",
        params={"system": "LTE", "message": "SystemInformationBlockType1"},
    )
    assert r.status_code == 200, r.text
    params = r.json().get("params", [])
    assert params, "SIB1 LTE devrait exposer au moins un paramètre"
    # Chercher un path portant q-RxLevMin (ou similaire) avec unit_converted non null.
    q_rx_lev_rows = [
        p for p in params if "q-RxLevMin" in p["path"] or "qRxLevMin" in p["path"]
    ]
    assert q_rx_lev_rows, (
        "SIB1 LTE devrait contenir au moins un path q-RxLevMin "
        "(cellSelectionInfo.q-RxLevMin typiquement)"
    )
    with_unit = [p for p in q_rx_lev_rows if p.get("unit_converted") == "dBm"]
    assert with_unit, (
        "au moins une occurrence q-RxLevMin devrait porter unit_converted='dBm' "
        "(table 3GPP TS 36.133 appliquée côté populate)"
    )


def test_dict_param_map_lte_plmn_identity(client):
    pid = _test2_id()
    # On vise un path connu de SIB1 LTE porteur de GPS côté events :
    # `cellAccessRelatedInfo/plmn-IdentityList/plmn-Identity/mcc`
    # (présent 174 fois en LTE pour TEST2). On essaie plusieurs variantes
    # — pycrate peut aplatir avec / sans séquence intermédiaire.
    candidates = []
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT path, COUNT(*) AS n
                FROM param_occurrence
                WHERE project_id = :p AND system = 'LTE'
                  AND lat IS NOT NULL AND lon IS NOT NULL
                  AND path LIKE '%plmn%'
                GROUP BY path
                ORDER BY n DESC
                LIMIT 5
                """
            ),
            {"p": pid},
        ).all()
        candidates = [r.path for r in rows]
    assert candidates, "Aucun path LTE lié à PLMN avec GPS — anomalie attendue"
    path = candidates[0]
    r = client.get(
        f"/projects/{pid}/dict/param/map",
        params={"path": path, "system": "LTE"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("path") == path
    assert body.get("system") == "LTE"
    assert len(body.get("points", [])) > 0, (
        f"Aucun point géolocalisé sur `{path}` — attendu > 0"
    )


def test_no_deny_list_in_db():
    """Vérifie DIRECTEMENT en base qu'aucune ligne de `param_occurrence`
    ne porte un path qui matche la deny-list identités d'abonné."""
    pid = _test2_id()
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT path FROM param_occurrence
                WHERE project_id = :p
                  AND path ~ 'ue-Identity|s-TMSI|dedicatedNAS|dedicatedInfoNAS|c-RNTI|m-TMSI|ng-5G-S-TMSI|guami|registeredMME|registeredAMF'
                LIMIT 5
                """
            ),
            {"p": pid},
        ).all()
    assert not rows, (
        f"Deny-list violation dans param_occurrence : {[r.path for r in rows[:5]]}"
    )


def test_no_deny_list_in_api(client):
    """Même check côté API (chemin de sortie `/dict/params` sans filtre
    message)."""
    pid = _test2_id()
    r = client.get(f"/projects/{pid}/dict/params", params={"system": "LTE"})
    assert r.status_code == 200
    params = r.json().get("params", [])
    deny_re = re.compile(
        r"ue-Identity|s-TMSI|m-TMSI|dedicatedNAS|dedicatedInfoNAS|c-RNTI|ng-5G-S-TMSI",
        re.I,
    )
    offenders = [p["path"] for p in params if deny_re.search(p["path"])]
    assert not offenders, (
        f"Deny-list violation côté API : {offenders[:5]}"
    )
