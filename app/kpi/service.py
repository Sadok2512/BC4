"""Calcul de statut KPI + exécution des agrégats (0.35.0).

Discipline (correctif de la spec) :
- Aucun chiffre sans sa requête.
- Scope `project_id` injecté serveur, jamais depuis le client.
- Zéro ligne brute, zéro SQL exposé au front.
- Ordre `(capture_id, seq)` jamais `ts` (ts inter-capture n'a aucun sens).
- Trend bucket = DATE DE CAPTURE (`nmf_file.start_at`), jamais un ordre ts.
- Un seul jour → trend à 1 point déclaré `period_unique`.
- `result_id` stable via `compute_result_id` (plan canonique + project_id).
- `validate_comparison` : verdict de comparabilité sur les sous-groupes
  by_operator (≥ 2 opérateurs).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.assistant.engine import AnalyticalResult, compute_result_id
from app.assistant.proof import ComparabilityVerdict, validate_comparison
from app.kpi.catalog import (
    CATALOG,
    FAMILIES_ORDER,
    KPI_BY_CODE,
    KPI_CATALOG_VERSION,
    KpiDef,
    Status,
)


# ---------------------------------------------------------------------------
# Parsing de date "DD.MM.YYYY HH:MM:SS.mmm" → "YYYY-MM-DD" côté SQL.
# ---------------------------------------------------------------------------
# `nmf_file.start_at` est stocké en VARCHAR par l'ingest.
def _date_from_start_at(alias: str = "nmf_file") -> str:
    """SQL expression returning YYYY-MM-DD from `<alias>.start_at`."""
    return (
        f"(substr({alias}.start_at, 7, 4) || '-' || "
        f"substr({alias}.start_at, 4, 2) || '-' || "
        f"substr({alias}.start_at, 1, 2))"
    )


# ---------------------------------------------------------------------------
# Statut par projet
# ---------------------------------------------------------------------------


@dataclass
class KpiStatus:
    status: Status
    reason: str | None


_MP_METRIC_COLS = {
    "rsrp", "rsrq", "sinr", "cqi", "dl", "thrpt_ul", "tx_power", "latency",
}


def _mp_metric_available(db: Session, project_id: str, col: str) -> bool:
    if col not in _MP_METRIC_COLS:
        raise ValueError(f"mp_metric_arg inconnu : {col!r}")
    row = db.execute(
        text(
            f"SELECT 1 FROM measurement_points "
            f"WHERE project_id = :pid AND {col} IS NOT NULL LIMIT 1"
        ),
        {"pid": project_id},
    ).first()
    return row is not None


def _param_match(
    db: Session, project_id: str, *, column: str, op: str, arg: str,
) -> bool:
    assert column in ("path", "message")
    assert op in ("eq", "ilike")
    sql_op = "=" if op == "eq" else "ILIKE"
    row = db.execute(
        text(
            f"SELECT 1 FROM param_occurrence "
            f"WHERE project_id = :pid AND {column} {sql_op} :arg LIMIT 1"
        ),
        {"pid": project_id, "arg": arg},
    ).first()
    return row is not None


def compute_status(db: Session, project_id: str, kpi: KpiDef) -> KpiStatus:
    rule = kpi.availability
    arg = kpi.availability_arg

    if rule == "always_unvalidated":
        return KpiStatus("UNVALIDATED", kpi.unavailable_reason)
    if rule == "always_unavailable":
        return KpiStatus("UNAVAILABLE", kpi.unavailable_reason)

    if rule == "mp_metric":
        if arg is None:
            raise ValueError(f"{kpi.code}: mp_metric sans arg")
        return (
            KpiStatus("AVAILABLE", None)
            if _mp_metric_available(db, project_id, arg)
            else KpiStatus(
                "PENDING", kpi.unavailable_reason or f"measurement_points.{arg} NULL",
            )
        )

    if rule == "param_message":
        if arg is None:
            raise ValueError(f"{kpi.code}: param_message sans arg")
        return (
            KpiStatus("AVAILABLE", None)
            if _param_match(db, project_id, column="message", op="eq", arg=arg)
            else KpiStatus(
                "UNAVAILABLE",
                f"aucune occurrence RRC pour message={arg!r} dans ce projet",
            )
        )

    if rule == "param_message_ilike":
        if arg is None:
            raise ValueError(f"{kpi.code}: param_message_ilike sans arg")
        return (
            KpiStatus("AVAILABLE", None)
            if _param_match(db, project_id, column="message", op="ilike", arg=arg)
            else KpiStatus(
                "UNAVAILABLE",
                f"aucune occurrence RRC pour message ILIKE {arg!r}",
            )
        )

    if rule == "param_path":
        if arg is None:
            raise ValueError(f"{kpi.code}: param_path sans arg")
        return (
            KpiStatus("AVAILABLE", None)
            if _param_match(
                db, project_id, column="path", op=kpi.availability_op, arg=arg
            )
            else KpiStatus(
                "UNAVAILABLE",
                f"aucune occurrence RRC pour path {kpi.availability_op} {arg!r}",
            )
        )

    raise ValueError(f"{kpi.code}: règle availability inconnue : {rule!r}")


# ---------------------------------------------------------------------------
# /catalog
# ---------------------------------------------------------------------------


def build_catalog_tree(db: Session, project_id: str) -> dict[str, Any]:
    families: dict[str, list[dict[str, Any]]] = {name: [] for name in FAMILIES_ORDER}
    for kpi in CATALOG:
        s = compute_status(db, project_id, kpi)
        families[kpi.family].append(
            {
                "code": kpi.code,
                "name": kpi.name,
                "techno": kpi.techno,
                "nature": kpi.nature,
                "unit": kpi.unit,
                "source": kpi.source,
                "formula": kpi.formula,
                "definition": kpi.definition,
                "status": s.status,
                "reason": s.reason,
            }
        )
    return {
        "project_id": project_id,
        "catalog_version": KPI_CATALOG_VERSION,
        "families": [
            {"name": name, "kpis": families[name]}
            for name in FAMILIES_ORDER
            if families[name]
        ],
    }


# ---------------------------------------------------------------------------
# /filters
# ---------------------------------------------------------------------------


def _distinct_values(
    db: Session, project_id: str, source: str, column: str
) -> list[str]:
    assert source in ("measurement_points", "param_occurrence", "nmf_file")
    assert column.replace("_", "").isalnum()
    rows = db.execute(
        text(
            f"SELECT DISTINCT {column} FROM {source} "
            f"WHERE project_id = :pid AND {column} IS NOT NULL "
            f"ORDER BY {column}"
        ),
        {"pid": project_id},
    ).all()
    return [r[0] for r in rows if r[0] is not None and str(r[0]) != ""]


def build_filters(db: Session, project_id: str) -> dict[str, Any]:
    ops_mp = _distinct_values(db, project_id, "measurement_points", "operator")
    ops_po = _distinct_values(db, project_id, "param_occurrence", "operator")
    operators = sorted(set(ops_mp) | set(ops_po))

    rats_rat = _distinct_values(db, project_id, "measurement_points", "rat")
    rats_tech = _distinct_values(db, project_id, "measurement_points", "tech")
    rats_sys = _distinct_values(db, project_id, "param_occurrence", "system")
    rats = sorted(set(rats_rat) | set(rats_tech) | set(rats_sys))

    bands_mp = _distinct_values(db, project_id, "measurement_points", "band")
    bands_po = _distinct_values(db, project_id, "param_occurrence", "band")
    bands = sorted(set(bands_mp) | set(bands_po))

    service_types = _distinct_values(
        db, project_id, "measurement_points", "service_type"
    )
    envs_mp = _distinct_values(db, project_id, "measurement_points", "env")
    envs_nmf = _distinct_values(db, project_id, "nmf_file", "env")
    envs = sorted(set(envs_mp) | set(envs_nmf))

    date_expr = _date_from_start_at("nmf_file")
    period_row = db.execute(
        text(
            f"SELECT MIN({date_expr}), MAX({date_expr}) "
            f"FROM nmf_file WHERE project_id = :pid AND start_at IS NOT NULL"
        ),
        {"pid": project_id},
    ).first()
    period_min = period_row[0] if period_row else None
    period_max = period_row[1] if period_row else None

    cell_rows = db.execute(text("SELECT COUNT(*) FROM cell_ref")).scalar_one() or 0
    geo: dict[str, Any] = {
        "available": bool(cell_rows > 0),
        "cell_ref_rows": int(cell_rows),
    }
    if not geo["available"]:
        geo["reason"] = "cell_ref vide — import ARCEP/geo non effectué"

    return {
        "project_id": project_id,
        "operators": operators,
        "rats": rats,
        "bands": bands,
        "service_types": service_types,
        "envs": envs,
        "period": {"min": period_min, "max": period_max},
        "geo": geo,
    }


# ---------------------------------------------------------------------------
# /kpi/{code}
# ---------------------------------------------------------------------------


@dataclass
class KpiFilters:
    operator: tuple[str, ...] = ()
    rat: tuple[str, ...] = ()
    band: tuple[str, ...] = ()
    service_type: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None

    def to_plan(self) -> dict[str, Any]:
        return {
            "operator": sorted(self.operator),
            "rat": sorted(self.rat),
            "band": sorted(self.band),
            "service_type": sorted(self.service_type),
            "env": sorted(self.env),
            "date_from": self.date_from,
            "date_to": self.date_to,
        }


def _in_clause(name: str, values: Iterable[str], params: dict[str, Any]) -> str:
    vals = tuple(values)
    if not vals:
        return "TRUE"
    placeholders = []
    for i, v in enumerate(vals):
        p = f"{name}{i}"
        params[p] = v
        placeholders.append(f":{p}")
    return f"({', '.join(placeholders)})"


def _mp_where(
    filters: KpiFilters, params: dict[str, Any], *, alias: str = ""
) -> str:
    """WHERE pour measurement_points. `alias` préfixe les colonnes (ex. 'mp.')
    pour les requêtes jointes. Vide = pas de préfixe (requête simple)."""
    a = f"{alias}." if alias else ""
    parts = [f"{a}project_id = :pid"]
    if filters.operator:
        parts.append(f"{a}operator IN {_in_clause('op', filters.operator, params)}")
    if filters.rat:
        parts.append(
            f"({a}rat IN {_in_clause('rat', filters.rat, params)} "
            f"OR {a}tech IN {_in_clause('tch', filters.rat, params)})"
        )
    if filters.band:
        parts.append(f"{a}band IN {_in_clause('bd', filters.band, params)}")
    if filters.service_type:
        parts.append(
            f"{a}service_type IN {_in_clause('svc', filters.service_type, params)}"
        )
    if filters.env:
        parts.append(f"{a}env IN {_in_clause('env', filters.env, params)}")
    return " AND ".join(parts)


def _po_where(
    filters: KpiFilters, params: dict[str, Any], *, alias: str = ""
) -> str:
    """WHERE pour param_occurrence. `service_type` et `env` sont ignorés
    (pas de colonne correspondante — on ne fabrique pas)."""
    a = f"{alias}." if alias else ""
    parts = [f"{a}project_id = :pid"]
    if filters.operator:
        parts.append(f"{a}operator IN {_in_clause('op', filters.operator, params)}")
    if filters.rat:
        parts.append(f"{a}system IN {_in_clause('sys', filters.rat, params)}")
    if filters.band:
        parts.append(f"{a}band IN {_in_clause('bd', filters.band, params)}")
    return " AND ".join(parts)


def _bucket_width(min_v: float, max_v: float) -> float:
    span = max(1.0, max_v - min_v)
    for w in (0.5, 1, 2, 5, 10, 20, 50, 100):
        if span / w <= 20:
            return float(w)
    return 100.0


def _mk_virtual_result(
    *, project_id: str, kpi_code: str, dataset: str, filters_subset: dict[str, Any],
    denominator: int, warnings: list[str] | None = None,
) -> AnalyticalResult:
    """AnalyticalResult minimal pour nourrir validate_comparison. Pas renvoyé
    au front — n'expose que les champs comparés par le validateur."""
    plan = {
        "kpi": kpi_code,
        "dataset": dataset,
        "dimensions": ["operator"],
        "measures": ["value"],
        "filters": filters_subset,
    }
    rid = compute_result_id(plan, project_id)
    return AnalyticalResult(
        result_id=rid,
        plan=plan,
        rows=[],
        n=0,
        denominator=int(denominator),
        dataset=dataset,
        date_range={"start": None, "end": None},
        filters_applied=filters_subset,
        sql_compiled="",
        params={},
        warnings=warnings or [],
    )


