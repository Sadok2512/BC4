"""G22 (0.22.3) — Désambigüisation des libellés d'arbre sur `/dict/tree`.

Vérifie, sur TEST2 (déjà peuplé via
`scripts/populate_dict_for_all_projects.py`) :

- Chaque `params[]` dans la réponse `/dict/tree` expose maintenant un
  champ `label` (nouveau 0.22.3).
- Pour chaque `(system, message)`, deux `params[]` distincts
  (`param` ≠ `param`) ne peuvent **plus** avoir le même `label`
  (le fix élimine 100% des collisions).
- Les leaves uniques (dont le dernier segment du path n'apparaît
  qu'une seule fois dans le `(system, message)`) ont un label
  **sans suffixe parenthésé** — pas de pollution.
- Les leaves en collision (dont le dernier segment apparaît plusieurs
  fois dans le `(system, message)`) ont un label **avec suffixe
  parenthésé** `(…)` — distinctif.
- **Non-régression** : `param` reste le path complet, inchangé — c'est
  la clé qui lie `/dict/tree` à `/dict/params?path=<param>`. Un sondage
  explicite confirme qu'au moins un `param` qui aurait collidé est
  bien récupéré en entier par un `/dict/params?path=<p>&system=<sys>`.

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
        pytest.fail("projet TEST2 absent — garde G22 skippée")
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


def _leaf(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def test_tree_params_expose_label_field(client):
    """`/dict/tree` v2 doit renvoyer `label` sur chaque param (0.22.3)."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/tree")
    assert r.status_code == 200, r.text
    tree = r.json()
    branches = tree.get("branches") or []
    assert branches, "tree v2 doit porter au moins une branche"
    n_params_seen = 0
    for br in branches:
        for m in br.get("messages", []):
            for p in m.get("params", []):
                assert "label" in p, (
                    f"param manque le champ 'label' (0.22.3) : {p!r}"
                )
                assert isinstance(p["label"], str) and p["label"], (
                    f"label doit être une string non vide : {p!r}"
                )
                n_params_seen += 1
    assert n_params_seen > 0, "aucun param dans l'arbre — pré-requis cassé"


def test_tree_labels_unique_within_message(client):
    """Dans un même `(system, message)`, aucun doublon de `label`
    (sauf si deux params ont le même `param`, ce qui ne se produit pas
    grâce au GROUP BY SQL)."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/tree")
    assert r.status_code == 200
    for br in r.json().get("branches", []):
        system = br["system"]
        for m in br.get("messages", []):
            msg = m["message"]
            seen: dict[str, str] = {}  # label -> param
            for p in m.get("params", []):
                label = p["label"]
                param = p["param"]
                if label in seen and seen[label] != param:
                    pytest.fail(
                        f"[{system}/{msg}] label '{label}' partagé par "
                        f"deux params distincts : {seen[label]!r} ET {param!r} "
                        "— désambigüisation 0.22.3 ratée"
                    )
                seen[label] = param


def test_tree_labels_leaf_only_when_unique(client):
    """Un leaf unique dans son `(system, message)` ne doit PAS porter
    de suffixe parenthésé — pas de pollution visuelle."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/tree")
    assert r.status_code == 200
    checked = 0
    for br in r.json().get("branches", []):
        for m in br.get("messages", []):
            # Compter les occurrences de chaque leaf dans le message.
            leaf_count: dict[str, int] = {}
            for p in m.get("params", []):
                leaf_count[_leaf(p["param"])] = leaf_count.get(_leaf(p["param"]), 0) + 1
            for p in m.get("params", []):
                leaf = _leaf(p["param"])
                if leaf_count[leaf] == 1:
                    # Leaf unique → label doit être le leaf nu.
                    assert p["label"] == leaf, (
                        f"[{br['system']}/{m['message']}] param={p['param']!r} "
                        f"a un leaf unique '{leaf}' mais label est "
                        f"{p['label']!r} — devrait être '{leaf}' sans suffixe"
                    )
                    checked += 1
    assert checked > 0, "aucun leaf unique testé — scénario improbable"


def test_tree_labels_suffixed_on_collision(client):
    """Un leaf en collision (plusieurs paths distincts partageant le
    même dernier segment dans un `(system, message)`) DOIT porter un
    suffixe parenthésé `(…)`."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/tree")
    assert r.status_code == 200
    tested_collision = 0
    for br in r.json().get("branches", []):
        for m in br.get("messages", []):
            leaf_count: dict[str, int] = {}
            for p in m.get("params", []):
                leaf_count[_leaf(p["param"])] = leaf_count.get(_leaf(p["param"]), 0) + 1
            for p in m.get("params", []):
                leaf = _leaf(p["param"])
                if leaf_count[leaf] > 1:
                    assert p["label"].startswith(f"{leaf} ("), (
                        f"[{br['system']}/{m['message']}] param={p['param']!r} "
                        f"leaf '{leaf}' en collision ({leaf_count[leaf]}× dans "
                        f"le message) mais label={p['label']!r} ne commence "
                        f"pas par '{leaf} (' — suffixe manquant"
                    )
                    assert p["label"].endswith(")"), (
                        f"label {p['label']!r} ne finit pas par ')' — "
                        "suffixe mal formé"
                    )
                    tested_collision += 1
    assert tested_collision > 0, (
        "aucune collision testée — TEST2 devrait porter des collisions "
        "(ex. rsrpResult sous mesResultPCell/measResult)"
    )


def test_tree_param_still_full_path_non_regression(client):
    """`param` reste le path complet (inchangé) — c'est la clé qui
    permet au front de faire `/dict/params?path=<param>` et de
    retrouver la ligne. On re-sonde une path qui aurait collidé
    (`.../rsrpResult`) et on exige que `/dict/params` la retrouve."""
    pid = _test2_id()
    _ensure_populated(pid)
    r = client.get(f"/projects/{pid}/dict/tree")
    assert r.status_code == 200
    # Chercher une path LTE qui contient '/' (donc path complet préservé)
    # et dont le leaf est en collision.
    target_param: str | None = None
    target_system: str | None = None
    for br in r.json().get("branches", []):
        for m in br.get("messages", []):
            leaf_count: dict[str, int] = {}
            for p in m.get("params", []):
                leaf_count[_leaf(p["param"])] = leaf_count.get(_leaf(p["param"]), 0) + 1
            for p in m.get("params", []):
                if "/" in p["param"] and leaf_count[_leaf(p["param"])] > 1:
                    target_param = p["param"]
                    target_system = br["system"]
                    break
            if target_param:
                break
        if target_param:
            break
    if not target_param:
        pytest.fail("aucune collision à re-sonder — scénario improbable")
    # Pas de filtre `path` sur /dict/params : on sonde system+message et
    # on vérifie que ParamRow.path == target_param existe bien.
    r2 = client.get(
        f"/projects/{pid}/dict/params",
        params={"system": target_system},
    )
    assert r2.status_code == 200
    paths = {row["path"] for row in r2.json().get("params", [])}
    assert target_param in paths, (
        f"param {target_param!r} présent dans /dict/tree mais absent de "
        f"/dict/params?system={target_system} — rupture clé"
    )
