"""Service dictionnaire v2 (0.45.0) — tree + distribution + fiche."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


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


def build_dict_tree(db: Session, project_id: str, view: str) -> dict[str, Any]:
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

    # Groupage python : techno → origin → message → group → feuilles
    tree: dict[str, dict[str, dict[str, dict[str, list[dict]]]]] = {}
    for r in rows:
        system = (r[0] or "LTE")
        origin = (r[1] or "network_config")
        msg    = (r[2] or "?")
        group  = (r[3] or "Autres")
        leaf = {
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

    return {
        "project_id":         project_id,
        "view":               view,
        "total_rows":         int(total_rows),
        "distinct_param_keys": int(distinct_param_keys),
        "tree":               tree_out,
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
) -> dict[str, Any]:
    """Distribution de valeurs par (param_key, group_by). Pour chaque
    clé : values[] = {value, value_display, groups{operator?/band?: n}}.
    """
    blocks: list[dict[str, Any]] = []

    for key in keys:
        # Métadonnées communes (unit, origin, choice_of, discriminators).
        meta = db.execute(
            text(
                """
                SELECT display_name, unit_converted, origin, choice_of,
                       MIN(discriminators::text), COUNT(*) AS n_total,
                       COUNT(DISTINCT value_converted) AS distinct_vals
                FROM param_occurrence
                WHERE project_id = :pid AND param_key = :k
                GROUP BY display_name, unit_converted, origin, choice_of
                ORDER BY COUNT(*) DESC LIMIT 1
                """
            ),
            {"pid": project_id, "k": key},
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

        # Groupage (operator | band | operator_band)
        if group_by == "operator":
            group_cols = ["operator"]
        elif group_by == "band":
            group_cols = ["band"]
        else:
            group_cols = ["operator", "band"]
        sel = ", ".join(group_cols)
        rows = db.execute(
            text(
                f"""
                SELECT COALESCE(value_converted, value) AS v,
                       {sel},
                       COUNT(*) AS n
                FROM param_occurrence
                WHERE project_id = :pid AND param_key = :k
                GROUP BY v, {sel}
                ORDER BY v
                """
            ),
            {"pid": project_id, "k": key},
        ).fetchall()

        # Pivot values[] = {value, value_display, groups[]}.
        by_value: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            v = r[0]
            if v is None:
                continue
            g: dict[str, Any] = {"n": int(r[-1])}
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

        blocks.append({
            "param_key":      key,
            "display_name":   display_name,
            "unit":           unit,
            "choice_of":      choice_of,
            "discriminators": None,
            "origin":         origin,
            "n_total":        int(n_total),
            "distinct_values": int(distinct_vals),
            "values":         values_out,
            "comparability":  comparability,
            "verdict":        verdict,
            "result_id":      _result_id(project_id, key, group_by),
        })

    return {
        "project_id": project_id,
        "group_by":   group_by,
        "blocks":     blocks,
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
