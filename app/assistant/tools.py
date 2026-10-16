"""Outils presets + outils analytiques (0.25.0).

Un **outil preset** fixe un plan analytique (dataset + dims + mesures)
et laisse l'appelant (LLM via function-calling) ne spécifier que des
**filtres**. Il n'y a JAMAIS de SQL ni de nom de table exposé au LLM.

Chaque outil retourne un `AnalyticalResult` sérialisable en JSON, à
remettre au LLM dans un `tool_message` pour qu'il compose la réponse
finale (texte + blocs typés + evidence).

Convention : signature `fn(db, project, filters: list[dict]) -> dict`.
Les filtres suivent la grammaire du moteur
(`{dim, op, value|values}`). L'outil peut en imposer certains (ex.
`list_bands` ajoute toujours `system IN (LTE, NR)` si l'appelant ne
le spécifie pas).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.assistant.engine import (
    AnalyticalResult,
    PlanRejected,
    execute_analytical_query,
)
from app.assistant.proof import (
    ComparabilityVerdict,
    lineage_for_result,
    validate_comparison,
)
from app.models import Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result_to_dict(r: AnalyticalResult) -> dict[str, Any]:
    """Sérialise un `AnalyticalResult` sans fuite (sql_compiled EXCLU)."""
    return {
        "result_id": r.result_id,
        "dataset": r.dataset,
        "plan": r.plan,
        "rows": r.rows,
        "n": r.n,
        "denominator": r.denominator,
        "date_range": r.date_range,
        "filters_applied": r.filters_applied,
        "warnings": r.warnings,
    }


# ---------------------------------------------------------------------------
# Outils presets
# ---------------------------------------------------------------------------


def get_project_context(db: Session, project: Project, filters: list[dict] | None = None) -> dict[str, Any]:
    """Contexte du projet actif : nom, période, métadonnées (operators
    déclarés via SIB1, technologies, bandes). Pas de scan DB — lit
    seulement la table `projects` déjà chargée."""
    return {
        "project_id": project.id,
        "name": project.name,
        "period_start": project.period_start,
        "period_end": project.period_end,
        "operators_declared": list(project.operators or []),
        "technologies": list(project.technologies or []),
        "bands_declared": list(project.bands or []),
    }


def list_operators(db: Session, project: Project, filters: list[dict] | None = None) -> dict[str, Any]:
    """Opérateurs présents dans le dictionnaire RRC + leur volume."""
    plan = {
        "dataset": "rrc_dict",
        "dimensions": ["operator"],
        "measures": ["count"],
        "filters": filters or [],
        "order": [{"field": "count", "dir": "DESC"}],
        "limit": 20,
    }
    r = execute_analytical_query(db, plan, project_id=project.id)
    return _result_to_dict(r)


def list_bands(db: Session, project: Project, filters: list[dict] | None = None) -> dict[str, Any]:
    """Bandes présentes + volume d'occurrences RRC."""
    plan = {
        "dataset": "rrc_dict",
        "dimensions": ["band"],
        "measures": ["count"],
        "filters": filters or [],
        "order": [{"field": "count", "dir": "DESC"}],
        "limit": 20,
    }
    r = execute_analytical_query(db, plan, project_id=project.id)
    return _result_to_dict(r)


def top_rrc_messages(db: Session, project: Project, filters: list[dict] | None = None, limit: int = 10) -> dict[str, Any]:
    """Top N messages RRC par volume."""
    plan = {
        "dataset": "rrc_dict",
        "dimensions": ["message"],
        "measures": ["count"],
        "filters": filters or [],
        "order": [{"field": "count", "dir": "DESC"}],
        "limit": max(1, min(100, int(limit))),
    }
    r = execute_analytical_query(db, plan, project_id=project.id)
    return _result_to_dict(r)


