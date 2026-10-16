"""Service KPI v2 (0.40.0).

Calcule le statut par projet de chaque entrée du catalogue v2 à partir
de sa règle ``available_check``. Expose :

- ``compute_status_v2(db, project_id, entry)`` → ``KpiStatusV2``.
- ``build_catalog_v2_response(db, project_id, services)`` → shape pour
  ``GET /projects/{pid}/kpi/catalog``.
- ``build_filters_v2(db, project_id)`` → services + phases + opérateurs
  réels (depuis ``measurement_points``).

Discipline :
- Aucun chiffre fabriqué. Les règles ``always_unvalidated`` renvoient
  toujours ``UNVALIDATED`` ; ``always_unavailable`` → ``UNAVAILABLE``.
- Un KPI hors de son ``service_scope`` vis-à-vis des services demandés
  → ``NOT_APPLICABLE`` déclaré (pas un ``n=0`` muet).
- Ordre d'affichage : Techno → Famille → KPI (voir ``catalog_v2.FAMILIES_ORDER``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

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

    Expose ``service_types``, ``phases``, ``operators``, ``rats``,
    ``bands``, ``envs``, ``deps``.
    """
    return {
        "project_id":    project_id,
        "service_types": _distinct(db, project_id, "service_type"),
        "phases":        _distinct(db, project_id, "phase"),
        "operators":     _distinct(db, project_id, "operator"),
        "rats":          _distinct(db, project_id, "tech"),
        "bands":         _distinct(db, project_id, "band"),
        "envs":          _distinct(db, project_id, "env"),
        "deps":          _distinct(db, project_id, "dep"),
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


def compute_kpi_v2(
    db: Session,
    project_id: str,
    code: str,
    *,
    operators: tuple[str, ...] = (),
    services: tuple[str, ...] = (),
    phases: tuple[str, ...] = (),
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
    }

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
        if total == 0:
            return {**base, "status": "UNAVAILABLE",
                    "reason": check.get("reason_if_absent"), "value": None,
                    "n": 0, "by_operator": []}
        return {**base, "status": "AVAILABLE", "reason": None,
                "value": total, "n": total, "by_operator": by_op}

    if kind == "param_path_ilike":
        pat = check.get("arg") or ""
        if entry["nature"] == "Métrique mesurée":
            d = _dist_param_path(db, project_id, pat, operators=operators)
            if d["n"] == 0:
                return {**base, "status": "UNAVAILABLE",
                        "reason": check.get("reason_if_absent"),
                        **d}
            return {**base, "status": "AVAILABLE", "reason": None, **d}
        # Compteur sur path (ex. HO_COUNT via mobilityControlInfo).
        total, by_op = _count_param_path_ilike(db, project_id, pat, operators=operators)
        if total == 0:
            return {**base, "status": "UNAVAILABLE",
                    "reason": check.get("reason_if_absent"),
                    "value": None, "n": 0, "by_operator": []}
        return {**base, "status": "AVAILABLE", "reason": None,
                "value": total, "n": total, "by_operator": by_op}

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
            return {
                **base,
                "status":    "AVAILABLE",
                "reason":    None,
                "threshold": threshold,
                "n_total":   denom,
                "n_above":   num,
                "value":     value,
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
        return {
            **base,
            "status": "AVAILABLE",
            "reason": None,
            "n":      int(row[0]) if row else 0,
            "value":  float(row[2]) if row and row[2] is not None else None,
            "p10":    float(row[1]) if row and row[1] is not None else None,
            "p50":    float(row[2]) if row and row[2] is not None else None,
            "p90":    float(row[3]) if row and row[3] is not None else None,
        }

    return {**base, "status": "UNAVAILABLE",
            "reason": f"règle 'available_check.kind={kind!r}' inconnue",
            "value": None}
