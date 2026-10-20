"""Endpoints KPI scopés projet — catalogue v2 (0.40.0).

Trois routes publiques (auth lecteur mini, injectée par le router) :
  - GET /projects/{project_id}/kpi/catalog     (+ ?service_type[])
  - GET /projects/{project_id}/kpi/filters
  - GET /projects/{project_id}/kpi/{code}      (+ query filtres)

Scope ``project_id`` injecté SERVEUR via le path (jamais depuis le body).
Zéro ligne brute, zéro SQL exposé — tout agrégé. Jamais de valeur
inventée : si une source est indisponible, le statut est renseigné
(UNVALIDATED | PENDING | UNAVAILABLE | NOT_APPLICABLE) et ``value``
reste ``null``.

0.40.0 — Les routes consomment désormais ``catalog_v2`` (194 KPI
canoniques + 14 alias, soit 208 entrées xlsx) et exposent le filtre
``service_type[]`` pour déclarer ``NOT_APPLICABLE`` sur un KPI hors
scope de service (pas un ``n=0`` muet).
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_actor, get_current_user, require_role, with_statement_timeout_60s
from app.kpi.service_v2 import (
    build_catalog_v2_response,
    build_filters_v2,
    compute_kpi_v2,
)
from app.measure.ecgi import populate_ecgi_for_project
from app.models import Project
from app.schemas.project_kpi import (
    ProjectKpiCatalog,
    ProjectKpiDetail,
    ProjectKpiFilters,
)
from app.schemas.settings import Actor
from app.routes.tasks import filters as analytics_filters
from app.kpi.population import validate_operators, QueryTrace
from app.routes.tasks import evidence


router = APIRouter(
    prefix="/projects",
    tags=["kpi-project"],
    # 0.48.0 — statement_timeout 60 s pour empêcher qu'une requête bloquée
    # (lock, scan dément) ne tombe en time-out seule au bout de plusieurs
    # minutes. Les routes write (_populate_ecgi, _rebuild_param_occurrence)
    # restent sous ce plafond : si une opération réelle a besoin de plus,
    # c'est qu'elle doit être async / batch, pas HTTP.
    dependencies=[Depends(get_current_user), Depends(with_statement_timeout_60s)],
)


def _require_project(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(
            404, {"code": "NOT_FOUND", "message": "Projet introuvable"}
        )
    return p


@router.get("/{project_id}/kpi/catalog", response_model=ProjectKpiCatalog)
def kpi_catalog(
    project_id: str,
    service_type: list[str] = Query(default_factory=list),
    db: Session = Depends(get_db),
) -> dict:
    """Catalogue v2 : 194 canoniques + 14 alias (208 input xlsx).

    Si ``service_type[]`` est fourni, les KPI hors scope sont marqués
    ``NOT_APPLICABLE`` dans l'arbre (jamais filtrés silencieusement).
    """
    _require_project(db, project_id)
    from app.kpi.catalog_cache import catalog_cache
    # Authorization and project existence are checked before cache access.
    # Only catalogue statuses are cached, for at most 30 seconds.
    services = tuple(sorted(set(service_type)))
    return catalog_cache.get(
        (project_id, services),
        lambda: build_catalog_v2_response(db, project_id, services=services),
    )


@router.get("/{project_id}/kpi/filters", response_model=ProjectKpiFilters)
def kpi_filters(project_id: str, db: Session = Depends(get_db)) -> dict:
    _require_project(db, project_id)
    return build_filters_v2(db, project_id)


@router.post("/{project_id}/kpi/_rebuild_param_occurrence")
def kpi_rebuild_param_occurrence(
    project_id: str,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> dict:
    """Admin — re-décode tous les events RRC du projet (purge + repopulate
    ``param_occurrence``). À appeler après un release du walker ASN.1
    (ex. 0.42.0 — BIT STRING long + MCC/MNC concaténés)."""
    require_role(actor, "admin")
    _require_project(db, project_id)
    from app.dict.populate import populate_param_occurrence
    stats = populate_param_occurrence(db, project_id, purge=True)
    db.commit()
    return {
        "project_id": project_id,
        "stats":      stats,
    }


@router.post("/{project_id}/kpi/_populate_ecgi")
def kpi_populate_ecgi(
    project_id: str,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> dict:
    """Admin — déclenche la propagation ECGI pour ce projet.

    Lit SIB1 depuis ``param_occurrence``, construit la liste des
    cellules observées, propage ``measurement_points.ecgi`` par
    ``(capture_id, earfcn)`` et alimente ``cell_ref`` depuis les logs.
    """
    require_role(actor, "admin")
    _require_project(db, project_id)
    report = populate_ecgi_for_project(db, project_id)
    return {
        "project_id":            report.project_id,
        "sib1_cells":            report.sib1_cells,
        "distinct_ecgi":         report.distinct_ecgi,
        "mp_total":              report.mp_total,
        "mp_with_ecgi":          report.mp_with_ecgi,
        "mp_pct_with_ecgi":      round(report.mp_pct_with_ecgi, 2),
        "plmn_mismatch":         report.plmn_mismatch,
        "plmn_mismatch_examples": report.plmn_mismatch_examples,
        "sample_cell":           report.sample_cell,
        "warnings":              report.warnings,
    }


@router.get("/{project_id}/kpi/{code}", response_model=ProjectKpiDetail)
def kpi_detail(
    project_id: str,
    code: str,
    operator: list[str] = Query(default_factory=list),
    service_type: list[str] = Query(default_factory=list),
    phase: list[str] = Query(default_factory=list),
    group_by: str = Query(default="none"),
    applied: dict = Depends(analytics_filters),
    db: Session = Depends(get_db),
) -> dict:
    _require_project(db, project_id)
    # 0.46.1 — Alignement avec service_v2.GroupBy (dim cell_ref géo
    # peuvent toutes servir de group_by si cell_ref.{col} est peuplé).
    if group_by not in ("none", "operator", "band", "operator_band", "dor", "dr", "plaque", "arcep_zone"):
        raise HTTPException(
            400,
            {
                "code": "GROUP_BY_UNKNOWN",
                "message": f"group_by {group_by!r} invalide. "
                "Valeurs admises : operator | band | operator_band | dor | dr | plaque | arcep_zone.",
            },
        )
    validate_operators(db,project_id,applied)
    trace=QueryTrace(db)
    result=compute_kpi_v2(
        trace,
        project_id,
        code,
        operators=tuple(operator),
        filters=applied,
        services=tuple(service_type),
        phases=tuple(phase),
        group_by=group_by,  # type: ignore[arg-type]
    )
    result['result_id']=evidence(db,project_id,';\n'.join(q['sql'] for q in trace.queries),
        {'applied_filters':applied,'code':code,'group_by':group_by,'queries':trace.queries},
        {'n':result.get('n'),'denominator':result.get('denominator')})
    return result


# ---------------------------------------------------------------------------
# 0.42.1 — Export CSV du référentiel cellule du projet
# ---------------------------------------------------------------------------


_EXPORT_HEADERS: tuple[str, ...] = (
    "ecgi", "plmn", "operator", "enb_id", "local_cell_id", "tac",
    "pci", "earfcn", "band", "n_points", "first_capture",
    # Vides à remplir par l'opérateur :
    "dr", "plaque", "dor", "arcep_zone", "commune", "insee",
)


@router.get("/{project_id}/cell-ref/export.csv")
def cell_ref_export_csv(
    project_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """Export CSV du référentiel cellule du projet (0.42.1).

    Une ligne par ECGI distinct observé dans ``measurement_points.ecgi``,
    enrichie des colonnes connues (depuis ``cell_ref``) ET du nombre
    de points mesurés par cellule (``n_points``) + le ``first_capture``
    où elle apparaît en ordre ``(capture_id, seq)``. Les colonnes
    opérateur (dr, plaque, dor, arcep_zone, commune, insee) sont
    volontairement vides si non chargées — pré-remplies seulement si
    déjà présentes dans ``cell_ref``.

    Format : UTF-8 BOM + séparateur ``;`` (Excel FR).

    Scope strict : seuls les ECGI du projet sont exportés.
    """
    _require_project(db, project_id)

    # 0.42.1 — Scope projet = UNION
    # (a) cellules dont au moins un mp.ecgi existe (serving actif), ET
    # (b) cellules observées en SIB1 pendant les captures du projet
    #     (cell_ref.snapshot_date ∈ captures-du-projet).
    # Les cellules (b) sans mesure serving sortent avec n_points=0 —
    # elles sont néanmoins DU projet (vues en SIB1), donc exposées pour
    # permettre à l'opérateur de les géo-tagger via l'upload retour.
    rows = db.execute(
        text(
            """
            WITH mp_agg AS (
                SELECT ecgi, COUNT(*) AS n_points
                FROM measurement_points
                WHERE project_id = :pid AND ecgi IS NOT NULL
                GROUP BY ecgi
            ),
            project_captures AS (
                SELECT DISTINCT capture_id
                FROM stg_event WHERE project_id = :pid
            ),
            scope AS (
                SELECT DISTINCT cr.eci
                FROM cell_ref cr
                WHERE cr.eci LIKE '%-%'
                  AND cr.snapshot_date IN (SELECT capture_id FROM project_captures)
                UNION
                SELECT ecgi AS eci FROM mp_agg
            )
            SELECT s.eci,
                   cr.enodebid,
                   cr.pci,
                   cr.earfcn,
                   cr.band_3gpp,
                   cr.snapshot_date       AS first_capture,
                   cr.dr, cr.plaque, cr.dor, cr.arcep_zone,
                   cr.commune, cr.insee,
                   COALESCE(mp_agg.n_points, 0) AS n_points
            FROM scope s
            LEFT JOIN cell_ref cr ON cr.eci = s.eci
            LEFT JOIN mp_agg ON mp_agg.ecgi = s.eci
            ORDER BY s.eci
            """
        ),
        {"pid": project_id},
    ).fetchall()

    # Lookup opérateur depuis le PLMN (préfixe avant '-')
    plmn_to_operator = {
        "20801": "Orange", "20802": "Orange",
        "20810": "SFR",    "20811": "SFR",    "20813": "SFR",
        "20820": "Bouygues","20821": "Bouygues","20888": "Bouygues",
        "20815": "Free",   "20816": "Free",
    }

    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(_EXPORT_HEADERS)
    for r in rows:
        ecgi = r[0] or ""
        plmn = ""
        cell_identity = None
        if "-" in ecgi:
            plmn, _, ci_str = ecgi.partition("-")
            try:
                cell_identity = int(ci_str)
            except (TypeError, ValueError):
                cell_identity = None
        operator = plmn_to_operator.get(plmn, "")
        enb_id = r[1] or ""
        local_cell_id = (cell_identity & 0xFF) if cell_identity is not None else ""
        tac = ""  # tac n'est pas persisté dans cell_ref — vide à l'export
        pci = "" if r[2] is None else str(r[2])
        earfcn = "" if r[3] is None else str(r[3])
        band = r[4] or ""
        first_capture = r[5] or ""
        n_points = int(r[12]) if r[12] is not None else 0
        dr      = r[6]  or ""
        plaque  = r[7]  or ""
        dor     = r[8]  or ""
        arcep   = r[9]  or ""
        commune = r[10] or ""
        insee   = r[11] or ""
        writer.writerow([
            ecgi, plmn, operator, enb_id, local_cell_id, tac,
            pci, earfcn, band, n_points, first_capture,
            dr, plaque, dor, arcep, commune, insee,
        ])
    # BOM UTF-8 pour Excel FR
    body = "﻿" + out.getvalue()
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=cell-ref-{project_id}.csv",
        },
    )