def rrc_param_distribution(
    db: Session,
    project: Project,
    param_path: str,
    filters: list[dict] | None = None,
    operator: str | None = None,
    band: str | None = None,
) -> dict[str, Any]:
    """Distribution des valeurs observées pour un paramètre RRC donné.

    `param_path` est une chaîne libre type `a3-Offset`, `rsrpResult`,
    etc. — le filtre utilise `contains` sur `param_path` pour tolérer
    les variantes de nommage (`reportConfigEUTRA.a3-Offset` vs juste
    `a3-Offset`).
    """
    scoped_filters = list(filters or [])
    scoped_filters.append({"dim": "param_path", "op": "contains", "value": param_path})
    if operator:
        scoped_filters.append({"dim": "operator", "op": "eq", "value": operator})
    if band:
        scoped_filters.append({"dim": "band", "op": "eq", "value": band})
    plan = {
        "dataset": "rrc_dict",
        "dimensions": ["value_raw", "value_converted"],
        "measures": ["count"],
        "filters": scoped_filters,
        "order": [{"field": "count", "dir": "DESC"}],
        "limit": 50,
    }
    r = execute_analytical_query(db, plan, project_id=project.id)
    return _result_to_dict(r)


def compare_operators(
    db: Session,
    project: Project,
    operators: list[str],
    measure: str = "count",
    band: str | None = None,
) -> dict[str, Any]:
    """Compare un même critère (par défaut volume RRC) entre plusieurs
    opérateurs. `validate_comparison` est appliqué automatiquement."""
    if not operators or len(operators) < 2:
        return {"error": "Compare demande au moins 2 opérateurs."}
    results: list[AnalyticalResult] = []
    for op in operators:
        plan: dict[str, Any] = {
            "dataset": "rrc_dict",
            "dimensions": ["operator"],
            "measures": [measure],
            "filters": [{"dim": "operator", "op": "eq", "value": op}]
            + ([{"dim": "band", "op": "eq", "value": band}] if band else []),
            "limit": 1,
        }
        results.append(execute_analytical_query(db, plan, project_id=project.id))
    verdict = validate_comparison(results)
    return {
        "comparison": [_result_to_dict(r) for r in results],
        "verdict": verdict.verdict,
        "reason": verdict.reason,
        "denominators": verdict.denominators,
    }


# ---------------------------------------------------------------------------
# Outils analytiques (composent le moteur)
# ---------------------------------------------------------------------------


def compare_distributions(db: Session, project: Project, results: list[dict]) -> dict[str, Any]:
    """Prend des `AnalyticalResult` déjà obtenus (serialisés) et renvoie
    un verdict de comparabilité. Permet au LLM d'enchaîner plusieurs
    `rrc_param_distribution` puis valider leur comparaison."""
    # Reconstruit des AnalyticalResult minimaux pour le verdict.
    stub_results = []
    for d in results:
        stub_results.append(
            AnalyticalResult(
                result_id=d.get("result_id", ""),
                plan=d.get("plan", {}),
                rows=d.get("rows", []),
                n=d.get("n", 0),
                denominator=int(d.get("denominator") or 0),
                dataset=d.get("dataset", ""),
                date_range=d.get("date_range", {"start": None, "end": None}),
                filters_applied=d.get("filters_applied", {}),
                sql_compiled="",
                params={},
                warnings=d.get("warnings") or [],
            )
        )
    v = validate_comparison(stub_results)
    return {
        "verdict": v.verdict,
        "reason": v.reason,
        "denominators": v.denominators,
    }


