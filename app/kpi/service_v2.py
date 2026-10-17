"""Service KPI v2 (0.40.0, étendu 0.41.0).

Calcule le statut par projet de chaque entrée du catalogue v2 à partir
de sa règle ``available_check``. Expose :

- ``compute_status_v2(db, project_id, entry)`` → ``KpiStatusV2``.
- ``build_catalog_v2_response(db, project_id, services)`` → shape pour
  ``GET /projects/{pid}/kpi/catalog``.
- ``build_filters_v2(db, project_id)`` → services + phases + opérateurs
  réels (depuis ``measurement_points``), chaque dimension portant
  ``available/reason/values`` (0.41.0 — pour les dimensions référentiel
  géo encore non chargées).
- ``compute_kpi_v2(db, project_id, code, group_by=…)`` → valeur + stats
  par groupe (operator | band | operator_band) + table[] + couleurs.

Discipline :
- Aucun chiffre fabriqué. Les règles ``always_unvalidated`` renvoient
  toujours ``UNVALIDATED`` ; ``always_unavailable`` → ``UNAVAILABLE``.
- Un KPI hors de son ``service_scope`` vis-à-vis des services demandés
  → ``NOT_APPLICABLE`` déclaré (pas un ``n=0`` muet).
- Un groupe sans donnée n'est **jamais omis** : il porte un ``status``
  typé (``ZERO_REEL`` ou ``ABSENT_DU_PERIMETRE``) + raison.
- Pas de ``mean-of-means`` : les percentiles sont calculés sur les
  mesures elles-mêmes, groupées par la dimension demandée.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dict.cell_ref_group import (
    CELL_REF_DIMS,
    build_group_by_options,
    check_cell_ref_dim,
    mp_metric_dim_percentiles,
)
from app.kpi.catalog_v2 import (
    ALIASES_COUNT,
    ALIASES_REPORT,
    CANONICAL_COUNT,
    CATALOG_V2_VERSION,
    FAMILIES_ORDER,
    NORMALIZATIONS,
    SOURCE_XLSX_NAME,
    SOURCE_XLSX_SHA256,
    TECHNO_ORDER,
    TOTAL_INPUT_ROWS,
    Status,
    is_in_service_scope,
    not_applicable_reason,
    sorted_entries,
)


# ---------------------------------------------------------------------------
# Statut par projet
# ---------------------------------------------------------------------------


@dataclass
class KpiStatusV2:
    status: Status
    reason: str | None


_MP_COLS = {"rsrp", "rsrq", "sinr", "cqi", "dl", "thrpt_ul", "tx_power",
            "latency", "rssi"}


# 0.41.0 — Palette couleurs opérateur / bande, servie par le back pour
# éviter que la UI invente ou dérive une couleur depuis un hash
# arbitraire. Les 4 MNO FR + un gris explicite pour les N/D.
_OPERATOR_COLORS: dict[str, str] = {
    "Orange":   "#FF7900",
    "SFR":      "#E2001A",
    "Bouygues": "#1E6EC1",
    "Free":     "#CD1F2A",
    "N/D":      "#888888",
}
_BAND_COLORS: dict[str, str] = {
    # LTE
    "B1":  "#4F46E5",
    "B3":  "#059669",
    "B7":  "#DC2626",
    "B20": "#D97706",
    "B28": "#7C3AED",
    "B38": "#0891B2",
    # NR
    "n78": "#DB2777",
    "n1":  "#2563EB",
    "n28": "#A855F7",
    # Fallback
    "N/D": "#888888",
}


def operator_color(op: str | None) -> str:
    return _OPERATOR_COLORS.get(op or "N/D", "#555555")


def band_color(band: str | None) -> str:
    return _BAND_COLORS.get(band or "N/D", "#555555")


# 0.41.0 — Expected operator set (used for ABSENT_DU_PERIMETRE on
# group_by=operator*). Lu depuis la col operator de param_occurrence
# OU mp selon la source. Les 4 MNO FR sont la référence.
_EXPECTED_OPERATORS = ("Orange", "SFR", "Bouygues", "Free")


def _mp_metric_available(db: Session, project_id: str, col: str) -> bool:
    if col not in _MP_COLS:
        return False
    row = db.execute(
        text(
            f"SELECT 1 FROM measurement_points "
            f"WHERE project_id = :pid AND {col} IS NOT NULL LIMIT 1"
        ),
        {"pid": project_id},
    ).first()
    return row is not None


def _message_present(db: Session, project_id: str, msg: str) -> bool:
    row = db.execute(
        text(
            "SELECT 1 FROM param_occurrence "
            "WHERE project_id = :pid AND message = :msg LIMIT 1"
        ),
        {"pid": project_id, "msg": msg},
    ).first()
    return row is not None


def _path_ilike_present(db: Session, project_id: str, pattern: str) -> bool:
    row = db.execute(
        text(
            "SELECT 1 FROM param_occurrence "
            "WHERE project_id = :pid AND path ILIKE :pat LIMIT 1"
        ),
        {"pid": project_id, "pat": pattern},
    ).first()
    return row is not None


def compute_status_v2(
    db: Session,
    project_id: str,
    entry: dict[str, Any],
    *,
    services: tuple[str, ...] = (),
) -> KpiStatusV2:
    """Évalue la règle ``available_check`` de l'entrée sur un projet.

    Un service hors scope → NOT_APPLICABLE **avant** toute requête DB
    (économise les I/O et expose la raison).
    """
    if services and not is_in_service_scope(entry, services):
        return KpiStatusV2("NOT_APPLICABLE", not_applicable_reason(entry, services))

    check = entry.get("available_check") or {}
    kind = check.get("kind")

    if kind == "always_unvalidated":
        return KpiStatusV2("UNVALIDATED", check.get("reason"))
    if kind == "always_unavailable":
        return KpiStatusV2("UNAVAILABLE", check.get("reason"))

    if kind == "mp_metric":
        col = check.get("arg") or ""
        if _mp_metric_available(db, project_id, col):
            return KpiStatusV2("AVAILABLE", None)
        return KpiStatusV2(
            "PENDING",
            check.get("reason_if_null")
            or f"measurement_points.{col} NULL partout",
        )

    # 0.42.2 — Compteur ECGI distincts (mp_ecgi_distinct).
    if kind == "mp_ecgi_distinct":
        row = db.execute(
            text(
                "SELECT COUNT(DISTINCT ecgi) FROM measurement_points "
                "WHERE project_id = :pid AND ecgi IS NOT NULL"
            ),
            {"pid": project_id},
        ).first()
        n = int(row[0]) if row and row[0] is not None else 0
        if n > 0:
            return KpiStatusV2("AVAILABLE", None)
        return KpiStatusV2(
            "PENDING",
            check.get("reason_if_null")
            or "measurement_points.ecgi NULL partout",
        )

    if kind == "param_message_eq":
        msg = check.get("arg") or ""
        if _message_present(db, project_id, msg):
            return KpiStatusV2("AVAILABLE", None)
        return KpiStatusV2(
            "UNAVAILABLE",
            check.get("reason_if_absent")
            or f"aucune occurrence RRC pour message={msg!r}",
        )

    if kind == "param_path_ilike":
        pat = check.get("arg") or ""
        if _path_ilike_present(db, project_id, pat):
            return KpiStatusV2("AVAILABLE", None)
        return KpiStatusV2(
            "UNAVAILABLE",
            check.get("reason_if_absent")
            or f"aucune occurrence RRC pour path LIKE {pat!r}",
        )

    # 0.45.2 — Débit depuis la TABLE DES TRANSFERTS (compute_transfers).
    # `transfers_table` : AVAILABLE si ≥ 1 transfert proven de la direction.
    # `transfers_dms`   : idem. La différence est dans compute_kpi_v2.
    if kind in ("transfers_table", "transfers_dms"):
        direction = (check.get("arg") or "dl").lower()
        from app.measure.throughput import compute_transfers
        ts = compute_transfers(db, project_id)
        n_proven = sum(
            1 for t in ts if t.verdict == "proven" and t.direction == direction and t.thrpt_mbps is not None
        )
        if n_proven > 0:
            return KpiStatusV2("AVAILABLE", None)
        return KpiStatusV2(
            "PENDING",
            check.get("reason_if_null")
            or f"compute_transfers : 0 transfert `proven` direction={direction!r}",
        )

    # Règle inconnue → écart déclaré, pas inventé.
    return KpiStatusV2(
        "UNAVAILABLE",
        f"règle 'available_check.kind={kind!r}' inconnue",
    )


# ---------------------------------------------------------------------------
# Catalogue avec arbre Techno → Famille → KPI
# ---------------------------------------------------------------------------


def build_catalog_v2_response(
    db: Session,
    project_id: str,
    *,
    services: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Construit la réponse ``/projects/{pid}/kpi/catalog`` v2.

    L'arbre est groupé par Techno → Famille → entries. Les métadonnées
    du catalogue (version, sha256 source, dédoublons) sont incluses.
    Les comptes par statut et par techno sont calculés au moment de
    l'appel (le statut dépend du projet).
    """
    entries = sorted_entries()
    status_cache: dict[str, KpiStatusV2] = {}
    for e in entries:
        status_cache[e["code"]] = compute_status_v2(db, project_id, e, services=services)

    # Comptes par statut
    counts_by_status: dict[str, int] = {}
    for s in status_cache.values():
        counts_by_status[s.status] = counts_by_status.get(s.status, 0) + 1

    # Comptes par (techno, status)
    counts_by_techno: dict[str, dict[str, int]] = {}
    for e in entries:
        t = e["techno"]
        s = status_cache[e["code"]].status
        counts_by_techno.setdefault(t, {})
        counts_by_techno[t][s] = counts_by_techno[t].get(s, 0) + 1

    # Groupage Techno → Famille → entries
    tree: list[dict[str, Any]] = []
    for techno in TECHNO_ORDER:
        techno_entries = [e for e in entries if e["techno"] == techno]
        if not techno_entries:
            continue
        families: dict[str, list[dict[str, Any]]] = {}
        for e in techno_entries:
            families.setdefault(e["family"], []).append(e)
        family_blocks: list[dict[str, Any]] = []
        for fam in FAMILIES_ORDER:
            if fam not in families:
                continue
            fam_entries = families[fam]
            fam_entries_out = []
            for e in fam_entries:
                st = status_cache[e["code"]]
                fam_entries_out.append({
                    "code":          e["code"],
                    "name":          e["name"],
                    "nature":        e["nature"],
                    "unit":          e["unit"],
                    "source":        e["source"],
                    "formula":       e["formula"],
                    "service_scope": e.get("service_scope") or [],
                    "aliases":       e.get("aliases") or [],
                    "status":        st.status,
                    "reason":        st.reason,
                })
            family_blocks.append({"family": fam, "kpis": fam_entries_out})
        tree.append({"techno": techno, "families": family_blocks})

    return {
        "project_id":           project_id,
        "catalog_version":      CATALOG_V2_VERSION,
        "source_xlsx":          SOURCE_XLSX_NAME,
        "source_xlsx_sha256":   SOURCE_XLSX_SHA256,
        "total_input_rows":     TOTAL_INPUT_ROWS,
        "canonical_count":      CANONICAL_COUNT,
        "aliases_count":        ALIASES_COUNT,
        "normalizations":       NORMALIZATIONS,
        "aliases":              ALIASES_REPORT,
        "services_requested":   list(services),
        "counts_by_status":     counts_by_status,
        "counts_by_techno":     counts_by_techno,
        "tree":                 tree,
    }


