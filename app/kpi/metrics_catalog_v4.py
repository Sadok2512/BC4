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
    avail_cols = _available_light_columns(db) | _available_group_columns(db)
    candidate_cols: set[str] = set()
    for lf in displayed_leaves:
        col = _column_for_leaf(lf)
        if col and col in avail_cols:
            candidate_cols.add(col)
    counts = _n_per_column(db, project_id, candidate_cols)

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

    # 3) Build metrics[] — one entry per displayed leaf (metric_id unique).
    metrics_out: list[dict] = []
    seen_codes: set[str] = set()
    for lf in displayed_leaves:
        metric_id = lf.get("metric_id") or ""
        if not metric_id or metric_id in seen_codes:
            continue
        seen_codes.add(metric_id)
        col = _column_for_leaf(lf)
        has_col = bool(col) and col in avail_cols
        n = counts.get(col, 0) if has_col else 0
        event = (lf.get("event") or "").lstrip("#")
        cat_label = (
            _category_label(nodes_by_id, lf.get("parent_id")) or "Undocumented"
        )
        metrics_out.append(
            dict(
                code=metric_id,
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
    for n in nodes_in:
        if n["node_id"] not in keep_ids:
            continue
        parent_id = n.get("parent_id")
        order = siblings_counter.get(parent_id, 0)
        siblings_counter[parent_id] = order + 1
        is_leaf = n.get("node_type") == "leaf"
        metric_id = n.get("metric_id") if is_leaf else None
        col = _column_for_leaf(n) if is_leaf else None
        has_col = bool(col) and col in avail_cols
        n_val = counts.get(col, 0) if has_col else 0
        field_no = n.get("field_no")
        field_idx: int | None = None
        try:
            field_idx = int(field_no) if field_no is not None else None
        except (TypeError, ValueError):
            field_idx = None
        selectable_flag = bool(
            is_leaf and n.get("selectable") and n.get("displayed") and has_col
        )
        # 2.51.1 — `selection` est le token consommé par /metrics/table
        # (parse_selection → definitions() → whitelist decoder). Il doit
        # porter la VRAIE colonne (`source_column@cell`) et non la
        # convention `event_slug@cell` du metric_id. Fallback metric_id
        # pour compat ascendante quand source_column vide.
        if is_leaf and n.get("selectable") and n.get("displayed"):
            cell_suffix = f"@{n.get('cell_type')}" if n.get("cell_type") is not None else ""
            if col:
                selection = f"{col}{cell_suffix}"
            else:
                selection = metric_id
        else:
            selection = None
        nodes_out.append(
            dict(
                node_id=n["node_id"],
                parent_id=parent_id,
                order=order,
                label=n.get("label") or "",
                note=n.get("description"),
                source=None,
                node_type=n.get("node_type"),
                metric_id=metric_id,
                selection=selection,
                event=(n.get("event") or "").lstrip("#") if is_leaf else None,
                field_idx=field_idx,
                source_column=col if has_col else None,
                unit=n.get("unit") or "",
                cell=None,
                n=n_val,
                proof=n.get("proof") or "open",
                selectable=selectable_flag,
                reason=(
                    None
                    if (not is_leaf or (has_col and n_val > 0))
                    else (
                        "Column not in decoder schema"
                        if not has_col
                        else "No observations in project"
                    )
                ),
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
