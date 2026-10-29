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
from app.nmf_decoder.cells import cell_source_for_index

# 2.56.0 — Variantes canoniques par enum NFF 2.50. La disponibilité vient
# exclusivement de nmf_cell_second.cell_index ; nmf_event_light.system choisit
# le libellé de l'enum pour le même événement.
CANONICAL_CTS_PER_ENUM: dict[str, frozenset[int]] = {
    "lte_scell": frozenset(range(32)),
    # CELLMEAS LTE raw 10..40 est normalisé en cell_index 1..31.
    "lte_cellmeas": frozenset(range(32)),
    "lte_mimo": frozenset({0} | set(range(10, 41))),
    "nr_cell": frozenset(
        {0, 199, 1000, 1001, 1002}
        | set(range(1, 32)) | set(range(100, 132))
    ),
}
# Fallback utilisé quand un event cell_scoped n'a pas de `cell_type_enum`
# baké (anciens JSON 2.53.0 et antérieurs).
_DEFAULT_ENUM = "lte_scell"


def _enum_name(event: str, system: int | None) -> str:
    if system == 9:
        return "nr_cell"
    if event == "CELLMEAS":
        return "lte_cellmeas"
    if event == "MIMOMEAS":
        return "lte_mimo"
    return "lte_scell"


def _cell_label(event: str, system: int | None, cell_index: int) -> str:
    """Libellé NFF 2.50 du cell_index projeté, par (event, system)."""
    source = cell_source_for_index(cell_index)
    encoded_source = source is not None
    occurrence = 0
    if source is not None:
        system, cell_index, occurrence = source
    def with_occurrence(label: str) -> str:
        return f"{label} #{occurrence + 1}" if occurrence else label
    if system == 9:
        if cell_index == 0:
            return with_occurrence("PCell")
        if 1 <= cell_index <= 31:
            return with_occurrence(f"SCell {cell_index}")
        if 100 <= cell_index <= 131:
            return with_occurrence(f"SCG SCell {cell_index - 100}")
        if cell_index == 199:
            return with_occurrence("SCG PSCell")
        label = {
            1000: "Listed NR neighbour",
            1001: "Detected NR neighbour",
            1002: "Scanner NR neighbour",
        }.get(cell_index, f"cell_index={cell_index}")
        return with_occurrence(label)
    if event == "CELLMEAS":
        # Decoder 1.8.1 normalized LTE raw 10..40 to 1..31.  Keep those
        # historical captures readable while 1.8.2 exposes raw 1/2 as the
        # distinct Listed/Detected enum through its encoded index.
        if not encoded_source:
            return "Serving" if cell_index == 0 else f"SCell {cell_index}"
        if cell_index == 0:
            label = "Serving"
        elif cell_index == 1:
            label = "Listed LTE neighbour"
        elif cell_index == 2:
            label = "Detected LTE neighbour"
        elif 10 <= cell_index <= 40:
            label = f"SCell {cell_index - 9}"
        else:
            label = f"cell_index={cell_index}"
        return with_occurrence(label)
    if event == "MIMOMEAS":
        if cell_index == 0:
            return with_occurrence("Serving")
        if 10 <= cell_index <= 40:
            return with_occurrence(f"SCell {cell_index - 9}")
    label = "PCell" if cell_index == 0 else f"SCell {cell_index}"
    return with_occurrence(label)


def cell_display(event: str, cell_index: int) -> dict[str, Any]:
    """Stable public display metadata for a projected cell.

    The numeric ``cell_index`` is a storage key only.  Its 1.8.2 inverse is
    authoritative for the radio system and raw NFF enum value.
    """
    source = cell_source_for_index(cell_index)
    system, raw, occurrence = source if source is not None else (None, cell_index, 0)
    return {
        "label": _cell_label(event, system, cell_index),
        "system": {7: "LTE", 9: "NR"}.get(system),
        "raw_cell_type": raw,
        "occurrence": occurrence,
        "internal_index": cell_index,
    }


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