# ---------------------------------------------------------------------------
# Filters (service_types + phases + opérateurs réels)
# ---------------------------------------------------------------------------


def _distinct(db: Session, project_id: str, column: str) -> list[str]:
    """SELECT DISTINCT ``column`` FROM measurement_points pour ce
    projet. NULL → N/D exposé explicitement."""
    rows = db.execute(
        text(
            f"SELECT DISTINCT {column} FROM measurement_points "
            f"WHERE project_id = :pid"
        ),
        {"pid": project_id},
    ).fetchall()
    out = sorted({r[0] for r in rows if r[0] is not None})
    has_null = any(r[0] is None for r in rows)
    if has_null:
        out.append("N/D")
    return out


def build_filters_v2(db: Session, project_id: str) -> dict[str, Any]:
    """Filtres réels issus de ``measurement_points`` du projet.

    0.41.0 — Chaque dimension porte ``{available, reason, values}`` :
    - ``available=False`` quand le référentiel n'est pas chargé OU que
      l'ECGI n'est pas propagé.
    - ``reason`` décrit explicitement l'écart.
    - ``values[]`` est la liste des valeurs réelles observées (vide
      si available=False).
    """
    # Dimensions directes depuis measurement_points.
    def _dim(col: str) -> dict[str, Any]:
        vals = _distinct(db, project_id, col)
        return {
            "available": bool(vals),
            "reason":    None if vals else f"aucune valeur distincte pour measurement_points.{col}",
            "values":    vals,
        }

    # ECGI propagé ? (prérequis pour les filtres référentiel géo)
    mp_total = db.execute(
        text("SELECT COUNT(*) FROM measurement_points WHERE project_id = :pid"),
        {"pid": project_id},
    ).scalar() or 0
    mp_with_ecgi = db.execute(
        text(
            "SELECT COUNT(*) FROM measurement_points "
            "WHERE project_id = :pid AND ecgi IS NOT NULL"
        ),
        {"pid": project_id},
    ).scalar() or 0
    ecgi_pct = (100.0 * mp_with_ecgi / mp_total) if mp_total else 0.0

    # Référentiel chargé ? (cell_ref.dr/plaque/dor/arcep/commune renseignés
    # pour les ECGI du projet)
    def _geo_dim(col: str) -> dict[str, Any]:
        if not mp_with_ecgi:
            return {
                "available": False,
                "reason": (
                    f"ECGI non propagé : {mp_with_ecgi}/{mp_total} points. "
                    "Lancer POST /projects/{id}/kpi/_populate_ecgi."
                ),
                "values": [],
            }
        rows = db.execute(
            text(
                f"SELECT DISTINCT cr.{col} FROM measurement_points mp "
                f"JOIN cell_ref cr ON cr.eci = mp.ecgi "
                f"WHERE mp.project_id = :pid AND cr.{col} IS NOT NULL"
            ),
            {"pid": project_id},
        ).fetchall()
        values = sorted({r[0] for r in rows if r[0] is not None})
        if not values:
            return {
                "available": False,
                "reason": (
                    f"référentiel non chargé : cell_ref.{col} vide pour les "
                    f"{mp_with_ecgi} points ECGI. Upload via "
                    "POST /settings/cell-ref/upload."
                ),
                "values": [],
            }
        return {"available": True, "reason": None, "values": values}

    return {
        "project_id":    project_id,
        "operators":     _dim("operator"),
        "bands":         _dim("band"),
        "rats":          _dim("tech"),
        "service_types": _dim("service_type"),
        "phases":        _dim("phase"),
        "envs":          _dim("env"),
        "deps":          _dim("dep"),
        "ecgi": {
            "available":    bool(mp_with_ecgi),
            "mp_total":     int(mp_total),
            "mp_with_ecgi": int(mp_with_ecgi),
            "pct":          round(ecgi_pct, 2),
            "reason":       None if mp_with_ecgi else "ECGI non encore propagé",
        },
        # Dimensions référentiel géo — join mp.ecgi → cell_ref.<col>.
        "dr":       _geo_dim("dr"),
        "plaque":   _geo_dim("plaque"),
        "dor":      _geo_dim("dor"),
        "arcep":    _geo_dim("arcep_zone"),
        "commune":  _geo_dim("commune"),
        "insee":    _geo_dim("insee"),
        # 0.47.0 — group_by utilisables sur ce projet (operator/band
        # toujours ; dor/dr/plaque/arcep_zone selon état du cell_ref,
        # strict ECGI uniquement).
        "group_by_options": build_group_by_options(db, project_id),
    }


