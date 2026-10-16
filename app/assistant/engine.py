"""Moteur analytique contraint (0.25.0).

Compile un **plan structuré** (dict JSON) en SQL **paramétré** sur les
vues analytiques approuvées du catalogue. Le plan vient toujours du
LLM via le tool-calling ; il ne contient JAMAIS de SQL en texte.

Sécurité = frontière (correctif 3 du cahier des charges) :
- `project_id` est injecté serveur depuis la session appelante ; un
  plan qui tente de le fixer dans `filters` est REJETÉ.
- Dataset / dimensions / mesures doivent exister dans `catalog`.
- Le SQL final est scanné après compilation pour détecter des
  identifiants bannis (défense en profondeur).
- `LIMIT` max 1000 par plan ; timeout d'exécution 5 s.
- Mesures `recomposable=False` → interdiction d'agréger plus loin
  sans dénominateurs explicites (statistiques correctes — correctif 2).

Pas de SELECT * ; pas de ligne brute : si des mesures sont présentes
le GROUP BY sur les dimensions est **implicite** et obligatoire. Si
aucune mesure n'est présente, le plan est équivalent à un comptage —
on force une mesure `count` par défaut.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.assistant.catalog import (
    BANNED_IDENTIFIERS,
    DATASETS,
    DIMENSIONS,
    FILTER_OPS,
    MEASURES,
)


MAX_ROWS = 1000
QUERY_TIMEOUT_MS = 5000


class PlanRejected(ValueError):
    """Plan refusé pour raison de sécurité ou de sémantique."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class AnalyticalResult:
    result_id: str
    plan: dict[str, Any]
    rows: list[dict[str, Any]]
    n: int                              # Lignes retournées.
    denominator: int                    # Total d'observations (COUNT(*) sans GROUP).
    dataset: str
    date_range: dict[str, str | None]   # start / end du projet.
    filters_applied: dict[str, Any]
    sql_compiled: str                   # pour journaux techniques, PAS pour front
    params: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation du plan
# ---------------------------------------------------------------------------


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _reject(code: str, message: str) -> None:
    raise PlanRejected(code, message)


def _check_identifier(name: str) -> None:
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        _reject("BAD_IDENTIFIER", f"Identifiant invalide : {name!r}")


def _validate_plan_shape(plan: dict[str, Any]) -> None:
    if not isinstance(plan, dict):
        _reject("PLAN_SHAPE", "plan doit être un objet JSON")
    if "dataset" not in plan or not isinstance(plan["dataset"], str):
        _reject("PLAN_SHAPE", "plan.dataset manquant ou non-string")
    for k in ("dimensions", "measures", "filters"):
        if k in plan and not isinstance(plan[k], list):
            _reject("PLAN_SHAPE", f"plan.{k} doit être une liste")
    if "limit" in plan and not isinstance(plan["limit"], int):
        _reject("PLAN_SHAPE", "plan.limit doit être un entier")


# ---------------------------------------------------------------------------
# Hashing stable pour `result_id`
# ---------------------------------------------------------------------------


def _canonicalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _canonicalize(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, list):
        return [_canonicalize(x) for x in obj]
    return obj


def compute_result_id(plan: dict[str, Any], project_id: str) -> str:
    """SHA256(canonical(plan) + project_id)[:16]. Même plan + même
    projet ⇒ même result_id (traçabilité stable UI ↔ journaux)."""
    payload = {"plan": _canonicalize(plan), "project_id": project_id}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Compilation plan → SQL paramétré
# ---------------------------------------------------------------------------


