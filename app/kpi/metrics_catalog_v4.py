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
import re
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


def _cell_label_for_type(event: str, system: int | None, cell_type: int) -> str:
    """Public NFF label for a semantic cell type, never a storage index."""
    if system == 9:
        if cell_type == 0:
            return "PCell"
        if 1 <= cell_type <= 31:
            return f"SCell {cell_type}"
        if 100 <= cell_type <= 131:
            return f"SCG SCell {cell_type - 100}"
        if cell_type == 199:
            return "SCG PSCell"
        return {
            1000: "Listed NR neighbour",
            1001: "Detected NR neighbour",
            1002: "Scanner NR neighbour",
        }.get(cell_type, f"NR cell type {cell_type}")
    if event == "CELLMEAS":
        if cell_type == 0:
            return "Serving"
        if cell_type == 1:
            return "Listed LTE neighbour"
        if cell_type == 2:
            return "Detected LTE neighbour"
        if 10 <= cell_type <= 40:
            return f"SCell {cell_type - 9}"
        return f"LTE cell type {cell_type}"
    if event == "MIMOMEAS":
        if cell_type == 0:
            return "Serving"
        if 10 <= cell_type <= 40:
            return f"SCell {cell_type - 9}"
    # L3 — raw cell_type > 40 n'est pas documenté comme SCell LTE dans NFF 2.50.
    # Les valeurs 100, 199, 1000-1002 sont des enums NR (SCG SCell / SCG PSCell /
    # Listed/Detected/Scanner neighbour) et ne doivent pas être étiquetées
    # "SCell N" côté LTE. On les expose comme "LTE cell type N" (= UNKNOWN label
    # explicite), sans toucher aux valeurs RF projetées ni au sélecteur API.
    if system == 7 and (cell_type < 0 or cell_type > 40):
        return f"LTE cell type {cell_type}"
    return "PCell" if cell_type == 0 else f"SCell {cell_type}"


def cell_type_selector(system: int | None, cell_type: int) -> str:
    """Stable API selector for an enum member; intentionally not an index."""
    return f"{'nr' if system == 9 else 'lte'}-type-{cell_type}"


def parse_cell_type_selector(value: str) -> tuple[int, int] | None:
    prefix, marker, raw = value.partition("-type-")
    if not marker or prefix not in {"lte", "nr"}:
        return None
    try:
        cell_type = int(raw)
    except ValueError:
        return None
    return (9 if prefix == "nr" else 7), cell_type


def cell_type_display(event: str, system: int, raw: int) -> dict[str, Any]:
    """Stable public metadata for one enum member, independent of occurrence."""
    return {
        "label": _cell_label_for_type(event, system, raw),
        "system": {7: "LTE", 9: "NR"}.get(system),
        "raw_cell_type": raw,
    }


def _cell_role_for_tree(event: str, system: int | None, raw: int) -> str:
    """Cell role shown by the Analytics tree.

    This is based on the event's documented enum member.  It deliberately
    does not use ``cell_index`` (an internal occurrence key) or PCI/ARFCN (a
    physical identity).  CELLMEAS LTE type 0 is the primary serving cell in
    this tree; types 1/2 remain neighbours and are never mislabeled SCells.
    """
    if system == 7 and event in {'CELLMEAS', 'MIMOMEAS'} and raw == 0:
        return 'PCell'
    label = _cell_label_for_type(event, system, raw)
    return 'PSCell' if label == 'SCG PSCell' else label


def _cell_relation_for_tree(event: str, system: int | None, raw: int) -> str | None:
    """Return the documented RF relation, never inferred from a label.

    L1 — étendu aux événements RF-cell-scopés qui héritent de la même
    convention cell_type que CELLMEAS :
        - MIMOMEAS : mesure MIMO par cellule, enum identique
        - CSI, PMI : mesures canal par cellule, enum identique
        - PHRATE, PHRATEU : power headroom par cellule

    Les événements liés à la couche connexion/transport (DCI, MACRATE,
    MACRATEU, TXPC, PLAID, PLAIU, SCELL, SCELLMOD, CQI, CI, TAD)
    conservent ``None`` : leur sémantique serving/neighbour n'est pas
    certifiée au niveau cellule par Nemo NFF 2.50 et n'est pas déduite
    du libellé de la cellule.
    """
    rf_cell_scoped_events = {"CELLMEAS", "MIMOMEAS", "CSI", "PMI", "PHRATE", "PHRATEU"}
    if event not in rf_cell_scoped_events:
        return None
    if (system == 7 and raw in {1, 2}) or (
        system == 9 and raw in {1000, 1001, 1002}
    ):
        return "neighbour"
    if (system == 7 and (raw == 0 or 10 <= raw <= 40)) or (
        system == 9 and (raw == 0 or 1 <= raw <= 31 or 100 <= raw <= 131 or raw == 199)
    ):
        return "serving"
    return None


def _technical_cell_label(
    technology: str | None,
    relation: str | None,
    metric: str | None,
    cell: str | None,
) -> str | None:
    """Stable display aid; canonical metric selectors remain unchanged."""
    if not technology or not relation or not metric or not cell:
        return None
    relation_token = "Serving" if relation == "serving" else "Neighbor"
    clean = lambda value: re.sub(r"[^A-Za-z0-9]+", "", value)
    return "_".join((clean(technology), relation_token, clean(metric), clean(cell)))


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
    db: Session,
    project_id: str,
    columns: set[str],
    capture_ids: tuple[str, ...] = (),
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
        scope = " AND capture_id=ANY(:capture_ids)" if capture_ids else ""
        sql = f"SELECT {expr} FROM nmf_event_light WHERE project_id=:pid{scope}"
        params = {"pid": project_id, "capture_ids": list(capture_ids)}
        row = db.execute(text(sql), params).first()
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
        scope = " AND capture_id=ANY(:capture_ids)" if capture_ids else ""
        sql = f"SELECT {expr} FROM nmf_event_light_group WHERE project_id=:pid{scope}"
        params = {"pid": project_id, "capture_ids": list(capture_ids)}
        row = db.execute(text(sql), params).first()
        if row is None:
            continue
        for idx, c in enumerate(chunk):
            out[c] = max(out[c], int(row[idx] or 0))
    return out