# ---------------------------------------------------------------------------
# compute_kpi_v2 — valeur d'un KPI précis
# ---------------------------------------------------------------------------


def _count_param_message(
    db: Session, project_id: str, msg: str,
    operators: tuple[str, ...] = (),
) -> tuple[int, list[dict[str, Any]]]:
    """Retourne ``(total, by_operator)`` pour un COUNT(DISTINCT stg_event_id)
    sur ``param_occurrence`` filtré par message."""
    params: dict[str, Any] = {"pid": project_id, "msg": msg}
    where = "project_id = :pid AND message = :msg"
    if operators:
        placeholders = ", ".join(f":op{i}" for i in range(len(operators)))
        where += f" AND operator IN ({placeholders})"
        for i, op in enumerate(operators):
            params[f"op{i}"] = op
    total = db.execute(
        text(
            f"SELECT COUNT(DISTINCT stg_event_id) FROM param_occurrence "
            f"WHERE {where}"
        ),
        params,
    ).scalar() or 0
    rows = db.execute(
        text(
            f"SELECT operator, COUNT(DISTINCT stg_event_id) "
            f"FROM param_occurrence WHERE {where} "
            f"GROUP BY operator ORDER BY operator"
        ),
        params,
    ).fetchall()
    by_op = [{"operator": r[0], "n": int(r[1])} for r in rows]
    return int(total), by_op