def _cell_index_counts_per_project(
    db: Session,
    project_id: str,
    event_columns: dict[str, set[str]],
) -> dict[tuple[str, int | None, int, str], int]:
    """Compte les projections réellement sélectionnables.

    `nmf_cell_second` est l'autorité pour `(metric_code, cell_index)`. Le
    système est repris du bucket Light ayant le même `(project_id,
    capture_id, seq_first, event_code)`. `nmf_event_light_native` est inclus
    comme stockage physique du mode Light sparse. La jointure ne dépend
    jamais de `ts`.
    """
    out: dict[tuple[str, int | None, int, str], int] = {}
    for event, columns in event_columns.items():
        safe = sorted(c for c in columns if c.replace("_", "").isalnum())
        if not safe:
            continue
        rows = db.execute(text("""
            WITH light_system AS (
                SELECT project_id, capture_id, seq, event_code, system
                FROM nmf_event_light
                UNION
                SELECT project_id, capture_id, seq, event_code, system
                FROM nmf_event_light_native
            )
            SELECT s.event_code, l.system, s.cell_index, s.metric_code,
                   COUNT(DISTINCT (s.capture_id, s.second)) AS n
            FROM nmf_cell_second s
            LEFT JOIN light_system l
              ON l.project_id=s.project_id
             AND l.capture_id=s.capture_id
             AND l.seq=s.seq_first
             AND l.event_code=s.event_code
            WHERE s.project_id=:pid AND s.event_code=:event
              AND s.metric_code=ANY(:columns) AND s.value IS NOT NULL
              AND s.cell_index >= 0
            GROUP BY s.event_code, l.system, s.cell_index, s.metric_code
        """), {"pid": project_id, "event": event, "columns": safe}).mappings()
        for row in rows:
            system = int(row["system"]) if row["system"] is not None else None
            out[(row["event_code"], system, int(row["cell_index"]),
                 row["metric_code"])] = int(row["n"] or 0)
    return out


