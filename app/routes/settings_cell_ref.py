"""Upload cell_ref géo (0.41.0).

``POST /settings/cell-ref/upload`` — accepte un CSV (séparateur `,` ou
`;`, UTF-8) OU un xlsx. Colonnes reconnues (insensible à la casse) :

- ``eci`` OU ``ecgi`` (identifiant cellule — autoritaire pour l'appariement)
- ``enodebid`` OU ``enb_id``
- ``dr``, ``plaque``, ``dor``, ``arcep_zone`` (ou ``arcep``)
- ``commune``, ``insee``

Au moins ``eci|ecgi|enodebid`` est requis par ligne — sinon ligne
rejetée avec raison. La route répond avec un rapport
``{processed, matched, inserted, updated, rejected[], ambiguous[]}``
+ un ``reference_id`` qui permet de revenir à l'upload.

Discipline :
- Pas d'invention : un champ absent du CSV ne touche pas la colonne
  existante (UPDATE … COALESCE).
- Pas de fichier gardé en base ; on persiste uniquement un
  ``reference_import`` (id + source filename + sha256 + taille).
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_actor, require_role
from app.schemas.settings import Actor


router = APIRouter(prefix="/settings/cell-ref", tags=["settings-cell-ref"])


_ALLOWED_FIELDS = {
    "dr", "plaque", "dor", "arcep_zone", "commune", "insee",
}
_ID_FIELDS = {"eci", "ecgi", "enodebid", "enb_id"}


def _normalize_header(h: str) -> str:
    h = (h or "").strip().lower()
    if h in ("arcep",): return "arcep_zone"
    if h in ("enb_id",): return "enodebid"
    if h in ("ecgi",): return "eci"
    return h


def _parse_csv(blob: bytes) -> tuple[list[dict[str, str]], list[str]]:
    """Parse CSV avec auto-detect séparateur. Retourne (rows,
    warnings)."""
    txt = blob.decode("utf-8-sig", errors="replace")
    # Heuristique sep.
    first_line = txt.splitlines()[0] if txt else ""
    sep = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(txt), delimiter=sep)
    norm_rows: list[dict[str, str]] = []
    for raw in reader:
        row = {}
        for k, v in raw.items():
            if k is None:
                continue
            row[_normalize_header(k)] = (v or "").strip()
        norm_rows.append(row)
    warnings: list[str] = []
    if not reader.fieldnames:
        warnings.append("CSV sans entête — aucune colonne reconnue")
    return norm_rows, warnings


def _apply_row(db: Session, row: dict[str, str]) -> tuple[str, str | None]:
    """Essaye d'appliquer une ligne. Retourne (``status``, ``reason``)
    avec ``status`` ∈ {``inserted``, ``updated``, ``rejected``,
    ``ambiguous``}."""
    eci = row.get("eci") or None
    enb = row.get("enodebid") or None
    if not eci and not enb:
        return "rejected", "ni eci ni enodebid dans la ligne"

    updates = {k: row[k] for k in _ALLOWED_FIELDS if row.get(k)}
    if not updates:
        return "rejected", "aucune colonne géo renseignée"

    # Lookup par eci d'abord, puis par enodebid.
    if eci:
        cnt = db.execute(
            text("SELECT COUNT(*) FROM cell_ref WHERE eci = :e"),
            {"e": eci},
        ).scalar() or 0
        if cnt > 1:
            return "ambiguous", f"{cnt} cellules avec eci={eci!r}"
        if cnt == 1:
            # UPDATE partiel : COALESCE préserve les colonnes existantes.
            set_sql = ", ".join(f"{k} = COALESCE(:{k}, {k})" for k in updates)
            params = {**updates, "e": eci}
            db.execute(text(f"UPDATE cell_ref SET {set_sql} WHERE eci = :e"), params)
            return "updated", None
        # Pas de ligne eci → tenter enodebid si fourni.
    if enb:
        cnt = db.execute(
            text("SELECT COUNT(*) FROM cell_ref WHERE enodebid = :e"),
            {"e": enb},
        ).scalar() or 0
        if cnt > 1:
            return "ambiguous", f"{cnt} cellules avec enodebid={enb!r}"
        if cnt == 1:
            set_sql = ", ".join(f"{k} = COALESCE(:{k}, {k})" for k in updates)
            params = {**updates, "e": enb}
            db.execute(text(f"UPDATE cell_ref SET {set_sql} WHERE enodebid = :e"), params)
            return "updated", None

    # Pas de match → insertion d'une nouvelle ligne.
    cell_id = f"upload-{uuid.uuid4().hex[:12]}"
    params = {
        "id":  cell_id,
        "rat": "LTE",
        "eci": eci,
        "enb": enb,
        **{k: updates.get(k) for k in _ALLOWED_FIELDS},
    }
    db.execute(
        text(
            """
            INSERT INTO cell_ref
                (id, rat, eci, enodebid, dr, plaque, dor, arcep_zone,
                 commune, insee)
            VALUES
                (:id, :rat, :eci, :enb, :dr, :plaque, :dor, :arcep_zone,
                 :commune, :insee)
            """
        ),
        params,
    )
    return "inserted", None


@router.post("/upload")
async def upload_cell_ref(
    file: UploadFile,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(actor, "admin")

    blob = await file.read()
    if not blob:
        raise HTTPException(
            400,
            {"code": "EMPTY_FILE", "message": "fichier vide"},
        )
    filename = file.filename or "upload.csv"
    sha256 = hashlib.sha256(blob).hexdigest()

    # Format : seul CSV supporté dans ce lot (xlsx = TODO).
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            400,
            {
                "code": "FORMAT_UNSUPPORTED",
                "message": (
                    f"{filename!r} : seul CSV supporté dans 0.41.0. "
                    "xlsx reporté au lot suivant."
                ),
            },
        )

    rows, parse_warnings = _parse_csv(blob)

    processed = 0
    inserted = updated = 0
    rejected: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=2):  # +2 : ligne CSV (1 = entête)
        processed += 1
        status, reason = _apply_row(db, row)
        if status == "inserted":
            inserted += 1
        elif status == "updated":
            updated += 1
        elif status == "ambiguous":
            ambiguous.append({"line": i, "row": row, "reason": reason})
        else:  # rejected
            rejected.append({"line": i, "row": row, "reason": reason})

    # Trace de l'import (persisté mais sans le blob — on garde juste
    # la métadonnée + sha256 pour reproductibilité).
    import json as _json
    reference_id = f"ref-{uuid.uuid4().hex[:12]}"
    db.execute(
        text(
            """
            INSERT INTO reference_import
                (id, filename, uploaded_at, actor, rows_read, rows_loaded,
                 rows_rejected, status, report)
            VALUES
                (:id, :fn, CURRENT_TIMESTAMP, :actor, :read, :loaded,
                 :rej, :status, CAST(:report AS JSON))
            """
        ),
        {
            "id":     reference_id,
            "fn":     filename,
            "actor":  actor.login,
            "read":   processed,
            "loaded": inserted + updated,
            "rej":    len(rejected),
            "status": "ok" if (inserted + updated) > 0 else "noop",
            "report": _json.dumps({
                "sha256":   sha256,
                "size":     len(blob),
                "inserted": inserted,
                "updated":  updated,
                "rejected": len(rejected),
                "ambiguous": len(ambiguous),
            }),
        },
    )
    db.commit()

    matched = inserted + updated
    return {
        "reference_id":   reference_id,
        "filename":       filename,
        "sha256":         sha256,
        "size_bytes":     len(blob),
        "processed":      processed,
        "matched":        matched,
        "inserted":       inserted,
        "updated":        updated,
        "rejected":       len(rejected),
        "ambiguous":      len(ambiguous),
        "rejected_detail":  rejected[:20],
        "ambiguous_detail": ambiguous[:20],
        "warnings":       parse_warnings,
    }