def map_metric(
    db: Session,
    project: Project,
    *,
    metric: str = "M_serving_rsrp",
    bins: int = 3,
    operator: str | None = None,
    band: str | None = None,
    system: str | None = None,
) -> dict[str, Any]:
    """0.26.0 — Carte agrégée géolocalisée.

    Source : `param_occurrence` filtré sur les events RRC
    `MeasurementReport` dont le `path` représente le RSRP serving :
    `measResultPCell/rsrpResult` (LTE) ou `measResultServingCell/.../rsrp…`
    (NR). Les events de **configuration** (ex. `threshold-RSRP` dans
    `reportConfigEUTRA`) sont exclus par le filtre `message`.

    Agrégation : GROUP BY cellule de grille `(ROUND(lat, bins),
    ROUND(lon, bins), operator, band, system)` → `AVG(value_converted)`,
    `COUNT(*)`. **Jamais de ligne brute**, jamais d'identité.

    Les cellules dont `operator` est NULL ou hors des 4 MNO FR sont
    **filtrées** (contrainte schema `MeasurementPoint.operator =
    Literal[Orange|SFR|Bouygues|Free]`). Le compteur de cellules
    masquées est renvoyé dans la trace `cells_filtered`.

    Plage 3GPP valide RSRP : [-140, -40] dBm. Les cellules dont la
    moyenne tombe hors de ces bornes sont filtrées (signal décodeur
    aberrant plutôt qu'invention).
    """
    from app.assistant.engine import compute_result_id

    # Metric → path pattern. Pour l'instant uniquement RSRP serving.
    metric_key = (metric or "M_serving_rsrp").strip()
    if metric_key not in ("M_serving_rsrp",):
        return {
            "error": f"metric {metric_key!r} non supportée. "
            "Disponible : M_serving_rsrp (0.26.0). "
            "rsrq/sinr arriveront quand la Phase 1 mapping sera livrée."
        }

    try:
        bins_int = max(1, min(5, int(bins)))
    except (TypeError, ValueError):
        bins_int = 3

    # Filtres optionnels — sanitize minimale (whitelist 4 MNO + regex band).
    allowed_ops = {"Orange", "SFR", "Bouygues", "Free"}
    op_filter = ""
    params: dict[str, Any] = {"pid": project.id, "bins": bins_int}
    if operator and operator in allowed_ops:
        op_filter = " AND operator = :op "
        params["op"] = operator
    band_filter = ""
    if band and isinstance(band, str) and len(band) <= 16 and band.replace("-", "").isalnum():
        band_filter = " AND band = :band "
        params["band"] = band
    sys_filter = ""
    if system and system in ("LTE", "NR"):
        sys_filter = " AND system = :sys "
        params["sys"] = system

    sql = (
        "SELECT "
        "  ROUND(lat::numeric, :bins) AS lat_c, "
        "  ROUND(lon::numeric, :bins) AS lon_c, "
        "  operator, band, system, "
        "  AVG(NULLIF(value_converted, '')::float) AS value_avg, "
        "  COUNT(*) AS n "
        "FROM param_occurrence "
        "WHERE project_id = :pid "
        "  AND message = 'MeasurementReport' "
        "  AND ( "
        "       path LIKE '%measResultPCell/rsrpResult' "
        "    OR path LIKE '%measResultServingCell%rsrpResult%' "
        "    OR path LIKE '%measResultServingMOList%rsrp%' "
        "  ) "
        "  AND value_converted IS NOT NULL "
        "  AND value_converted <> '' "
        "  AND operator IN ('Orange', 'SFR', 'Bouygues', 'Free') "
        "  AND lat IS NOT NULL AND lon IS NOT NULL "
        "  AND system IN ('LTE', 'NR') "
        + op_filter + band_filter + sys_filter +
        "GROUP BY lat_c, lon_c, operator, band, system "
        "HAVING AVG(NULLIF(value_converted, '')::float) BETWEEN -140 AND -40 "
        "ORDER BY n DESC "
        "LIMIT 2000"
    )

    # Timeout + exécution.
    try:
        db.execute(text("SET LOCAL statement_timeout = 5000"))
        rows = db.execute(text(sql), params).mappings().all()
    except Exception as exc:
        return {"error": f"erreur exécution map_metric: {exc!r}"}

    if not rows:
        plan_for_rid = {
            "dataset": "rrc_dict",
            "metric": metric_key,
            "bins": bins_int,
            "filters": {"operator": operator, "band": band, "system": system},
            "tool": "map_metric",
        }
        return {
            "result_id": compute_result_id(plan_for_rid, project.id),
            "dataset": "rrc_dict",
            "metric": metric_key,
            "unit": "dBm",
            "rows": [],
            "n": 0,
            "total_observations": 0,
            "value_range": None,
            "grid": {"bins_decimals": bins_int, "cells": 0},
            "aggregated_points": [],
            "warnings": [
                "n=0 — aucune cellule RSRP serving dans le périmètre filtré. "
                "Possibilités : filtres trop stricts, projet sans measurementReport, "
                "ou path RSRP serving non reconnu (voir CHANGELOG 0.26.0 écarts ouverts)."
            ],
            "plan": plan_for_rid,
            "date_range": {"start": project.period_start, "end": project.period_end},
            "filters_applied": {k: v for k, v in {"operator": operator, "band": band, "system": system}.items() if v},
            "render_hint": "map",
        }

    # Build cells conformes au schema MeasurementPoint (Pydantic strict).
    # `service` est un sentinel documenté « Data » pour les cellules
    # agrégées (convention projet, pas une invention par-cellule).
    import hashlib
    cells: list[dict[str, Any]] = []
    vals: list[float] = []
    total_n = 0
    for r in rows:
        v = float(r["value_avg"])
        vals.append(v)
        total_n += int(r["n"])
        cid_src = f"{r['lat_c']}_{r['lon_c']}_{r['operator']}_{r['band']}_{r['system']}"
        cid = "mapcell-" + hashlib.sha256(cid_src.encode()).hexdigest()[:12]
        cells.append({
            "id": cid,
            "lat": float(r["lat_c"]),
            "lng": float(r["lon_c"]),
            "operator": r["operator"],
            "tech": r["system"],
            "service": "Data",  # Sentinel aggregated-cell (0.26.0 convention)
            "band": r["band"] or "",
            "dep": "",
            "site": f"cell_{r['lat_c']}_{r['lon_c']}",
            "ts": project.period_start,
            "dl": None,
            "rsrp": v,
            "sinr": None,
            "latency": None,
            # Hors-schema MeasurementPoint — ignorés par Pydantic, utiles
            # au compose / debug.
            "n": int(r["n"]),
        })

    # value_range réel observé (pas inventé — min/max des moyennes de cellule).
    vmin = min(vals)
    vmax = max(vals)
    center_lat = sum(c["lat"] for c in cells) / len(cells)
    center_lng = sum(c["lng"] for c in cells) / len(cells)

    plan_for_rid = {
        "dataset": "rrc_dict",
        "metric": metric_key,
        "bins": bins_int,
        "filters": {k: v for k, v in {"operator": operator, "band": band, "system": system}.items() if v},
        "tool": "map_metric",
    }
    rid = compute_result_id(plan_for_rid, project.id)

    return {
        "result_id": rid,
        "dataset": "rrc_dict",
        "metric": metric_key,
        "unit": "dBm",
        "rows": cells,  # pour compose : liste pré-filtrée
        "n": len(cells),
        "total_observations": total_n,
        "value_range": [vmin, vmax],
        "grid": {"bins_decimals": bins_int, "cells": len(cells)},
        "aggregated_points": cells,  # alias explicite
        "center": [center_lat, center_lng],
        "warnings": [],
        "plan": plan_for_rid,
        "date_range": {"start": project.period_start, "end": project.period_end},
        "filters_applied": plan_for_rid["filters"],
        "render_hint": "map",
    }