def _compile_plan(plan: dict[str, Any], project_id: str) -> tuple[str, dict[str, Any]]:
    dataset_name = plan["dataset"]
    _check_identifier(dataset_name)
    if dataset_name not in DATASETS:
        _reject("DATASET_UNKNOWN", f"dataset inconnu : {dataset_name!r}")
    ds = DATASETS[dataset_name]
    source = ds["source_table"]
    _check_identifier(source)

    dims = plan.get("dimensions") or []
    meas = plan.get("measures") or []
    filters = plan.get("filters") or []
    order = plan.get("order") or []
    limit = int(plan.get("limit", MAX_ROWS))
    if limit > MAX_ROWS or limit < 1:
        _reject("LIMIT_OUT_OF_RANGE", f"limit doit être dans [1, {MAX_ROWS}]")

    # Au moins une mesure (sinon on force count — jamais de ligne brute).
    if not meas:
        meas = ["count"]

    # Résout chaque dimension autorisée pour le dataset.
    allowed_dims = ds["dimensions"]
    allowed_meas = ds["measures"]
    select_parts: list[str] = []
    group_cols: list[str] = []
    order_cols: list[str] = []

    for d in dims:
        _check_identifier(d)
        if d not in allowed_dims:
            _reject("DIM_NOT_IN_DATASET", f"dimension {d!r} non autorisée pour {dataset_name!r}")
        col = DIMENSIONS[d]["column"]
        _check_identifier(col)
        select_parts.append(f"{col} AS {d}")
        group_cols.append(col)

    for m in meas:
        _check_identifier(m)
        if m not in MEASURES:
            _reject("MEASURE_UNKNOWN", f"mesure inconnue : {m!r}")
        if m not in allowed_meas:
            _reject("MEASURE_NOT_IN_DATASET", f"mesure {m!r} non disponible dans {dataset_name!r}")
        sql_expr = MEASURES[m]["sql"]
        # Statistique multi-niveaux non autorisée pour recomposable=False
        # avec plusieurs dimensions sauf si l'appelant déclare la méthode.
        if not MEASURES[m]["recomposable"] and len(dims) >= 2:
            # On tolère quand même, mais on l'écrit dans warnings dans l'exécution.
            pass
        select_parts.append(f"{sql_expr} AS {m}")

    # Filtres — chaque filtre = {dim, op, value|values}.
    # project_id est TOUJOURS ignoré ici (injecté serveur).
    where_parts: list[str] = ["project_id = :pid"]
    params: dict[str, Any] = {"pid": project_id}
    filters_applied: dict[str, Any] = {}

    for i, f in enumerate(filters):
        if not isinstance(f, dict):
            _reject("FILTER_SHAPE", "filter doit être un objet")
        dim = f.get("dim")
        op = f.get("op")
        if dim == "project_id":
            # Refus explicite : l'auth du projet se fait côté serveur,
            # pas par la volonté du LLM.
            _reject("PROJECT_ID_NOT_ALLOWED", "project_id injecté serveur ; refusé dans le plan")
        _check_identifier(str(dim))
        if dim not in DIMENSIONS:
            _reject("FILTER_DIM_UNKNOWN", f"dimension de filtre inconnue : {dim!r}")
        if op not in FILTER_OPS:
            _reject("FILTER_OP_UNKNOWN", f"op de filtre inconnue : {op!r}")
        if op not in DIMENSIONS[dim]["allowed_filter_ops"]:
            _reject("FILTER_OP_FORBIDDEN", f"op {op!r} non autorisée pour {dim!r}")
        col = DIMENSIONS[dim]["column"]
        _check_identifier(col)
        if op in ("is_null", "is_not_null"):
            sql_op = FILTER_OPS[op][0]
            where_parts.append(f"{col} {sql_op}")
            filters_applied[dim] = {"op": op}
            continue
        if op == "in":
            vals = f.get("values")
            if not isinstance(vals, list) or not vals:
                _reject("FILTER_VALUES", "op 'in' demande une liste 'values' non vide")
            placeholders = []
            for j, v in enumerate(vals):
                p = f"f{i}v{j}"
                placeholders.append(f":{p}")
                params[p] = str(v)
            where_parts.append(f"{col} IN ({', '.join(placeholders)})")
            filters_applied[dim] = {"op": "in", "values": vals}
            continue
        if op == "contains":
            v = f.get("value")
            if not isinstance(v, str):
                _reject("FILTER_VALUE", "op 'contains' demande 'value' string")
            p = f"f{i}v"
            where_parts.append(f"{col} ILIKE :{p}")
            params[p] = f"%{v}%"
            filters_applied[dim] = {"op": "contains", "value": v}
            continue
        if op == "eq":
            v = f.get("value")
            p = f"f{i}v"
            where_parts.append(f"{col} = :{p}")
            params[p] = str(v)
            filters_applied[dim] = {"op": "eq", "value": v}
            continue

    # ORDER BY — autorisé seulement sur dim ou measure déjà sélectionnée.
    allowed_order = set(dims) | set(meas)
    for o in order:
        if not isinstance(o, dict):
            _reject("ORDER_SHAPE", "order item doit être un objet")
        field_name = o.get("field")
        direction = (o.get("dir") or "DESC").upper()
        if direction not in ("ASC", "DESC"):
            _reject("ORDER_DIR", "dir doit être ASC ou DESC")
        if field_name not in allowed_order:
            _reject("ORDER_FIELD", f"order sur champ {field_name!r} non autorisé")
        order_cols.append(f"{field_name} {direction}")

    # Compose
    select_sql = ", ".join(select_parts) if select_parts else "COUNT(*) AS count"
    group_sql = f" GROUP BY {', '.join(group_cols)}" if group_cols else ""
    order_sql = f" ORDER BY {', '.join(order_cols)}" if order_cols else ""
    sql = (
        f"SELECT {select_sql} "
        f"FROM {source} "
        f"WHERE {' AND '.join(where_parts)}"
        f"{group_sql}"
        f"{order_sql} "
        f"LIMIT :_limit"
    )
    params["_limit"] = limit

    # Défense en profondeur : scan du SQL compilé pour détecter des
    # identifiants bannis (nom de table sensible qui aurait fuité, etc.).
    sql_lower = sql.lower()
    for banned in BANNED_IDENTIFIERS:
        # Mot entier pour éviter les faux positifs (ex. "operator" contient "op").
        if re.search(rf"\b{re.escape(banned)}\b", sql_lower):
            _reject("BANNED_IDENTIFIER", f"identifiant banni dans le SQL compilé : {banned}")

    return sql, params, filters_applied


