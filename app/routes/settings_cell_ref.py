"""Upload cell_ref géo (0.41.0, étendu 0.47.1).

``POST /settings/cell-ref/upload`` — accepte un CSV (séparateur `,` ou
`;`, UTF-8). Colonnes reconnues (insensible à la casse) :

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
- **0.47.1** — Le blob est désormais persisté dans
  ``/var/lib/bc4/references/<reference_id>.csv`` ; le chemin est
  stocké dans ``reference_import.source_path``. Jusqu'à 0.47.0, seuls
  les hash + metadata étaient conservés → impossible d'auditer /
  rejouer un import.
- **0.47.1** — Un import où ``cells_affected = 0`` renvoie désormais
  ``status='rejected'`` + ``report.reject_reasons`` ventilé par motif
  (ni_eci_ni_enodebid, ambiguous, aucune_colonne_geo, arcep_invalide,
  entete_non_reconnu). Plus jamais ``status='ok'`` quand rien n'est
  écrit en base.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_actor, require_role
from app.schemas.settings import Actor

# 0.47.1 — Dossier de persistance des blobs d'upload. Montable via
# bind-mount docker-compose (voir compose.yaml). Mode défensif : si le
# dossier n'existe pas, on tente de le créer au premier upload.
REFERENCES_STORAGE_DIR = Path(
    os.environ.get("BC4_REFERENCES_DIR", "/var/lib/bc4/references")
)


router = APIRouter(prefix="/settings/cell-ref", tags=["settings-cell-ref"])


_ALLOWED_FIELDS = {
    "dr", "plaque", "dor", "arcep_zone", "commune", "insee",
}
_ID_FIELDS = {"eci", "ecgi", "enodebid", "enb_id"}

# 0.42.1 — ARCEP catégorise les zones en 3 densités autoritaires.
# Toute autre valeur (vide tolérée) → ligne rejetée nominativement.
_ARCEP_VALID = {"ZTD", "ZMD", "ZPD"}


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


def _apply_row(db: Session, row: dict[str, str]) -> tuple[str, str | None, int]:
    """Essaye d'appliquer une ligne. Retourne
    ``(status, reason, affected_rows)`` avec
    ``status`` ∈ {``inserted``, ``updated``, ``rejected``, ``ambiguous``,
    ``skipped_empty``}.

    0.42.1 :
    - ``enb_id`` matché sur plusieurs cell_ref → UPDATE EN LOT sur
      toutes les cellules de l'eNB (plus "ambiguous"). Permet le flux
      « 1 ligne enb_id dans le CSV = toute la station remplie ».
    - ``arcep_zone`` validé contre ``{ZTD, ZMD, ZPD}`` ; valeur hors
      ensemble → ligne rejetée nominativement.
    - Ligne entièrement vide (aucun champ géo renseigné) → status
      ``skipped_empty`` (pas une erreur, juste ignorée).
    """
    eci = row.get("eci") or None
    enb = row.get("enodebid") or None
    if not eci and not enb:
        return "rejected", "ni eci ni enodebid dans la ligne", 0

    updates = {k: row[k] for k in _ALLOWED_FIELDS if row.get(k)}
    if not updates:
        return "skipped_empty", "aucune colonne géo renseignée", 0

    # 0.42.1 — Validation ARCEP.
    if "arcep_zone" in updates:
        az = updates["arcep_zone"]
        if az not in _ARCEP_VALID:
            return (
                "rejected",
                f"arcep_zone={az!r} invalide — attendu ∈ {sorted(_ARCEP_VALID)}",
                0,
            )

    # Lookup par eci d'abord.
    if eci:
        cnt = db.execute(
            text("SELECT COUNT(*) FROM cell_ref WHERE eci = :e"),
            {"e": eci},
        ).scalar() or 0
        if cnt > 1:
            return "ambiguous", f"{cnt} cellules avec eci={eci!r}", 0
        if cnt == 1:
            set_sql = ", ".join(f"{k} = COALESCE(:{k}, {k})" for k in updates)
            params = {**updates, "e": eci}
            db.execute(text(f"UPDATE cell_ref SET {set_sql} WHERE eci = :e"), params)
            return "updated", None, 1

    # Lookup par enodebid — 0.42.1 : multi-apply explicite (pas
    # d'ambiguité, 1 ligne CSV enb_id écrit toutes les cellules de l'eNB).
    if enb:
        cnt = db.execute(
            text("SELECT COUNT(*) FROM cell_ref WHERE enodebid = :e"),
            {"e": enb},
        ).scalar() or 0
        if cnt >= 1:
            set_sql = ", ".join(f"{k} = COALESCE(:{k}, {k})" for k in updates)
            params = {**updates, "e": enb}
            db.execute(
                text(f"UPDATE cell_ref SET {set_sql} WHERE enodebid = :e"),
                params,
            )
            # Multi-cellules = 1 ligne CSV, n cellules affectées.
            return "updated", None, int(cnt)

    # Pas de match → insertion d'une nouvelle ligne (si eci fourni).
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
    return "inserted", None, 1


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
    inserted = updated_lines = cells_affected = skipped_empty = 0
    rejected: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=2):  # +2 : ligne CSV (1 = entête)
        processed += 1
        status, reason, affected = _apply_row(db, row)
        if status == "inserted":
            inserted += 1
            cells_affected += affected
        elif status == "updated":
            updated_lines += 1
            cells_affected += affected
        elif status == "ambiguous":
            ambiguous.append({"line": i, "row": row, "reason": reason})
        elif status == "skipped_empty":
            skipped_empty += 1
        else:  # rejected
            rejected.append({"line": i, "row": row, "reason": reason})

    # 0.47.1 — Persistance du blob source (défaut historique corrigé).
    # Toujours écrit — même quand l'import est rejected — pour qu'un
    # debug ultérieur puisse voir exactement ce qui a été envoyé.
    reference_id = f"ref-{uuid.uuid4().hex[:12]}"
    try:
        REFERENCES_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        source_path = REFERENCES_STORAGE_DIR / f"{reference_id}.csv"
        source_path.write_bytes(blob)
        source_path_str: str | None = str(source_path)
    except OSError as e:
        # Dossier non montable : on log mais on ne fait pas échouer
        # l'import (le blob est perdu mais les lignes écrites restent
        # valides). Le rapport porte le warning.
        parse_warnings.append(
            f"persistance source impossible : {e!r} — vérifier le "
            "montage {REFERENCES_STORAGE_DIR}"
        )
        source_path_str = None

    # 0.47.1 — Ventilation des rejets par motif (pour status=rejected).
    reject_reasons: dict[str, int] = {}
    for r in rejected:
        key = (r.get("reason") or "").split(" — ", 1)[0]
        reject_reasons[key] = reject_reasons.get(key, 0) + 1

    # 0.47.1 — Un import à 0 ligne écrite = ÉCHEC DÉCLARÉ, plus
    # jamais ``status='ok'``. On exploite les signaux pour construire
    # une raison lisible.
    if cells_affected == 0:
        status_final = "rejected"
        if processed == 0:
            top_reason = "fichier vide ou en-tête non reconnu"
        elif skipped_empty == processed:
            top_reason = (
                "toutes les lignes sans colonne géo renseignée "
                "(aucun dor/dr/plaque/arcep_zone/commune/insee)"
            )
        elif rejected:
            # Motif dominant (le plus fréquent)
            top_reason = max(reject_reasons, key=reject_reasons.get)
            top_reason = f"ligne(s) rejetée(s) : {top_reason}"
        elif ambiguous:
            top_reason = f"{len(ambiguous)} ligne(s) ambigues — eci multiples"
        else:
            top_reason = "aucune cellule affectée en base (motif indéterminé)"
    else:
        status_final = "ok"
        top_reason = None

    import json as _json
    db.execute(
        text(
            """
            INSERT INTO reference_import
                (id, filename, uploaded_at, actor, rows_read, rows_loaded,
                 rows_rejected, status, report, source_path)
            VALUES
                (:id, :fn, CURRENT_TIMESTAMP, :actor, :read, :loaded,
                 :rej, :status, CAST(:report AS JSON), :source_path)
            """
        ),
        {
            "id":     reference_id,
            "fn":     filename,
            "actor":  actor.login,
            "read":   processed,
            "loaded": cells_affected,
            "rej":    len(rejected),
            "status": status_final,
            "source_path": source_path_str,
            "report": _json.dumps({
                "sha256":          sha256,
                "size":            len(blob),
                "inserted":        inserted,
                "updated_lines":   updated_lines,
                "cells_affected":  cells_affected,
                "skipped_empty":   skipped_empty,
                "rejected":        len(rejected),
                "ambiguous":       len(ambiguous),
                "reject_reasons":  reject_reasons,
                "status_reason":   top_reason,
                "parse_warnings":  parse_warnings,
                "source_path":     source_path_str,
            }),
        },
    )
    db.commit()

    matched = inserted + updated_lines
    return {
        "reference_id":    reference_id,
        "filename":        filename,
        "sha256":          sha256,
        "size_bytes":      len(blob),
        "source_path":     source_path_str,
        "status":          status_final,
        "status_reason":   top_reason,
        "processed":       processed,
        "matched":         matched,       # lignes CSV matchées (insert+update)
        "cells_affected":  cells_affected, # cellules effectivement écrites
        "inserted":        inserted,
        "updated_lines":   updated_lines,
        "skipped_empty":   skipped_empty,
        "not_found":       0,             # jamais : si pas de match on INSERT
        "rejected":        len(rejected),
        "ambiguous":       len(ambiguous),
        "reject_reasons":  reject_reasons,
        "rejected_detail":  rejected[:20],
        "ambiguous_detail": ambiguous[:20],
        "warnings":        parse_warnings,
    }
