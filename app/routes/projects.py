from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_actor, get_current_user, require_role
from app.ingest.nmf import (
    BodyTooLarge,
    MAX_FILE_BYTES,
    ingest_upload,
    refresh_project_summary,
    resolve_decoder,
)
from app.models import NmfFile, Project, NmfImportJob
from app.services.import_jobs import enqueue, job_view, active_job
from app.schemas.ingest import NmfImportJobView
from app.schemas.common import FilterContext, OverviewData, Project as ProjectSchema
from app.schemas.ingest import (
    NmfFileEntry,
    NmfImportReport,
    ProjectCreate,
    ProjectIngestView,
)
from app.schemas.settings import Actor
from app.services.filters import parse_csv_list
from app.services.import_report import (
    ORIGIN_LAT,
    ORIGIN_LNG,
    PROJECT_ID_LEN,
    build_import_report,
)
from app.services.overview import compute_overview, project_to_schema
from app.services.populate_chain import run_populate_chain

# Auth minimum « lecteur » exigée pour TOUTES les routes de ce routeur :
# lecture et écriture passent par la même porte, la différentiation
# lecteur/ingenieur se fait DANS les handlers d'écriture via `require_role`.
router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[ProjectSchema])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectSchema]:
    return [project_to_schema(p) for p in db.query(Project).order_by(Project.imported_at.desc()).all()]


def _ingest_view(p: Project) -> ProjectIngestView:
    created = (
        p.created_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if p.created_at
        else None
    )
    status = p.status_ingest or ("ready" if p.status == "ready" else "draft")
    perimeter = p.perimeter if isinstance(p.perimeter, dict) else None
    return ProjectIngestView(
        id=p.id,
        name=p.name,
        created_at=created,
        actor=p.actor,
        status=status,  # type: ignore[arg-type]
        operators=p.operators_plmn if p.operators_plmn is not None else None,
        technos=p.technos_seen if p.technos_seen is not None else None,
        n_captures=p.n_captures_ingest,
        n_events=p.n_events_ingest,
        gps_coverage_pct=p.gps_coverage_pct,
        perimeter=perimeter,  # type: ignore[arg-type]
    )


@router.post("", response_model=ProjectIngestView, status_code=201)
def create_project(
    body: ProjectCreate,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> ProjectIngestView:
    """Crée un projet draft (= lot NMF vide, prêt à recevoir des uploads)."""
    require_role(actor, "admin", "editor")
    now = datetime.now(timezone.utc)
    pid = uuid.uuid4().hex[:PROJECT_ID_LEN]
    # On remplit AUSSI les colonnes Zod existantes avec des valeurs honnêtes :
    # listes vides, 0 captures, imported_at = création. Elles seront
    # recalculées par `refresh_project_summary()` à mesure que les NMF
    # arrivent.
    p = Project(
        id=pid,
        name=body.name,
        geography="",
        center_lng=ORIGIN_LNG,
        center_lat=ORIGIN_LAT,
        operators=[],
        technologies=[],
        services=[],
        bands=[],
        departements=[],
        period_start=now.date().isoformat(),
        period_end=now.date().isoformat(),
        captures=0,
        imported_at=now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        status="processing",  # mapping draft → processing (contrat Zod existant)
        created_at=now,
        actor=actor.login,
        status_ingest="draft",
        operators_plmn={},
        technos_seen={},
        n_captures_ingest=0,
        n_events_ingest=0,
        gps_coverage_pct=None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _ingest_view(p)


@router.get("/{project_id}", response_model=ProjectSchema)
def get_project(project_id: str, db: Session = Depends(get_db)) -> ProjectSchema:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
    return project_to_schema(p)


@router.delete("/{project_id}", response_class=Response)
def delete_project(
    project_id: str,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> Response:
    """Supprime un projet et ses enfants en cascade (nmf_file, stg_event,
    measurement_points, rrc_observations) via les FK `ondelete=CASCADE`
    déjà déclarées en migration. Portée strictement limitée à l'ID :
    aucune autre table n'est touchée.

    - admin + ingenieur peuvent supprimer (via mapping `editor`).
    - **204** No Content si supprimé.
    - **404** si l'ID n'existe pas (jamais confondu avec un 403 — ne pas
      laisser fuiter l'existence du projet par le code HTTP).
    - **403** si le rôle est insuffisant (lecteur).
    """
    require_role(actor, "admin", "editor")
    p = db.query(Project).filter(Project.id == project_id).with_for_update().one_or_none()
    if not p:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
    if active_job(db, project_id):
        raise HTTPException(409, "Un import est en cours pour ce projet.")
    db.delete(p)
    db.commit()
    return Response(status_code=204)


@router.get("/{project_id}/ingest", response_model=ProjectIngestView)
def get_project_ingest(project_id: str, db: Session = Depends(get_db)) -> ProjectIngestView:
    """Vue projet côté ingestion : status draft/importing/ready/error +
    résumé rempli à l'ingestion. Le GET /{project_id} classique garde le
    contrat Zod existant (compat front)."""
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
    return _ingest_view(p)


@router.post("/{project_id}/nmf", response_model=NmfImportJobView, status_code=202)
def upload_nmf(
    project_id: str,
    files: list[UploadFile] = File(...),
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> NmfImportJobView:
    require_role(actor, "admin", "editor")
    return job_view(enqueue(db, project_id, files))


@router.get("/{project_id}/imports/{job_id}", response_model=NmfImportJobView)
def get_import_job(project_id: str, job_id: str, db: Session = Depends(get_db)) -> NmfImportJobView:
    job = db.get(NmfImportJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Import introuvable")
    return job_view(job)


@router.get("/{project_id}/import", response_model=NmfImportReport)
def get_import_report(
    project_id: str,
    db: Session = Depends(get_db),
) -> NmfImportReport:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
    files = db.query(NmfFile).filter(NmfFile.project_id == project.id).order_by(NmfFile.uploaded_at).all()
    entries = [
        NmfFileEntry(
            filename=f.filename,
            status=f.status,  # type: ignore[arg-type]
            n_captures=f.n_captures,
            n_events=f.n_events,
            n_gps=f.n_gps,
            decoder_version=f.decoder_version,
            error_msg=f.error_msg,
        )
        for f in files
    ]
    done = sum(1 for f in files if f.status == "done")
    err = sum(1 for f in files if f.status == "error")
    return build_import_report(
        db, project, entries,
        files_received=len(files),
        files_done=done,
        files_error=err,
    )


@router.get("/{project_id}/overview", response_model=OverviewData)
def overview(
    project_id: str,
    op: str | None = Query(default=None, description="CSV operators"),
    tech: str | None = Query(default=None),
    svc: str | None = Query(default=None),
    band: str | None = Query(default=None),
    dep: str | None = Query(default=None),
    metric: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> OverviewData:
    f = FilterContext(
        project=project_id,
        op=parse_csv_list(op),
        tech=parse_csv_list(tech),
        svc=parse_csv_list(svc),
        band=parse_csv_list(band),
        dep=parse_csv_list(dep),
        metric=metric,  # type: ignore[arg-type]
    )
    try:
        return compute_overview(db, f)
    except LookupError:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
