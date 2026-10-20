"""Service dictionnaire v2 (0.45.0) — tree + distribution + fiche."""

from __future__ import annotations

import hashlib
import json
from app.dict.geo_filters import geographic_scope
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dict.cell_ref_group import (
    CELL_REF_DIMS,
    build_group_by_options,
    check_cell_ref_dim,
    param_occurrence_dim_counts,
)


# Palette opérateur / bande — alignée avec kpi.service_v2.
_OPERATOR_COLORS: dict[str, str] = {
    "Orange":   "#FF7900",
    "SFR":      "#E2001A",
    "Bouygues": "#1E6EC1",
    "Free":     "#CD1F2A",
    "N/D":      "#888888",
}
_BAND_COLORS: dict[str, str] = {
    "B1": "#4F46E5", "B3": "#059669", "B7": "#DC2626", "B20": "#D97706",
    "B28": "#7C3AED", "B38": "#0891B2", "n78": "#DB2777", "N/D": "#888888",
}


def _op_color(op: str | None) -> str:  return _OPERATOR_COLORS.get(op or "N/D", "#555555")
def _band_color(band: str | None) -> str: return _BAND_COLORS.get(band or "N/D", "#555555")


# ---------------------------------------------------------------------------
# Tree catalog + raw
# ---------------------------------------------------------------------------


def build_dict_tree(db: Session, project_id: str, view: str, message: str | None = None) -> dict[str, Any]:
    """Construit l'arbre dictionnaire.

    - ``view=catalog`` : grouping (techno → origin → message → functional_group → feuilles).
      Agrège sur ``param_key`` (CHOICE collapsé). ``is_identifier=TRUE`` exclus.
    - ``view=raw`` : grouping (techno → origin → message → "RAW" → feuilles).
      Groupage sur ``path`` brut. Tous les paths inclus (identifiants compris).
    """
    assert view in ("catalog", "raw")

    if view == "catalog":
        rows = db.execute(
            text(
                """
                SELECT system, origin, message, functional_group,
                       param_key, display_name, choice_of,
                       discriminators, unit_converted, is_identifier,
                       COUNT(*) AS n
                FROM param_occurrence
                WHERE project_id = :pid
                  AND param_key IS NOT NULL
                  AND COALESCE(is_identifier, false) = false
                GROUP BY system, origin, message, functional_group,
                         param_key, display_name, choice_of,
                         discriminators, unit_converted, is_identifier
                ORDER BY system, origin, message, functional_group, param_key
                """
            ),
            {"pid": project_id},
        ).fetchall()
    else:  # raw
        rows = db.execute(
            text(
                """
                SELECT system, origin, message,
                       'RAW' AS functional_group,
                       path AS param_key, path AS display_name,
                       NULL::text AS choice_of,
                       NULL::jsonb AS discriminators,
                       unit_converted,
                       COALESCE(is_identifier, false) AS is_identifier,
                       COUNT(*) AS n
                FROM param_occurrence
                WHERE project_id = :pid
                GROUP BY system, origin, message, path, unit_converted, is_identifier
                ORDER BY system, origin, message, path
                """
            ),
            {"pid": project_id},
        ).fetchall()

    # Compte global
    total_rows = db.execute(
        text("SELECT COUNT(*) FROM param_occurrence WHERE project_id = :pid"),
        {"pid": project_id},
    ).scalar() or 0
    distinct_param_keys = db.execute(
        text(
            "SELECT COUNT(DISTINCT param_key) FROM param_occurrence "
            "WHERE project_id = :pid AND param_key IS NOT NULL"
        ),
        {"pid": project_id},
    ).scalar() or 0

    from app.dict.templates import category_maps, classify
    maps = category_maps(db) if view == "catalog" else []
    if view == 'catalog':
        backup = db.execute(text("SELECT payload FROM dict_v22_backup WHERE name='dict_category_map'")).scalar()
        labels = {r['category_id']:(r['label'],r['position']) for r in maps}
        maps = [dict(r,label=labels.get(r['category_id'],(r['category_id'],99))[0],position=labels.get(r['category_id'],('',99))[1]) for r in backup]
    # Groupage python : techno → origin → message → group → feuilles
    tree: dict[str, dict[str, dict[str, dict[str, list[dict]]]]] = {}
    for r in rows:
        if message is not None and r[2] != message:
            continue
        if view == 'catalog' and r[1] == 'network_config':
            continue
        system = (r[0] or "LTE")
        origin = (r[1] or "network_config")
        msg    = (r[2] or "?")
        category_id, category_label, category_position = classify(system, r[4], maps) if view == "catalog" else (None, "RAW", 0)
        group = category_label
        leaf = {
            "category_id": category_id,
            "param_key":      r[4],
            "display_name":   r[5],
            "choice_of":      r[6],
            "discriminators": r[7],
            "unit":           r[8],
            "is_identifier":  bool(r[9]),
            "origin":         origin,
            "n":              int(r[10]),
            "sample_paths":   [],
        }
        tree.setdefault(system, {}).setdefault(origin, {}).setdefault(msg, {}).setdefault(group, []).append(leaf)

    # Reshape pour la réponse Pydantic.
    tree_out: list[dict[str, Any]] = []
    for techno, origins in tree.items():
        o_out: list[dict[str, Any]] = []
        for origin, msgs in origins.items():
            m_out: list[dict[str, Any]] = []
            for msg, groups in msgs.items():
                g_out: list[dict[str, Any]] = []
                for group_name, leaves in groups.items():
                    g_out.append({"name": group_name, "kpis": leaves})
                m_out.append({"message": msg, "groups": g_out})
            o_out.append({"origin": origin, "messages": m_out})
        tree_out.append({"techno": techno, "origins": o_out})

    if view == 'catalog':
        from app.dict.catalog_v22 import network_catalog
        network = network_catalog(db,project_id,message)
        for techno,categories in network.items():
            bucket = next((t for t in tree_out if t['techno']==techno),None)
            if bucket is None:
                bucket={'techno':techno,'origins':[]};tree_out.append(bucket)
            bucket['origins'].insert(0,{'origin':'network_config','categories':categories})
    available_messages = db.execute(text('SELECT DISTINCT message FROM param_occurrence WHERE project_id=:pid AND message IS NOT NULL ORDER BY message'),{'pid':project_id}).scalars().all()
    return {
        "project_id":         project_id,
        "view":               view,
        "available_messages": available_messages,
        "total_rows":         int(total_rows),
        "distinct_param_keys": int(distinct_param_keys),
        "tree":               tree_out,
        # 0.47.0 — group_by utilisables pour ce projet.
        "group_by_options":   build_group_by_options(db, project_id),
    }


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------


