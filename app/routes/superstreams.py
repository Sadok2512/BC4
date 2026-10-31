"""Routes /projects/{id}/superstreams — groupage ordonné de captures.

Un superstream est une liste ORDONNÉE de captures d'un MÊME projet,
jamais entrelacée par ts (règle d'ordre canonique). Aucune donnée n'est
copiée : les membres pointent par `(project_id, capture_id)` via FK
composite vers `nmf_capture`.

Les écritures utilisent exclusivement les identités réelles `captureIds`.
`logIds` reste exposé en lecture pendant la transition du front, mais n'est
jamais accepté comme identité d'écriture.

Accès : lecture via `get_accessible_project` (owner + public + share) ;
écriture via `require_project_write` (owner uniquement). Mêmes règles
que le projet lui-même — un stream est une vue du projet.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_accessible_project, require_project_write
from app.models import AppUser, Project, Superstream, SuperstreamMember
from app.kpi.nmf_bins import query_metric_bins


router = APIRouter(
    prefix="/projects/{project_id}/superstreams",
    tags=["superstreams"],
    dependencies=[Depends(get_current_user), Depends(get_accessible_project)],
)


# ---------------------------------------------------------------------------
# Pydantic shapes — alignés sur le contrat front (camelCase pour sortie)
# ---------------------------------------------------------------------------


class SuperstreamCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    captureIds: list[str] = Field(min_length=1)


class SuperstreamRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class SuperstreamMembersIn(BaseModel):
    captureIds: list[str] = Field(min_length=1)


class SuperstreamMemberSummary(BaseModel):
    position: int
    captureId: str
    captureName: str


class SuperstreamOut(BaseModel):
    """Shape de sortie identique au `SuperstreamSchema` front +
    `captureIds`/`positions` pour les consommateurs qui lisent le flux.
    """

    id: str
    projectId: str
    name: str
    logIds: list[str]
    captureIds: list[str]
    positions: list[int]
    members: list[SuperstreamMemberSummary]
    revision: int
    createdAt: str
    updatedAt: str


# ---------------------------------------------------------------------------
# Validation captureIds
# ---------------------------------------------------------------------------


def _validate_capture_ids(
    db: Session, project_id: str, capture_ids: list[str]
) -> list[tuple[str, str]]:
    """Validate an ordered member list without guessing or reordering it."""
    if len(capture_ids) != len(set(capture_ids)):
        raise HTTPException(
            422,
            {"code": "SUPERSTREAM_DUPLICATE_CAPTURE", "message": "Une capture ne peut apparaître qu'une fois."},
        )
    rows = db.execute(text("""
        SELECT c.capture_id, f.status
        FROM nmf_capture c
        JOIN nmf_file f ON f.id = c.nmf_file_id AND f.project_id = c.project_id
        WHERE c.project_id = :pid AND c.capture_id = ANY(:caps)
    """), {"pid": project_id, "caps": capture_ids}).all()
    states = {str(capture_id): status for capture_id, status in rows}
    unknown = [capture_id for capture_id in capture_ids if capture_id not in states]
    not_done = [capture_id for capture_id in capture_ids if states.get(capture_id) != "done" and capture_id in states]
    if unknown or not_done:
        raise HTTPException(
            422,
            {
                "code": "SUPERSTREAM_INVALID_CAPTURES",
                "message": "Toutes les captures doivent exister dans le projet et être terminées.",
                "unknown": unknown,
                "not_done": not_done,
            },
        )
    return [(project_id, capture_id) for capture_id in capture_ids]


def _clean_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        raise HTTPException(422, {"code": "SUPERSTREAM_NAME_REQUIRED", "message": "Le nom est obligatoire."})
    return clean


def _expected_revision(if_match: str | None) -> int:
    if if_match is None:
        raise HTTPException(
            428,
            {"code": "PRECONDITION_REQUIRED", "message": "If-Match est obligatoire."},
        )
    raw = if_match.strip()
    if raw.startswith("W/"):
        raw = raw[2:].strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        raw = raw[1:-1]
    try:
        revision = int(raw)
    except ValueError as exc:
        raise HTTPException(400, {"code": "INVALID_IF_MATCH", "message": "If-Match doit contenir une révision entière."}) from exc
    if revision < 1:
        raise HTTPException(400, {"code": "INVALID_IF_MATCH", "message": "La révision doit être positive."})
    return revision


def _set_etag(response: Response, revision: int) -> None:
    response.headers["ETag"] = f'"{revision}"'


def _reverse_log_id(db: Session, project_id: str, capture_ids: list[str]) -> list[str]:
    """Reconstruit les `logIds` depuis des `capture_id` : lookup
    `nmf_capture.nmf_file_id → nmf_file.filename` + suffixe `#N` si
    doublon. Garde l'ordre d'entrée."""
    if not capture_ids:
        return []
    rows = db.execute(text("""
        SELECT c.capture_id, f.filename
        FROM nmf_capture c JOIN nmf_file f ON f.id = c.nmf_file_id
        WHERE c.project_id = :pid AND c.capture_id = ANY(:caps)
    """), {"pid": project_id, "caps": capture_ids}).all()
    cap_to_filename = {cap: fname for cap, fname in rows}

    # Compte filenames pour savoir si suffixe #N nécessaire
    all_files = db.execute(text(
        "SELECT filename FROM nmf_file WHERE project_id=:pid ORDER BY uploaded_at"
    ), {"pid": project_id}).all()
    seen: dict[str, int] = {}
    file_order: dict[str, list[int]] = {}
    for i, (fname,) in enumerate(all_files):
        seen[fname] = seen.get(fname, 0) + 1

    # Pour chaque capture_id, retrouver le filename et l'index si doublon.
    # Ici simplifié : si filename apparaît >1 dans le projet, suffixe #N
    # basé sur l'ordre uploaded_at.
    occurrence_idx: dict[str, int] = {}
    out: list[str] = []
    for cap in capture_ids:
        fname = cap_to_filename.get(cap)
        if fname is None:
            out.append(cap)  # fallback défensif, ne devrait pas arriver
            continue
        if seen.get(fname, 0) > 1:
            idx = occurrence_idx.get(fname, 0)
            occurrence_idx[fname] = idx + 1
            out.append(f"{fname}#{idx}" if idx > 0 else fname)
        else:
            out.append(fname)
    return out


def _serialize(db: Session, ss: Superstream) -> SuperstreamOut:
    members = db.execute(text("""
        SELECT m.capture_id, m.position, f.filename
        FROM superstream_member m
        JOIN nmf_capture c
          ON c.project_id = m.project_id AND c.capture_id = m.capture_id
        JOIN nmf_file f ON f.id = c.nmf_file_id AND f.project_id = c.project_id
        WHERE m.superstream_id = :sid AND m.project_id = :pid
        ORDER BY m.position
    """), {"sid": ss.id, "pid": ss.project_id}).all()
    capture_ids = [m[0] for m in members]
    positions = [m[1] for m in members]
    log_ids = _reverse_log_id(db, ss.project_id, capture_ids)
    return SuperstreamOut(
        id=ss.id,
        projectId=ss.project_id,
        name=ss.name,
        logIds=log_ids,
        captureIds=capture_ids,
        positions=positions,
        members=[
            SuperstreamMemberSummary(position=m[1], captureId=m[0], captureName=m[2])
            for m in members
        ],
        revision=ss.revision,
        createdAt=ss.created_at.isoformat().replace("+00:00", "Z"),
        updatedAt=ss.updated_at.isoformat().replace("+00:00", "Z"),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[SuperstreamOut])
def list_project_superstreams(
    project_id: str,
    db: Session = Depends(get_db),
) -> list[SuperstreamOut]:
    """Liste les superstreams du projet. Lecture : `get_accessible_project`."""
    streams = (
        db.query(Superstream)
        .filter(Superstream.project_id == project_id)
        .order_by(Superstream.created_at, Superstream.id)
        .all()
    )
    return [_serialize(db, s) for s in streams]


@router.post(
    "",
    response_model=SuperstreamOut,
    status_code=201,
    dependencies=[Depends(require_project_write)],
)
def create_project_superstream(
    project_id: str,
    body: SuperstreamCreateIn,
    response: Response,
    db: Session = Depends(get_db),
    current: AppUser = Depends(get_current_user),
) -> SuperstreamOut:
    """Create an ordered group from real capture identifiers."""
    members = _validate_capture_ids(db, project_id, body.captureIds)

    now = datetime.now(timezone.utc)
    ss = Superstream(
        id=f"ss_{uuid.uuid4().hex[:16]}",
        project_id=project_id,
        name=_clean_name(body.name),
        created_by=current.id,
        created_at=now,
        updated_at=now,
        revision=1,
    )
    db.add(ss)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            {"code": "CONFLICT", "message": "Un superstream du même nom existe déjà."},
        )

    for pos, (pid, cap) in enumerate(members):
        db.add(SuperstreamMember(
            superstream_id=ss.id, project_id=pid, capture_id=cap, position=pos
        ))
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            422,
            {"code": "SUPERSTREAM_INTEGRITY", "message": str(e.orig)},
        )
    db.refresh(ss)
    _set_etag(response, ss.revision)
    return _serialize(db, ss)


@router.get("/{ss_id}", response_model=SuperstreamOut)
def get_project_superstream(
    project_id: str,
    ss_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> SuperstreamOut:
    ss = db.get(Superstream, ss_id)
    if ss is None or ss.project_id != project_id:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Superstream introuvable"})
    _set_etag(response, ss.revision)
    return _serialize(db, ss)


def _raise_missing_or_revision_conflict(
    db: Session, project_id: str, ss_id: str, expected: int
) -> None:
    actual = db.execute(
        text("SELECT revision FROM superstream WHERE id=:sid AND project_id=:pid"),
        {"sid": ss_id, "pid": project_id},
    ).scalar_one_or_none()
    if actual is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Superstream introuvable"})
    raise HTTPException(
        409,
        {
            "code": "REVISION_CONFLICT",
            "message": "Le Superstream a été modifié par une autre requête.",
            "expected": expected,
            "actual": int(actual),
        },
    )


@router.patch(
    "/{ss_id}",
    response_model=SuperstreamOut,
    dependencies=[Depends(require_project_write)],
)
def rename_project_superstream(
    project_id: str,
    ss_id: str,
    body: SuperstreamRenameIn,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> SuperstreamOut:
    expected = _expected_revision(if_match)
    try:
        row = db.execute(text("""
            UPDATE superstream
            SET name=:name, updated_at=:now, revision=revision+1
            WHERE id=:sid AND project_id=:pid AND revision=:expected
            RETURNING revision
        """), {
            "name": _clean_name(body.name),
            "now": datetime.now(timezone.utc),
            "sid": ss_id,
            "pid": project_id,
            "expected": expected,
        }).one_or_none()
        if row is None:
            _raise_missing_or_revision_conflict(db, project_id, ss_id, expected)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            409,
            {"code": "SUPERSTREAM_NAME_CONFLICT", "message": "Un Superstream du même nom existe déjà."},
        ) from e
    ss = db.get(Superstream, ss_id)
    assert ss is not None
    db.refresh(ss)
    _set_etag(response, ss.revision)
    return _serialize(db, ss)


@router.put(
    "/{ss_id}/members",
    response_model=SuperstreamOut,
    dependencies=[Depends(require_project_write)],
)
def replace_project_superstream_members(
    project_id: str,
    ss_id: str,
    body: SuperstreamMembersIn,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> SuperstreamOut:
    expected = _expected_revision(if_match)
    members = _validate_capture_ids(db, project_id, body.captureIds)
    row = db.execute(text("""
        UPDATE superstream
        SET updated_at=:now, revision=revision+1
        WHERE id=:sid AND project_id=:pid AND revision=:expected
        RETURNING revision
    """), {
        "now": datetime.now(timezone.utc),
        "sid": ss_id,
        "pid": project_id,
        "expected": expected,
    }).one_or_none()
    if row is None:
        _raise_missing_or_revision_conflict(db, project_id, ss_id, expected)

    db.execute(
        text("DELETE FROM superstream_member WHERE superstream_id=:sid AND project_id=:pid"),
        {"sid": ss_id, "pid": project_id},
    )
    for position, (member_project_id, capture_id) in enumerate(members):
        db.add(SuperstreamMember(
            superstream_id=ss_id,
            project_id=member_project_id,
            capture_id=capture_id,
            position=position,
        ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            422,
            {"code": "SUPERSTREAM_INTEGRITY", "message": "La liste des membres viole les contraintes d'intégrité."},
        ) from exc
    ss = db.get(Superstream, ss_id)
    assert ss is not None
    db.refresh(ss)
    _set_etag(response, ss.revision)
    return _serialize(db, ss)


@router.delete(
    "/{ss_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require_project_write)],
)
def delete_project_superstream(
    project_id: str,
    ss_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> Response:
    expected = _expected_revision(if_match)
    deleted = db.execute(text("""
        DELETE FROM superstream
        WHERE id=:sid AND project_id=:pid AND revision=:expected
        RETURNING id
    """), {"sid": ss_id, "pid": project_id, "expected": expected}).scalar_one_or_none()
    if deleted is None:
        _raise_missing_or_revision_conflict(db, project_id, ss_id, expected)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Lecture du flux (pour Signaling/Metrics plus tard)
# ---------------------------------------------------------------------------


class SuperstreamMemberOut(BaseModel):
    position: int
    projectId: str
    captureId: str
    captureName: str  # = nmf_file.filename
    parseDecodeLevel: str | None  # snapshot projet au moment du upload (nullable si NMF ancien)
    parseBinningMode: str | None
    parseTemporalResolution: str | None
    parseSpatialBinM: int | None
    decodeLevel: str  # 'light' | 'deep' depuis nmf_capture
    n_records: int


class SuperstreamStreamOut(BaseModel):
    id: str
    projectId: str
    name: str
    members: list[SuperstreamMemberOut]
    # Si plusieurs snapshots de parsing distincts dans les membres :
    # on expose le fait, jamais silencieux.
    parse_snapshots_distinct: bool
    parse_snapshots: list[dict[str, Any]]


@router.get("/{ss_id}/stream", response_model=SuperstreamStreamOut)
def get_project_superstream_stream(
    project_id: str,
    ss_id: str,
    db: Session = Depends(get_db),
) -> SuperstreamStreamOut:
    """Retourne la liste ordonnée des membres avec leur snapshot de
    parsing. Les consommateurs (Signaling/Metrics) lisent dans l'ordre
    (position, seq) — JAMAIS trié par ts. Les frontières entre membres
    sont marquées par la frontière de `position`.

    Mélange de snapshots : autorisé mais DÉCLARÉ (`parse_snapshots_
    distinct=true` + liste explicite).
    """
    ss = db.get(Superstream, ss_id)
    if ss is None or ss.project_id != project_id:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Superstream introuvable"})

    rows = db.execute(text("""
        SELECT m.position, m.project_id, m.capture_id,
               f.filename AS capture_name,
               c.decode_level,
               (SELECT COALESCE(SUM(n_records),0) FROM nmf_capture WHERE project_id=m.project_id AND capture_id=m.capture_id) AS n_records
        FROM superstream_member m
        JOIN nmf_capture c ON c.project_id=m.project_id AND c.capture_id=m.capture_id
        JOIN nmf_file f    ON f.id = c.nmf_file_id
        WHERE m.superstream_id = :sid
        ORDER BY m.position
    """), {"sid": ss_id}).mappings().all()

    # Pour chaque membre, on cherche le snapshot de parsing du projet au
    # moment où le fichier a été uploadé. Pour l'instant, on expose les
    # defaults projet courants ; alembic 0059 (project_parsing_defaults) a
    # posé ces colonnes. Snapshot per-upload = lot ultérieur (NMFHE4).
    proj = db.get(Project, project_id)
    snap_default = {
        "parse_decode_level": getattr(proj, "parse_decode_level", None),
        "parse_binning_mode": getattr(proj, "parse_binning_mode", None),
        "parse_temporal_resolution": getattr(proj, "parse_temporal_resolution", None),
        "parse_spatial_bin_m": getattr(proj, "parse_spatial_bin_m", None),
    }

    members = []
    distinct_snaps: list[dict[str, Any]] = []
    for r in rows:
        snap = dict(snap_default)  # TODO (NMFHE4) : lire snapshot per-upload
        if snap not in distinct_snaps:
            distinct_snaps.append(snap)
        members.append(SuperstreamMemberOut(
            position=r["position"],
            projectId=r["project_id"],
            captureId=r["capture_id"],
            captureName=r["capture_name"],
            parseDecodeLevel=snap["parse_decode_level"],
            parseBinningMode=snap["parse_binning_mode"],
            parseTemporalResolution=snap["parse_temporal_resolution"],
            parseSpatialBinM=snap["parse_spatial_bin_m"],
            decodeLevel=r["decode_level"],
            n_records=int(r["n_records"] or 0),
        ))

    return SuperstreamStreamOut(
        id=ss.id,
        projectId=ss.project_id,
        name=ss.name,
        members=members,
        parse_snapshots_distinct=len(distinct_snaps) > 1,
        parse_snapshots=distinct_snaps,
    )


@router.get("/{ss_id}/bins")
def get_project_superstream_bins(
    project_id: str,
    ss_id: str,
    source_column: str = Query(...),
    binning_mode: Literal["temporal", "spatial"] | None = None,
    temporal_resolution: Literal["native", "1ms", "10ms", "100ms", "1s"] | None = None,
    spatial_bin_m: Literal[10, 25, 50, 100] | None = None,
    db: Session = Depends(get_db),
):
    """Bin each member independently and preserve `(position, capture, seq)`."""
    ss = db.get(Superstream, ss_id)
    if ss is None or ss.project_id != project_id:
        raise HTTPException(404, {"code": "NOT_FOUND"})
    members = db.execute(text("""SELECT position,capture_id FROM superstream_member
      WHERE superstream_id=:sid AND project_id=:pid ORDER BY position"""),
      {"sid": ss_id, "pid": project_id}).mappings().all()
    output = []
    try:
        for member in members:
            resolution, bins = query_metric_bins(
                db, project_id, member["capture_id"], source_column,
                mode=binning_mode, temporal=temporal_resolution, spatial=spatial_bin_m,
            )
            output.append({"position": member["position"],
                           "capture_id": member["capture_id"],
                           "resolution": resolution, "bins": bins})
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, {"reason": str(exc)}) from exc
    return {"project_id": project_id, "superstream_id": ss_id,
            "order": "position,seq", "members": output}