# ---------- Distribution sur measurement_points ----------


def _kpi_mp_distribution(
    db: Session, project_id: str, kpi: KpiDef, filters: KpiFilters,
) -> dict[str, Any]:
    col = kpi.availability_arg
    assert col in _MP_METRIC_COLS

    params: dict[str, Any] = {"pid": project_id}
    where_simple = _mp_where(filters, params) + f" AND {col} IS NOT NULL"

    # Total.
    row = db.execute(
        text(
            f"SELECT "
            f"  percentile_cont(0.10) WITHIN GROUP (ORDER BY {col}) AS p10, "
            f"  percentile_cont(0.50) WITHIN GROUP (ORDER BY {col}) AS p50, "
            f"  percentile_cont(0.90) WITHIN GROUP (ORDER BY {col}) AS p90, "
            f"  MIN({col}) AS vmin, MAX({col}) AS vmax, "
            f"  COUNT(*) AS n "
            f"FROM measurement_points WHERE {where_simple}"
        ),
        params,
    ).mappings().one()
    n = int(row["n"] or 0)
    p10, p50, p90 = row["p10"], row["p50"], row["p90"]
    vmin, vmax = row["vmin"], row["vmax"]

    tech_rows = db.execute(
        text(
            f"SELECT DISTINCT COALESCE(rat, tech) AS t FROM measurement_points "
            f"WHERE {where_simple} AND COALESCE(rat, tech) IS NOT NULL ORDER BY t"
        ),
        params,
    ).all()
    technologies = [r[0] for r in tech_rows if r[0]]

    # Période observée via join nmf_file.start_at.
    where_joined = (
        _mp_where(filters, params, alias="mp")
        + f" AND mp.{col} IS NOT NULL"
    )
    date_expr = _date_from_start_at("nf")
    try:
        prow = db.execute(
            text(
                f"SELECT MIN(d) AS dmin, MAX(d) AS dmax FROM ("
                f"  SELECT {date_expr} AS d FROM measurement_points mp "
                f"  JOIN stg_event se ON se.project_id=mp.project_id "
                f"       AND se.capture_id=mp.capture_id AND se.seq=mp.seq "
                f"  JOIN nmf_file nf ON nf.id=se.nmf_file_id "
                f"  WHERE {where_joined}"
                f") q"
            ),
            params,
        ).mappings().one()
        period = {"min": prow["dmin"], "max": prow["dmax"]}
    except Exception:
        # Fallback honnête : période du projet depuis nmf_file.
        prow = db.execute(
            text(
                f"SELECT MIN({_date_from_start_at('nmf_file')}) AS dmin, "
                f"MAX({_date_from_start_at('nmf_file')}) AS dmax "
                f"FROM nmf_file WHERE project_id=:pid AND start_at IS NOT NULL"
            ),
            {"pid": project_id},
        ).mappings().one()
        period = {"min": prow["dmin"], "max": prow["dmax"]}

    # by_operator.
    by_op_rows = db.execute(
        text(
            f"SELECT operator AS op, "
            f"  percentile_cont(0.50) WITHIN GROUP (ORDER BY {col}) AS v, "
            f"  COUNT(*) AS n "
            f"FROM measurement_points WHERE {where_simple} "
            f"GROUP BY operator ORDER BY n DESC"
        ),
        params,
    ).mappings().all()
    by_operator = [
        {
            "operator": r["op"],
            "value": float(r["v"]) if r["v"] is not None else None,
            "n": int(r["n"]),
        }
        for r in by_op_rows
    ]

    # Distribution (histogramme).
    distribution: list[dict[str, Any]] = []
    if n > 0 and vmin is not None and vmax is not None:
        width = _bucket_width(float(vmin), float(vmax))
        params_h = dict(params)
        params_h["w"] = width
        hist_rows = db.execute(
            text(
                f"SELECT floor({col} / :w) * :w AS b, COUNT(*) AS c "
                f"FROM measurement_points WHERE {where_simple} "
                f"GROUP BY floor({col} / :w) ORDER BY b"
            ),
            params_h,
        ).all()
        total = sum(int(r[1]) for r in hist_rows) or 1
        for b, c in hist_rows:
            low = float(b)
            distribution.append(
                {
                    "bucket": f"[{low:g}, {low + width:g})",
                    "count": int(c),
                    "pct": round(100.0 * int(c) / total, 2),
                }
            )

    # Trend : par date de capture (nmf_file.start_at).
    try:
        trend_rows = db.execute(
            text(
                f"SELECT {date_expr} AS d, "
                f"  percentile_cont(0.50) WITHIN GROUP (ORDER BY mp.{col}) AS v, "
                f"  COUNT(*) AS n "
                f"FROM measurement_points mp "
                f"JOIN stg_event se ON se.project_id=mp.project_id "
                f"     AND se.capture_id=mp.capture_id AND se.seq=mp.seq "
                f"JOIN nmf_file nf ON nf.id=se.nmf_file_id "
                f"WHERE {where_joined} "
                f"GROUP BY {date_expr} ORDER BY d"
            ),
            params,
        ).all()
    except Exception:
        trend_rows = []
    trend = [
        {
            "date": r[0],
            "value": float(r[1]) if r[1] is not None else None,
            "n": int(r[2]),
        }
        for r in trend_rows
        if r[0] is not None
    ]
    period_unique = len(trend) <= 1

    return {
        "value": float(p50) if p50 is not None else None,
        "p10": float(p10) if p10 is not None else None,
        "p90": float(p90) if p90 is not None else None,
        "n": n,
        "technologies": technologies,
        "period": period,
        "by_operator": by_operator,
        "distribution": distribution,
        "trend": trend,
        "period_unique": period_unique,
    }