_UNIT_FROM_LAST_SEG = {
    "a3-Offset":   "dB",
    "hysteresis":  "dB",
    "timeToTrigger": "ms",
}


def _result_id(project_id: str, param_key: str, group_by: str) -> str:
    h = hashlib.sha256(f"{project_id}:{param_key}:{group_by}".encode()).hexdigest()
    return h[:16]


def build_distribution(
    db: Session, project_id: str, keys: list[str], group_by: str,
    *, operators: tuple[str, ...] = (), bands: tuple[str, ...] = (),
    geographic: dict[str, tuple[str, ...]] | None = None,
    technology: str | None = None,
) -> dict[str, Any]:
    """Distribution de valeurs par (param_key, group_by). Pour chaque
    clé : values[] = {value, value_display, groups{operator?/band?: n}}.

    0.47.0 — Accepte aussi ``group_by ∈ {dor, dr, plaque, arcep_zone}``.
    Joint ``mp.ecgi → cell_ref.<col>`` (ecgi_source='sib1_strict'
    uniquement). Si la dimension est absente du cell_ref pour ce projet,
    renvoie le bloc avec ``status='UNAVAILABLE'`` + ``reason``.
    """
    if group_by in CELL_REF_DIMS and any(key.startswith('dict22:') for key in keys):
        from fastapi import HTTPException
        raise HTTPException(422, detail={'code':'AGGREGATE_GEO_GROUP_UNSUPPORTED','message':'Clés agrégées : regroupement opérateur/bande uniquement ; les filtres géographiques restent utilisables.'})
    geo_cte, geo_predicate, geo_params = geographic_scope(db, project_id, geographic)
    if technology:
        geo_predicate += " AND param_occurrence.system = :technology"
        geo_params["technology"] = technology
    group_by_options = build_group_by_options(db, project_id)
    is_cell_ref_dim = group_by in CELL_REF_DIMS
    cell_ref_status = (
        check_cell_ref_dim(db, project_id, group_by) if is_cell_ref_dim else None
    )

    blocks: list[dict[str, Any]] = []

    # 0.47.0 — Court-circuit : si group_by dimensionnel non disponible,
    # on renvoie UNAVAILABLE pour toutes les clés sans requêter meta.
    if is_cell_ref_dim and cell_ref_status and not cell_ref_status.available:
        for key in keys:
            blocks.append({
                "param_key":       key,
                "display_name":    key.rsplit("/", 1)[-1] if "/" in key else key,
                "unit":            None,
                "choice_of":       None,
                "discriminators":  None,
                "origin":          "network_config",
                "n_total":         0,
                "distinct_values": 0,
                "values":          [],
                "comparability":   "NO_DATA",
                "verdict":         "NON_COMPARE",
                "result_id":       _result_id(project_id, key, group_by),
                "status":          "UNAVAILABLE",
                "reason":          cell_ref_status.reason,
                "coverage": {
                    "with_value": cell_ref_status.n_with_value,
                    "total":      cell_ref_status.n_total_mp,
                    "pct":        cell_ref_status.pct,
                },
            })
        return {
            "project_id":        project_id,
            "group_by":          group_by,
            "blocks":            blocks,
            "group_by_options":  group_by_options,
        }

    for key in keys:
        from app.dict.catalog_v22 import selector_predicate
        key_predicate,key_params=selector_predicate(key,db,project_id)
        # Métadonnées communes (unit, origin, choice_of, discriminators).
        # 0.45.1 — distinct_values = COUNT(DISTINCT COALESCE(value_converted, value))
        # pour que les feuilles non-converties (ex. hysteresis en 0.45.0)
        # soient aussi comptées correctement.
        meta = db.execute(
            text(
                geo_cte + f"""
                SELECT MIN(display_name), MIN(unit_converted), MIN(origin), MIN(choice_of),
                       MIN(discriminators::text), COUNT(*) AS n_total,
                       COUNT(DISTINCT COALESCE(value_converted, value)) AS distinct_vals
                FROM param_occurrence
                WHERE project_id = :pid AND ({key_predicate}) {geo_predicate}
                HAVING COUNT(*) > 0
                """
            ),
            {"pid": project_id, **key_params, **geo_params},
        ).first()
        if meta is None:
            blocks.append({
                "param_key":      key,
                "display_name":   key.rsplit("/", 1)[-1] if "/" in key else key,
                "unit":           None,
                "choice_of":      None,
                "discriminators": None,
                "origin":         "network_config",
                "n_total":        0,
                "distinct_values": 0,
                "values":         [],
                "comparability":  "NO_DATA",
                "verdict":        "NON_COMPARE",
                "result_id":      _result_id(project_id, key, group_by),
            })
            continue
        display_name, unit, origin, choice_of, discs_json, n_total, distinct_vals = meta

        if origin == "ue_report":
            # Pour les mesures rapportées, pas de distribution config : on
            # redirige vers un KPI éventuel (indicatif).
            blocks.append({
                "param_key":      key,
                "display_name":   display_name,
                "unit":           unit,
                "choice_of":      choice_of,
                "discriminators": None,
                "origin":         "ue_report",
                "n_total":        int(n_total),
                "distinct_values": int(distinct_vals),
                "values":         [],
                "comparability":  "NO_DATA",
                "verdict":        "NON_COMPARE",
                "result_id":      _result_id(project_id, key, group_by),
            })
            continue

        # Pivot values[] = {value, value_display, groups[]} selon la
        # branche group_by. On distingue :
        #   - operator / band / operator_band : lecture directe
        #     param_occurrence.(operator, band).
        #   - dor / dr / plaque / arcep_zone : jointure cell_ref via
        #     stg_event_id → mp.ecgi (strict).
        by_value: dict[str, list[dict[str, Any]]] = {}
        coverage: dict[str, Any] | None = None
        group_totals: dict[tuple, dict[str, Any]] = {}

        if is_cell_ref_dim:
            dim_rows, cov = param_occurrence_dim_counts(
                db, project_id, key, group_by,
            )
            for r in dim_rows:
                g: dict[str, Any] = {group_by: r["dim"], "n": r["n"]}
                by_value.setdefault(str(r["value"]), []).append(g)
            total = cov["total"]
            pct = round(100.0 * cov["with_value"] / total, 2) if total else 0.0
            coverage = {
                "with_value": cov["with_value"],
                "total":      total,
                "pct":        pct,
            }
        else:
            # Groupage classique (operator | band | operator_band).
            if group_by == "operator":
                group_cols = ["operator"]
            elif group_by == "band":
                group_cols = ["band"]
            else:
                group_cols = ["operator", "band"]
            sel = ", ".join(group_cols)
            rows = db.execute(
                text(
                    geo_cte + f"""
                    SELECT COALESCE(value_converted, value) AS v,
                           {sel},
                           COUNT(*) AS n,
                           SUM(COUNT(*)) OVER (PARTITION BY {sel}) AS denominator
                    FROM param_occurrence
                    WHERE project_id = :pid AND ({key_predicate}) {geo_predicate}
                    GROUP BY v, {sel}
                    ORDER BY v
                    """
                ),
                {"pid": project_id, **key_params, **geo_params},
            ).fetchall()
            for r in rows:
                v = r[0]
                dimensions = {c: r[1 + i] for i, c in enumerate(group_cols)}
                group_totals[tuple(dimensions.values())] = {**dimensions, "n": int(r[-1])}
                if v is None:
                    continue
                g = {"n": int(r[-2])}
                for i, c in enumerate(group_cols):
                    g[c] = r[1 + i]
                    if c == "operator":
                        g["operator_color"] = _op_color(r[1 + i])
                    elif c == "band":
                        g["band_color"] = _band_color(r[1 + i])
                by_value.setdefault(str(v), []).append(g)

        values_out: list[dict[str, Any]] = []
        for v, groups in by_value.items():
            values_out.append({
                "value":         v,
                "value_display": f"{v} {unit}" if unit else v,
                "groups":        groups,
            })

        # Verdict : IDENTIQUE si 1 valeur distincte, DIFFERENT si >1.
        if distinct_vals == 0:
            verdict = "NON_COMPARE"; comparability = "NO_DATA"
        elif distinct_vals == 1:
            verdict = "IDENTIQUE"; comparability = "COMPARABLE"
        else:
            verdict = "DIFFERENT"; comparability = "COMPARABLE"

        block: dict[str, Any] = {
            "param_key":      key,
            "display_name":   display_name,
            "unit":           unit,
            "choice_of":      choice_of,
            "discriminators": None,
            "origin":         origin,
            "n_total":        int(n_total),
            "distinct_values": int(distinct_vals),
            "values":         values_out,
            "group_totals":   list(group_totals.values()),
            "comparability":  comparability,
            "verdict":        verdict,
            "result_id":      _result_id(project_id, key, group_by),
            "status":         "AVAILABLE",
            "reason":         None,
        }
        if coverage is not None:
            block["coverage"] = coverage
        blocks.append(block)

    if geo_predicate:
        scope = json.dumps({key: sorted(set(values)) for key, values in sorted((geographic or {}).items()) if values}, sort_keys=True)
        for block in blocks:
            block["source_result_id"] = block["result_id"]
            block["result_id"] = hashlib.sha256(f"{block['result_id']}:{scope}".encode()).hexdigest()[:16]
    return {
        "project_id":        project_id,
        "group_by":          group_by,
        "blocks":            blocks,
        "group_by_options":  group_by_options,
    }


