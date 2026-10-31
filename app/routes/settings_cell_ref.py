"""Asynchronous cell-reference upload used by the Settings interface.

The multipart body is streamed to durable storage with the shared 256 MiB
limit. A 202 response is returned as soon as the file and queued history row
are durable; the import worker performs the same streaming upsert used by the
guarded ``reimport_cell_reference`` command.
"""
import csv
import io

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_actor, require_role
from app.schemas.reference import CellReferenceJob, CellReferenceJobAccepted
from app.schemas.settings import Actor
from app.services.cell_ref_jobs import enqueue, get_job


router = APIRouter(prefix="/settings/cell-ref", tags=["settings-cell-ref"])


def _normalize_header(header: str) -> str:
    """Compatibility helper for the documented vendor CSV vocabulary."""
    value = (header or "").strip().lower()
    aliases = {
        "arcep": "arcep_zone", "enb_id": "enodebid", "ecgi": "eci",
        "sac_ci_eci": "eci", "nom_dr": "dr", "plaque_site": "plaque",
        "id_site": "site_id", "etat_fonctionnement": "etat",
        "cat_arcep_code": "arcep_zone", "latitude": "lat",
        "longitude": "lng", "band": "band_src", "earfcn": "band_mhz",
        "dl_earfcn": "earfcn", "physical_cell_id": "pci", "pci_id": "pci",
    }
    return aliases.get(value, value)


def _parse_csv(blob: bytes) -> tuple[list[dict[str, str]], list[str]]:
    """Small compatibility parser; production ingestion stays streaming."""
    decoded = blob.decode("utf-8-sig", errors="replace")
    first_line = decoded.splitlines()[0] if decoded else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
    rows = []
    for raw in reader:
        row: dict[str, str] = {}
        for key, value in raw.items():
            if key is None:
                continue
            normalized = _normalize_header(key)
            candidate = (value or "").strip()
            if normalized in row and row[normalized] and not candidate:
                continue
            row[normalized] = candidate
        rows.append(row)
    return rows, ([] if reader.fieldnames else ["CSV sans entête — aucune colonne reconnue"])


@router.post(
    "/upload",
    response_model=CellReferenceJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_cell_ref(
    file: UploadFile = File(...),
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> CellReferenceJobAccepted:
    require_role(actor, "admin")
    return CellReferenceJobAccepted.model_validate(enqueue(db, file, actor.login))


@router.get("/jobs/{job_id}", response_model=CellReferenceJob)
def cell_reference_job(
    job_id: str,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> CellReferenceJob:
    require_role(actor, "admin")
    return CellReferenceJob.model_validate(get_job(db, job_id))