def _cell_index_counts_per_project(
    db: Session,
    project_id: str,
    event_columns: dict[str, set[str]],
    capture_ids: tuple[str, ...] = (),
) -> dict[tuple[str, int | None, int, str], int]:
    """Compte les projections réellement sélectionnables.

    `nmf_cell_second` est l'autorité pour `(metric_code, cell_index)`. Le
    système est repris du bucket Light ayant le même `(project_id,
    capture_id, seq_first, event_code)`. `nmf_event_light_native` est inclus
    comme stockage physique du mode Light sparse. La jointure ne dépend
    jamais de `ts`.
    """
    out: dict[tuple[str, int | None, int, str], int] = defaultdict(int)
    for event, columns in event_columns.items():
        safe = sorted(c for c in columns if c.replace("_", "").isalnum())
        if not safe:
            continue
        capture_scope = " AND s.capture_id=ANY(:capture_ids)" if capture_ids else ""
        if event == "CELLMEAS":
            # Exact parity with Dataset._load_semantic_cell: one exploitable
            # point per (seq, physical identity), after the same authoritative
            # nmf_cell_identity join.  Summing storage occurrences inflated
            # PCell/SCell counts and made the tree disagree with Graph/Table.
            query = """
                SELECT s.event_code, i.system, i.cell_type AS raw_cell_type,
                       s.metric_code,
                       COUNT(DISTINCT (s.capture_id,s.seq_first,
                                             i.cell_arfcn,i.cell_pci)) AS n
                FROM nmf_cell_second s
                JOIN nmf_cell_identity i
                  ON i.project_id=s.project_id AND i.capture_id=s.capture_id
                 AND i.seq=s.seq_first AND i.event_code=s.event_code
                 AND i.cell_index=s.cell_index
                 AND i.decoder_version=s.decoder_version
                WHERE s.project_id=:pid AND s.event_code=:event
                  {capture_scope}
                  AND s.metric_code=ANY(:columns) AND s.value IS NOT NULL
                  AND s.cell_index >= 0
                GROUP BY s.event_code,i.system,i.cell_type,s.metric_code
            """
        else:
            query = """
                SELECT s.event_code,NULL::integer AS system,
                       s.cell_index,s.metric_code,COUNT(*) AS n
                FROM nmf_cell_second s
                WHERE s.project_id=:pid AND s.event_code=:event
                  {capture_scope}
                  AND s.metric_code=ANY(:columns) AND s.value IS NOT NULL
                  AND s.cell_index >= 0
                GROUP BY s.event_code,s.cell_index,s.metric_code
            """
        rows = db.execute(text(query.format(capture_scope=capture_scope)), {
            "pid": project_id,
            "event": event,
            "columns": safe,
            "capture_ids": list(capture_ids),
        }).mappings()
        for row in rows:
            if event == "CELLMEAS":
                source_system = int(row["system"])
                raw = int(row["raw_cell_type"])
            else:
                index = int(row["cell_index"])
                source = cell_source_for_index(index)
                source_system, raw, _occurrence = (
                    source if source is not None else (None, index, 0)
                )
            # The enum member is public identity. Occurrence is only the
            # storage discriminator needed by nmf_cell_second's primary key.
            out[(row["event_code"], source_system, raw,
                 row["metric_code"])] += int(row["n"] or 0)
    return dict(out)


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


def _is_physical_neighbour(event: str, system: int | None, cell_type: int) -> bool:
    """True only for NFF CELLMEAS enum members that represent neighbours."""
    return event == "CELLMEAS" and (
        (system == 7 and cell_type in {1, 2})
        or (system == 9 and cell_type in {1000, 1001, 1002})
    )


def _physical_neighbour_counts(
    db: Session,
    project_id: str,
    metric_codes: set[str],
    capture_ids: tuple[str, ...] = (),
) -> dict[tuple[str, int, int, str], list[tuple[int, int, int]]]:
    """Return series-point counts by real radio cell for catalog leaves.

    The metric projection remains authoritative for the value.  Its local
    occurrence key is joined to ``nmf_cell_identity`` at the exact canonical
    sequence; public grouping is then solely ``(system, ARFCN, PCI)``.
    """
    safe = sorted(code for code in metric_codes if code.replace("_", "").isalnum())
    if not safe:
        return {}
    capture_scope = " AND s.capture_id=ANY(:capture_ids)" if capture_ids else ""
    rows = db.execute(text("""
        SELECT s.event_code,i.system,i.cell_type,s.metric_code,
               i.cell_arfcn,i.cell_pci,
               COUNT(DISTINCT (s.capture_id,s.seq_first))::bigint AS n
        FROM nmf_cell_second s
        JOIN nmf_cell_identity i
          ON i.project_id=s.project_id AND i.capture_id=s.capture_id
         AND i.seq=s.seq_first AND i.event_code=s.event_code
         AND i.cell_index=s.cell_index
         AND i.decoder_version=s.decoder_version
        WHERE s.project_id=:pid AND s.event_code='CELLMEAS'
          {capture_scope}
          AND s.metric_code=ANY(:metrics) AND s.value IS NOT NULL
          AND ((i.system=7 AND i.cell_type IN (1,2))
            OR (i.system=9 AND i.cell_type IN (1000,1001,1002)))
          AND i.cell_arfcn IS NOT NULL AND i.cell_pci IS NOT NULL
        GROUP BY s.event_code,i.system,i.cell_type,s.metric_code,
                 i.cell_arfcn,i.cell_pci
        ORDER BY s.event_code,i.system,i.cell_type,s.metric_code,
                 i.cell_arfcn,i.cell_pci
    """.format(capture_scope=capture_scope)), {
        "pid": project_id,
        "metrics": safe,
        "capture_ids": list(capture_ids),
    }).mappings()
    out: dict[tuple[str, int, int, str], list[tuple[int, int, int]]] = defaultdict(list)
    for row in rows:
        out[(row["event_code"], int(row["system"]), int(row["cell_type"]),
             row["metric_code"])].append(
            (int(row["cell_arfcn"]), int(row["cell_pci"]), int(row["n"]))
        )
    return dict(out)


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


