"""Metric vs Time generic engine (0.59.0).

Donne, pour un couple (capture_id, KPI_code), la série
``(seq, time_s, value)`` validée. Le moteur ne décode rien ; il relie :

  - ``catalog_v2`` → résout un KPI canonique vers sa règle
    ``available_check``. Seuls les KPI dont ``kind == 'nmf_metric'``
    sont servis ici (métriques Nemo directes). Les KPI calculés
    (``transfers_table``, ``param_message_eq``, etc.) renvoient
    ``status: UNAVAILABLE`` avec ``reason`` explicite — jamais une
    série fabriquée (règle n°1 BC4).

  - ``metric_catalog(db)`` → source SQL de la métrique NMF (``mac.dl_bler``,
    ``pdsch.bler``, ``cell_rsrp``, ``app_dl_bitrate``, …).

  - ``clock()`` de ``app.routes.metrics`` → origine temporelle de la
    capture (``time_s = ts - premier_ts_valide``). Ordre canonique
    ``(capture_id, seq)``. Aucune interpolation, aucune concaténation
    inter-captures (règle n°6 BC4).

  - ``sample()`` de ``app.routes.metrics`` → down-sampling
    seq-bucket min/max qui **préserve les extrema par bucket**
    (vérifié G9). LTTB a été écarté : il peut masquer un pic unique
    entre deux buckets voisins ; min/max garantit la préservation.

Discipline :
  - Pas de null converti en zéro.
  - Pas de fallback silencieux vers un agrégat : si la requête
    temporelle échoue, le statut est ``UNAVAILABLE`` + ``reason``.
  - Toutes les valeurs retournées proviennent de ``nmf_event_deep`` ∪
    ``nmf_event_group`` ∪ ``nmf_event_light`` via la projection
    ``source_sql(metric_code)`` ; aucune ligne synthétisée.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, with_statement_timeout_60s
from app.kpi.catalog_v2 import get as catalog_v2_get, resolve as catalog_v2_resolve
from app.kpi.metrics import metric_catalog
from app.models import Project
from app.routes.metrics import clock, sample
from app.routes.tasks import evidence


router = APIRouter(
    tags=["kpi-timeseries"],
    dependencies=[Depends(get_current_user), Depends(with_statement_timeout_60s)],
)

VERSION = "0.59.0"


# ---------------------------------------------------------------------------
# Pydantic contracts
# ---------------------------------------------------------------------------


class AxisInfo(BaseModel):
    model_config = ConfigDict(extra="allow")
    field: str
    unit: Optional[str] = None


class TimeSeriesPoint(BaseModel):
    model_config = ConfigDict(extra="allow")
    seq: int
    time_s: float
    value: float | str
    # 0.60.0 — Enrichissement contextuel joint à partir de ``stg_event_raw``
    # et ``nmf_file`` sur ``(project_id, capture_id, seq)``. Les champs
    # sont **optionnels** : si la source ne porte pas la colonne (p.ex.
    # GPS off / indoor capture), la valeur est `null` et le front
    # affiche ``—`` sans fabriquer de coordonnée.
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    nmf_file: Optional[str] = None
    # 0.60.1 — Horodatage absolu de l'observation : ``event_ts`` est la
    # time-of-day stockée dans ``stg_event_raw.ts`` (format
    # ``HH:MM:SS.ms``) et ``nmf_file_start`` l'horodatage de début
    # fichier (``DD.MM.YYYY HH:MM:SS.ms``). Le front combine la partie
    # DATE de ``nmf_file_start`` avec ``event_ts`` pour afficher
    # l'horodatage complet. Aucun calcul côté back : on sert les
    # chaînes brutes de la DB, le front formate (règle n°2 BC4).
    event_ts: Optional[str] = None
    nmf_file_start: Optional[str] = None


class TimeSeriesSampling(BaseModel):
    model_config = ConfigDict(extra="allow")
    method: Literal["none", "seq_bucket_min_max", "state_changes"]
    factor: float
    seq_bucket_width: Optional[int] = None


class TimeSeriesEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")
    source_view: Optional[str] = None
    source_table: Optional[str] = None
    source_column: Optional[str] = None
    metric_code_nmf: Optional[str] = None
    n: int = 0
    result_id: Optional[str] = None
    decoder_version: Optional[str] = None
    schema_version: Optional[str] = None
    decode_level: Optional[str] = None
    origin_seq: Optional[int] = None
    origin_ts: Optional[str] = None


class MetricTimeSeriesResponse(BaseModel):
    """Réponse ``GET /projects/{pid}/captures/{cid}/kpi/{code}/time-series``."""
    model_config = ConfigDict(extra="allow")

    status: Literal["AVAILABLE", "PENDING", "UNVALIDATED", "UNAVAILABLE", "NOT_APPLICABLE"]
    reason: Optional[str] = None
    metric_code: str
    metric_name: Optional[str] = None
    capture_id: str
    x_axis: AxisInfo
    y_axis: AxisInfo
    n_total: int = 0
    n_returned: int = 0
    points: list[TimeSeriesPoint] = Field(default_factory=list)
    sampling: Optional[TimeSeriesSampling] = None
    evidence: TimeSeriesEvidence
    time_policy: str = (
        "time_s = ts - premier ts valide en ordre seq ; "
        "égalités conservées ; régression rejetée ; aucune interpolation"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_project(db: Session, project_id: str) -> None:
    if not db.get(Project, project_id):
        raise HTTPException(404, {"reason": "project_not_found"})


def _axes(entry: dict[str, Any], metric_unit: Optional[str]) -> tuple[AxisInfo, AxisInfo]:
    return (
        AxisInfo(field="capture_time_s", unit="s"),
        AxisInfo(field="value", unit=metric_unit if metric_unit is not None else entry.get("unit")),
    )


def _unavailable(
    *,
    metric_code: str,
    capture_id: str,
    reason: str,
    entry: Optional[dict[str, Any]] = None,
    metric_name: Optional[str] = None,
    metric_code_nmf: Optional[str] = None,
) -> dict[str, Any]:
    x_axis, y_axis = _axes(entry or {}, (entry or {}).get("unit"))
    return {
        "status": "UNAVAILABLE",
        "reason": reason,
        "metric_code": metric_code,
        "metric_name": metric_name or (entry or {}).get("name"),
        "capture_id": capture_id,
        "x_axis": x_axis.model_dump(),
        "y_axis": y_axis.model_dump(),
        "n_total": 0,
        "n_returned": 0,
        "points": [],
        "sampling": None,
        "evidence": TimeSeriesEvidence(metric_code_nmf=metric_code_nmf).model_dump(),
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/captures/{capture_id}/kpi/{code}/time-series",
    response_model=MetricTimeSeriesResponse,
)
def kpi_time_series(
    project_id: str,
    capture_id: str,
    code: str,
    max_points: int = Query(5000, ge=2, le=100000, description="Plafond de points retournés — down-sampling seq-bucket min/max préservant les extrema."),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Observations (time_s, value) d'une métrique NMF sur une capture.

    Statuts retournés :

    - ``AVAILABLE`` : au moins un point validé pour cette capture.
    - ``UNAVAILABLE`` + ``reason`` : KPI non résolvable, mapping absent,
      métrique sans observations décodées, capture inconnue, règle
      non ``nmf_metric``.
    - ``PENDING`` : règle ``nmf_metric`` mais la métrique n'a aucune
      observation décodée dans le projet (pas encore décodé / absent du
      corpus).

    Jamais : bascule silencieuse vers un agrégat, points interpolés,
    temps fabriqué, null converti en zéro.
    """
    _require_project(db, project_id)

    canonical = catalog_v2_resolve(code)
    if canonical is None:
        return _unavailable(metric_code=code, capture_id=capture_id, reason="unknown_kpi_code")
    entry = catalog_v2_get(canonical) or {}

    check = entry.get("available_check") or {}
    kind = check.get("kind")
    if kind != "nmf_metric":
        return _unavailable(
            metric_code=canonical,
            capture_id=capture_id,
            reason=f"no_direct_metric_mapping (available_check.kind={kind!r})",
            entry=entry,
        )

    metric_code_nmf = check.get("arg") or ""
    definitions = metric_catalog(db)
    if metric_code_nmf not in definitions:
        return _unavailable(
            metric_code=canonical,
            capture_id=capture_id,
            reason=f"metric_not_in_nmf_catalog (nmf_code={metric_code_nmf!r})",
            entry=entry,
            metric_code_nmf=metric_code_nmf,
        )
    metric = definitions[metric_code_nmf]
    if metric.kind == "categorical":
        return _unavailable(
            metric_code=canonical,
            capture_id=capture_id,
            reason=f"categorical_not_charted (nmf_code={metric_code_nmf!r})",
            entry=entry,
            metric_code_nmf=metric_code_nmf,
        )

    # Capture validée (nmf_capture = source de vérité pour le decode level).
    state = db.execute(
        text(
            "SELECT decoder_version, schema_version, decode_level "
            "FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap"
        ),
        {"pid": project_id, "cap": capture_id},
    ).mappings().first()
    if state is None:
        return _unavailable(
            metric_code=canonical,
            capture_id=capture_id,
            reason="capture_not_decoded_for_project",
            entry=entry,
            metric_code_nmf=metric_code_nmf,
        )

    # Horloge capture-locale : (seq, ts) → time_s depuis l'origine, ordre canonique.
    times, origin_seq, origin_ts = clock(db, project_id, capture_id)

    # Observations décodées de la métrique sur cette capture. 0.60.0 —
    # LEFT JOIN ``stg_event_raw`` (lat/lon par séquence NMF) + ``nmf_file``
    # (nom du fichier source) sur ``(project_id, capture_id, seq)``. La
    # LEFT JOIN ne filtre jamais le point métrique : si une séquence
    # ``nmf_event_light`` n'a pas de ligne ``stg_event_raw`` correspondante,
    # longitude / latitude / nmf_file ressortent ``null`` et le front
    # affiche ``—`` (règle n°1 — jamais fabriqué).
    metric_sql = (
        "SELECT src.seq AS seq, src.value AS value, "
        "r.lat AS latitude, r.lon AS longitude, "
        "f.filename AS nmf_file, r.ts AS event_ts, f.start_at AS nmf_file_start "
        "FROM (" + metric.sql + ") src "
        "LEFT JOIN stg_event_raw r ON r.project_id=:pid AND r.capture_id=src.capture_id AND r.seq=src.seq "
        "LEFT JOIN nmf_file f ON f.id=r.nmf_file_id "
        "WHERE src.capture_id=:cap ORDER BY src.seq"
    )
    rows = db.execute(text(metric_sql), {"pid": project_id, "cap": capture_id}).mappings().all()

    if any(r["seq"] not in times for r in rows):
        raise HTTPException(409, {"reason": "metric_timestamp_missing", "code": canonical})

    if not rows:
        # Métrique au catalogue mais zéro observation décodée pour cette capture :
        # vérifier si c'est strictement une absence capture-locale (projet a
        # d'autres captures avec cette métrique) ou projet-wide (PENDING).
        has_project_wide = db.execute(
            text("SELECT EXISTS(SELECT 1 FROM (" + metric.sql + ") available LIMIT 1)"),
            {"pid": project_id},
        ).scalar_one()
        payload = _unavailable(
            metric_code=canonical,
            capture_id=capture_id,
            reason=(
                "no_observations_in_capture" if has_project_wide
                else "no_observations_in_project"
            ),
            entry=entry,
            metric_code_nmf=metric_code_nmf,
        )
        if not has_project_wide:
            payload["status"] = "PENDING"
            payload["reason"] = "aucune mesure Nemo documentée décodée"
        return payload

    points = [
        dict(
            seq=r["seq"],
            t_rel_s=times[r["seq"]],
            value=float(r["value"]),
            longitude=float(r["longitude"]) if r["longitude"] is not None else None,
            latitude=float(r["latitude"]) if r["latitude"] is not None else None,
            nmf_file=r["nmf_file"],
            event_ts=r["event_ts"],
            nmf_file_start=r["nmf_file_start"],
        )
        for r in rows
    ]
    out, sampling = sample(points, max_points, metric.kind)

    # L'évidence est une trace SQL + paramètres rejouables (règle n°2 BC4).
    rid = evidence(
        db,
        project_id,
        ";\n".join(["-- clock\n" + "SELECT seq,ts FROM stg_event_raw/stg_event (capture scope)",
                    metric_sql]),
        {
            "pid": project_id,
            "cap": capture_id,
            "kpi_code": canonical,
            "metric_code_nmf": metric_code_nmf,
            "max_points": max_points,
        },
        {
            "n_total": len(points),
            "n_returned": len(out),
            "sampling": sampling,
        },
    )

    source_table = "nmf_event_light" if state["decode_level"] == "light" else metric.source_table
    source_view = (
        f"{source_table} ∪ nmf_event_light"
        if source_table != "nmf_event_light"
        else source_table
    ) + " LEFT JOIN stg_event_raw(lat,lon,ts) LEFT JOIN nmf_file(filename,start_at)"

    x_axis, y_axis = _axes(entry, metric.unit)
    return {
        "status": "AVAILABLE",
        "reason": None,
        "metric_code": canonical,
        "metric_name": entry.get("name") or metric.label,
        "capture_id": capture_id,
        "x_axis": x_axis.model_dump(),
        "y_axis": y_axis.model_dump(),
        "n_total": len(points),
        "n_returned": len(out),
        "points": [
            {
                "seq": p["seq"],
                "time_s": float(p["t_rel_s"]),
                "value": p["value"],
                "longitude": p.get("longitude"),
                "latitude": p.get("latitude"),
                "nmf_file": p.get("nmf_file"),
                "event_ts": p.get("event_ts"),
                "nmf_file_start": p.get("nmf_file_start"),
            }
            for p in out
        ],
        "sampling": sampling,
        "evidence": {
            "source_view": source_view,
            "source_table": source_table,
            "source_column": metric.source_column,
            "metric_code_nmf": metric_code_nmf,
            "n": len(points),
            "result_id": rid,
            "decoder_version": state["decoder_version"],
            "schema_version": state["schema_version"],
            "decode_level": state["decode_level"],
            "origin_seq": origin_seq,
            "origin_ts": origin_ts,
        },
    }