def _count_param_path_ilike(
    db: Session, project_id: str, pattern: str,
    operators: tuple[str, ...] = (),
) -> tuple[int, list[dict[str, Any]]]:
    params: dict[str, Any] = {"pid": project_id, "pat": pattern}
    where = "project_id = :pid AND path ILIKE :pat"
    if operators:
        placeholders = ", ".join(f":op{i}" for i in range(len(operators)))
        where += f" AND operator IN ({placeholders})"
        for i, op in enumerate(operators):
            params[f"op{i}"] = op
    total = db.execute(
        text(
            f"SELECT COUNT(DISTINCT stg_event_id) FROM param_occurrence "
            f"WHERE {where}"
        ),
        params,
    ).scalar() or 0
    rows = db.execute(
        text(
            f"SELECT operator, COUNT(DISTINCT stg_event_id) "
            f"FROM param_occurrence WHERE {where} "
            f"GROUP BY operator ORDER BY operator"
        ),
        params,
    ).fetchall()
    by_op = [{"operator": r[0], "n": int(r[1])} for r in rows]
    return int(total), by_op


def _dist_param_path(
    db: Session, project_id: str, pattern: str,
    operators: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Retourne percentiles P10/P50/P90 + distribution sur
    ``value_converted`` pour ``path ILIKE pattern``. Les valeurs sont
    castées en DOUBLE PRECISION ; les lignes non-numériques sont
    ignorées (``IS NUMERIC`` approximation côté SQL)."""
    params: dict[str, Any] = {"pid": project_id, "pat": pattern}
    where = (
        "project_id = :pid AND path ILIKE :pat "
        "AND value_converted ~ '^-?[0-9]+(\\.[0-9]+)?$'"
    )
    if operators:
        placeholders = ", ".join(f":op{i}" for i in range(len(operators)))
        where += f" AND operator IN ({placeholders})"
        for i, op in enumerate(operators):
            params[f"op{i}"] = op
    row = db.execute(
        text(
            "SELECT COUNT(*) AS n, "
            "       percentile_cont(0.10) WITHIN GROUP (ORDER BY CAST(value_converted AS DOUBLE PRECISION)) AS p10, "
            "       percentile_cont(0.50) WITHIN GROUP (ORDER BY CAST(value_converted AS DOUBLE PRECISION)) AS p50, "
            "       percentile_cont(0.90) WITHIN GROUP (ORDER BY CAST(value_converted AS DOUBLE PRECISION)) AS p90 "
            f"FROM param_occurrence WHERE {where}"
        ),
        params,
    ).first()
    n = int(row[0]) if row else 0
    if n == 0:
        return {"n": 0, "value": None, "p10": None, "p50": None, "p90": None,
                "by_operator": []}
    by_op_rows = db.execute(
        text(
            "SELECT operator, COUNT(*) AS n, "
            "       percentile_cont(0.50) WITHIN GROUP (ORDER BY CAST(value_converted AS DOUBLE PRECISION)) AS p50 "
            f"FROM param_occurrence WHERE {where} GROUP BY operator ORDER BY operator"
        ),
        params,
    ).fetchall()
    return {
        "n":   n,
        "value": float(row[2]) if row[2] is not None else None,  # P50 par défaut
        "p10":  float(row[1]) if row[1] is not None else None,
        "p50":  float(row[2]) if row[2] is not None else None,
        "p90":  float(row[3]) if row[3] is not None else None,
        "by_operator": [
            {
                "operator": r[0],
                "n":        int(r[1]),
                "value":    float(r[2]) if r[2] is not None else None,
            } for r in by_op_rows
        ],
    }


# ---------------------------------------------------------------------------
# Group_by aggregation helpers (0.41.0)
# ---------------------------------------------------------------------------


# 0.47.0 — Ajoute `dor` / `dr` / `plaque` / `arcep_zone` via jointure
# mp.ecgi → cell_ref.<col> (ecgi_source='sib1_strict' uniquement).
GroupBy = Literal[
    "operator", "band", "operator_band",
    "dor", "dr", "plaque", "arcep_zone",
]


def _group_cols(group_by: GroupBy) -> list[str]:
    if group_by == "operator":
        return ["operator"]
    if group_by == "band":
        return ["band"]
    if group_by in CELL_REF_DIMS:
        return [group_by]
    return ["operator", "band"]


def _group_key(row: dict[str, Any], cols: list[str]) -> dict[str, Any]:
    return {c: row.get(c) for c in cols}


def _tag_group(row: dict[str, Any], expected_operators_in_project: set[str]) -> tuple[str, str | None]:
    """Un groupe sans donnée n'est JAMAIS omis. On lui attribue :
    - ``PRESENT`` : n > 0.
    - ``ZERO_REEL`` : n == 0 mais la combinaison existe dans les
      dimensions du projet (opérateur attendu, bande utilisée).
    - ``ABSENT_DU_PERIMETRE`` : la combinaison n'existe pas dans le
      périmètre du projet.
    """
    n = int(row.get("n") or 0)
    if n > 0:
        return "PRESENT", None
    op = row.get("operator")
    if op is not None and op not in expected_operators_in_project:
        return (
            "ABSENT_DU_PERIMETRE",
            f"opérateur {op!r} hors périmètre projet",
        )
    return "ZERO_REEL", "n = 0 sur ce périmètre"


def _project_distinct(db: Session, project_id: str, table: str, col: str) -> set[str]:
    rows = db.execute(
        text(f"SELECT DISTINCT {col} FROM {table} WHERE project_id = :pid"),
        {"pid": project_id},
    ).fetchall()
    return {r[0] for r in rows if r[0] is not None}


def _grouped_mp(
    db: Session, project_id: str, mp_col: str, group_cols: list[str],
    *, operators: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Group-by percentile sur ``measurement_points.<col>``.

    Les percentiles sont calculés PAR GROUPE sur les mesures du groupe —
    jamais une moyenne de moyennes.
    """
    sel = ", ".join(group_cols)
    params: dict[str, Any] = {"pid": project_id}
    where = f"project_id = :pid AND {mp_col} IS NOT NULL"
    if operators:
        placeholders = ", ".join(f":op{i}" for i in range(len(operators)))
        where += f" AND operator IN ({placeholders})"
        for i, op in enumerate(operators):
            params[f"op{i}"] = op
    rows = db.execute(
        text(
            f"SELECT {sel}, COUNT({mp_col}) AS n, "
            f"       percentile_cont(0.10) WITHIN GROUP (ORDER BY {mp_col}) AS p10, "
            f"       percentile_cont(0.50) WITHIN GROUP (ORDER BY {mp_col}) AS p50, "
            f"       percentile_cont(0.90) WITHIN GROUP (ORDER BY {mp_col}) AS p90 "
            f"FROM measurement_points WHERE {where} GROUP BY {sel} ORDER BY {sel}"
        ),
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        row: dict[str, Any] = {}
        for i, c in enumerate(group_cols):
            row[c] = r[i]
        row["n"]   = int(r[len(group_cols)])
        row["p10"] = float(r[len(group_cols)+1]) if r[len(group_cols)+1] is not None else None
        row["p50"] = float(r[len(group_cols)+2]) if r[len(group_cols)+2] is not None else None
        row["p90"] = float(r[len(group_cols)+3]) if r[len(group_cols)+3] is not None else None
        out.append(row)
    return out


def _grouped_param_path(
    db: Session, project_id: str, pattern: str, group_cols: list[str],
    *, operators: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Group-by percentile sur ``param_occurrence.value_converted`` filtré
    ``path ILIKE pattern``. Pour RSRP/RSRQ serving (RRC autoritaire)."""
    sel = ", ".join(group_cols)
    params: dict[str, Any] = {"pid": project_id, "pat": pattern}
    where = (
        "project_id = :pid AND path ILIKE :pat "
        "AND value_converted ~ '^-?[0-9]+(\\.[0-9]+)?$'"
    )
    if operators:
        placeholders = ", ".join(f":op{i}" for i in range(len(operators)))
        where += f" AND operator IN ({placeholders})"
        for i, op in enumerate(operators):
            params[f"op{i}"] = op
    rows = db.execute(
        text(
            f"SELECT {sel}, COUNT(*) AS n, "
            f"       percentile_cont(0.10) WITHIN GROUP (ORDER BY CAST(value_converted AS DOUBLE PRECISION)) AS p10, "
            f"       percentile_cont(0.50) WITHIN GROUP (ORDER BY CAST(value_converted AS DOUBLE PRECISION)) AS p50, "
            f"       percentile_cont(0.90) WITHIN GROUP (ORDER BY CAST(value_converted AS DOUBLE PRECISION)) AS p90 "
            f"FROM param_occurrence WHERE {where} GROUP BY {sel} ORDER BY {sel}"
        ),
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        row: dict[str, Any] = {}
        for i, c in enumerate(group_cols):
            row[c] = r[i]
        row["n"]   = int(r[len(group_cols)])
        row["p10"] = float(r[len(group_cols)+1]) if r[len(group_cols)+1] is not None else None
        row["p50"] = float(r[len(group_cols)+2]) if r[len(group_cols)+2] is not None else None
        row["p90"] = float(r[len(group_cols)+3]) if r[len(group_cols)+3] is not None else None
        out.append(row)
    return out


def _grouped_param_count(
    db: Session, project_id: str, group_cols: list[str],
    *, message: str | None = None, path_ilike: str | None = None,
    operators: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Group-by COUNT(DISTINCT stg_event_id) sur ``param_occurrence``."""
    sel = ", ".join(group_cols)
    params: dict[str, Any] = {"pid": project_id}
    where_parts = ["project_id = :pid"]
    if message is not None:
        where_parts.append("message = :msg")
        params["msg"] = message
    if path_ilike is not None:
        where_parts.append("path ILIKE :pat")
        params["pat"] = path_ilike
    if operators:
        placeholders = ", ".join(f":op{i}" for i in range(len(operators)))
        where_parts.append(f"operator IN ({placeholders})")
        for i, op in enumerate(operators):
            params[f"op{i}"] = op
    where = " AND ".join(where_parts)
    rows = db.execute(
        text(
            f"SELECT {sel}, COUNT(DISTINCT stg_event_id) AS n "
            f"FROM param_occurrence WHERE {where} GROUP BY {sel} ORDER BY {sel}"
        ),
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        row: dict[str, Any] = {}
        for i, c in enumerate(group_cols):
            row[c] = r[i]
        row["n"] = int(r[len(group_cols)])
        out.append(row)
    return out


def _comparability(groups: list[dict[str, Any]]) -> str:
    """Verdict de comparabilité d'un groupement.

    - ``NO_DATA`` : zéro groupe avec n>0.
    - ``SINGLE_GROUP`` : 1 seul groupe avec n>0 (rien à comparer).
    - ``COMPARABLE`` : ≥ 2 groupes avec n>0 et chaque groupe a au
      moins 30 mesures (seuil pragmatique « petits échantillons »).
    - ``COMPARABLE_WITH_LIMITATIONS`` : ≥ 2 groupes mais au moins un
      a n < 30 (comparaison possible mais échantillons déséquilibrés).
    """
    with_data = [g for g in groups if (g.get("n") or 0) > 0]
    if not with_data:
        return "NO_DATA"
    if len(with_data) == 1:
        return "SINGLE_GROUP"
    if any((g.get("n") or 0) < 30 for g in with_data):
        return "COMPARABLE_WITH_LIMITATIONS"
    return "COMPARABLE"


def _decorate_groups(
    groups: list[dict[str, Any]],
    group_cols: list[str],
    expected_operators: set[str],
) -> list[dict[str, Any]]:
    """Ajoute colors + status + reason sur chaque ligne groupée."""
    out: list[dict[str, Any]] = []
    for g in groups:
        status, reason = _tag_group(g, expected_operators)
        row = dict(g)
        row["status"] = status
        row["reason"] = reason
        if "operator" in group_cols:
            row["operator_color"] = operator_color(g.get("operator"))
        if "band" in group_cols:
            row["band_color"] = band_color(g.get("band"))
        out.append(row)
    # Tri déterministe : operator ASC, band ASC
    out.sort(key=lambda r: (
        str(r.get("operator") or "~"), str(r.get("band") or "~")
    ))
    return out


def compute_kpi_v2(
    db: Session,
    project_id: str,
    code: str,
    *,
    operators: tuple[str, ...] = (),
    services: tuple[str, ...] = (),
    phases: tuple[str, ...] = (),
    group_by: GroupBy = "operator",
) -> dict[str, Any]:
    """Calcule la valeur du KPI ``code`` pour un projet.

    - Résolution d'alias via ``catalog_v2.resolve``.
    - Si hors ``service_scope`` → ``NOT_APPLICABLE`` déclaré, value=null.
    - Sinon, délégation par ``available_check.kind`` :
        - ``param_message_eq`` → comptage.
        - ``param_path_ilike`` → comptage OU distribution (si nature
          "Métrique mesurée" → percentiles P10/P50/P90).
        - ``mp_metric`` → percentile si AVAILABLE, sinon PENDING déclaré.
        - ``always_unvalidated`` / ``always_unavailable`` → statut
          renvoyé avec ``value=null``, pas de requête DB.
    """
    from app.kpi.catalog_v2 import ALIAS_TO_CANONICAL, CATALOG_V2

    requested = code
    canonical = code if code in CATALOG_V2 else ALIAS_TO_CANONICAL.get(code)
    if canonical is None or canonical not in CATALOG_V2:
        return {
            "requested_code": requested,
            "code":           None,
            "status":         "UNAVAILABLE",
            "reason":         f"KPI inconnu : {requested!r}",
            "value":          None,
        }
    entry = CATALOG_V2[canonical]

    # 0.47.0 — group_by_options exposés systématiquement pour que le
    # front sache quelles dimensions sont utilisables sur ce projet.
    group_by_options = build_group_by_options(db, project_id)
    base = {
        "requested_code":    requested,
        "code":              canonical,
        "name":              entry["name"],
        "techno":            entry["techno"],
        "nature":            entry["nature"],
        "family":            entry["family"],
        "unit":              entry["unit"],
        "formula":           entry["formula"],
        "source":            entry["source"],
        "service_scope":     entry.get("service_scope") or [],
        "aliases":           entry.get("aliases") or [],
        "services_requested": list(services),
        "operators_requested": list(operators),
        "phases_requested":   list(phases),
        "group_by":          group_by,
        "group_by_options":  group_by_options,
    }

    # 0.47.0 — Court-circuit : si group_by dimensionnel (dor/dr/plaque/
    # arcep_zone) et cell_ref ne porte pas cette dimension pour les
    # ECGI du projet, UNAVAILABLE immédiat avec reason. Aucune requête
    # inutile ensuite.
    if group_by in CELL_REF_DIMS:
        st = check_cell_ref_dim(db, project_id, group_by)
        if not st.available:
            return {
                **base,
                "status":  "UNAVAILABLE",
                "reason":  st.reason,
                "value":   None,
                "n":       0,
                "groups":  [],
                "table":   [],
                "comparability": "NO_DATA",
                "coverage": {
                    "with_value": st.n_with_value,
                    "total":      st.n_total_mp,
                    "pct":        st.pct,
                },
            }

    group_cols = _group_cols(group_by)
    expected_ops = set(_EXPECTED_OPERATORS) & _project_distinct(
        db, project_id, "measurement_points", "operator"
    )
    # Si le projet n'a pas peuplé mp (ex. REF partiellement), on retombe
    # sur param_occurrence pour les opérateurs attendus.
    if not expected_ops:
        expected_ops = set(_EXPECTED_OPERATORS) & _project_distinct(
            db, project_id, "param_occurrence", "operator"
        )

    # service_scope filter
    if services and not is_in_service_scope(entry, services):
        return {
            **base,
            "status": "NOT_APPLICABLE",
            "reason": not_applicable_reason(entry, services),
            "value":  None,
        }

    check = entry.get("available_check") or {}
    kind = check.get("kind")

    if kind == "always_unvalidated":
        return {**base, "status": "UNVALIDATED", "reason": check.get("reason"), "value": None}

    if kind == "always_unavailable":
        return {**base, "status": "UNAVAILABLE", "reason": check.get("reason"), "value": None}

    if kind == "param_message_eq":
        msg = check.get("arg") or ""
        total, by_op = _count_param_message(db, project_id, msg, operators=operators)
        groups_raw = _grouped_param_count(
            db, project_id, group_cols, message=msg, operators=operators,
        )
        groups = _decorate_groups(groups_raw, group_cols, expected_ops)
        if total == 0:
            return {**base, "status": "UNAVAILABLE",
                    "reason": check.get("reason_if_absent"), "value": None,
                    "n": 0, "by_operator": [], "groups": [], "table": [],
                    "comparability": "NO_DATA"}
        return {**base, "status": "AVAILABLE", "reason": None,
                "value": total, "n": total, "by_operator": by_op,
                "groups": groups, "table": groups,
                "comparability": _comparability(groups)}

    if kind == "param_path_ilike":
        pat = check.get("arg") or ""
        if entry["nature"] == "Métrique mesurée":
            d = _dist_param_path(db, project_id, pat, operators=operators)
            groups_raw = _grouped_param_path(
                db, project_id, pat, group_cols, operators=operators,
            )
            groups = _decorate_groups(groups_raw, group_cols, expected_ops)
            if d["n"] == 0:
                return {**base, "status": "UNAVAILABLE",
                        "reason": check.get("reason_if_absent"),
                        **d, "groups": [], "table": [],
                        "comparability": "NO_DATA"}
            return {**base, "status": "AVAILABLE", "reason": None, **d,
                    "groups": groups, "table": groups,
                    "comparability": _comparability(groups)}
        # Compteur sur path (ex. HO_COUNT via mobilityControlInfo).
        total, by_op = _count_param_path_ilike(db, project_id, pat, operators=operators)
        groups_raw = _grouped_param_count(
            db, project_id, group_cols, path_ilike=pat, operators=operators,
        )
        groups = _decorate_groups(groups_raw, group_cols, expected_ops)
        if total == 0:
            return {**base, "status": "UNAVAILABLE",
                    "reason": check.get("reason_if_absent"),
                    "value": None, "n": 0, "by_operator": [],
                    "groups": [], "table": [], "comparability": "NO_DATA"}
        return {**base, "status": "AVAILABLE", "reason": None,
                "value": total, "n": total, "by_operator": by_op,
                "groups": groups, "table": groups,
                "comparability": _comparability(groups)}

    # 0.42.2 — Compteur ECGI (identifiant cellule globale dérivé SIB1).
    if kind == "mp_ecgi_distinct":
        row = db.execute(
            text(
                "SELECT COUNT(DISTINCT ecgi) AS n_cells, "
                "       COUNT(*) FILTER (WHERE ecgi IS NOT NULL) AS n_mp "
                "FROM measurement_points WHERE project_id = :pid"
            ),
            {"pid": project_id},
        ).first()
        n_cells = int(row[0]) if row and row[0] is not None else 0
        n_mp    = int(row[1]) if row and row[1] is not None else 0
        if n_cells == 0:
            return {**base, "status": "PENDING",
                    "reason": check.get("reason_if_null"),
                    "value": None, "n": 0, "n_mp_with_ecgi": 0}
        # Groupes : par opérateur et/ou par bande, COUNT(DISTINCT ecgi).
        sel = ", ".join(group_cols)
        rows = db.execute(
            text(
                f"SELECT {sel}, COUNT(DISTINCT ecgi) AS n_cells, "
                f"       COUNT(*) FILTER (WHERE ecgi IS NOT NULL) AS n_mp "
                f"FROM measurement_points WHERE project_id = :pid "
                f"GROUP BY {sel} ORDER BY {sel}"
            ),
            {"pid": project_id},
        ).fetchall()
        groups_raw: list[dict[str, Any]] = []
        for r in rows:
            row_d: dict[str, Any] = {}
            for i, c in enumerate(group_cols):
                row_d[c] = r[i]
            row_d["n"]       = int(r[len(group_cols)])
            row_d["n_mp"]    = int(r[len(group_cols) + 1])
            groups_raw.append(row_d)
        groups = _decorate_groups(groups_raw, group_cols, expected_ops)
        return {
            **base,
            "status":         "AVAILABLE",
            "reason":         None,
            "value":          n_cells,
            "n":              n_cells,
            "n_mp_with_ecgi": n_mp,
            "groups":         groups,
            "table":          groups,
            "comparability":  _comparability(groups),
        }

    if kind == "mp_metric":
        col = check.get("arg") or ""
        if not _mp_metric_available(db, project_id, col):
            return {**base, "status": "PENDING",
                    "reason": check.get("reason_if_null"),
                    "value": None, "n": 0}
        # 0.40.0 — DMS (ex. AGG_DMS_DL_30_MBPS) : taux = 100 × count(col ≥ seuil) / count(col IS NOT NULL).
        # Pas une percentile. Le seuil est encodé dans le code.
        import re as _re
        m_dms = _re.match(r"^AGG_DMS_(DL|UL)_(\d+)_MBPS$", canonical)
        if m_dms is not None:
            threshold = int(m_dms.group(2))
            r = db.execute(
                text(
                    f"SELECT COUNT({col}) AS denom, "
                    f"       COUNT(*) FILTER (WHERE {col} >= :t) AS num "
                    f"FROM measurement_points WHERE project_id = :pid"
                ),
                {"pid": project_id, "t": float(threshold)},
            ).first()
            denom = int(r[0]) if r else 0
            num = int(r[1]) if r else 0
            value = (100.0 * num / denom) if denom else None
            # Groupes DMS = taux par groupe (jamais mean-of-means).
            sel = ", ".join(group_cols)
            grouped = db.execute(
                text(
                    f"SELECT {sel}, COUNT({col}) AS denom, "
                    f"       COUNT(*) FILTER (WHERE {col} >= :t) AS num "
                    f"FROM measurement_points WHERE project_id = :pid "
                    f"AND {col} IS NOT NULL GROUP BY {sel} ORDER BY {sel}"
                ),
                {"pid": project_id, "t": float(threshold)},
            ).fetchall()
            groups_raw: list[dict[str, Any]] = []
            for gr in grouped:
                row: dict[str, Any] = {}
                for i, c in enumerate(group_cols):
                    row[c] = gr[i]
                d = int(gr[len(group_cols)])
                nnum = int(gr[len(group_cols) + 1])
                row["n"]       = d
                row["n_above"] = nnum
                row["value"]   = (100.0 * nnum / d) if d else None
                groups_raw.append(row)
            groups = _decorate_groups(groups_raw, group_cols, expected_ops)
            return {
                **base,
                "status":    "AVAILABLE",
                "reason":    None,
                "threshold": threshold,
                "n_total":   denom,
                "n_above":   num,
                "value":     value,
                "groups":    groups,
                "table":     groups,
                "comparability": _comparability(groups),
            }
        # Métrique mesurée AVAILABLE : percentile_cont sur mp.<col>
        row = db.execute(
            text(
                f"SELECT COUNT({col}) AS n, "
                f"       percentile_cont(0.10) WITHIN GROUP (ORDER BY {col}) AS p10, "
                f"       percentile_cont(0.50) WITHIN GROUP (ORDER BY {col}) AS p50, "
                f"       percentile_cont(0.90) WITHIN GROUP (ORDER BY {col}) AS p90 "
                f"FROM measurement_points WHERE project_id = :pid"
            ),
            {"pid": project_id},
        ).first()
        # 0.47.0 — group_by dimensionnel → mp_metric_dim_percentiles
        # (jointure ECGI strict → cell_ref.<col>), avec N/D pour les
        # points sans ECGI strict ou sans valeur cell_ref.
        coverage: dict[str, Any] | None = None
        if group_by in CELL_REF_DIMS:
            groups_raw, cov = mp_metric_dim_percentiles(db, project_id, col, group_by)
            total = cov["total"]
            pct = round(100.0 * cov["with_value"] / total, 2) if total else 0.0
            coverage = {
                "with_value": cov["with_value"],
                "total":      total,
                "pct":        pct,
            }
            groups = groups_raw  # pas de _decorate_groups (pas d'operator)
        else:
            groups_raw = _grouped_mp(db, project_id, col, group_cols, operators=operators)
            groups = _decorate_groups(groups_raw, group_cols, expected_ops)
        out = {
            **base,
            "status": "AVAILABLE",
            "reason": None,
            "n":      int(row[0]) if row else 0,
            "value":  float(row[2]) if row and row[2] is not None else None,
            "p10":    float(row[1]) if row and row[1] is not None else None,
            "p50":    float(row[2]) if row and row[2] is not None else None,
            "p90":    float(row[3]) if row and row[3] is not None else None,
            "groups": groups,
            "table":  groups,
            "comparability": _comparability(groups),
        }
        if coverage is not None:
            out["coverage"] = coverage
        return out

    # 0.45.2 — Débit depuis la TABLE DES TRANSFERTS (compute_transfers).
    if kind in ("transfers_table", "transfers_dms"):
        direction = (check.get("arg") or "dl").lower()
        from app.measure.throughput import compute_transfers
        ts = compute_transfers(db, project_id)
        proven = [
            t for t in ts
            if t.verdict == "proven" and t.direction == direction and t.thrpt_mbps is not None
        ]
        if not proven:
            return {**base, "status": "PENDING",
                    "reason": check.get("reason_if_null")
                              or f"compute_transfers : 0 transfert proven direction={direction!r}",
                    "value": None, "n": 0}
        mbps = sorted(float(t.thrpt_mbps) for t in proven)  # type: ignore[arg-type]
        n = len(mbps)
        p10 = mbps[int(n * 0.10)]
        p50 = mbps[n // 2]
        p90 = mbps[min(n - 1, int(n * 0.90))]

        if kind == "transfers_dms":
            # Taux ≥ seuil (seuil encodé dans le code du KPI).
            import re as _re
            m_dms = _re.match(r"^AGG_DMS_(DL|UL)_(\d+)_MBPS$", canonical)
            if m_dms is None:
                return {**base, "status": "UNAVAILABLE",
                        "reason": f"code {canonical!r} ne matche pas AGG_DMS_(DL|UL)_<N>_MBPS",
                        "value": None}
            threshold = int(m_dms.group(2))
            n_above = sum(1 for v in mbps if v >= threshold)
            value = (100.0 * n_above / n) if n else None
            return {
                **base,
                "status":    "AVAILABLE",
                "reason":    None,
                "threshold": threshold,
                "n_total":   n,
                "n_above":   n_above,
                "value":     value,
                "n":         n,
                "groups":    [],
                "table":     [],
            }

        # transfers_table : percentiles directs sur thrpt_mbps.
        return {
            **base,
            "status": "AVAILABLE",
            "reason": None,
            "n":      n,
            "value":  float(p50),
            "p10":    float(p10),
            "p50":    float(p50),
            "p90":    float(p90),
            "groups": [],
            "table":  [],
        }

    return {**base, "status": "UNAVAILABLE",
            "reason": f"règle 'available_check.kind={kind!r}' inconnue",
            "value": None}