def _root_technology(nodes_by_id: dict, node: dict) -> str | None:
    system = node.get('field_system')
    if system == 7:
        return 'LTE'
    if system == 9:
        return 'NR'
    current = node
    seen: set[str] = set()
    while current and current.get('node_id') not in seen:
        seen.add(current.get('node_id'))
        if current.get('node_type') == 'tech':
            label = str(current.get('label') or '').strip()
            return 'EN-DC' if label.upper() == 'ENDC' else label or None
        current = nodes_by_id.get(current.get('parent_id'))
    return None


def _tree_metric_label(label: str) -> str:
    value = label.split(' @ ', 1)[0].strip()
    # Technology is already the parent.  Strip only an exact trailing marker;
    # semantic names such as SS-RSRP are preserved.
    return re.sub(r'\s+\((?:LTE|NR|EN-DC)\)$', '', value, flags=re.IGNORECASE)


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
    db: Session,
    project_id: str,
    current: CurrentCatalog,
    *,
    capture_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build the /metrics payload from `catalog_release.is_current` JSON.

    Payload shape matches `MetricCatalogResponse` with the envelope fields
    `catalog_release`, `decoder_version`, `reason` added.
    """
    catalog = load_catalog_json(current.version)
    nodes_in = catalog["nodes"]
    nodes_by_id = {n["node_id"]: n for n in nodes_in}
    analytics_policy = catalog.get("analytics_classification_policy", {})
    analytics_fallback = analytics_policy.get("fallback", "metrics")
    message_measurement_tab = analytics_policy.get(
        "message_measurement_tab", analytics_fallback
    )
    removed_series = {
        decision["code"]
        for decision in catalog.get("analytics_series_decisions", [])
        if decision.get("visible") is False
    }

    def _series_code(leaf: dict) -> str:
        col = _column_for_leaf(leaf) or leaf.get("metric_id") or ""
        if leaf.get("cell_type") is None:
            return col
        return f"{col}@{cell_type_selector(_leaf_system(leaf), int(leaf['cell_type']))}"

    def _series_visible(event: str, code: str) -> bool:
        # /metrics/series resolves a code without event discriminator. A
        # catalog decision therefore removes that code from every branch;
        # ``event`` remains recorded in the decision for audit provenance.
        return code not in removed_series

    def _leaf_system(leaf: dict) -> int | None:
        value = leaf.get("field_system")
        return int(value) if value is not None else None

    # Lot 3 — drop les placeholders hérités de l'oracle sur des cell_types
    # qui n'existent QUE pour NR (100..131=SCG SCell N, 199=SCG PSCell,
    # 1000/1001/1002=Listed/Detected/Scanner NR neighbour, NFF 2.50 p.561-562).
    # Avant catalog_release 2.63.0 ces cell_types étaient émis AUSSI pour
    # field_system None/7 (LTE), avec cell_label "SCell 100" / "SCell 199" /
    # "SCell 1000" etc. et n=0 : 2 405 feuilles fantômes sur 9 001. Les NR
    # réels (field_system=9) sont conservés : 110 feuilles légitimes.
    _NR_ONLY_CELL_TYPES = {100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
                            110, 111, 112, 113, 114, 115, 116, 117, 118, 119,
                            120, 121, 122, 123, 124, 125, 126, 127, 128, 129,
                            130, 131, 198, 199, 1000, 1001, 1002}
    def _is_ghost_nr_placeholder(n: dict) -> bool:
        ct = n.get("cell_type")
        if ct is None or ct not in _NR_ONLY_CELL_TYPES:
            return False
        return n.get("field_system") != 9
    # Lot 5 — classer chaque leaf en {KPI, KPI_CATEGORICAL, DIMENSION, STRUCT}
    # d'après le `label`/`metric_label`/`metric_id`. STRUCT = sortis de l'arbre
    # (ne sont pas des mesures mais des compteurs/dimensions internes du schéma
    # NFF : #Params, #Variables, Count, Measured system, LTE_CQI_N_PARAMS_*).
    _STRUCT_PAT = (
        "#params", "#variables", "measured system",
    )
    _CATEG_PAT = ("rank", "modulation", "dci format", "rrc state")
    _DIM_PAT = ("pci", "arfcn", "nr-arfcn", "band", "port", "bwp id")
    def _kind_for_leaf(n: dict) -> str:
        label = (n.get("label") or "").lower()
        mlabel = (n.get("metric_label") or "").lower()
        mid = (n.get("metric_id") or "").lower()
        src = (n.get("source_column") or "").lower()
        joined = f"{label}|{mlabel}|{mid}|{src}"
        # STRUCT ciblé : compteurs/paramètres structurels NFF uniquement.
        # #PRBs, #SCells added, #Ranks, #RSRP results etc. sont des KPI/
        # dimensions DATA, pas des structs. Les vrais structs ont des codes
        # finissant par `_n_params`, `_params_*`, `_n_variables`, `cqi_n_params`.
        # Les labels "#Params…" / "#Variables" / "#Header params" sont les
        # seuls hash-prefix qui sont vraiment structurels.
        _STRUCT_LABEL = (
            "#params", "#variables", "#header params",
        )
        if any(label.startswith(p) or mlabel.startswith(p) for p in _STRUCT_LABEL):
            return "STRUCT"
        if "cqi_n_params" in mid or any(p in label or p in mlabel for p in _STRUCT_PAT):
            return "STRUCT"
        # Count field under a group counts samples : STRUCT
        if (mlabel == "count" or label.startswith("count ")) and n.get("source_column"):
            return "STRUCT"
        if any(p in mlabel or p in label for p in _CATEG_PAT) or "rrc_state" in src:
            return "KPI_CATEGORICAL"
        if any(p in mlabel or p in label for p in _DIM_PAT) or src.endswith("_pci") or src.endswith("_ch") or src.endswith("_band") or src.endswith("_arfcn") or src.endswith("_port"):
            return "DIMENSION"
        return "KPI"

    # Lot 4 (patch 2.63.1) — bloc étranger : drop UNIQUEMENT les feuilles
    # dont `field_system` est explicitement un système étranger (NFF
    # measured_system codes). Les feuilles multi-system (field_system=None)
    # sont CONSERVÉES — leur label "(bloc X)" est un marqueur de section
    # NFF mais la feuille porte des valeurs réelles pour LTE/NR (ex.
    # `mei_measurement_event` = 15 valeurs ikea.6).
    # Codes NFF measured_system : 1=GSM, 2=TETRA, 5=UMTS FDD, 6=UMTS TD-SCDMA,
    # 7=LTE FDD, 8=LTE TDD, 9=NR, 10=cdmaOne, 11=CDMA 1x, 12=EVDO, 13=DVB-H,
    # 21=GAN WLAN, 25=WiMAX, 51/52/53/55=AMPS/NAMPS/DAMPS/iDEN.
    _FOREIGN_SYSTEM_IDS = {1, 2, 5, 6, 10, 11, 12, 13, 21, 25, 51, 52, 53, 55}
    def _is_foreign_bloc(n: dict) -> bool:
        fs = n.get('field_system')
        if fs is None:
            return False
        try:
            return int(fs) in _FOREIGN_SYSTEM_IDS
        except (TypeError, ValueError):
            return False

    # Lot 4 — MIMOMEAS/CSI/PMI sur voisines : ces events n'ont pas de sens
    # sur les cellules voisines (NFF 2.50 : events par cellule serving).
    def _is_mimo_csi_on_neighbour(n: dict) -> bool:
        ev = (n.get('event') or '').upper()
        cl = (n.get('cell_label') or '')
        return ev in {'MIMOMEAS', 'CSI', 'PMI'} and 'neighbour' in cl.lower()

    displayed_leaves = []
    for n in nodes_in:
        if n.get("node_type") != "leaf":
            continue
        if not n.get("displayed"):
            continue
        if not _series_visible(n.get("event") or "", _series_code(n)):
            continue
        if _is_ghost_nr_placeholder(n):
            continue
        if _is_foreign_bloc(n):
            continue  # Lot 4 — bloc étranger drop
        if _is_mimo_csi_on_neighbour(n):
            continue  # Lot 4 — MIMOMEAS/CSI/PMI non-serving
        kind = _kind_for_leaf(n)
        n["_kind"] = kind
        if kind == "STRUCT":
            continue  # Lot 5 — STRUCT hors de l'arbre
        displayed_leaves.append(n)

    # 1) Map leaf → candidate column; keep only columns present in DB.
    avail_light_cols = _available_light_columns(db)
    avail_group_cols = _available_group_columns(db)
    avail_cols = avail_light_cols | avail_group_cols
    candidate_cols: set[str] = set()
    for lf in displayed_leaves:
        col = _column_for_leaf(lf)
        if col and col in avail_cols:
            candidate_cols.add(col)
    counts = _n_per_column(db, project_id, candidate_cols, capture_ids)

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
    # 2.63.3 (REPRISE 7 Lot 1 + écart Point 1) — étendre event_columns à
    # TOUTE colonne `cell_scoped=True` déclarée par `metrics_v3.definitions()`
    # dont l'event est cell_scoped. Fichier:ligne précédent qui bloquait :
    # cette boucle n'ingérait que les leaves baked, donc plaid_mcs0 /
    # plaiu_mcs0 / cqi_* NR / dci_* NR / scell_* NR / scellmod_* n'étaient
    # jamais interrogés dans nmf_cell_second → 0 feuille dynamique émise
    # malgré 1796/2/79 valeurs live sur NR PSCell 199.
    from app.kpi.metrics_v3 import definitions as _v3_defs
    # 2.64.1 — §3 enum RRC : accès direct aux YAML fields pour exposer
    # enum_values sur chaque leaf (ex. chi_rrc_state : {1:Idle, 2:Connected}).
    from app.nmf_decoder.schema import fields as _yaml_fields
    _fields_by_col = _yaml_fields()
    def _enum_for_col(col: str | None) -> dict:
        f = _fields_by_col.get(col) if col else None
        raw = (f or {}).get("enum")
        if not isinstance(raw, dict) or not raw:
            # Les enums-listes (ex. ci_port=[0,1]) sont de simples
            # domaines, pas des mappings value->label — rien à exposer.
            return {}
        out = {}
        for k, v in raw.items():
            try:
                out[int(k)] = v
            except (TypeError, ValueError):
                out[k] = v
        return out
    for code, defn in _v3_defs().items():
        if not defn.get("cell_scoped"):
            continue
        ev = (defn.get("event") or "").lstrip("#")
        if ev not in cell_scoped_events:
            continue
        col = defn.get("source_column") or code
        if col in avail_cols:
            event_columns[ev].add(col)
    cell_index_counts = _cell_index_counts_per_project(
        db, project_id, event_columns, capture_ids
    )

    def _n_per_cell(ev: str, system: int | None, ct: int, col: str) -> int:
        return sum(
            nn for (event, observed_system, raw, metric), nn in cell_index_counts.items()
            if event == ev and observed_system == system and raw == ct and metric == col
        )

    def _label_per_type(ev: str, system: int | None, ct: int, fallback: str) -> str:
        return _cell_label_for_type(ev, system, ct) if system in {7, 9} else fallback

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
                n = _n_per_cell(ev_lf, _leaf_system(lf), int(ct_leaf), col) if has_col else 0
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
        cell_suffix = (
            f"@{cell_type_selector(_leaf_system(lf), int(lf['cell_type']))}"
            if lf.get("cell_type") is not None else ""
        )
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
            raw_cell_type = int(lf["cell_type"])
            system = _leaf_system(lf)
            cell_label = _label_per_type(
                event, system, raw_cell_type, lf.get("cell_label") or str(raw_cell_type)
            )
            metric_label = f"{field_name} @ {cell_label}"
            selector = cell_type_selector(system, raw_cell_type)
            metric_cells = [raw_cell_type]
            metric_cell_options = [{
                "cell": selector, "label": cell_label,
                "n_in_project": n, "available": True, "reason": None,
            }]
        cat_label = (
            _category_label(nodes_by_id, lf.get("parent_id")) or "Undocumented"
        )
        # 2.64.1 §1 — fallback unit depuis v3_defs si leaf.unit vide. Le
        # YAML du décodeur porte souvent unit=null bien que metrics_v3
        # expose une unit (ex. cell_band='code', cell_ch='earfcn').
        _baked_unit = (lf.get("unit") or "").strip()
        if not _baked_unit:
            _baked_unit = (_v3_defs().get(col) or {}).get("unit") or ""
        metrics_out.append(
            dict(
                code=code,
                label=metric_label,
                unit=_baked_unit,
                source_table="nmf_cell_second" if is_cell_metric else "nmf_event_light",
                source_tables=["nmf_cell_second"] if is_cell_metric else ["nmf_event_light"],
                source_column=col if has_col else "",
                tech="BOTH",
                # 2.64.1 — §2 : aligner metrics[] sur l'arbre : taxonomie
                # KPI / KPI_CATEGORICAL / DIMENSION / STRUCT (chi_rrc_state
                # devient KPI_CATEGORICAL ici au lieu de 'numeric' legacy).
                kind=lf.get("_kind") or _kind_from_type(lf.get("type")),
                enum_values=_enum_for_col(col) if has_col else {},
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
    # 2.66.1 (REPRISE 12 P1) — pré-pass : construire les events NR miroirs
    # pour les leaves baked avec field_system=9 dont le parent event est sous
    # LTE. Nécessaire pour que CELLMEAS NR (cell_rsrp, cell_rsrq, cell_sinr @
    # cell_type NR) remontent sous la branche NR dans le tree.
    _LTE_TO_NR_CAT = {
        "cat_LTE_serving_radio":      ("cat_NR_serving_radio",      "Serving radio"),
        "cat_LTE_allocation_mcs":     ("cat_NR_allocation_mcs",     "Allocation & MCS"),
        "cat_LTE_throughput_per_layer": ("cat_NR_throughput_per_layer", "Throughput per layer"),
        "cat_LTE_link_quality":       ("cat_NR_link_quality",       "Link quality"),
        "cat_LTE_signalling":         ("cat_NR_signalling",         "Signalling"),
        "cat_LTE_neighbours":         ("cat_NR_neighbours",         "Neighbours"),
        "cat_LTE_mimo_per_port":      ("cat_NR_mimo_per_port",      "MIMO per port"),
        "cat_LTE_carrier_aggregation":("cat_NR_carrier_aggregation","Carrier aggregation"),
        "cat_LTE_scanner":            ("cat_NR_scanner",            "Scanner"),
        "cat_LTE_ul_power":           ("cat_NR_ul_power",           "UL power"),
    }
    _tech_nr_id = None
    for n in nodes_in:
        if n.get("node_type") == "tech" and n.get("label") == "NR":
            _tech_nr_id = n.get("node_id")
            break
    _lte_to_nr_event: dict[str, str] = {}
    if _tech_nr_id:
        for lf in displayed_leaves:
            if lf.get("field_system") != 9:
                continue
            ev_parent_id = None
            cur_p = nodes_by_id.get(lf.get("parent_id"))
            if cur_p and cur_p.get("node_type") == "event":
                ev_parent_id = cur_p.get("node_id")
            if not ev_parent_id or ev_parent_id in _lte_to_nr_event:
                continue
            # Resolve parent cat of this event
            ev_node = nodes_by_id.get(ev_parent_id) or {}
            cat_lte_id = ev_node.get("parent_id")
            nr_info = _LTE_TO_NR_CAT.get(cat_lte_id)
            if not nr_info:
                continue
            nr_cat_id, nr_cat_label = nr_info
            # Insérer catégorie NR miroir si absente dans nodes_out
            if not any(x.get("node_id") == nr_cat_id for x in nodes_out):
                nodes_out.append(dict(
                    node_id=nr_cat_id, parent_id=_tech_nr_id, node_type="category",
                    label=nr_cat_label, order=0, event=None, source_column=None,
                    metric_id=None, display_code=None, cell=None, cell_label=None,
                    cell_system=None, technology="NR", unit="", analytics_tab=None,
                    availability_status=None, n=0, proof=None, selectable=False,
                    reason=None, kind=None,
                ))
            # Créer event NR miroir
            ev_nr_id = f"{ev_parent_id}_nr"
            ev_code = (ev_node.get("event") or ev_node.get("label") or "").lstrip("#")
            if not any(x.get("node_id") == ev_nr_id for x in nodes_out):
                nodes_out.append(dict(
                    node_id=ev_nr_id, parent_id=nr_cat_id, node_type="event",
                    label=ev_code, order=0, event=ev_code, source_column=None,
                    metric_id=None, display_code=None, cell=None, cell_label=None,
                    cell_system="NR", technology="NR", unit="", analytics_tab=None,
                    availability_status=None, n=0, proof=None, selectable=False,
                    reason=None, kind=None,
                ))
            _lte_to_nr_event[ev_parent_id] = ev_nr_id

    for node in nodes_in:
        if node["node_id"] not in keep_ids:
            continue
        parent_id = node.get("parent_id")
        # 2.66.1 — rediriger parent baked NR leaf vers NR event miroir
        if node.get("node_type") == "leaf" and node.get("field_system") == 9:
            nr_target = _lte_to_nr_event.get(parent_id)
            if nr_target:
                parent_id = nr_target
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
                n_val = _n_per_cell(ev_lf, _leaf_system(node), int(ct_node), col) if has_col else 0
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
            cell_suffix = (
                f"@{cell_type_selector(_leaf_system(node), int(ct_node))}"
                if ct_node is not None else ""
            )
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
        technology_val = _root_technology(nodes_by_id, node) if is_leaf else None
        metric_label_val = _tree_metric_label(label_val) if is_leaf else None
        cell_selector_val = None
        cell_label_val = None
        cell_system_val = None
        raw_cell_type_val = None
        cell_relation_val = None
        technical_label_val = None
        if is_leaf and ct_node is not None:
            field_name = label_val.split(" @ ", 1)[0]
            ev_lf = (node.get("event") or "").lstrip("#")
            raw_cell_type_val = int(ct_node)
            cell_selector_val = cell_type_selector(_leaf_system(node), raw_cell_type_val)
            cell_system_val = {7: "LTE", 9: "NR"}.get(_leaf_system(node))
            cell_label_val = _cell_role_for_tree(
                ev_lf, _leaf_system(node), raw_cell_type_val
            )
            cell_relation_val = _cell_relation_for_tree(
                ev_lf, _leaf_system(node), raw_cell_type_val
            )
            cell_label = _label_per_type(
                ev_lf, _leaf_system(node), int(ct_node), node.get("cell_label") or str(ct_node)
            )
            label_val = f"{field_name} @ {cell_label}"
            metric_label_val = _tree_metric_label(field_name)
            technical_label_val = _technical_cell_label(
                technology_val, cell_relation_val, metric_label_val, cell_label_val
            )
        if not is_leaf:
            availability_status = None
        elif not has_col:
            availability_status = "not_projected"
        elif n_val > 0:
            availability_status = "available"
        elif baked_sel is False:
            availability_status = "not_applicable"
        else:
            availability_status = "no_data"
        display_code_val = None
        if is_leaf:
            # 2.64.0 — Lot 6 : display_code UNIQUE par baked leaf. Deux leaves
            # avec `source_column` identique mais `metric_id` différent
            # (ex. dci_ul_grants@6 vs dci_ul_grants_f5@6, même `source_column`
            # `dci_ul_grants`) collideraient si on utilisait `selection`
            # (col@selector). On préfère `metric_id` qui est l'identité
            # baked unique par node ; `selection` reste utilisée côté table/graph.
            display_code_val = metric_id or (col and selection) or col
        nodes_out.append(
            dict(
                node_id=node["node_id"],
                parent_id=parent_id,
                order=order,
                label=label_val,
                display_code=display_code_val,
                enum_values=_enum_for_col(col) if is_leaf else {},
                note=node.get("description"),
                source=None,
                node_type=node.get("node_type"),
                # Compatibilité de livraison ordonnée : le code back est
                # déployable avant l'activation 2.57.0. Les releases plus
                # anciennes n'exposent que des feuilles Metrics sur cette
                # route ; 2.57.0 devient ensuite la source explicite.
                analytics_tab=(node.get("analytics_tab") or analytics_fallback) if is_leaf else None,
                metric_id=(selection if ct_node is not None and selection else metric_id),
                selection=selection,
                event=(node.get("event") or "").lstrip("#") if is_leaf else None,
                field_idx=field_idx,
                source_column=col if has_col else None,
                # 2.64.1 §1 — fallback unit depuis v3_defs si node.unit vide
                unit=(node.get("unit") or "").strip() or ((_v3_defs().get(col) or {}).get("unit") or "") if is_leaf else (node.get("unit") or ""),
                cell=cell_selector_val,
                technology=technology_val,
                metric_label=metric_label_val,
                cell_label=cell_label_val,
                cell_system=cell_system_val,
                raw_cell_type=raw_cell_type_val,
                cell_relation=cell_relation_val,
                technical_label=technical_label_val,
                availability_status=availability_status,
                n=n_val,
                proof=node.get("proof") or "open",
                selectable=selectable_flag,
                reason=reason_val,
                kind=node.get("_kind") if is_leaf else None,
            )
        )

    # 4.a) Real CELLMEAS neighbours. A repeated-set occurrence and its
    # PCI/ARFCN identity remain row details; the catalogue exposes one leaf
    # for the documented semantic neighbour role.
    node_input_by_id = {node["node_id"]: node for node in nodes_in}
    metrics_by_code = {metric["code"]: metric for metric in metrics_out}
    # Physical PCI/ARFCN identities are details of a semantic neighbour role,
    # not extra cells in the Technology -> Metric -> Cell catalogue.  Keep the
    # role leaf selectable and let Graph/Table expose physical identity in
    # their rows.  Expanding every observed neighbour here both confused the
    # two identities and made a capture switch rebuild thousands of leaves.
    physical_count_index: dict[
        tuple[str, int, int, str], list[tuple[int, int, int]]
    ] = {}
    replaced_metric_codes: set[str] = set()
    physical_metrics: list[dict] = []
    physical_nodes: list[dict] = []
    for parent in nodes_out:
        if parent.get("node_type") != "leaf" or not parent.get("selectable"):
            continue
        source = node_input_by_id.get(parent["node_id"], {})
        raw_cell_type = source.get("cell_type")
        system = _leaf_system(source)
        event = parent.get("event") or ""
        metric_code = parent.get("source_column") or ""
        if raw_cell_type is None or system is None or not metric_code:
            continue
        raw_cell_type = int(raw_cell_type)
        if not _is_physical_neighbour(event, system, raw_cell_type):
            continue
        base_selection = parent.get("selection")
        base_metric = metrics_by_code.get(base_selection or "")
        if not base_selection or base_metric is None:
            continue
        if base_selection in replaced_metric_codes:
            # Several NFF blocks may document the same decoded projection.
            # Only the first content-equivalent parent owns the real-cell
            # leaves; duplicating them would make one radio cell selectable
            # more than once.
            parent["selectable"] = False
            parent["selection"] = None
            parent["n"] = 0
            parent["reason"] = "Projection identique déjà exposée par cellule radio"
            continue
        identities = physical_count_index.get(
            (event, system, raw_cell_type, metric_code), []
        )
        if not identities:
            continue
        parent["selectable"] = False
        parent["selection"] = None
        parent["reason"] = "Sélection disponible dans les feuilles par cellule radio"
        parent["n"] = sum(n for _, _, n in identities)
        replaced_metric_codes.add(base_selection)
        for order, (arfcn, pci, count) in enumerate(identities):
            selection = f"{base_selection}!{arfcn}:{pci}"
            node_id = f"{parent['node_id']}__arfcn_{arfcn}__pci_{pci}"
            label = f"ARFCN {arfcn} · PCI {pci}"
            physical_nodes.append(dict(
                node_id=node_id,
                parent_id=parent["node_id"],
                order=order,
                label=label,
                note="Identité radio observée dans nmf_cell_identity",
                source=f"{event} · system={system} · cell_type={raw_cell_type}",
                node_type="leaf",
                analytics_tab="metrics",
                metric_id=selection,
                selection=selection,
                event=event,
                field_idx=parent.get("field_idx"),
                source_column=metric_code,
                unit=parent.get("unit") or "",
                cell=parent.get("cell"),
                technology=parent.get("technology"),
                metric_label=parent.get("metric_label"),
                cell_label=label,
                cell_system=parent.get("cell_system"),
                raw_cell_type=parent.get("raw_cell_type"),
                cell_relation="neighbour",
                technical_label=_technical_cell_label(
                    parent.get("technology"), "neighbour",
                    parent.get("metric_label"), label,
                ),
                availability_status="available",
                n=count,
                proof="physical-cell-identity",
                selectable=True,
                reason=None,
            ))
            physical_metrics.append(dict(
                base_metric,
                code=selection,
                label=f"{base_metric['label']} · ARFCN {arfcn} · PCI {pci}",
                n_in_project=count,
                proof="physical-cell-identity",
                proof_ref="nmf_cell_second + nmf_cell_identity",
            ))
    if replaced_metric_codes:
        metrics_out = [
            metric for metric in metrics_out
            if metric["code"] not in replaced_metric_codes
        ]
        metrics_out.extend(physical_metrics)
        nodes_out.extend(physical_nodes)

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
    # 2.63.3 — Fallback label depuis metrics_v3 pour colonnes non baked
    # (plaid_mcs0, cqi_sb_cqi_0, dci_dl_grants, scell_*, scellmod_*).
    for code, defn in _v3_defs().items():
        if not defn.get("cell_scoped"):
            continue
        ev = (defn.get("event") or "").lstrip("#")
        col = defn.get("source_column") or code
        label = defn.get("label") or code
        human_field_by_col.setdefault((ev, None, col), label)

    def _field_name_for(ev: str, system: int | None, col: str) -> str:
        return (human_field_by_col.get((ev, system, col))
                or human_field_by_col.get((ev, None, col)) or col)

    baked_cells = {
        ((lf.get("event") or "").lstrip("#"), _leaf_system(lf), int(lf["cell_type"]),
         _column_for_leaf(lf))
        for lf in displayed_leaves if lf.get("cell_type") is not None
    }
    # 2.64.0 (REPRISE 7 Lot 6) — un leaf baked avec `field_system=None`
    # (multi-system, ex. DCI avec cell_type=6 et pas de bloc tech explicite)
    # masque TOUTES les émissions dynamiques pour la même (event, cell_type,
    # col) peu importe le system observé — sinon display_code dupliqué entre
    # baked (sel.=`col@lte-type-N`) et dynamic (sel.=`col@lte-type-N`).
    baked_cells_no_sys = {
        (ev, ct, col) for (ev, sys_, ct, col) in baked_cells if sys_ is None
    }
    dynamic_entries = sorted(
        (ev, system, ct, col, nn)
        for (ev, system, ct, col), nn in cell_index_counts.items()
        if nn > 0
        and (ev, system, ct, col) not in baked_cells
        and (ev, ct, col) not in baked_cells_no_sys
        and _series_visible(ev, f"{col}@{cell_type_selector(system, ct)}")
    )
    # 2.66.1 (REPRISE 12 P1) — pour les events multi-system (CELLMEAS, CQI,
    # DCI, PLAID, PLAIU, MACRATE, MACRATEU), le baked tree n'a qu'une seule
    # instance `ev_X` parentée sous LTE. Les leaves dynamiques @nr-type-*
    # héritaient donc de la branche LTE. On crée dynamiquement, pour chaque
    # (event, system=NR), un parent miroir `ev_X_nr` sous une catégorie NR
    # miroir (créée si manquante). Les leaves @nr-type-* se rangent sous NR.
    LTE_TO_NR_CAT = {
        "cat_LTE_serving_radio":      ("cat_NR_serving_radio",      "Serving radio"),
        "cat_LTE_allocation_mcs":     ("cat_NR_allocation_mcs",     "Allocation & MCS"),
        "cat_LTE_throughput_per_layer": ("cat_NR_throughput_per_layer", "Throughput per layer"),
        "cat_LTE_link_quality":       ("cat_NR_link_quality",       "Link quality"),
        "cat_LTE_signalling":         ("cat_NR_signalling",         "Signalling"),
        "cat_LTE_neighbours":         ("cat_NR_neighbours",         "Neighbours"),
        "cat_LTE_mimo_per_port":      ("cat_NR_mimo_per_port",      "MIMO per port"),
        "cat_LTE_carrier_aggregation":("cat_NR_carrier_aggregation","Carrier aggregation"),
        "cat_LTE_scanner":            ("cat_NR_scanner",            "Scanner"),
        "cat_LTE_ul_power":           ("cat_NR_ul_power",           "UL power"),
    }
    tech_nr_id = None
    for n in nodes_out:
        if n.get("node_type") == "tech" and n.get("label") == "NR":
            tech_nr_id = n.get("node_id")
            break
    _nr_mirror_cache: dict[str, str] = {}
    def _nr_event_mirror(ev_lte_nid: str, ev_code: str) -> str | None:
        """Retourne (créé si manquant) l'id de `ev_X_nr` sous une catégorie
        NR miroir. Si l'event LTE n'est pas sous une catégorie connue, None."""
        if not tech_nr_id or not ev_lte_nid:
            return None
        if ev_lte_nid in _nr_mirror_cache:
            return _nr_mirror_cache[ev_lte_nid]
        # Résoudre parent catégorie du event LTE existant.
        ev_lte_node = next((x for x in nodes_out if x.get("node_id") == ev_lte_nid), None)
        if not ev_lte_node:
            return None
        cat_lte_id = ev_lte_node.get("parent_id")
        nr_cat_info = LTE_TO_NR_CAT.get(cat_lte_id)
        if not nr_cat_info:
            return None
        nr_cat_id, nr_cat_label = nr_cat_info
        # Créer catégorie NR miroir si absente
        if not any(x.get("node_id") == nr_cat_id for x in nodes_out):
            nodes_out.append(dict(
                node_id=nr_cat_id, parent_id=tech_nr_id, node_type="category",
                label=nr_cat_label, order=0, event=None, source_column=None,
                metric_id=None, display_code=None, cell=None, cell_label=None,
                cell_system=None, technology="NR", unit="", analytics_tab=None,
                availability_status=None, n=0, proof=None, selectable=False,
                reason=None, kind=None,
            ))
        # Créer event NR miroir si absent
        ev_nr_id = f"{ev_lte_nid}_nr"
        if not any(x.get("node_id") == ev_nr_id for x in nodes_out):
            nodes_out.append(dict(
                node_id=ev_nr_id, parent_id=nr_cat_id, node_type="event",
                label=ev_code, order=0, event=ev_code, source_column=None,
                metric_id=None, display_code=None, cell=None, cell_label=None,
                cell_system="NR", technology="NR", unit="", analytics_tab=None,
                availability_status=None, n=0, proof=None, selectable=False,
                reason=None, kind=None,
            ))
        _nr_mirror_cache[ev_lte_nid] = ev_nr_id
        return ev_nr_id

    for ev, system, ct, col, nn in dynamic_entries:
        ev_nid = event_node_by_code.get(ev)
        if not ev_nid:
            continue
        field_name = _field_name_for(ev, system, col)
        label_from_enum = _label_per_type(ev, system, ct, f"cell type {ct}")
        label_full = f"{field_name} @ {label_from_enum}"
        selector = cell_type_selector(system, ct)
        node_id = f"lf_observed_{ev.lower()}_{selector}_{col}"
        selection = f"{col}@{selector}"
        parent_id = ev_nid
        # 2.66.1 — rediriger vers l'event NR miroir si system=NR et parent LTE
        if system == 9:
            nr_parent = _nr_event_mirror(ev_nid, ev)
            if nr_parent:
                parent_id = nr_parent
        # 2.64.0 (REPRISE 7 Lot 6) — filtrer STRUCT dynamic (ex. compteurs
        # NFF cqi_count/dci_count @ cell). Même logique que la boucle
        # displayed_leaves ligne 687 : STRUCT = hors arbre.
        _dyn_kind = _kind_for_leaf({
            "label": label_full,
            "metric_label": _tree_metric_label(field_name),
            "metric_id": selection,
            "source_column": col,
        })
        if _dyn_kind == "STRUCT":
            continue
        order = siblings_counter.get(parent_id, 0)
        siblings_counter[parent_id] = order + 1
        # 2.64.1 — §7.8 : unit depuis metrics_v3.definitions() au lieu de "".
        _dyn_defn = _v3_defs().get(col) or {}
        _dyn_unit = _dyn_defn.get("unit") or ""
        _dyn_enum = _enum_for_col(col)
        nodes_out.append(
            dict(
                node_id=node_id,
                parent_id=parent_id,
                order=order,
                label=label_full,
                display_code=selection,
                enum_values=_dyn_enum,
                note="Cellule observée dans nmf_cell_second",
                source=None,
                node_type="leaf",
                analytics_tab=message_measurement_tab,
                metric_id=selection,
                selection=selection,
                event=ev,
                field_idx=None,
                source_column=col,
                unit=_dyn_unit,
                cell=selector,
                technology={7: "LTE", 9: "NR"}.get(system),
                metric_label=_tree_metric_label(field_name),
                cell_label=_cell_role_for_tree(ev, system, ct),
                cell_system={7: "LTE", 9: "NR"}.get(system),
                raw_cell_type=ct,
                cell_relation=_cell_relation_for_tree(ev, system, ct),
                technical_label=_technical_cell_label(
                    {7: "LTE", 9: "NR"}.get(system),
                    _cell_relation_for_tree(ev, system, ct),
                    _tree_metric_label(field_name),
                    _cell_role_for_tree(ev, system, ct),
                ),
                availability_status="available",
                n=int(nn),
                proof="observed-cell-second",
                selectable=True,
                reason=None,
                kind=_kind_for_leaf({
                    "label": label_full,
                    "metric_label": _tree_metric_label(field_name),
                    "metric_id": selection,
                    "source_column": col,
                }),
            )
        )
        if selection not in seen_codes:
            seen_codes.add(selection)
            cat_label = _category_label(nodes_by_id, ev_nid) or "Undocumented"
            metrics_out.append(dict(
                code=selection, display_code=selection, label=label_full, unit=_dyn_unit,
                source_table="nmf_cell_second", source_tables=["nmf_cell_second"],
                source_column=col, tech="BOTH", kind=_dyn_kind, enum_values=_dyn_enum,
                n_in_project=int(nn), decoder_version=DECODER_VERSION,
                event=ev, category_label=cat_label, cell_scoped=True,
                cells=[ct], cell_options=[{
                    "cell": selector, "label": label_from_enum,
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
