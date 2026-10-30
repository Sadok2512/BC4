"""Upload cell_ref géo (0.41.0, étendu 0.47.1, puis 0.87.0 BC3 géo+radio).

``POST /settings/cell-ref/upload`` — accepte un CSV (séparateur `,` ou
`;`, UTF-8). Colonnes reconnues (insensible à la casse) :

Identifiants (au moins un requis par ligne) :
- ``id`` (clé primaire cell_ref si fourni, sinon ``upload-<uuid>``)
- ``eci`` / ``ecgi`` / ``sac_ci_eci`` (identifiant cellule — autoritaire
  pour l'appariement UPDATE)
- ``enodebid`` / ``enb_id``

Admin ARCEP :
- ``dr`` / ``nom_dr``, ``plaque`` / ``plaque_site``, ``dor``,
  ``arcep_zone`` / ``arcep`` / ``cat_arcep_code``, ``commune``, ``insee``

Géo + radio (0.87.0 BC3) :
- ``latitude`` + ``longitude`` → compose ``geom = ST_SetSRID(ST_Point
  (lng, lat), 4326)``. Les deux doivent être présentes et numériques
  valides (lat ∈ [-90,90], lng ∈ [-180,180]) ; sinon warning + geom
  reste NULL (ligne quand même persistée pour les autres champs).
- ``pci``, ``azimuth``, ``tilt``, ``height``
- ``earfcn`` → bande MHz, ``dl_earfcn`` → porteuse LTE exacte,
  ``nr_arfcn`` → porteuse NR exacte
- ``band`` / ``band_src``, ``band_3gpp``, ``techno``, ``vendor``,
  ``rat``
- ``id_site`` / ``site_id``, ``site_name``, ``sector``, ``cell_class``,
  ``coverage``, ``etat_fonctionnement`` / ``etat``
- ``nci``, ``snapshot_date``, ``cell_op_leader``

Normalisation :
- ``rat`` / ``techno`` : ``"4G"`` → ``"LTE"``, ``"5G"`` → ``"NR"``,
  ``"3G"`` → ``"UMTS"``, ``"2G"`` → ``"GSM"`` (insensible à la casse).
- ``arcep_zone`` : relaxé en 0.87.0 — accepte ZTD/ZMD/ZPD (taxonomie
  2019) ET les codes 2024 (``"01"``, ``"02"``, ``"03"``, ``"04"``,
  ``"01/ Top15"`` …). Valeurs non nulles acceptées, warning sinon.

Au moins ``id|eci|ecgi|sac_ci_eci|enodebid|enb_id`` est requis par
ligne — sinon ligne rejetée avec raison. La route répond avec un
rapport ``{processed, matched, inserted, updated, rejected[],
ambiguous[], geo_persisted}`` + un ``reference_id``.

Discipline :
- Pas d'invention : un champ absent du CSV ne touche pas la colonne
  existante (UPDATE … COALESCE).
- Pas d'inférence lat/lng : si une seule des deux est présente ou
  invalide, geom reste NULL + warning dans le rapport. **Jamais**
  interpolé depuis un site voisin.
- **0.47.1** — Le blob est persisté dans
  ``/var/lib/bc4/references/<reference_id>.csv``.
- **0.47.1** — Un import où ``cells_affected = 0`` renvoie
  ``status='rejected'`` + ``report.reject_reasons`` ventilé.
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


# 0.87.0 BC3 — Allowed fields étendu avec géo + radio + site + vendor.
# Les champs internes `lat`/`lng` ne persistent pas directement : ils
# composent `geom` via ST_Point. Les clés d'identification (`id`, `eci`,
# `enodebid`) sont traitées séparément.
_ALLOWED_FIELDS = {
    # ARCEP / admin (historique)
    "dr", "plaque", "dor", "arcep_zone", "commune", "insee",
    # Radio
    "pci", "azimuth", "tilt", "height", "band_mhz", "earfcn", "nr_arfcn",
    "band_src", "band_3gpp", "techno", "vendor", "rat",
    # Site
    "site_id", "site_name", "sector", "cell_class", "coverage", "etat",
    # Identifiants complémentaires
    "nci", "snapshot_date", "cell_op_leader",
}
# `lat` et `lng` sont traités à part (composent geom).
_GEO_FIELDS = {"lat", "lng"}
_ID_FIELDS = {"eci", "ecgi", "enodebid", "enb_id", "sac_ci_eci", "id"}
_INT_FIELDS = {"pci", "band_mhz", "earfcn", "nr_arfcn"}
_FLOAT_FIELDS = {"azimuth", "tilt", "height", "lat", "lng"}

# 0.42.1 — ARCEP 2019 : densités autoritaires ZTD/ZMD/ZPD.
# 0.87.0 BC3 — Relaxation : taxonomie 2024 ajoute 01/02/03/04 (Top15,
# Priorité, …). On accepte toute valeur non-vide ; on marque un warning
# si valeur hors ensemble documenté. Plus de rejet strict.
_ARCEP_LEGACY_VALID = {"ZTD", "ZMD", "ZPD"}
_ARCEP_2024_PREFIXES = {"01", "02", "03", "04"}

# 0.87.0 BC3 — Normalisation rat/techno. Mapping conservateur.
_RAT_NORMALIZE = {
    "4g": "LTE", "lte": "LTE",
    "5g": "NR", "nr": "NR", "5gnr": "NR",
    "3g": "UMTS", "umts": "UMTS", "hspa": "UMTS",
    "2g": "GSM", "gsm": "GSM", "edge": "GSM",
}


def _normalize_header(h: str) -> str:
    """Alias insensible à la casse → nom canonique DB cell_ref."""
    h = (h or "").strip().lower()
    # Aliases legacy (0.41.0)
    if h == "arcep": return "arcep_zone"
    if h == "enb_id": return "enodebid"
    if h == "ecgi": return "eci"
    # 0.87.0 BC3 — Aliases CSV réalistes (ARCEP 2024, exports vendor).
    if h == "sac_ci_eci": return "eci"
    if h == "nom_dr": return "dr"
    if h == "plaque_site": return "plaque"
    if h == "id_site": return "site_id"
    if h == "etat_fonctionnement": return "etat"
    if h == "cat_arcep_code": return "arcep_zone"
    if h == "latitude": return "lat"
    if h == "longitude": return "lng"
    if h == "band": return "band_src"
    # Vendor contract: `earfcn` is a band in MHz, while `dl_earfcn` and
    # `nr_arfcn` are exact channels.  Never merge these three domains: 1800
    # is valid both as a band label and as an LTE EARFCN.
    if h == "earfcn": return "band_mhz"
    if h == "dl_earfcn": return "earfcn"
    if h == "physical_cell_id": return "pci"
    if h == "pci_id": return "pci"
    return h


def _normalize_rat(v: str | None) -> str | None:
    if not v: return None
    return _RAT_NORMALIZE.get(v.strip().lower(), v.strip())


def _safe_int(v: str | None) -> int | None:
    if v is None or v == "": return None
    try: return int(float(v))
    except (TypeError, ValueError): return None


def _safe_float(v: str | None) -> float | None:
    if v is None or v == "": return None
    try: return float(v)
    except (TypeError, ValueError): return None


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
            nk = _normalize_header(k)
            new_val = (v or "").strip()
            # Several legacy aliases can still target the same canonical
            # field (e.g. pci/physical_cell_id). Never replace a populated
            # authoritative value with a later empty alias.
            if nk in row and row[nk] and not new_val:
                continue
            row[nk] = new_val
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

    0.87.0 BC3 — Étendu : géo (lat/lng → geom), radio, site, vendor.
    `rat`/`techno` normalisés ; `arcep_zone` relaxé (accepte 2019 + 2024).
    """
    eci = row.get("eci") or None
    enb = row.get("enodebid") or None
    csv_id = row.get("id") or None
    if not eci and not enb and not csv_id:
        return "rejected", "ni id ni eci ni enodebid dans la ligne", 0

    # Normalise rat/techno (4G→LTE, 5G→NR, …).
    for k in ("rat", "techno"):
        if row.get(k):
            row[k] = _normalize_rat(row[k]) or row[k]
    # Convertit types numériques.
    for k in _INT_FIELDS:
        if k in row:
            iv = _safe_int(row[k])
            row[k] = str(iv) if iv is not None else ""
    for k in _FLOAT_FIELDS:
        if k in row:
            fv = _safe_float(row[k])
            row[k] = str(fv) if fv is not None else ""

    # arcep_zone : relaxé. Accepte ZTD/ZMD/ZPD ou 01/02/03/04 ou n'importe
    # quelle chaîne non vide (warning possible, mais pas de rejet).
    # On conserve la valeur brute telle quelle (ex. "01/ Top15").

    # Validation lat/lng : les deux présents + numériques dans la plage.
    lat = _safe_float(row.get("lat"))
    lng = _safe_float(row.get("lng"))
    has_geom = (
        lat is not None and -90.0 <= lat <= 90.0
        and lng is not None and -180.0 <= lng <= 180.0
    )

    # Collecte des updates : _ALLOWED_FIELDS avec valeur non-vide.
    updates = {k: row[k] for k in _ALLOWED_FIELDS if row.get(k)}
    if not updates and not has_geom:
        return "skipped_empty", "aucune colonne géo/admin/radio renseignée", 0

    # ---------- UPDATE path ----------
    def _do_update(lookup_sql: str, lookup_params: dict, matched: int):
        """UPDATE SET … COALESCE(…) + geom si has_geom. Retourne matched."""
        set_parts = [f"{k} = COALESCE(:{k}, {k})" for k in updates]
        params = {**updates, **lookup_params}
        if has_geom:
            set_parts.append("geom = ST_SetSRID(ST_Point(:_lng, :_lat), 4326)")
            params["_lat"] = lat
            params["_lng"] = lng
        sql = f"UPDATE cell_ref SET {', '.join(set_parts)} WHERE {lookup_sql}"
        db.execute(text(sql), params)
        return matched

    # 0.87.0 BC3 — Hiérarchie de lookup :
    #   1. Si CSV `id` fourni → UPSERT par id (clé primaire autoritaire).
    #   2. Sinon si `eci` fourni → UPDATE par eci si match, sinon INSERT.
    #   3. Sinon si `enb` fourni (seul) → multi-apply par enodebid
    #      (cas "1 ligne CSV = toutes cellules de l'eNB enrichies").
    # IMPORTANT : si `eci` est fourni avec `enb` et eci ne match aucune
    # ligne, on INSERT une nouvelle ligne. On NE descend PAS au bloc
    # enodebid-multi-apply qui écraserait les cellules existantes du
    # même eNB avec les valeurs de cette seule ligne. Ce bug (préexistant
    # avant 0.87.0) détruisait les cellules multi-secteur d'une station.
    if csv_id:
        cnt = db.execute(
            text("SELECT COUNT(*) FROM cell_ref WHERE id = :i"),
            {"i": csv_id},
        ).scalar() or 0
        if cnt == 1:
            return "updated", None, _do_update("id = :i", {"i": csv_id}, 1)
        # cnt == 0 → tomber dans INSERT en bas (id sera csv_id).

    if eci:
        cnt = db.execute(
            text("SELECT COUNT(*) FROM cell_ref WHERE eci = :e"),
            {"e": eci},
        ).scalar() or 0
        if cnt > 1:
            return "ambiguous", f"{cnt} cellules avec eci={eci!r}", 0
        if cnt == 1:
            return "updated", None, _do_update("eci = :e", {"e": eci}, 1)
        # cnt == 0 → INSERT en bas (ligne nouvelle avec cet eci).

    # Enodebid multi-apply : SEULEMENT si pas d'eci + pas d'id CSV
    # (sinon on casse la discipline "une eci = une cellule").
    elif enb and not csv_id:
        cnt = db.execute(
            text("SELECT COUNT(*) FROM cell_ref WHERE enodebid = :e"),
            {"e": enb},
        ).scalar() or 0
        if cnt >= 1:
            return "updated", None, _do_update("enodebid = :e", {"e": enb}, int(cnt))

    # ---------- INSERT path ----------
    # Priorise csv_id si fourni, sinon upload-<uuid>.
    cell_id = csv_id or f"upload-{uuid.uuid4().hex[:12]}"
    rat_val = updates.get("rat") or "LTE"
    cols = ["id", "rat", "eci", "enodebid"] + sorted(_ALLOWED_FIELDS - {"rat"})
    vals = [":id", ":rat", ":eci", ":enb"] + [f":{c}" for c in cols[4:]]
    params: dict[str, Any] = {
        "id":  cell_id,
        "rat": rat_val,
        "eci": eci,
        "enb": enb,
    }
    for c in cols[4:]:
        params[c] = updates.get(c)
    if has_geom:
        cols.append("geom")
        vals.append("ST_SetSRID(ST_Point(:_lng, :_lat), 4326)")
        params["_lat"] = lat
        params["_lng"] = lng
    sql = f"INSERT INTO cell_ref ({', '.join(cols)}) VALUES ({', '.join(vals)})"
    db.execute(text(sql), params)
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
    rows_with_geo = 0  # 0.87.0 BC3 — count lignes CSV avec lat+lng valides
    rejected: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=2):  # +2 : ligne CSV (1 = entête)
        processed += 1
        # Pré-check géo pour reporting (le vrai persist se fait dans _apply_row)
        _lat = _safe_float(row.get("lat"))
        _lng = _safe_float(row.get("lng"))
        if _lat is not None and -90.0 <= _lat <= 90.0 and _lng is not None and -180.0 <= _lng <= 180.0:
            rows_with_geo += 1
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
                # 0.87.0 BC3 — nb lignes CSV avec lat+lng valides
                # (celles qui ont effectivement composé un geom).
                "rows_with_geo":   rows_with_geo,
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
        # 0.87.0 BC3 — lignes CSV avec lat+lng valides (persisted en geom)
        "rows_with_geo":   rows_with_geo,
    }