def _event_col_total(
    db: Session,
    project_id: str,
    event_code: str,
    col: str,
    avail_light_cols: set[str],
    avail_group_cols: set[str],
) -> int:
    """Nombre de secondes projetées pour `(event, metric_code)`.

    Une feuille cellule n'est consommable que via `nmf_cell_second`; sa
    conservation se vérifie donc sur cette table, pas sur le champ Light brut.
    """
    if not col or not col.replace("_", "").isalnum():
        return 0
    return int(db.execute(text("""
        SELECT COUNT(DISTINCT (capture_id, second, cell_index))
        FROM nmf_cell_second
        WHERE project_id=:pid AND event_code=:ev AND metric_code=:col
          AND value IS NOT NULL AND cell_index >= 0
    """), {"pid": project_id, "ev": event_code, "col": col}).scalar() or 0)


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

    # 1.a) 2.56.0 — disponibilité par cell_index projeté. Le champ Light
    # brut sert à documenter l'événement ; la sélection est consommée dans
    # nmf_cell_second et doit donc être comptée dans cette même table.
    cell_scoped_events: set[str] = {
        (n.get("event") or "").lstrip("#")
        for n in nodes_in
        if n.get("node_type") == "event" and n.get("cell_scoped")
    }
    event_columns: dict[str, set[str]] = defaultdict(set)
    for lf in displayed_leaves:
        if lf.get("cell_type") is None:
            continue
        ev = (lf.get("event") or "").lstrip("#")
        if ev not in cell_scoped_events:
            continue
        col = _column_for_leaf(lf)
        if not col or col not in avail_cols:
            continue
        event_columns[ev].add(col)
    cell_index_counts = _cell_index_counts_per_project(db, project_id, event_columns)

    def _n_per_cell(ev: str, ct: int, col: str) -> int:
        return sum(
            nn for (event, _system, cell, metric), nn in cell_index_counts.items()
            if event == ev and cell == ct and metric == col
        )

    def _systems_per_cell(ev: str, ct: int, col: str) -> list[int | None]:
        return sorted(
            (system for (event, system, cell, metric), nn in cell_index_counts.items()
             if event == ev and cell == ct and metric == col and nn > 0),
            key=lambda value: (value is None, value if value is not None else 0),
        )

    def _label_per_cell(ev: str, ct: int, col: str, fallback: str) -> str:
        systems = _systems_per_cell(ev, ct, col)
        labels = list(dict.fromkeys(_cell_label(ev, system, ct) for system in systems))
        return " / ".join(labels) if labels else fallback

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
        metric_label = lf.get("label") or metric_id
        metric_cells: list[int] = []
        metric_cell_options: list[dict] = []
        is_cell_metric = lf.get("cell_type") is not None
        if is_cell_metric:
            field_name = metric_label.split(" @ ", 1)[0]
            cell_index = int(lf["cell_type"])
            cell_label = _label_per_cell(
                event, cell_index, col, lf.get("cell_label") or str(cell_index)
            )
            metric_label = f"{field_name} @ {cell_label}"
            metric_cells = [cell_index]
            metric_cell_options = [{
                "cell": str(cell_index), "label": cell_label,
                "n_in_project": n, "available": True, "reason": None,
            }]
        cat_label = (
            _category_label(nodes_by_id, lf.get("parent_id")) or "Undocumented"
        )
        metrics_out.append(
            dict(
                code=code,
                label=metric_label,
                unit=lf.get("unit") or "",
                source_table="nmf_cell_second" if is_cell_metric else "nmf_event_light",
                source_tables=["nmf_cell_second"] if is_cell_metric else ["nmf_event_light"],
                source_column=col if has_col else "",
                tech="BOTH",
                kind=_kind_from_type(lf.get("type")),
                n_in_project=n,
                decoder_version=DECODER_VERSION,
                event=event,
                category_label=cat_label,
                cell_scoped=is_cell_metric,
                cells=metric_cells,
                cell_options=metric_cell_options,
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
        label_val = node.get("label") or ""
        if is_leaf and ct_node is not None:
            field_name = label_val.split(" @ ", 1)[0]
            ev_lf = (node.get("event") or "").lstrip("#")
            cell_label = _label_per_cell(
                ev_lf, int(ct_node), col or "", node.get("cell_label") or str(ct_node)
            )
            label_val = f"{field_name} @ {cell_label}"
        nodes_out.append(
            dict(
                node_id=node["node_id"],
                parent_id=parent_id,
                order=order,
                label=label_val,
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
    human_field_by_col: dict[tuple[str, int | None, str], str] = {}
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
        field_system = lf.get("field_system")
        human_field_by_col.setdefault((ev_lf, field_system, sc), field_name)

    def _field_name_for(ev: str, ct: int, col: str) -> str:
        source = cell_source_for_index(ct)
        system = source[0] if source is not None else None
        return (human_field_by_col.get((ev, system, col))
                or human_field_by_col.get((ev, None, col)) or col)

    baked_cells = {
        ((lf.get("event") or "").lstrip("#"), int(lf["cell_type"]),
         _column_for_leaf(lf))
        for lf in displayed_leaves if lf.get("cell_type") is not None
    }
    observed_cells: dict[tuple[str, int, str], int] = defaultdict(int)
    for (ev, _system, ct, col), nn in cell_index_counts.items():
        observed_cells[(ev, ct, col)] += nn
    dynamic_entries = sorted(
        (ev, ct, col, nn)
        for (ev, ct, col), nn in observed_cells.items()
        if nn > 0 and (ev, ct, col) not in baked_cells
    )
    for ev, ct, col, nn in dynamic_entries:
        ev_nid = event_node_by_code.get(ev)
        if not ev_nid:
            continue
        field_name = _field_name_for(ev, ct, col)
        label_from_enum = _label_per_cell(ev, ct, col, f"cell_index={ct}")
        label_full = f"{field_name} @ {label_from_enum}"
        node_id = f"lf_observed_{ev.lower()}_{ct}_{col}"
        selection = f"{col}@{ct}"
        parent_id = ev_nid
        order = siblings_counter.get(parent_id, 0)
        siblings_counter[parent_id] = order + 1
        nodes_out.append(
            dict(
                node_id=node_id,
                parent_id=parent_id,
                order=order,
                label=label_full,
                note="Cellule observée dans nmf_cell_second",
                source=None,
                node_type="leaf",
                metric_id=selection,
                selection=selection,
                event=ev,
                field_idx=None,
                source_column=col,
                unit="",
                cell=None,
                n=int(nn),
                proof="observed-cell-second",
                selectable=True,
                reason=None,
            )
        )
        if selection not in seen_codes:
            seen_codes.add(selection)
            cat_label = _category_label(nodes_by_id, ev_nid) or "Undocumented"
            metrics_out.append(dict(
                code=selection, label=label_full, unit="",
                source_table="nmf_cell_second", source_tables=["nmf_cell_second"],
                source_column=col, tech="BOTH", kind="numeric",
                n_in_project=int(nn), decoder_version=DECODER_VERSION,
                event=ev, category_label=cat_label, cell_scoped=True,
                cells=[ct], cell_options=[{
                    "cell": str(ct), "label": label_from_enum,
                    "n_in_project": int(nn), "available": True, "reason": None,
                }], attributes=[], proof="observed-cell-second", available=True,
                reason=None, alias_of=None, event_group=None,
                unproven_cells=[], root_notices=[], event_code=ev,
                proof_ref="nmf_cell_second + nmf_event_light.system",
                category=cat_label.lower().replace(" ", "_"),
            ))

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