# ---------- Count sur param_occurrence ----------


def _po_match_clause(
    kpi: KpiDef, params: dict[str, Any], *, alias: str = ""
) -> str:
    a = f"{alias}." if alias else ""
    if kpi.availability == "param_message":
        params["kpi_arg"] = kpi.availability_arg
        return f"{a}message = :kpi_arg"
    if kpi.availability == "param_message_ilike":
        params["kpi_arg"] = kpi.availability_arg
        return f"{a}message ILIKE :kpi_arg"
    if kpi.availability == "param_path":
        params["kpi_arg"] = kpi.availability_arg
        sql_op = "=" if kpi.availability_op == "eq" else "ILIKE"
        return f"{a}path {sql_op} :kpi_arg"
    raise ValueError(f"{kpi.code}: règle de match param inattendue")


def _kpi_po_count(
    db: Session, project_id: str, kpi: KpiDef, filters: KpiFilters,
) -> dict[str, Any]:
    params: dict[str, Any] = {"pid": project_id}
    where_simple = (
        _po_where(filters, params) + " AND " + _po_match_clause(kpi, params)
    )

    total = int(
        db.execute(
            text(
                f"SELECT COUNT(DISTINCT stg_event_id) FROM param_occurrence "
                f"WHERE {where_simple}"
            ),
            params,
        ).scalar_one()
        or 0
    )

    # Technologies via join stg_event.
    where_joined = (
        _po_where(filters, params, alias="po")
        + " AND "
        + _po_match_clause(kpi, params, alias="po")
    )
    tech_rows = db.execute(
        text(
            f"SELECT DISTINCT se.system FROM param_occurrence po "
            f"JOIN stg_event se ON se.id=po.stg_event_id "
            f"WHERE {where_joined} AND se.system IS NOT NULL ORDER BY se.system"
        ),
        params,
    ).all()
    technologies = [r[0] for r in tech_rows if r[0]]

    date_expr = _date_from_start_at("nf")
    prow = db.execute(
        text(
            f"SELECT MIN({date_expr}) AS dmin, MAX({date_expr}) AS dmax "
            f"FROM param_occurrence po "
            f"JOIN stg_event se ON se.id=po.stg_event_id "
            f"JOIN nmf_file nf ON nf.id=se.nmf_file_id "
            f"WHERE {where_joined}"
        ),
        params,
    ).mappings().one()
    period = {"min": prow["dmin"], "max": prow["dmax"]}

    by_op_rows = db.execute(
        text(
            f"SELECT operator AS op, COUNT(DISTINCT stg_event_id) AS n "
            f"FROM param_occurrence WHERE {where_simple} "
            f"GROUP BY operator ORDER BY n DESC"
        ),
        params,
    ).mappings().all()
    by_operator = [
        {"operator": r["op"], "value": int(r["n"]), "n": int(r["n"])}
        for r in by_op_rows
    ]

    trend_rows = db.execute(
        text(
            f"SELECT {date_expr} AS d, COUNT(DISTINCT po.stg_event_id) AS n "
            f"FROM param_occurrence po "
            f"JOIN stg_event se ON se.id=po.stg_event_id "
            f"JOIN nmf_file nf ON nf.id=se.nmf_file_id "
            f"WHERE {where_joined} GROUP BY {date_expr} ORDER BY d"
        ),
        params,
    ).all()
    trend = [
        {"date": r[0], "value": int(r[1]), "n": int(r[1])}
        for r in trend_rows if r[0] is not None
    ]
    period_unique = len(trend) <= 1

    return {
        "value": total,
        "p10": None,
        "p90": None,
        "n": total,
        "technologies": technologies,
        "period": period,
        "by_operator": by_operator,
        "distribution": [],
        "trend": trend,
        "period_unique": period_unique,
    }