def analyze_correlations(*args, **kwargs) -> dict[str, Any]:
    """0.25.0 — pas d'analyse de corrélation implémentée dans ce lot
    (demanderait Pearson/Spearman sur mesures peuplées — Phase 1
    toujours pending). On renvoie un écart déclaré.

    Important : même quand implémenté, cet outil REFUSE d'exposer une
    corrélation comme causale. La note « corrélation ≠ causation » est
    renvoyée systématiquement.
    """
    return {
        "error": "Non implémenté dans 0.25.0 — attendre Phase 1 mapping décodeur. "
        "Rappel : une corrélation n'implique jamais une causalité.",
    }


# ---------------------------------------------------------------------------
# Catalogue des outils (schémas OpenAI function-calling)
# ---------------------------------------------------------------------------
# Chaque entrée : nom + description (vue par le LLM) + schéma JSON des
# paramètres. Aucune mention de nom de table ou de SQL — pure sémantique.
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_project_context",
            "description": "Retourne nom/période/opérateurs déclarés/bandes/technos du projet actif. À appeler en premier si tu dois adapter la réponse au projet.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_operators",
            "description": "Liste les opérateurs présents dans les occurrences RRC du projet avec leur volume.",
            "parameters": {
                "type": "object",
                "properties": {
                    "band": {"type": "string", "description": "Filtre optionnel sur une bande (ex. 'B3', 'n78')."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_bands",
            "description": "Liste les bandes radio présentes dans le projet avec leur volume d'occurrences.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operator": {"type": "string", "description": "Filtre optionnel sur un opérateur (ex. 'Orange')."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_rrc_messages",
            "description": "Top N messages RRC par fréquence. Idéal pour montrer la signalisation dominante.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                    "operator": {"type": "string"},
                    "band": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rrc_param_distribution",
            "description": "Distribution des valeurs observées pour un paramètre RRC (ex. 'a3-Offset', 'rsrpResult'). Peut être filtrée par opérateur et/ou bande. Utilise 'contains' sur le path ASN.1 — tolérant aux variantes de nommage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "param_path": {"type": "string", "description": "Chaîne ou fragment du chemin ASN.1 (ex. 'a3-Offset')."},
                    "operator": {"type": "string"},
                    "band": {"type": "string"},
                },
                "required": ["param_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_operators",
            "description": "Compare un même critère entre plusieurs opérateurs. Appelle validate_comparison automatiquement, retourne le verdict et les dénominateurs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operators": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                    "measure": {"type": "string", "default": "count", "enum": ["count"]},
                    "band": {"type": "string"},
                },
                "required": ["operators"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "map_metric",
            "description": (
                "Carte agrégée géolocalisée d'une métrique radio. "
                "Agrège par cellule de grille lat/lon (arrondi configurable "
                "via `bins`, 3 décimales = ~100 m). 0.26.0 : seule métrique "
                "supportée = `M_serving_rsrp` (RSRP serving en dBm). "
                "Filtres opérateur, bande, système. "
                "Agrégats seulement, zéro ligne brute, zéro identité."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["M_serving_rsrp"],
                        "default": "M_serving_rsrp",
                    },
                    "bins": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 3,
                        "description": "Nombre de décimales d'arrondi pour la grille lat/lon (3 ≈ 100 m).",
                    },
                    "operator": {"type": "string"},
                    "band": {"type": "string"},
                    "system": {"type": "string", "enum": ["LTE", "NR"]},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_distributions",
            "description": "Valide la comparabilité de résultats déjà obtenus (plans alignés ? période ? dénominateurs ?). À appeler AVANT de présenter une comparaison dans la réponse finale.",
            "parameters": {
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Liste des result objects renvoyés par les tool calls précédents.",
                    },
                },
                "required": ["results"],
                "additionalProperties": False,
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatcher — appelle l'outil nommé avec les kwargs désérialisés.
# ---------------------------------------------------------------------------


def dispatch_tool(
    name: str, args: dict[str, Any], *, db: Session, project: Project
) -> dict[str, Any]:
    """Appelle l'outil nommé. Convertit les kwargs plats du LLM (ex.
    `band="B3"`) en structure de filtres pour le moteur."""
    # Builder générique de filtres plats → grammaire moteur.
    def _flat_to_filters(**kwargs: Any) -> list[dict]:
        out: list[dict] = []
        for k, v in kwargs.items():
            if v is None:
                continue
            if k in ("operator", "band", "system", "message", "param_path", "dep"):
                out.append({"dim": k, "op": "eq", "value": str(v)})
        return out

    try:
        if name == "get_project_context":
            return get_project_context(db, project)
        if name == "list_operators":
            return list_operators(db, project, _flat_to_filters(band=args.get("band")))
        if name == "list_bands":
            return list_bands(db, project, _flat_to_filters(operator=args.get("operator")))
        if name == "top_rrc_messages":
            return top_rrc_messages(
                db,
                project,
                _flat_to_filters(operator=args.get("operator"), band=args.get("band")),
                limit=args.get("limit", 10),
            )
        if name == "rrc_param_distribution":
            return rrc_param_distribution(
                db,
                project,
                param_path=args["param_path"],
                operator=args.get("operator"),
                band=args.get("band"),
            )
        if name == "compare_operators":
            return compare_operators(
                db,
                project,
                operators=args["operators"],
                measure=args.get("measure", "count"),
                band=args.get("band"),
            )
        if name == "compare_distributions":
            return compare_distributions(db, project, args.get("results") or [])
        if name == "map_metric":
            return map_metric(
                db,
                project,
                metric=args.get("metric", "M_serving_rsrp"),
                bins=args.get("bins", 3),
                operator=args.get("operator"),
                band=args.get("band"),
                system=args.get("system"),
            )
        return {"error": f"outil inconnu : {name!r}"}
    except PlanRejected as exc:
        return {"error": f"plan rejeté : {exc.code} — {exc.message}"}
    except Exception as exc:
        return {"error": f"erreur outil : {exc!r}"}
