"""Routes d'agrégats mesure (0.24.0 Keystone — Phase 2 skeleton).

Endpoints :

- `GET /projects/{id}/measurements/summary`
  Agrégats scopés projet : counts par (operator, band, system, event_code),
  moyennes des métriques peuplées (NULL tant que Phase 1 non faite).
  Alimente l'outil assistant `query_measurements` et la page KPI à terme.

- `GET /projects/{id}/measurements/raw?event_code=CELLMEAS&limit=20`
  (admin-only) Retourne N lignes brutes de `stg_measurement_raw` pour
  **l'investigation Phase 1** (mapping champ→métrique par preuve). Pas
  pour la UI standard — c'est un outil d'inspection.

Toujours :
- Scope strict `project_id` dans la WHERE.
- Agrégats seulement, zéro ligne brute abonné.
- NULL (par ex. métriques non mappées) → remonté tel quel, jamais 0.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Actor, get_actor, get_current_user, require_role
from app.models import Project


router = APIRouter(
    prefix="/projects",
    tags=["measurements"],
    dependencies=[Depends(get_current_user)],
)


def _project_or_404(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
    return p


@router.get("/{project_id}/measurements/summary")
def measurements_summary(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retourne les agrégats mesure du projet.

    Shape :
    ```
    {
      "project_id": "...",
      "total_points": int,
      "by_system":     [{"key": "LTE" | "NR" | null, "count": int}],
      "by_operator":   [{"key": "Orange" | ... | null, "count": int}],
      "by_band":       [{"key": "B20" | "n78" | ... | null, "count": int}],
      "by_event_code": [{"key": "CELLMEAS" | ... | null, "count": int}],
      "metric_averages": {
        "rsrp": null|float, "rsrq": null|float, "sinr": null|float,
        "rssi": null|float, "cqi":  null|float, "mimo_rank": null|float,
        "tx_power": null|float, "dl": null|float, "thrpt_ul": null|float,
        "latency": null|float
      },
      "metric_coverage": {
        "<metric>": {"filled": int, "null": int}
      },
      "raw_staging": {
        "measurement_rows": int,   # stg_measurement_raw.category='measurement'
        "throughput_rows": int,    # stg_measurement_raw.category='throughput'
        "by_event_code":   [{"key": ..., "count": int}]
      }
    }
    ```
    """
    _project_or_404(db, project_id)

    total = db.execute(
        text("SELECT COUNT(*) FROM measurement_points WHERE project_id = :pid"),
        {"pid": project_id},
    ).scalar_one()

    def _by(column: str) -> list[dict]:
        rows = db.execute(
            text(
                f"""
                SELECT {column} AS k, COUNT(*) AS c
                FROM measurement_points
                WHERE project_id = :pid
                GROUP BY {column}
                ORDER BY c DESC
                """
            ),
            {"pid": project_id},
        ).all()
        return [{"key": r.k, "count": int(r.c)} for r in rows]

    metric_cols = (
        "rsrp", "rsrq", "sinr", "rssi", "cqi", "mimo_rank",
        "tx_power", "dl", "thrpt_ul", "latency",
    )
    # Moyennes + coverage, en une seule requête.
    agg_sql = (
        "SELECT " + ", ".join(
            f"AVG({c}) AS avg_{c}, "
            f"SUM(CASE WHEN {c} IS NOT NULL THEN 1 ELSE 0 END) AS filled_{c}, "
            f"SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) AS null_{c}"
            for c in metric_cols
        )
        + " FROM measurement_points WHERE project_id = :pid"
    )
    agg = db.execute(text(agg_sql), {"pid": project_id}).mappings().one()
    metric_averages = {c: float(agg[f"avg_{c}"]) if agg[f"avg_{c}"] is not None else None for c in metric_cols}
    metric_coverage = {
        c: {"filled": int(agg[f"filled_{c}"] or 0), "null": int(agg[f"null_{c}"] or 0)}
        for c in metric_cols
    }

    # Staging raw — fournit la contre-mesure (combien d'events capturés
    # vs combien insérés dans measurement_points).
    staging = db.execute(
        text(
            """
            SELECT
              SUM(CASE WHEN category='measurement' THEN 1 ELSE 0 END) AS measurement_rows,
              SUM(CASE WHEN category='throughput'  THEN 1 ELSE 0 END) AS throughput_rows
            FROM stg_measurement_raw
            WHERE project_id = :pid
            """
        ),
        {"pid": project_id},
    ).mappings().one()
    staging_by_code = db.execute(
        text(
            """
            SELECT event_code AS k, COUNT(*) AS c
            FROM stg_measurement_raw
            WHERE project_id = :pid
            GROUP BY event_code
            ORDER BY c DESC
            """
        ),
        {"pid": project_id},
    ).all()

    return {
        "project_id": project_id,
        "total_points": int(total),
        "by_system":     _by("tech"),
        "by_operator":   _by("operator"),
        "by_band":       _by("band"),
        "by_event_code": _by("event_code"),
        "metric_averages": metric_averages,
        "metric_coverage": metric_coverage,
        "raw_staging": {
            "measurement_rows": int(staging["measurement_rows"] or 0),
            "throughput_rows":  int(staging["throughput_rows"] or 0),
            "by_event_code":    [{"key": r.k, "count": int(r.c)} for r in staging_by_code],
        },
    }


@router.get("/{project_id}/measurements/raw")
def measurements_raw(
    project_id: str,
    event_code: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Lignes brutes `stg_measurement_raw` pour investigation Phase 1.

    Admin-only (le mapping champ→métrique est un travail de validation
    qui expose des positions CSV internes du NMF — pas de la donnée
    standard UI).

    Retourne au max 200 lignes. `raw_fields` est renvoyé tel quel.
    """
    require_role(actor, "admin")
    _project_or_404(db, project_id)

    rows = db.execute(
        text(
            """
            SELECT capture_id, seq, ts, event_code, category, system, lat, lon, raw_fields
            FROM stg_measurement_raw
            WHERE project_id = :pid AND event_code = :code
            ORDER BY capture_id, seq
            LIMIT :lim
            """
        ),
        {"pid": project_id, "code": event_code, "lim": limit},
    ).mappings().all()
    return {
        "project_id": project_id,
        "event_code": event_code,
        "limit": limit,
        "rows": [dict(r) for r in rows],
    }