# ---------- Distribution sur param_occurrence ----------


def _parse_number(v: str | None) -> float | None:
    if v is None:
        return None
    s = str(v).strip().split()[0]
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _percentiles_from_counts(
    pairs: list[tuple[float, int]], qs: tuple[float, ...]
) -> list[float | None]:
    """Percentiles continus sur `(valeur, poids)` trié croissant. Interpolation
    linéaire — alignée sur l'implémentation Postgres percentile_cont."""
    if not pairs:
        return [None] * len(qs)
    total = sum(c for _, c in pairs)
    if total <= 0:
        return [None] * len(qs)
    cum: list[tuple[float, int]] = []
    acc = 0
    for v, c in pairs:
        acc += c
        cum.append((v, acc))

    def _val_at(idx: int) -> float:
        for v, c in cum:
            if idx < c:
                return v
        return pairs[-1][0]

    out: list[float | None] = []
    for q in qs:
        target = q * (total - 1)
        lo_idx = int(target)
        hi_idx = min(lo_idx + 1, total - 1)
        frac = target - lo_idx
        v_lo = _val_at(lo_idx)
        v_hi = _val_at(hi_idx)
        out.append(v_lo + (v_hi - v_lo) * frac)
    return out


def _kpi_po_distribution(
    db: Session, project_id: str, kpi: KpiDef, filters: KpiFilters,
) -> dict[str, Any]:
    """Distribution sur `param_occurrence.value_converted` (texte → float).

    Les lignes non parsables en nombre sont IGNORÉES déclaré, jamais
    comblées. On expose `n` = occurrences numériques comptées.
    """
    params: dict[str, Any] = {"pid": project_id}
    where_simple = (
        _po_where(filters, params) + " AND " + _po_match_clause(kpi, params)
    )

    rows = db.execute(
        text(
            f"SELECT value_converted AS v, operator AS op, COUNT(*) AS c "
            f"FROM param_occurrence WHERE {where_simple} "
            f"AND value_converted IS NOT NULL "
            f"GROUP BY value_converted, operator"
        ),
        params,
    ).mappings().all()

    all_pairs: list[tuple[float, int]] = []
    by_op_pairs: dict[str, list[tuple[float, int]]] = {}
    for r in rows:
        f = _parse_number(r["v"])
        c = int(r["c"])
        if f is None:
            continue
        all_pairs.append((f, c))
        by_op_pairs.setdefault(r["op"], []).append((f, c))

    all_pairs.sort()
    for op in by_op_pairs:
        by_op_pairs[op].sort()

    n = sum(c for _, c in all_pairs)
    p10, p50, p90 = _percentiles_from_counts(all_pairs, (0.1, 0.5, 0.9))

    by_operator: list[dict[str, Any]] = []
    for op, pairs in by_op_pairs.items():
        _, p50_op, _ = _percentiles_from_counts(pairs, (0.1, 0.5, 0.9))
        by_operator.append(
            {"operator": op, "value": p50_op, "n": sum(c for _, c in pairs)}
        )
    by_operator.sort(key=lambda d: d["n"], reverse=True)

    distribution: list[dict[str, Any]] = []
    if all_pairs:
        vmin = all_pairs[0][0]
        vmax = all_pairs[-1][0]
        width = _bucket_width(vmin, vmax)
        buckets: dict[float, int] = {}
        for v, c in all_pairs:
            key = (v // width) * width
            buckets[key] = buckets.get(key, 0) + c
        total = sum(buckets.values()) or 1
        for key in sorted(buckets):
            distribution.append(
                {
                    "bucket": f"[{key:g}, {key + width:g})",
                    "count": buckets[key],
                    "pct": round(100.0 * buckets[key] / total, 2),
                }
            )

    # Trend joint.
    where_joined = (
        _po_where(filters, params, alias="po")
        + " AND "
        + _po_match_clause(kpi, params, alias="po")
    )
    date_expr = _date_from_start_at("nf")
    trend_rows = db.execute(
        text(
            f"SELECT {date_expr} AS d, po.value_converted AS v, COUNT(*) AS c "
            f"FROM param_occurrence po "
            f"JOIN stg_event se ON se.id=po.stg_event_id "
            f"JOIN nmf_file nf ON nf.id=se.nmf_file_id "
            f"WHERE {where_joined} AND po.value_converted IS NOT NULL "
            f"GROUP BY {date_expr}, po.value_converted ORDER BY d"
        ),
        params,
    ).all()
    per_day: dict[str, list[tuple[float, int]]] = {}
    for d, v, c in trend_rows:
        if d is None:
            continue
        f = _parse_number(v)
        if f is None:
            continue
        per_day.setdefault(d, []).append((f, int(c)))
    trend: list[dict[str, Any]] = []
    for d in sorted(per_day):
        pairs = sorted(per_day[d])
        _, p50_d, _ = _percentiles_from_counts(pairs, (0.1, 0.5, 0.9))
        trend.append({"date": d, "value": p50_d, "n": sum(c for _, c in pairs)})

    prow = db.execute(
        text(
            f"SELECT MIN({date_expr}) AS dmin, MAX({date_expr}) AS dmax "
            f"FROM param_occurrence po "
            f"JOIN stg_event se ON se.id=po.stg_event_id "
            f"JOIN nmf_file nf ON nf.id=se.nmf_file_id "
            f"WHERE {where_joined}"
        ),
        params,
    ).mappings().one()
    period = {"min": prow["dmin"], "max": prow["dmax"]}

    tech_rows = db.execute(
        text(
            f"SELECT DISTINCT system FROM param_occurrence "
            f"WHERE {where_simple} AND system IS NOT NULL ORDER BY system"
        ),
        params,
    ).all()
    technologies = [r[0] for r in tech_rows if r[0]]

    return {
        "value": p50,
        "p10": p10,
        "p90": p90,
        "n": n,
        "technologies": technologies,
        "period": period,
        "by_operator": by_operator,
        "distribution": distribution,
        "trend": trend,
        "period_unique": len(trend) <= 1,
    }


# ---------- Entry point ----------


def _comparability(
    *, project_id: str, kpi: KpiDef, by_operator: list[dict[str, Any]]
) -> dict[str, str]:
    if len(by_operator) < 2:
        return {
            "verdict": "SINGLE_GROUP",
            "reason": "un seul opérateur observé — comparaison sans objet",
        }
    dataset = "measurements" if kpi.availability == "mp_metric" else "rrc_dict"
    results = [
        _mk_virtual_result(
            project_id=project_id,
            kpi_code=kpi.code,
            dataset=dataset,
            filters_subset={"operator": [row["operator"]]},
            denominator=int(row["n"] or 0),
        )
        for row in by_operator
    ]
    verdict: ComparabilityVerdict = validate_comparison(results)
    return {"verdict": verdict.verdict, "reason": verdict.reason}


def compute_kpi(
    db: Session, *, project_id: str, code: str, filters: KpiFilters,
) -> dict[str, Any]:
    """Calcul principal. Statut d'abord ; valeurs ensuite SI AVAILABLE."""
    kpi = KPI_BY_CODE.get(code)
    if kpi is None:
        raise KeyError(code)

    status = compute_status(db, project_id, kpi)
    plan = {"kpi": kpi.code, "filters": filters.to_plan()}
    result_id = compute_result_id(plan, project_id)

    base: dict[str, Any] = {
        "code": kpi.code,
        "name": kpi.name,
        "family": kpi.family,
        "nature": kpi.nature,
        "unit": kpi.unit,
        "formula": kpi.formula,
        "source": kpi.source,
        "status": status.status,
        "reason": status.reason,
        "value": None,
        "p10": None,
        "p90": None,
        "n": 0,
        "technologies": [],
        "period": {"min": None, "max": None},
        "by_operator": [],
        "distribution": [],
        "trend": [],
        "period_unique": True,
        "filters_applied": filters.to_plan(),
        "comparability": {
            "verdict": "NOT_APPLICABLE",
            "reason": f"statut {status.status} — pas de calcul",
        },
        "result_id": result_id,
    }

    if status.status != "AVAILABLE":
        return base

    if kpi.availability == "mp_metric":
        agg = _kpi_mp_distribution(db, project_id, kpi, filters)
    elif kpi.availability in ("param_message", "param_message_ilike"):
        agg = _kpi_po_count(db, project_id, kpi, filters)
    elif kpi.availability == "param_path":
        agg = (
            _kpi_po_count(db, project_id, kpi, filters)
            if kpi.nature == "count"
            else _kpi_po_distribution(db, project_id, kpi, filters)
        )
    else:
        return base

    base.update(agg)
    base["comparability"] = _comparability(
        project_id=project_id, kpi=kpi, by_operator=base["by_operator"]
    )
    return base
