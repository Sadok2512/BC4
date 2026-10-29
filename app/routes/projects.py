from __future__ import annotations

import gzip
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import exists, text
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
from app.models import AppUser, NmfFile, Project, ProjectShare, NmfImportJob
from app.services.import_jobs import enqueue, job_view, active_job
from app.schemas.ingest import NmfImportJobView
from app.schemas.common import FilterContext, OverviewData, Project as ProjectSchema
from app.schemas.ingest import (
    NmfFileEntry,
    NmfImportReport,
    ProjectCreate,
    ProjectParsingUpdate,
    ProjectShareCreate,
    ProjectShareView,
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
from app.services.capture_delete import (
    CaptureDeleteBusy,
    CaptureDeleteFinalizationError,
    CaptureNotFound,
    delete_capture as delete_capture_service,
)

# Auth minimum « lecteur » exigée pour TOUTES les routes de ce routeur :
# lecture et écriture passent par la même porte, la différentiation
# lecteur/ingenieur se fait DANS les handlers d'écriture via `require_role`.
router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[ProjectSchema])
def list_projects(
    scope: str = Query(default="my", pattern="^(my|all)$"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectSchema]:
    query = db.query(Project)
    if scope == "my":
        query = query.filter(Project.owner_id == current_user.id)
    else:
        query = query.filter(
            (Project.owner_id == current_user.id)
            | (Project.visibility == "public")
            | exists().where(
                (ProjectShare.project_id == Project.id)
                & (ProjectShare.user_id == current_user.id)
            )
        )
    return [project_to_schema(p) for p in query.order_by(Project.imported_at.desc()).all()]


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
        owner_id=p.owner_id,
        visibility=p.visibility,
        parse_decode_level=p.parse_decode_level,
        parse_binning_mode=p.parse_binning_mode,
        parse_temporal_resolution=p.parse_temporal_resolution,
        parse_spatial_bin_m=p.parse_spatial_bin_m,
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
    current_user=Depends(get_current_user),
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
        owner_id=current_user.id,
        visibility=body.visibility,
        parse_decode_level=body.parse_decode_level,
        parse_binning_mode=body.parse_binning_mode,
        parse_temporal_resolution=body.parse_temporal_resolution,
        parse_spatial_bin_m=body.parse_spatial_bin_m,
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


@router.patch("/{project_id}/parsing", response_model=ProjectIngestView)
def update_project_parsing(
    project_id: str,
    body: ProjectParsingUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectIngestView:
    project = _owned_project(db, project_id, current_user.id)
    project.parse_decode_level = body.parse_decode_level
    project.parse_binning_mode = body.parse_binning_mode
    project.parse_temporal_resolution = body.parse_temporal_resolution
    project.parse_spatial_bin_m = body.parse_spatial_bin_m
    db.commit()
    db.refresh(project)
    return _ingest_view(project)


def _owned_project(db: Session, project_id: str, user_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user_id:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
    return project


def _share_view(share: ProjectShare, user: AppUser) -> ProjectShareView:
    return ProjectShareView(
        user_id=user.id,
        email=user.email,
        role=user.role,
        created_at=share.created_at.isoformat().replace("+00:00", "Z"),
    )


@router.get("/{project_id}/shares", response_model=list[ProjectShareView])
def list_project_shares(
    project_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectShareView]:
    _owned_project(db, project_id, current_user.id)
    rows = (
        db.query(ProjectShare, AppUser)
        .join(AppUser, AppUser.id == ProjectShare.user_id)
        .filter(ProjectShare.project_id == project_id)
        .order_by(AppUser.email)
        .all()
    )
    return [_share_view(share, user) for share, user in rows]


@router.post("/{project_id}/shares", response_model=ProjectShareView, status_code=201)
def create_project_share(
    project_id: str,
    body: ProjectShareCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectShareView:
    _owned_project(db, project_id, current_user.id)
    email = body.email.strip().lower()
    user = db.query(AppUser).filter(AppUser.email == email, AppUser.active.is_(True)).one_or_none()
    if user is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Utilisateur introuvable"})
    if user.id == current_user.id:
        raise HTTPException(409, {"code": "CONFLICT", "message": "Le propriétaire a déjà accès"})
    existing = db.get(ProjectShare, (project_id, user.id))
    if existing is not None:
        return _share_view(existing, user)
    share = ProjectShare(
        project_id=project_id,
        user_id=user.id,
        created_by=current_user.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return _share_view(share, user)


@router.delete("/{project_id}/shares/{user_id}", status_code=204, response_class=Response)
def delete_project_share(
    project_id: str,
    user_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    _owned_project(db, project_id, current_user.id)
    share = db.get(ProjectShare, (project_id, user_id))
    if share is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Partage introuvable"})
    db.delete(share)
    db.commit()
    return Response(status_code=204)


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


@router.delete(
    "/{project_id}/captures/{capture_id}",
    status_code=204,
    response_class=Response,
)
def delete_capture(
    project_id: str,
    capture_id: str,
    reason: str = Query(min_length=10, description="Justification tracée dans le journal JSON"),
    db: Session = Depends(get_db),
) -> Response:
    """Supprime une capture strictement dans le projet accessible.

    ``require_project_write`` est appliqué globalement à ce routeur dans
    ``app.main`` : un projet absent, privé ou non possédé renvoie toujours
    404 avant d'atteindre le service.
    """
    try:
        report = delete_capture_service(db, project_id, capture_id, reason=reason)
    except CaptureNotFound as exc:
        raise HTTPException(
            404, {"code": "NOT_FOUND", "message": "Capture introuvable"}
        ) from exc
    except CaptureDeleteBusy as exc:
        raise HTTPException(
            409,
            {"code": "IMPORT_ACTIVE", "message": "Un import est en cours pour ce projet."},
        ) from exc
    except CaptureDeleteFinalizationError as exc:
        raise HTTPException(
            500,
            {
                "code": "FINALIZATION_FAILED",
                "message": "Capture supprimée, mais finalisation du projet en échec.",
                "audit": str(exc),
            },
        ) from exc
    return Response(status_code=204, headers={"X-BC4-Audit-Id": report["op_id"]})


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
    # NMFHE2 — récupérer n_records par capture pour alimenter la colonne
    # Records du dialog Superstream (complément de n_events qui ne compte
    # que les messages L3 décodés).
    cap_n_records = dict(db.execute(text(
        "SELECT nmf_file_id, SUM(n_records) FROM nmf_capture "
        "WHERE project_id=:pid GROUP BY nmf_file_id"
    ), {"pid": project.id}).all())
    cap_ids: dict[str, list[str]] = {}
    for file_id, capture_id in db.execute(text(
        "SELECT nmf_file_id, capture_id FROM nmf_capture "
        "WHERE project_id=:pid ORDER BY nmf_file_id, capture_id"
    ), {"pid": project.id}).all():
        cap_ids.setdefault(str(file_id), []).append(str(capture_id))
    entries = [
        NmfFileEntry(
            filename=f.filename,
            status=f.status,  # type: ignore[arg-type]
            n_captures=f.n_captures,
            n_events=f.n_events,
            n_gps=f.n_gps,
            decoder_version=f.decoder_version,
            error_msg=f.error_msg,
            imported_at=f.uploaded_at.isoformat().replace("+00:00", "Z"),
            n_records=int(cap_n_records.get(f.id) or 0),
            capture_ids=cap_ids.get(f.id, []),
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
    request: Request,
    op: str | None = Query(default=None, description="CSV operators"),
    tech: str | None = Query(default=None),
    svc: str | None = Query(default=None),
    band: str | None = Query(default=None),
    dep: str | None = Query(default=None),
    metric: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
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
        data = compute_overview(db, f)
        # Already validated Pydantic models: serialize directly in Rust instead
        # of expanding the entire population into a second Python object tree.
        payload = data.model_dump_json().encode("utf-8")
        encodings = request.headers.get("accept-encoding", "").lower().split(",")
        gzip_allowed = any(
            entry.split(";")[0].strip() == "gzip"
            and not any(
                part.strip().startswith("q=") and part.strip()[2:].strip() in ("0", "0.0", "0.00", "0.000")
                for part in entry.split(";")[1:]
            )
            for entry in encodings
        )
        if gzip_allowed:
            return Response(
                gzip.compress(payload, compresslevel=3),
                media_type="application/json",
                headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
            )
        return Response(payload, media_type="application/json",
                        headers={"Vary": "Accept-Encoding"})
    except LookupError:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
