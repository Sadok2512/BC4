"""Catalog served from `catalog_release.is_current` + `catalog_<v>.json`.

Phase 3a (feat/bc3-metrics-v3) — remplace l'ancien chemin
`catalog_v3`+`catalogue_v6` (NFF 2.19, 885 feuilles BC2) par le catalogue
NFF 2.50.4 (5115 feuilles affichées) servi via `/projects/{pid}/metrics`.

Enveloppe ajoutée au payload :
- `catalog_release` : {version, spec_version, decoder_min_version,
  sha256, n_leaves} tiré de la ligne `catalog_release.is_current=TRUE`.
- `decoder_version` : runtime `app.nmf_decoder.DECODER_VERSION`.
- `reason` : `"from_catalog_release"` quand ce chemin est pris, ou
  `"fallback_legacy_no_catalog_release"` (côté route) quand la table est
  vide (bootstrap frais).

Taille réponse : le JSON 2.50.4 contient 28 718 nodes. On PRUNE le tree
aux ancêtres des 5115 feuilles `displayed=true` pour que le payload
reste navigable côté front (≈1–2 Mo). Les branches sans feuille affichée
sont écartées — elles réapparaîtront en 2.2b quand les events "deep"
hors corpus seront matérialisés.

Pas de donnée fabriquée : `n_in_project` vient d'un `COUNT(*)` live sur
`nmf_event_light.<col>` ; `source_column` est le nom de colonne existant
en base (sinon `None` + `reason="Column not in decoder schema"`).
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.kpi.catalog_release.registry import (
    CurrentCatalog,
    current_catalog,
    load_catalog_json,
)
from app.nmf_decoder import DECODER_VERSION

# 2.54.0 — Variantes canoniques couvertes par le build **par enum NFF 2.50**.
# `cell_type_enum` est porté sur chaque event node par
# `scripts/catalog/build_catalog.py` (clé EVENT_CELL_TYPE_ENUM, citée spec
# ligne par ligne). Toute valeur `cell_type` observée en base hors du jeu
# canonique d'une event (SCell 5, 6 en CA LTE pour un event lte_scell,
# SCell NR 1000+ listed neighbour pour un lte_cellmeas) est émise au
# serve-time comme feuille grise « cellule non cataloguée » avec tooltip.
# Jamais un rejet silencieux (règle Codex67 2026-10-28).
CANONICAL_CTS_PER_ENUM: dict[str, frozenset[int]] = {
    # Serving cell type (RRC) : 0 PCell, 1-4 SCell 1-4 + bucket SCG 100-131 +
    # PSCell 199 (via EN-DC pour les events partagés LTE/NR).
    "lte_scell": frozenset({0, 1, 2, 3, 4, 199} | set(range(100, 132))),
    # Spec NFF 2.50 CELLMEAS LTE (p.30475) : 0 Serving, 1 Listed, 2 Detected,
    # 10-13 SCell 1-4.
    "lte_cellmeas": frozenset({0, 1, 2, 10, 11, 12, 13}),
    # Spec NFF 2.50 MIMOMEAS LTE (p.31586) : 0 Serving, 10-13 SCell 1-4.
    "lte_mimo": frozenset({0, 10, 11, 12, 13}),
}
# Fallback utilisé quand un event cell_scoped n'a pas de `cell_type_enum`
# baké (anciens JSON 2.53.0 et antérieurs).
_DEFAULT_ENUM = "lte_scell"


_KIND_MAP = {
    "Float": "numeric",
    "Integer": "numeric",
    "Int": "numeric",
    "Number": "numeric",
    "Boolean": "categorical",
    "Bool": "categorical",
    "String": "categorical",
    "Text": "categorical",
    "Date": "categorical",
    "Time": "categorical",
    "DateTime": "categorical",
    "Enum": "categorical",
}


def _kind_from_type(t: str | None) -> str:
    return _KIND_MAP.get((t or "").strip(), "categorical")


def _column_from_metric_id(metric_id: str) -> str | None:
    """2.51.1 — Fallback LEGACY : convention `[#]event_field[@cell]` →
    `event_field`. Utilisée seulement quand une feuille 2.51.0 ou
    antérieur n'a pas de clé `source_column` directe (compat ascendante).

    Depuis 2.51.1, les feuilles portent `source_column` tirée du YAML
    du décodeur, source autoritaire : build_catalog.source_column_for().
    """
    if not metric_id:
        return None
    core = metric_id.lstrip("#").split("@", 1)[0]
    return core or None


def _column_for_leaf(leaf: dict) -> str | None:
    """Retourne la source_column autoritaire du leaf (depuis le YAML du
    décodeur, enregistrée dans le JSON catalog par build_catalog 2.51.1+).
    Fallback LEGACY sur la convention `_column_from_metric_id` si absente.
    """
    sc = leaf.get("source_column")
    if isinstance(sc, str) and sc:
        return sc
    return _column_from_metric_id(leaf.get("metric_id") or "")


def _available_light_columns(db: Session) -> set[str]:
    rows = db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='nmf_event_light'"
        )
    ).all()
    return {r[0] for r in rows}


def _available_group_columns(db: Session) -> set[str]:
    """2.51.1 — colonnes de `nmf_event_light_group`. Les champs de groupe
    des YAMLs (ex `cell.rsrp` → colonne `cell_rsrp`) y sont stockés en
    plus de leur propagation vers `nmf_event_light`.
    """
    rows = db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='nmf_event_light_group'"
        )
    ).all()
    return {r[0] for r in rows}


_LIGHT_COLS_CACHE: set[str] | None = None


def _is_group_only(db: Session, col: str) -> bool:
    global _LIGHT_COLS_CACHE
    if _LIGHT_COLS_CACHE is None:
        _LIGHT_COLS_CACHE = _available_light_columns(db)
    return col not in _LIGHT_COLS_CACHE


_N_PER_COLUMN_CHUNK = 50


def _n_per_column(
    db: Session, project_id: str, columns: set[str]
) -> dict[str, int]:
    """COUNT per column — rows with col IS NOT NULL.

    2.51.1 — Les colonnes sont scannées dans `nmf_event_light` ET
    `nmf_event_light_group` (certaines colonnes de groupe comme
    `cell_rsrp` existent dans les deux). Chaque colonne est associée au
    MAX des 2 counts (= observations réelles).
    """
    safe = [c for c in columns if c.replace("_", "").isalnum()]
    if not safe:
        return {}
    light_cols = _available_light_columns(db)
    group_cols = _available_group_columns(db)
    out: dict[str, int] = {c: 0 for c in safe}
    # nmf_event_light
    cols_in_light = [c for c in safe if c in light_cols]
    for i in range(0, len(cols_in_light), _N_PER_COLUMN_CHUNK):
        chunk = cols_in_light[i : i + _N_PER_COLUMN_CHUNK]
        expr = ", ".join(
            f'COUNT(*) FILTER (WHERE "{c}" IS NOT NULL) AS "c_{idx}"'
            for idx, c in enumerate(chunk)
        )
        sql = f"SELECT {expr} FROM nmf_event_light WHERE project_id=:pid"
        row = db.execute(text(sql), {"pid": project_id}).first()
        if row is None:
            continue
        for idx, c in enumerate(chunk):
            out[c] = max(out[c], int(row[idx] or 0))
    # nmf_event_light_group — pour les colonnes qui n'existent que là
    # (ex cell_rsrp sur CELLMEAS LTE 1.5.1, pas propagé dans Light).
    cols_in_group_only = [c for c in safe if c in group_cols and c not in light_cols]
    for i in range(0, len(cols_in_group_only), _N_PER_COLUMN_CHUNK):
        chunk = cols_in_group_only[i : i + _N_PER_COLUMN_CHUNK]
        expr = ", ".join(
            f'COUNT(*) FILTER (WHERE "{c}" IS NOT NULL) AS "c_{idx}"'
            for idx, c in enumerate(chunk)
        )
        sql = f"SELECT {expr} FROM nmf_event_light_group WHERE project_id=:pid"
        row = db.execute(text(sql), {"pid": project_id}).first()
        if row is None:
            continue
        for idx, c in enumerate(chunk):
            out[c] = max(out[c], int(row[idx] or 0))
    return out


def _cell_type_counts_per_project(
    db: Session,
    project_id: str,
    event_cols_light: dict[str, set[str]],
    event_cols_group: dict[str, set[str]],
    avail_light_cols: set[str],
    avail_group_cols: set[str],
) -> dict[tuple[str, int, str], int]:
    """2.54.0 — Comptage ligne par ligne par (event, cell_type, source_column).

    Deux sources distinctes agrégées :

    (A) **dimension header** (CI/CQI/DCI/MACRATE/.../TXPC) : la cellule
        vit dans `nmf_event_light.<event_lower>_cell_type`. Un GROUP BY
        sur cette colonne, avec `COUNT(*) FILTER` par source_column, est
        exécuté par événement.

    (B) **groupes** (CELLMEAS LTE+NR, MIMOMEAS) : la cellule vit dans
        `nmf_event_light_group.cell_type`. Un JOIN sur
        `(project_id, capture_id, seq)` + GROUP BY `g.cell_type`.

    Appelé une fois par requête `/metrics`. Si l'event n'a aucune
    source_column cell_scoped à compter, aucun SQL n'est émis.

    Codex67 2026-10-28 — contrat de comptage : une feuille `@<cellule>`
    compte UNIQUEMENT les lignes de CETTE cellule pour CET event dans CE
    projet, filtrées `source_column IS NOT NULL`.
    """
    out: dict[tuple[str, int, str], int] = {}
    # (A) dimension header — un GROUP BY par event
    for ev, cols in event_cols_light.items():
        if not cols:
            continue
        ct_col = f"{ev.lower()}_cell_type"
        if ct_col not in avail_light_cols:
            continue
        safe_cols = [c for c in cols if c.replace("_", "").isalnum()]
        if not safe_cols:
            continue
        count_exprs = ", ".join(
            f'COUNT(*) FILTER (WHERE "{c}" IS NOT NULL) AS "cnt_{idx}"'
            for idx, c in enumerate(safe_cols)
        )
        sql = (
            f'SELECT "{ct_col}" AS ct, {count_exprs} '
            f"FROM nmf_event_light "
            f"WHERE project_id=:pid AND event_code=:ev "
            f'GROUP BY "{ct_col}"'
        )
        for row in db.execute(text(sql), {"pid": project_id, "ev": ev}).mappings():
            ct = row["ct"]
            if ct is None:
                # 2.54.0 — Les lignes `cell_type IS NULL` sont rangées
                # sous un bucket sentinelle `-1`, émis en feuille grise
                # « cellule non renseignée » par le découvreur uncatalogued
                # (point 4 Codex67 : jamais un rejet silencieux).
                ct_int = -1
            else:
                try:
                    ct_int = int(ct)
                except (TypeError, ValueError):
                    continue
            for idx, c in enumerate(safe_cols):
                nn = int(row[f"cnt_{idx}"] or 0)
                if nn > 0:
                    out[(ev, ct_int, c)] = nn
    # (B) groupes — un GROUP BY par event. Pour les colonnes qui existent
    # dans nmf_event_light ET nmf_event_light_group (ex cell_rsrp), on
    # qualifie `g.<col>` quand la col est côté groupe, `l.<col>` sinon.
    for ev, cols in event_cols_group.items():
        if not cols:
            continue
        safe_cols = [c for c in cols if c.replace("_", "").isalnum()]
        if not safe_cols:
            continue
        exprs = []
        for idx, c in enumerate(safe_cols):
            qual = "g" if c in avail_group_cols else "l"
            exprs.append(
                f'COUNT(*) FILTER (WHERE {qual}."{c}" IS NOT NULL) AS "cnt_{idx}"'
            )
        count_exprs = ", ".join(exprs)
        sql = (
            f"SELECT g.cell_type AS ct, {count_exprs} "
            f"FROM nmf_event_light_group g "
            f"JOIN nmf_event_light l "
            f"  ON l.project_id=g.project_id "
            f" AND l.capture_id=g.capture_id "
            f" AND l.seq=g.seq "
            f"WHERE l.project_id=:pid AND l.event_code=:ev "
            f"  AND g.group_name IN ('cells','measurements') "
            f"GROUP BY g.cell_type"
        )
        for row in db.execute(text(sql), {"pid": project_id, "ev": ev}).mappings():
            ct = row["ct"]
            if ct is None:
                # 2.54.0 — Les lignes `cell_type IS NULL` sont rangées
                # sous un bucket sentinelle `-1`, émis en feuille grise
                # « cellule non renseignée » par le découvreur uncatalogued
                # (point 4 Codex67 : jamais un rejet silencieux).
                ct_int = -1
            else:
                try:
                    ct_int = int(ct)
                except (TypeError, ValueError):
                    continue
            for idx, c in enumerate(safe_cols):
                nn = int(row[f"cnt_{idx}"] or 0)
                if nn > 0:
                    out[(ev, ct_int, c)] = nn
    return out


def _event_col_total(
    db: Session,
    project_id: str,
    event_code: str,
    col: str,
    avail_light_cols: set[str],
    avail_group_cols: set[str],
) -> int:
    """2.54.0 — COUNT global de `col IS NOT NULL` pour un (project, event)
    sans filtre cellule. Sert à la conservation (ct=-1 bucket). Choisit la
    table où `col` existe réellement.
    """
    if not col or not col.replace("_", "").isalnum():
        return 0
    if col in avail_light_cols:
        sql = (
            f'SELECT COUNT(*) FROM nmf_event_light '
            f'WHERE project_id=:pid AND event_code=:ev AND "{col}" IS NOT NULL'
        )
        return int(
            db.execute(text(sql), {"pid": project_id, "ev": event_code}).scalar() or 0
        )
    if col in avail_group_cols:
        sql = (
            f'SELECT COUNT(*) FROM nmf_event_light_group g '
            f'JOIN nmf_event_light l '
            f'  ON l.project_id=g.project_id '
            f' AND l.capture_id=g.capture_id '
            f' AND l.seq=g.seq '
            f'WHERE l.project_id=:pid AND l.event_code=:ev AND g."{col}" IS NOT NULL'
        )
        return int(
            db.execute(text(sql), {"pid": project_id, "ev": event_code}).scalar() or 0
        )
    return 0


def _bucket_ct_lte_scell(ct: int) -> int:
    """Bucket SCG SCell NR : 100-131 → 100 pour l'enum `lte_scell`
    uniquement (events partagés LTE/NR en EN-DC). Autres canoniques
    s'auto-renvoient. Non-canoniques renvoient leur valeur.
    """
    if 100 <= ct <= 131:
        return 100
    return ct


def _category_label(nodes_by_id: dict, start_parent_id: str | None) -> str | None:
    """Walk parent chain upward to the first `node_type='category'` label."""
    seen: set[str] = set()
    current = start_parent_id
    while current and current not in seen:
        seen.add(current)
        node = nodes_by_id.get(current)
        if not node:
            return None
        if node.get("node_type") == "category":
            return node.get("label")
        current = node.get("parent_id")
    return None


def _ancestors(nodes_by_id: dict, start_id: str) -> set[str]:
    """Return {start_id, parent, grandparent, …} up to root (cycle-safe)."""
    out: set[str] = set()
    current: str | None = start_id
    while current and current not in out:
        out.add(current)
        node = nodes_by_id.get(current)
        if not node:
            break
        current = node.get("parent_id")
    return out


def build_catalog_v4(
    db: Session, project_id: str, current: CurrentCatalog
) -> dict[str, Any]:
    """Build the /metrics payload from `catalog_release.is_current` JSON.

    Payload shape matches `MetricCatalogResponse` with the envelope fields
    `catalog_release`, `decoder_version`, `reason` added.
    """
    catalog = load_catalog_json(current.version)
    nodes_in = catalog["nodes"]
    nodes_by_id = {n["node_id"]: n for n in nodes_in}

    displayed_leaves = [
        n
        for n in nodes_in
        if n.get("node_type") == "leaf" and n.get("displayed")
    ]

    # 1) Map leaf → candidate column; keep only columns present in DB.
    avail_light_cols = _available_light_columns(db)
    avail_group_cols = _available_group_columns(db)
    avail_cols = avail_light_cols | avail_group_cols
    candidate_cols: set[str] = set()
    for lf in displayed_leaves:
        col = _column_for_leaf(lf)
        if col and col in avail_cols:
            candidate_cols.add(col)
    counts = _n_per_column(db, project_id, candidate_cols)

    # 1.a) 2.54.0 — Comptage par (event, cell_type, source_column).
    # Pour les feuilles cell_scoped (`cell_type` présent dans le node),
    # `n` doit être le nombre d'observations de CETTE cellule pour CET
    # event dans CE projet (Codex67 2026-10-28, point 3). Les events
    # sont scindés entre dimension-header (`<ev>_cell_type` colonne) et
    # groupes (`nmf_event_light_group.cell_type`).
    cell_scoped_events: set[str] = {
        (n.get("event") or "").lstrip("#")
        for n in nodes_in
        if n.get("node_type") == "event" and n.get("cell_scoped")
    }
    # 2.54.0 — Enum NFF 2.50 par event (baké par build_catalog.py).
    # Fallback `lte_scell` pour les anciens JSON (compat 2.53.0−).
    event_ct_enum: dict[str, str] = {}
    for n in nodes_in:
        if n.get("node_type") != "event":
            continue
        ev = (n.get("event") or "").lstrip("#")
        event_ct_enum[ev] = n.get("cell_type_enum") or _DEFAULT_ENUM
    # Un event est dispatché par CELL_TYPE soit en header (colonne
    # `<ev_lower>_cell_type` dans nmf_event_light, cas CI/CQI/DCI/…), soit
    # en groupe (nmf_event_light_group.cell_type, cas CELLMEAS/MIMOMEAS).
    # On range chaque source_column observée côté leaves dans le bucket
    # qui correspond au cell_type de son event, pas à l'endroit où vit la
    # colonne : certaines colonnes de groupe sont propagées dans
    # `nmf_event_light` (ex. cell_rsrp) et il faut quand même grouper
    # par `g.cell_type` pour l'event CELLMEAS.
    event_cols_light: dict[str, set[str]] = defaultdict(set)
    event_cols_group: dict[str, set[str]] = defaultdict(set)
    for lf in displayed_leaves:
        if lf.get("cell_type") is None:
            continue
        ev = (lf.get("event") or "").lstrip("#")
        if ev not in cell_scoped_events:
            continue
        col = _column_for_leaf(lf)
        if not col or col not in avail_cols:
            continue
        if f"{ev.lower()}_cell_type" in avail_light_cols:
            event_cols_light[ev].add(col)
        else:
            event_cols_group[ev].add(col)
    cell_type_counts = _cell_type_counts_per_project(
        db,
        project_id,
        event_cols_light,
        event_cols_group,
        avail_light_cols,
        avail_group_cols,
    )
    # 1.b) 2.54.0 — Conservation : pour chaque (event, source_column)
    # cell_scoped, la somme des per-ct comptés doit atteindre le COUNT
    # global de la colonne. Toute différence tombe dans le bucket ct=-1
    # (`cell_type non renseigné / dispatch inconnu`). Cela attrape :
    #   • les lignes où la colonne de dispatch (`<ev>_cell_type` ou
    #     `g.cell_type`) est NULL ;
    #   • les events `cell_scoped=true` dans categories.yaml dont le
    #     décodeur n'alimente ni colonne ni groupe de cell_type (ex.
    #     PLAIU — observé 2026-10-28, à retravailler côté catégorisation).
    # Garantit G25.4 par construction, sans jamais inventer de dispatch.
    for ev in set(event_cols_light.keys()) | set(event_cols_group.keys()):
        cols_for_ev = (
            event_cols_light.get(ev, set()) | event_cols_group.get(ev, set())
        )
        for col in cols_for_ev:
            total = _event_col_total(
                db, project_id, ev, col, avail_light_cols, avail_group_cols
            )
            if total <= 0:
                continue
            current_sum = sum(
                nn
                for (e, c, co), nn in cell_type_counts.items()
                if e == ev and co == col
            )
            delta = total - current_sum
            if delta > 0:
                prev = cell_type_counts.get((ev, -1, col), 0)
                cell_type_counts[(ev, -1, col)] = prev + delta
    # Bucket SCG SCell NR 100-131 → résumé sous la variante `cell_type=100`
    # du catalogue (« SCell NR 100+ »). N'est appliqué qu'aux events qui
    # ont effectivement une variante bucketée dans leur enum (`lte_scell`).
    scg_bucket_counts: dict[tuple[str, str], int] = defaultdict(int)
    for (ev, ct, col), nn in cell_type_counts.items():
        if 100 <= ct <= 131 and event_ct_enum.get(ev) == "lte_scell":
            scg_bucket_counts[(ev, col)] += nn

    def _n_per_cell(ev: str, ct: int, col: str) -> int:
        """Lookup n for a cell_scoped leaf. ct=100 agrège le bucket
        SCG SCell NR 100-131 **uniquement** pour les events d'enum
        `lte_scell` (standard RRC). Les autres canoniques et uncatalogued
        s'auto-renvoient par leur valeur exacte.
        """
        if ct == 100 and event_ct_enum.get(ev) == "lte_scell":
            return int(scg_bucket_counts.get((ev, col), 0))
        return int(cell_type_counts.get((ev, ct, col), 0))

    def _per_cell_reason(ev: str, ct: int, col: str, cell_label: str | None) -> str:
        """Reason honnête quand n_per_cell=0 pour une col décodée. Pas de
        test sur le texte de la raison (Codex67 2026-10-28, point 2) —
        on produit ici une raison factuelle par-projet.
        """
        return (
            f"Aucune observation de {cell_label or f'cell_type={ct}'} "
            f"pour {ev} dans ce projet"
        )

    # 2) Prune nodes to displayed-leaves + ancestors (coherent tree).
    #    Phase 3b : on garde AUSSI tous les `tech` nodes même s'ils n'ont
    #    aucune feuille affichée (ex. NR en 2.50.5 : 0 leaf displayed, mais
    #    la racine Technology doit rester visible pour signaler la dette
    #    2.2b et préserver la cohérence de l'arbre côté front).
    keep_ids: set[str] = {
        n["node_id"] for n in nodes_in if n.get("node_type") == "tech"
    }
    for lf in displayed_leaves:
        keep_ids |= _ancestors(nodes_by_id, lf["node_id"])

    # 3) Build metrics[] — DÉFINITION FERMÉE (BC3 2026-10-26) :
    #    metrics[] = feuilles SELECTABLE uniquement (consommables par
    #    /metrics/table). Les feuilles grisées (reason="Column not in
    #    schema" ou "No observations in project") restent dans nodes[]
    #    pour l'arbre navigable, mais ne figurent PAS dans metrics[].
    #    code = source_column[@cell_type] (le même token que
    #    nodes[].selection), donc G25.1 orphans = 0 par construction.
    metrics_out: list[dict] = []
    seen_codes: set[str] = set()
    for lf in displayed_leaves:
        metric_id = lf.get("metric_id") or ""
        # 2.53.0 — CAPTURE leaves : short-circuit col-based check. Elles
        # résolvent via `cap_{group}_{slug}` dans metrics_v3 (Dataset
        # dispatch sur préfixe cap_). n=1 marker pour ne pas être filtrées
        # (le vrai count est capture-local, calculé par le resolver).
        is_capture = lf.get("tech") == "CAPTURE"
        if is_capture:
            col = metric_id or _column_for_leaf(lf)
            has_col = bool(col)
            n = 1 if lf.get("selectable") else 0
            is_selectable = bool(lf.get("selectable"))
        else:
            col = _column_for_leaf(lf)
            has_col = bool(col) and col in avail_cols
            ct_leaf = lf.get("cell_type")
            if ct_leaf is None:
                # Feuille bare : COUNT global de la colonne.
                n = counts.get(col, 0) if has_col else 0
            else:
                # 2.54.0 — Feuille cell_scoped : COUNT filtré par cell_type
                # pour CET event dans CE projet. ct=100 agrège le bucket NR.
                ev_lf = (lf.get("event") or "").lstrip("#")
                n = _n_per_cell(ev_lf, int(ct_leaf), col) if has_col else 0
            # 2.54.0 — Décision selectable par-projet, pas de bake corpus-wide.
            # Si le build a figé selectable=False (structural : non applicable
            # LTE-only/NR-only, ou champ FF 2.62 non documenté 2.50), on
            # respecte. Sinon : selectable = col décodée ET n_per_cell > 0.
            baked_sel = lf.get("selectable")
            if baked_sel is False:
                is_selectable = False
            else:
                is_selectable = has_col and n > 0
        if not is_selectable:
            continue
        cell_suffix = f"@{lf.get('cell_type')}" if lf.get("cell_type") is not None else ""
        code = f"{col}{cell_suffix}"
        if code in seen_codes:
            continue
        seen_codes.add(code)
        event = (lf.get("event") or "").lstrip("#")
        cat_label = (
            _category_label(nodes_by_id, lf.get("parent_id")) or "Undocumented"
        )
        metrics_out.append(
            dict(
                code=code,
                label=lf.get("label") or metric_id,
                unit=lf.get("unit") or "",
                source_table="nmf_event_light",
                source_tables=["nmf_event_light"],
                source_column=col if has_col else "",
                tech="BOTH",
                kind=_kind_from_type(lf.get("type")),
                n_in_project=n,
                decoder_version=DECODER_VERSION,
                event=event,
                category_label=cat_label,
                cell_scoped=False,
                cells=[],
                cell_options=[],
                attributes=[],
                proof=lf.get("proof") or "none",
                available=has_col and n > 0,
                reason=(
                    None
                    if (has_col and n > 0)
                    else (
                        "Column not in decoder schema"
                        if not has_col
                        else "No observations in project"
                    )
                ),
                alias_of=None,
                event_group=None,
                unproven_cells=[],
                root_notices=[],
                event_code=event,
                proof_ref="",
                category=cat_label.lower().replace(" ", "_"),
            )
        )

    # 4) Build nodes[] — pruned tree, order inferred from input position.
    siblings_counter: dict[str | None, int] = {}
    nodes_out: list[dict] = []
    for node in nodes_in:
        if node["node_id"] not in keep_ids:
            continue
        parent_id = node.get("parent_id")
        order = siblings_counter.get(parent_id, 0)
        siblings_counter[parent_id] = order + 1
        is_leaf = node.get("node_type") == "leaf"
        metric_id = node.get("metric_id") if is_leaf else None
        is_capture_leaf = is_leaf and node.get("tech") == "CAPTURE"
        col = _column_for_leaf(node) if is_leaf else None
        ct_node = node.get("cell_type") if is_leaf else None
        if is_capture_leaf:
            col = metric_id or col
            has_col = bool(col)
            n_val = 1 if node.get("selectable") else 0
        else:
            has_col = bool(col) and col in avail_cols
            if ct_node is None:
                n_val = counts.get(col, 0) if has_col else 0
            else:
                # 2.54.0 — cell_scoped : COUNT par (event, cell_type,
                # source_column), pas la col globale.
                ev_lf = (node.get("event") or "").lstrip("#")
                n_val = _n_per_cell(ev_lf, int(ct_node), col) if has_col else 0
        field_no = node.get("field_no")
        field_idx: int | None = None
        try:
            field_idx = int(field_no) if field_no is not None else None
        except (TypeError, ValueError):
            field_idx = None
        # 2.54.0 — Décision selectable par-projet pour les feuilles
        # cell_scoped applicables ; respect strict d'un bake False
        # structural (applicabilité tech, _fil/extra_). Pour les feuilles
        # bare : décision identique au métriques[] (has_col ET n>0).
        baked_sel = node.get("selectable")
        if not is_leaf or not node.get("displayed"):
            selectable_flag = False
        elif is_capture_leaf:
            selectable_flag = bool(baked_sel) and has_col
        elif baked_sel is False:
            selectable_flag = False
        else:
            selectable_flag = bool(has_col and n_val > 0)
        # 2.51.1 — `selection` est le token consommé par /metrics/table
        # (parse_selection → definitions() → whitelist decoder). Il doit
        # porter la VRAIE colonne (`source_column@cell`) et non la
        # convention `event_slug@cell` du metric_id. Fallback metric_id
        # pour compat ascendante quand source_column vide.
        if selectable_flag:
            cell_suffix = f"@{ct_node}" if ct_node is not None else ""
            if col:
                selection = f"{col}{cell_suffix}"
            else:
                selection = metric_id
        else:
            selection = None
        # 2.54.0 — Raison honnête :
        #   (1) baked reason prioritaire (CAPTURE "Privacy by design",
        #       applicability "N/A — event LTE-only/NR-only", extras
        #       "FF 2.62 non documenté 2.50") ;
        #   (2) sinon col absente → "Column not in decoder schema" ;
        #   (3) sinon cell_scoped sans obs sur CE project pour CETTE
        #       cellule → "Aucune observation de <cellule> pour
        #       <event> dans ce projet" ;
        #   (4) sinon feuille bare sans obs → "No observations in
        #       project" ;
        #   (5) sinon None (feuille sélectable).
        if is_leaf and node.get("reason"):
            reason_val = node.get("reason")
        elif not is_leaf:
            reason_val = None
        elif not has_col:
            reason_val = "Column not in decoder schema"
        elif n_val > 0:
            reason_val = None
        elif ct_node is not None:
            ev_lf = (node.get("event") or "").lstrip("#")
            reason_val = _per_cell_reason(
                ev_lf, int(ct_node), col or "", node.get("cell_label")
            )
        else:
            reason_val = "No observations in project"
        nodes_out.append(
            dict(
                node_id=node["node_id"],
                parent_id=parent_id,
                order=order,
                label=node.get("label") or "",
                note=node.get("description"),
                source=None,
                node_type=node.get("node_type"),
                metric_id=metric_id,
                selection=selection,
                event=(node.get("event") or "").lstrip("#") if is_leaf else None,
                field_idx=field_idx,
                source_column=col if has_col else None,
                unit=node.get("unit") or "",
                cell=None,
                n=n_val,
                proof=node.get("proof") or "open",
                selectable=selectable_flag,
                reason=reason_val,
            )
        )

    # 5) 2.54.0 — Découverte « cellules observées non cataloguées » par
    # projet. Pour chaque cell_scoped event, si une valeur `cell_type`
    # observée tombe hors de l'arbre canonique (ni 0-4, ni 199, ni
    # 100-131), on émet UNE feuille par (event, cell_type, source_column)
    # observé, grise + tooltip de cause. Jamais un rejet silencieux
    # (Codex67 2026-10-28, point 4).
    event_node_by_code: dict[str, str] = {
        (n.get("event") or "").lstrip("#"): n["node_id"]
        for n in nodes_in
        if n.get("node_type") == "event"
    }
    # 2.54.0 — Nom humain du champ par source_column, construit à partir
    # des labels canoniques (strip du suffixe « @ <cell> »). Codex67
    # 2026-10-28 point 3 : les feuilles outsider doivent afficher le
    # libellé humain (« UL grants @ SCell 6 »), pas le nom de colonne
    # brut (« dci_ul_grants @ SCell 6 »).
    human_field_by_col: dict[tuple[str, str], str] = {}
    for lf in displayed_leaves:
        # 2.54.0 — Résout aussi la col par fallback metric_id pour les
        # feuilles 2.51.0+ dont le baked source_column est vide
        # (ex. PLAIU, où le mapping YAML du décodeur n'a pas abouti au
        # build, mais la convention nom reste utilisable à la lecture).
        sc = _column_for_leaf(lf)
        if not sc:
            continue
        lab = lf.get("label") or ""
        if " @ " in lab:
            field_name = lab.split(" @ ", 1)[0]
        else:
            field_name = lab
        ev_lf = (lf.get("event") or "").lstrip("#")
        human_field_by_col.setdefault((ev_lf, sc), field_name)

    def _field_name_for(ev: str, col: str) -> str:
        return human_field_by_col.get((ev, col), col)

    uncatalogued_entries: list[tuple[str, int, str, int]] = []
    for (ev, ct, col), nn in cell_type_counts.items():
        enum_name = event_ct_enum.get(ev, _DEFAULT_ENUM)
        canonical = CANONICAL_CTS_PER_ENUM.get(enum_name, frozenset())
        if ct in canonical:
            continue
        if nn <= 0:
            continue
        uncatalogued_entries.append((ev, ct, col, nn))
    uncatalogued_entries.sort()
    for ev, ct, col, nn in uncatalogued_entries:
        ev_nid = event_node_by_code.get(ev)
        if not ev_nid:
            continue
        field_name = _field_name_for(ev, col)
        enum_name = event_ct_enum.get(ev, _DEFAULT_ENUM)
        # Nom d'enum NFF 2.50 pour tooltip (lte_scell / lte_cellmeas /
        # lte_mimo / lte_mesure / nr).
        spec_enum_name = (
            {"lte_scell": "cell_type_lte_scell",
             "lte_cellmeas": "cell_type_lte_cellmeas",
             "lte_mimo": "cell_type_lte_mimo",
             }.get(enum_name, enum_name)
        )
        if ct == -1:
            # cell_type NULL sur la ligne de dispatch (header ou group).
            label_full = f"{field_name} @ cell_type non renseigné (NULL)"
            reason_outsider = (
                f"La ligne n'était pas rattachée à une cellule au décodage "
                f"(nmf_event_light.{ev.lower()}_cell_type / "
                f"nmf_event_light_group.cell_type IS NULL). "
                f"{nn} observations."
            )
            node_id = f"lf_outsider_{ev.lower()}_null_{col}"
            proof_tag = "observed-no-cell-type"
        else:
            # Libellé humain de la valeur : on cherche d'abord dans l'enum
            # standard générique du catalog JSON (ex. `cell_type_lte_scell`
            # pour SCell 5, SCell 6 observés hors des 7 canoniques), puis
            # on retombe sur `cell_type_nr` pour les valeurs NR hautes
            # (bucket neighbours 1000+).
            label_from_enum = None
            for enum_name_json in (
                "cell_type_lte_scell",
                "cell_type_nr",
                "cell_type_lte_mesure",
            ):
                for entry in (catalog.get("enums") or {}).get(enum_name_json, []):
                    if entry.get("value") == ct:
                        label_from_enum = entry.get("label")
                        break
                if label_from_enum:
                    break
            spec_hint = f"NFF 2.50 {spec_enum_name}:{ct}"
            label_full = (
                f"{field_name} @ {label_from_enum} (cellule non cataloguée)"
                if label_from_enum
                else f"{field_name} @ cell_type={ct} (cellule non cataloguée)"
            )
            node_id = f"lf_outsider_{ev.lower()}_{ct}_{col}"
            reason_outsider = (
                f"cell_type={ct} observée dans ce projet mais hors arbre "
                f"canonique ({spec_hint}). {nn} observations."
            )
            proof_tag = "observed-no-catalog"
        parent_id = ev_nid
        order = siblings_counter.get(parent_id, 0)
        siblings_counter[parent_id] = order + 1
        nodes_out.append(
            dict(
                node_id=node_id,
                parent_id=parent_id,
                order=order,
                label=label_full,
                note=reason_outsider,
                source=None,
                node_type="leaf",
                metric_id=None,
                selection=None,
                event=ev,
                field_idx=None,
                source_column=col,
                unit="",
                cell=None,
                n=int(nn),
                proof=proof_tag,
                selectable=False,
                reason=reason_outsider,
            )
        )

    return dict(
        catalogue_version=current.version,
        catalog_release=dict(
            version=current.version,
            spec_version=current.spec_version,
            decoder_min_version=current.decoder_min_version,
            sha256=current.sha256,
            n_leaves=current.n_leaves,
        ),
        decoder_version=DECODER_VERSION,
        reason="from_catalog_release",
        title=f"Catalog NFF {current.spec_version} ({current.version})",
        header=f"Decoder {DECODER_VERSION} · Catalog {current.version}",
        metrics=metrics_out,
        nodes=nodes_out,
    )