# ---------------------------------------------------------------------------
# Fiche paramètre
# ---------------------------------------------------------------------------


def build_param_sheet(db: Session, project_id: str, key: str) -> dict[str, Any]:
    meta = db.execute(
        text(
            """
            SELECT display_name, unit_converted, origin, choice_of,
                   COUNT(*) AS n_total
            FROM param_occurrence
            WHERE project_id = :pid AND param_key = :k
            GROUP BY display_name, unit_converted, origin, choice_of
            ORDER BY COUNT(*) DESC LIMIT 1
            """
        ),
        {"pid": project_id, "k": key},
    ).first()
    if meta is None:
        return {
            "project_id":        project_id,
            "param_key":         key,
            "display_name":      key.rsplit("/", 1)[-1] if "/" in key else key,
            "unit":              None,
            "choice_of":         None,
            "discriminators_examples": [],
            "origin":            "network_config",
            "source":            "param_occurrence (vide pour ce projet)",
            "carrying_messages": [],
            "n_total":           0,
            "sample_paths":      [],
            "kpi_hint":          None,
        }
    display_name, unit, origin, choice_of, n_total = meta
    # Jusqu'à 5 discriminators distincts
    discs = db.execute(
        text(
            """
            SELECT DISTINCT discriminators FROM param_occurrence
            WHERE project_id = :pid AND param_key = :k
              AND discriminators IS NOT NULL
            LIMIT 5
            """
        ),
        {"pid": project_id, "k": key},
    ).fetchall()
    # Messages porteurs
    msgs = db.execute(
        text(
            """
            SELECT message, COUNT(*) FROM param_occurrence
            WHERE project_id = :pid AND param_key = :k
            GROUP BY message ORDER BY COUNT(*) DESC
            """
        ),
        {"pid": project_id, "k": key},
    ).fetchall()
    # 3 sample paths bruts
    sample_paths = db.execute(
        text(
            """
            SELECT DISTINCT path FROM param_occurrence
            WHERE project_id = :pid AND param_key = :k
            LIMIT 3
            """
        ),
        {"pid": project_id, "k": key},
    ).fetchall()

    kpi_hint = None
    if origin == "ue_report":
        # Heuristique : param_key avec 'rsrp' → KPI_RSRP_AT_MR
        if "rsrp" in key.lower():   kpi_hint = "LTE_RF_RSRP"
        elif "rsrq" in key.lower(): kpi_hint = "LTE_RF_RSRQ"

    return {
        "project_id":        project_id,
        "param_key":         key,
        "display_name":      display_name,
        "unit":              unit,
        "choice_of":         choice_of,
        "discriminators_examples": [r[0] for r in discs if r[0] is not None],
        "origin":            origin,
        "source":            f"param_occurrence (project_id={project_id}, {n_total} occurrences)",
        "carrying_messages": [{"message": r[0], "n": int(r[1])} for r in msgs],
        "n_total":           int(n_total),
        "sample_paths":      [r[0] for r in sample_paths],
        "kpi_hint":          kpi_hint,
    }