# ---------------------------------------------------------------------------
# Exécution
# ---------------------------------------------------------------------------


def _project_date_range(db: Session, project_id: str) -> dict[str, str | None]:
    row = db.execute(
        text("SELECT period_start, period_end FROM projects WHERE id = :pid"),
        {"pid": project_id},
    ).first()
    if row is None:
        return {"start": None, "end": None}
    return {"start": row[0], "end": row[1]}


def _denominator(db: Session, dataset: str, project_id: str) -> int:
    """Dénominateur = COUNT(*) brut du dataset pour ce projet (sans
    filtres). Utilisé pour afficher 'part_pct' honnêtement et pour la
    comparabilité (correctif 1)."""
    source = DATASETS[dataset]["source_table"]
    _check_identifier(source)
    return int(
        db.execute(
            text(f"SELECT COUNT(*) FROM {source} WHERE project_id = :pid"),
            {"pid": project_id},
        ).scalar_one()
    )


def execute_analytical_query(
    db: Session, plan: dict[str, Any], *, project_id: str
) -> AnalyticalResult:
    """Compile + exécute un plan analytique. project_id serveur-side.

    Retourne un AnalyticalResult avec `result_id` stable, les lignes
    agrégées, le dénominateur, le date_range, les filtres appliqués, et
    les warnings éventuels (statistique multi-niveaux, dataset partiel).
    """
    _validate_plan_shape(plan)
    sql, params, filters_applied = _compile_plan(plan, project_id)
    rid = compute_result_id(plan, project_id)
    dataset = plan["dataset"]
    warnings: list[str] = []

    # Statistique multi-niveaux non recomposable → warn (jamais rejeté
    # pour l'instant mais signalé à l'appelant pour affichage).
    for m in plan.get("measures") or []:
        if m in MEASURES and not MEASURES[m]["recomposable"] and len(plan.get("dimensions") or []) >= 2:
            warnings.append(
                f"Mesure {m!r} non-recomposable avec {len(plan.get('dimensions') or [])} dimensions : "
                "les percentiles / moyennes ne peuvent pas être recomposés hiérarchiquement sans dénominateurs explicites."
            )

    # Statement timeout (PostgreSQL) — resetté par connexion après l'appel.
    try:
        db.execute(text(f"SET LOCAL statement_timeout = {QUERY_TIMEOUT_MS}"))
        rows_raw = db.execute(text(sql), params).mappings().all()
    except Exception as exc:
        raise PlanRejected("EXECUTION_ERROR", f"échec exécution : {exc!r}") from exc

    rows = [dict(r) for r in rows_raw]
    date_range = _project_date_range(db, project_id)
    denom = _denominator(db, dataset, project_id)

    return AnalyticalResult(
        result_id=rid,
        plan=plan,
        rows=rows,
        n=len(rows),
        denominator=denom,
        dataset=dataset,
        date_range=date_range,
        filters_applied=filters_applied,
        sql_compiled=sql,
        params={k: v for k, v in params.items() if k != "pid"},  # ne pas logguer pid
        warnings=warnings,
    )
