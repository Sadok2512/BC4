from __future__ import annotations

import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_actor, get_current_user, require_role
from app.models import CellRef, ReferenceImport
from app.schemas.reference import (
    CellSummary,
    CellSummaryBucket,
    ImportReport,
    ReferenceImportEntry,
)
from app.schemas.settings import Actor
from app.services.cell_ref_ingest import (
    SPOOL_THRESHOLD,
    BodyTooLarge,
    HeaderError,
    ingest_csv_stream,
    spool_upload,
)

# Auth min « lecteur » pour toutes les routes de ce routeur ; les
# handlers d'écriture impose « ingenieur » via `require_role` (comme
# `upload_cell_reference`).
router = APIRouter(
    prefix="/reference",
    tags=["reference"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/cell/upload",
    response_model=ImportReport,
    response_model_exclude_none=True,
)
def upload_cell_reference(
    file: UploadFile = File(..., description="CSV référence cellulaire"),
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> ImportReport:
    require_role(actor, "admin", "editor")

    # Spool the body into a bounded temp file so we never hold the whole
    # 128 Mo in RAM, and we reject anything > 256 Mo straight away.
    tmp = tempfile.SpooledTemporaryFile(max_size=SPOOL_THRESHOLD)
    try:
        spool_upload(file.file, tmp)
    except BodyTooLarge as e:
        raise HTTPException(413, {"code": "PAYLOAD_TOO_LARGE", "message": str(e)})
    finally:
        file.file.close()

    try:
        report = ingest_csv_stream(db, tmp, filename=file.filename or "upload.csv", actor=actor.login)
    except HeaderError as e:
        raise HTTPException(
            422,
            {
                "code": "VALIDATION",
                "message": "En-tête CSV non conforme — rien n'a été inséré",
                "missing_columns": sorted(e.missing),
                "unknown_columns": sorted(e.extra),
            },
        )
    finally:
        tmp.close()

    return report


@router.get("/cell/imports", response_model=list[ReferenceImportEntry])
def list_cell_imports(db: Session = Depends(get_db)) -> list[ReferenceImportEntry]:
    rows = db.query(ReferenceImport).order_by(ReferenceImport.uploaded_at.desc()).all()
    return [
        ReferenceImportEntry(
            id=r.id,
            filename=r.filename,
            uploaded_at=r.uploaded_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            actor=r.actor,
            snapshot_date=r.snapshot_date,
            rows_read=r.rows_read,
            rows_loaded=r.rows_loaded,
            rows_rejected=r.rows_rejected,
            status=r.status,
            report=ImportReport.model_validate(r.report),
        )
        for r in rows
    ]


def _bucket(db: Session, column) -> list[CellSummaryBucket]:
    """Group cells by a given column and return [{key, count}] with
    null-safe output : les lignes sans valeur sont déclarées sous le
    label `N/D`, jamais remplacées par 0."""
    stmt = (
        db.query(column, func.count(CellRef.id))
        .group_by(column)
        .order_by(func.count(CellRef.id).desc())
    )
    return [CellSummaryBucket(key=(k or "N/D"), count=int(n)) for k, n in stmt.all()]


@router.get("/cell/summary", response_model=CellSummary)
def cell_summary(db: Session = Depends(get_db)) -> CellSummary:
    total = db.query(func.count(CellRef.id)).scalar() or 0
    return CellSummary(
        total=int(total),
        by_rat=_bucket(db, CellRef.rat),
        by_band_3gpp=_bucket(db, CellRef.band_3gpp),
        by_dor=_bucket(db, CellRef.dor),
        by_dr=_bucket(db, CellRef.dr),
        # Dimension ARCEP, ORTHOGONALE à la géo (DOR/DR/Plaque) — pas
        # dans `/geo/tree`. Les 11 libellés source réels sortent tels
        # quels ; les lignes NULL tombent dans le bucket `N/D` via
        # `_bucket()`.
        arcep_breakdown=_bucket(db, CellRef.arcep_zone),
    )
