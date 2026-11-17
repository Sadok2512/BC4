"""Drive-test report datasets built only from persisted, decoded project data.

The endpoint deliberately returns nullable values plus coverage metadata.  It
does not derive radio procedures (E-RAB, NR PDU sessions, BLER, MCS or PRB)
from unrelated measurements.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, with_statement_timeout_60s
from app.models import Project


router = APIRouter(
    prefix="/projects",
    tags=["drive-test-reports"],
    dependencies=[Depends(get_current_user), Depends(with_statement_timeout_60s)],
)

METRICS: tuple[tuple[str, str, str], ...] = (
    ("dl", "DL Throughput", "Mbit/s"),
    ("thrpt_ul", "UL Throughput", "Mbit/s"),
    ("rsrp", "RSRP", "dBm"),
    ("rsrq", "RSRQ", "dB"),
    ("sinr", "SINR", "dB"),
    ("cqi", "CQI", "index"),
    ("mimo_rank", "Rank / Layers", "rank"),
)

SplitBy = Literal["none", "operator", "stream"]


def _project(db: Session, project_id: str) -> None:
    if not db.get(Project, project_id):
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Project not found"})


def _scope(
    project_id: str,
    capture_id: list[str],
    operator: list[str],
    rat: list[str],
    band: list[str],
    service: list[str],
    cell: list[str],
    site: list[str],
    time_start: str | None,
    time_end: str | None,
) -> tuple[str, dict[str, Any]]:
    clauses = ["m.project_id=:pid"]
    params: dict[str, Any] = {"pid": project_id}
    for key, column, values in (
        ("capture_ids", "m.capture_id", capture_id),
        ("operators", "m.operator", operator),
        ("rats", "coalesce(m.rat,m.tech)", rat),
        ("bands", "m.band", band),
        ("services", "coalesce(m.service_type,m.service_name,m.service)", service),
        ("cells", "m.ecgi", cell),
        ("sites", "m.site", site),
    ):
        if values:
            clauses.append(f"{column}=ANY(:{key})")
            params[key] = values
    if time_start:
        clauses.append("m.ts>=:time_start")
        params["time_start"] = time_start
    if time_end:
        clauses.append("m.ts<=:time_end")
        params["time_end"] = time_end
    return " AND ".join(clauses), params


def _percentile_row(row: Any, code: str, label: str, unit: str) -> dict[str, Any]:
    n = int(row[f"{code}_n"] or 0)
    return {
        "code": code,
        "label": label,
        "unit": unit,
        "status": "AVAILABLE" if n else "UNAVAILABLE",
        "reason": None if n else f"No non-null {code} samples in the filtered dataset",
        "n": n,
        "avg": row[f"{code}_avg"],
        "p10": row[f"{code}_p10"],
        "p50": row[f"{code}_p50"],
        "p90": row[f"{code}_p90"],
        "max": row[f"{code}_max"],
    }


def _task_summary(row: Any | None) -> dict[str, Any]:
    if row is None:
        return {
            "attempts": 0, "successes": 0, "failures": 0,
            "avg_duration_s": None, "volume_bytes": None,
        }
    return {
        "attempts": int(row["attempts"] or 0),
        "successes": int(row["successes"] or 0),
        "failures": int(row["failures"] or 0),
        "avg_duration_s": float(row["avg_duration_s"]) if row["avg_duration_s"] is not None else None,
        "volume_bytes": int(row["volume_bytes"]) if row["volume_bytes"] is not None else None,
    }


@router.get("/{project_id}/drive-test-reports/filters")
def report_filters(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    _project(db, project_id)
    row = db.execute(text("""
        SELECT
          coalesce(array_remove(array_agg(DISTINCT capture_id ORDER BY capture_id),NULL),'{}') captures,
          coalesce(array_remove(array_agg(DISTINCT operator ORDER BY operator),NULL),'{}') operators,
          coalesce(array_remove(array_agg(DISTINCT coalesce(rat,tech) ORDER BY coalesce(rat,tech)),NULL),'{}') rats,
          coalesce(array_remove(array_agg(DISTINCT band ORDER BY band),NULL),'{}') bands,
          coalesce(array_remove(array_agg(DISTINCT coalesce(service_type,service_name,service)
            ORDER BY coalesce(service_type,service_name,service)),NULL),'{}') services,
          coalesce(array_remove(array_agg(DISTINCT ecgi ORDER BY ecgi),NULL),'{}') cells,
          coalesce(array_remove(array_agg(DISTINCT site ORDER BY site),NULL),'{}') sites,
          min(ts) time_min,max(ts) time_max
        FROM measurement_points WHERE project_id=:pid
    """), {"pid": project_id}).mappings().one()
    return {"project_id": project_id, **dict(row)}


@router.get("/{project_id}/drive-test-reports/data")
def report_data(
    project_id: str,
    capture_id: list[str] = Query(default_factory=list),
    operator: list[str] = Query(default_factory=list),
    rat: list[str] = Query(default_factory=list),
    band: list[str] = Query(default_factory=list),
    service: list[str] = Query(default_factory=list),
    cell: list[str] = Query(default_factory=list),
    site: list[str] = Query(default_factory=list),
    time_start: str | None = None,
    time_end: str | None = None,
    split_by: SplitBy = "none",
    limit: int = Query(5000, ge=100, le=10000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _project(db, project_id)
    where, params = _scope(
        project_id, capture_id, operator, rat, band, service, cell, site, time_start, time_end
    )
    expressions: list[str] = ["count(*) total"]
    for code, _, _ in METRICS:
        expressions.extend((
            f"count({code}) {code}_n",
            f"avg({code}) {code}_avg",
            f"percentile_cont(.1) within group(order by {code}) {code}_p10",
            f"percentile_cont(.5) within group(order by {code}) {code}_p50",
            f"percentile_cont(.9) within group(order by {code}) {code}_p90",
            f"max({code}) {code}_max",
        ))
    aggregate = db.execute(text(
        "SELECT " + ",".join(expressions) + " FROM measurement_points m WHERE " + where
    ), params).mappings().one()
    total = int(aggregate["total"] or 0)
    metrics = [_percentile_row(aggregate, *metric) for metric in METRICS]

    # Stable canonical order and rank sampling; no interpolation.
    point_rows = db.execute(text(f"""
        WITH scoped AS (
          SELECT m.*,row_number() over(order by capture_id,seq,id) rn,
            count(*) over() population
          FROM measurement_points m WHERE {where}
        )
        SELECT capture_id,seq,ts,operator,coalesce(rat,tech) rat,band,
          coalesce(service_type,service_name,service) service,ecgi cell,site,
          dl,thrpt_ul,rsrp,rsrq,sinr,cqi,mimo_rank,population
        FROM scoped
        WHERE population<=:limit OR mod(rn-1,greatest(1,ceil(population::numeric/:limit)::int))=0
        ORDER BY capture_id,seq,id LIMIT :limit
    """), {**params, "limit": limit}).mappings().all()

    # Tasks are admitted only when they overlap the exact same filtered
    # measurement population used by the charts and summary table.
    task_params: dict[str, Any] = dict(params)
    task_where = (
        "t.project_id=:pid AND EXISTS (SELECT 1 FROM measurement_points m WHERE "
        + where
        + " AND m.capture_id=t.capture_id AND m.seq BETWEEN t.seq_start AND t.seq_end)"
    )
    tasks = [dict(row) for row in db.execute(text(f"""
        SELECT id,capture_id,seq_start,seq_end,task_type,operator,tech,band,
          duration_s,status,reason,bytes_dcomp
        FROM task_run t WHERE {task_where}
        ORDER BY capture_id,seq_start LIMIT 2000
    """), task_params).mappings()]
    task_stats = db.execute(text(f"""
        SELECT count(*) attempts,count(*) filter(where status='ok') successes,
          count(*) filter(where status<>'ok') failures,
          avg(duration_s) avg_duration_s,sum(bytes_dcomp) volume_bytes
        FROM task_run t WHERE {task_where}
    """), task_params).mappings().one()
    task_summary = _task_summary(task_stats)

    groups: list[dict[str, Any]] = []
    if split_by != "none":
        measurement_key = (
            "coalesce(m.operator,'Unassigned')"
            if split_by == "operator"
            else "coalesce(m.capture_id,'Unassigned')"
        )
        group_rows = db.execute(text(
            "SELECT " + measurement_key + " split_key,"
            + ",".join(expressions)
            + ",coalesce(array_remove(array_agg(DISTINCT m.capture_id),NULL),'{}') sources "
            + "FROM measurement_points m WHERE " + where
            + " GROUP BY 1 ORDER BY 1"
        ), params).mappings().all()
        task_key = (
            "coalesce(t.operator,'Unassigned')"
            if split_by == "operator"
            else "coalesce(t.capture_id,'Unassigned')"
        )
        grouped_tasks = db.execute(text(f"""
            SELECT {task_key} split_key,count(*) attempts,
              count(*) filter(where status='ok') successes,
              count(*) filter(where status<>'ok') failures,
              avg(duration_s) avg_duration_s,sum(bytes_dcomp) volume_bytes
            FROM task_run t WHERE {task_where}
            GROUP BY 1 ORDER BY 1
        """), task_params).mappings().all()
        task_stats_by_key = {str(row["split_key"]): row for row in grouped_tasks}
        returned_by_key: dict[str, int] = defaultdict(int)
        for row in point_rows:
            raw_key = row["operator"] if split_by == "operator" else row["capture_id"]
            returned_by_key[str(raw_key or "Unassigned")] += 1
        groups = [
            {
                "key": str(row["split_key"]),
                "label": str(row["split_key"]),
                "population": {
                    "samples": int(row["total"] or 0),
                    "returned": returned_by_key[str(row["split_key"])],
                },
                "metrics": [_percentile_row(row, *metric) for metric in METRICS],
                "task_summary": _task_summary(task_stats_by_key.get(str(row["split_key"]))),
                "sources": list(row["sources"] or []),
            }
            for row in group_rows
        ]

    services: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"attempts": 0, "successes": 0, "failures": 0, "volume_bytes": 0}
    )
    for task in tasks:
        bucket = services[task["task_type"] or "OTHER"]
        bucket["attempts"] += 1
        bucket["successes" if task["status"] == "ok" else "failures"] += 1
        if task["bytes_dcomp"] is not None:
            bucket["volume_bytes"] += int(task["bytes_dcomp"])

    unsupported = [
        {"code": code, "status": "UNAVAILABLE", "value": None, "n": 0, "reason": reason}
        for code, reason in (
            ("erab", "LTE E-RAB procedure counters are not decoded for this dataset"),
            ("nr_pdu_session", "NR PDU session procedure counters are not decoded for this dataset"),
            ("bler_dl", "No proven BLER field in measurement_points"),
            ("bler_ul", "No proven BLER field in measurement_points"),
            ("mcs_dl", "No proven MCS field in measurement_points"),
            ("mcs_ul", "No proven MCS field in measurement_points"),
            ("prb_dl", "No proven PRB utilization field in measurement_points"),
            ("prb_ul", "No proven PRB utilization field in measurement_points"),
        )
    ]
    return {
        "project_id": project_id,
        "filters": {
            "capture_id": capture_id, "operator": operator, "rat": rat, "band": band,
            "service": service, "cell": cell, "site": site,
            "time_start": time_start, "time_end": time_end, "split_by": split_by,
        },
        "split_by": split_by,
        "groups": groups,
        "methodology": "Persisted decoded observations ordered by (capture_id, seq); no interpolation",
        "population": {"samples": total, "returned": len(point_rows), "sampling": "stable rank" if total > limit else "none"},
        "metrics": metrics,
        "unsupported": unsupported,
        "points": [dict(row) for row in point_rows],
        "tasks": tasks,
        "task_summary": task_summary,
        "services": [{"service": key, **value} for key, value in sorted(services.items())],
        "failures": [task for task in tasks if task["status"] != "ok"],
        "sources": sorted({row["capture_id"] for row in point_rows if row["capture_id"]}),
    }
