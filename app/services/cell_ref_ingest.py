"""Ingestion de la référence cellulaire — streaming CSV → cell_ref.

Règles :
- lecture par flux (SpooledTemporaryFile de FastAPI), jamais tout en mémoire ;
- en-tête CSV validé AVANT ingestion — 422 si une colonne attendue manque ;
- upsert idempotent sur `id` (rejouer le même fichier ne duplique rien) ;
- mapping bande fixe (table ci-dessous) ; les bandes non prévues sont
  comptées dans `bands_unmapped`, jamais devinées (écart déclaré ouvert) ;
- position implausible = hors bbox France métropolitaine : rejet motivé
  `bad_position`. On ne filtre pas sur `etat` : la colonne reste présente.

Aucun chiffre renvoyé qui ne vienne d'un comptage réel du flux ingéré.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import IO, Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.reference import ImportReport


# ---------------------------------------------------------------------------
# Expected header & band map — table only, no heuristic.

EXPECTED_COLUMNS: set[str] = {
    "id",
    "snapshot_date",
    "rat",
    "vendor",
    "sac_ci_eci",
    "nci",
    "enodebid",
    "pci",
    "band",
    "techno",
    "earfcn",
    "azimuth",
    "tilt",
    "height",
    "coverage",
    "cell_class",
    "etat_fonctionnement",
    "nom_upr",
    "nom_dr",
    "plaque_site",
    "id_site",
    "site_name",
    "sector",
    "cell_op_leader",
    "cat_arcep_code",
    "longitude",
    "latitude",
}

# Zone ARCEP : les valeurs source "(null)" (littéral) et "" (vide)
# tombent en NULL base. Jamais une catégorie `"(null)"`. Les 11 autres
# libellés sont persistés tels quels, sans normalisation.
ARCEP_NULL_SOURCES: frozenset[str] = frozenset({"", "(null)"})

# Clé explicite pour le bucket NULL dans `arcep_breakdown` du rapport
# (NULL n'étant pas sérialisable comme clé JSON). Choisie pour ne JAMAIS
# collisionner avec un libellé source réel (qui commence par un chiffre
# et un slash, p. ex. "01/ Top15"). Documentée côté Zod.
ARCEP_NULL_BUCKET: str = "__null"

# Table de mapping libellé source → identifiant 3GPP. Chaque entrée est
# tracée à sa norme 3GPP ; aucune heuristique. Une bande dont le libellé
# source ne figure pas ici tombe dans `bands_unmapped` du rapport et est
# déclarée écart ouvert (pas de deviné silencieux).
BAND_MAP: dict[str, str] = {
    # LTE (3GPP TS 36.101 §5.5)
    "LTE700": "B28",   # 703–748 / 758–803 MHz FDD
    "LTE800": "B20",   # 832–862 / 791–821 MHz FDD
    "LTE900": "B8",    # 880–915 / 925–960 MHz FDD (ajouté 0.3.2)
    "LTE1800": "B3",   # 1710–1785 / 1805–1880 MHz FDD
    "LTE2100": "B1",   # 1920–1980 / 2110–2170 MHz FDD
    "LTE2600": "B7",   # 2500–2570 / 2620–2690 MHz FDD
    # NR (3GPP TS 38.101-1 §5.2 pour FR1, 38.101-2 §5.2 pour FR2)
    "NR_700": "n28",   # 703–748 / 758–803 MHz FDD
    "NR_1400": "n75",  # 1432–1517 MHz SDL (band L) — TS 38.101-1 §5.2 (ajouté 0.3.2)
    "NR_1800": "n3",   # 1710–1785 / 1805–1880 MHz FDD (ajouté 0.3.2)
    "NR_2100": "n1",   # 1920–1980 / 2110–2170 MHz FDD
    "NR_2600": "n7",   # 2500–2570 / 2620–2690 MHz FDD (ajouté 0.3.2 ;
    #                    homologue direct de LTE2600→B7, mêmes bornes)
    "NR_3500": "n78",  # 3300–3800 MHz TDD
    "NR_26_GHZ_000": "n258",  # 24.25–27.5 GHz TDD (FR2) — TS 38.101-2 §5.2 (ajouté 0.3.2)
}

# Metropolitan France + a safety margin. Any lat/lng outside is rejected.
FRANCE_BBOX = {"lat_min": 40.0, "lat_max": 52.0, "lng_min": -6.0, "lng_max": 11.0}

MAX_BODY_BYTES = 256 * 1024 * 1024  # 256 MiB
SPOOL_THRESHOLD = 16 * 1024 * 1024  # bascule disque au-delà de 16 MiB
BATCH_SIZE = 1000


class HeaderError(Exception):
    def __init__(self, missing: set[str], extra: set[str]):
        self.missing = missing
        self.extra = extra
        super().__init__(f"Missing columns: {sorted(missing)}; extra ignored: {sorted(extra)}")


def _f(v: str | None) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


def _i(v: str | None) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v.replace(",", ".")))
    except ValueError:
        return None


def _s(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    return s or None


def _rat(v: str | None) -> str | None:
    """Normalize rat values. Accepts '4G', '5G', 'LTE' → '4G', 'NR' → '5G'."""
    s = _s(v)
    if not s:
        return None
    s = s.upper()
    if s in {"4G", "LTE"}:
        return "4G"
    if s in {"5G", "NR"}:
        return "5G"
    return None


def reference_channels(row: dict[str, str], rat: str) -> tuple[int | None, int | None, int | None]:
    """Return ``(band_mhz, lte_earfcn, nr_arfcn)`` without cross-domain fallback."""
    return (
        _i(row.get("earfcn")),
        _i(row.get("dl_earfcn")) if rat == "4G" else None,
        _i(row.get("nr_arfcn")) if rat == "5G" else None,
    )


def _chunked(iterable: Iterator[dict], size: int) -> Iterator[list[dict]]:
    batch: list[dict] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def validate_header(reader_fields: list[str] | None) -> None:
    if not reader_fields:
        raise HeaderError(missing=EXPECTED_COLUMNS, extra=set())
    present = {f.strip().lower() for f in reader_fields}
    missing = EXPECTED_COLUMNS - present
    if missing:
        extras = present - EXPECTED_COLUMNS
        raise HeaderError(missing=missing, extra=extras)


def ingest_csv_stream(
    db: Session,
    stream: IO[bytes],
    filename: str,
    actor: str,
    *,
    import_id: str | None = None,
) -> ImportReport:
    """Lit le CSV depuis `stream`, insère par lots, renvoie le rapport."""
    # Decode as UTF-8 (BOM-tolerant) without buffering the entire file.
    text_stream = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
    reader = csv.DictReader(text_stream)
    try:
        validate_header(reader.fieldnames)
    except HeaderError:
        text_stream.detach()
        raise

    rows_read = 0
    rows_loaded = 0
    rejected: Counter[str] = Counter()
    bands_unmapped: Counter[str] = Counter()
    by_rat: Counter[str] = Counter()
    etat_breakdown: Counter[str] = Counter()
    arcep_breakdown: Counter[str] = Counter()
    eci_set: set[str] = set()
    nci_set: set[str] = set()
    snapshot_date: str | None = None
    import_id = import_id or uuid.uuid4().hex[:12]

    # --- Chemin rapide : COPY STDIN → table de staging TEMP → upsert ---
    # Les motifs de rejet et les comptes restent calculés en Python ligne
    # par ligne (ImportReport = source de vérité). Seule la couche
    # d'écriture DB change : on remplace l'executemany par un COPY binaire,
    # puis un INSERT ... ON CONFLICT qui préserve l'idempotence sur `id`.
    #
    # Les colonnes de la staging sont celles de cell_ref SAUF `geom`, qu'on
    # recalcule via ST_SetSRID(ST_MakePoint(lng, lat), 4326) à l'upsert.
    STG_COLUMNS = (
        "id", "snapshot_date", "rat", "vendor", "eci", "nci", "enodebid",
        "pci", "band_src", "band_3gpp", "techno", "band_mhz", "earfcn",
        "nr_arfcn", "azimuth",
        "tilt", "height", "coverage", "cell_class", "etat", "dor", "dr",
        "plaque", "site_id", "site_name", "sector", "cell_op_leader",
        "arcep_zone", "lng", "lat", "reference_import_id",
    )

    create_stg_sql = """
        CREATE TEMP TABLE cell_ref_stg (
            id             text,
            snapshot_date  text,
            rat            text,
            vendor         text,
            eci            text,
            nci            text,
            enodebid       text,
            pci            integer,
            band_src       text,
            band_3gpp      text,
            techno         text,
            band_mhz       integer,
            earfcn         integer,
            nr_arfcn       integer,
            azimuth        double precision,
            tilt           double precision,
            height         double precision,
            coverage       text,
            cell_class     text,
            etat           text,
            dor            text,
            dr             text,
            plaque         text,
            site_id        text,
            site_name      text,
            sector         text,
            cell_op_leader text,
            arcep_zone     text,
            lng            double precision,
            lat            double precision,
            reference_import_id text
        ) ON COMMIT DROP
    """

    upsert_sql = """
        INSERT INTO cell_ref (
            id, snapshot_date, rat, vendor, eci, nci, enodebid, pci,
            band_src, band_3gpp, techno, band_mhz, earfcn, nr_arfcn,
            azimuth, tilt, height,
            coverage, cell_class, etat, dor, dr, plaque, site_id,
            site_name, sector, cell_op_leader, arcep_zone, geom,
            reference_import_id
        )
        SELECT
            id, snapshot_date, rat, vendor, eci, nci, enodebid, pci,
            band_src, band_3gpp, techno, band_mhz, earfcn, nr_arfcn,
            azimuth, tilt, height,
            coverage, cell_class, etat, dor, dr, plaque, site_id,
            site_name, sector, cell_op_leader, arcep_zone,
            ST_SetSRID(ST_MakePoint(lng, lat), 4326),
            reference_import_id
        FROM cell_ref_stg
        ON CONFLICT (id) DO UPDATE SET
            snapshot_date = EXCLUDED.snapshot_date,
            rat = EXCLUDED.rat,
            vendor = EXCLUDED.vendor,
            eci = EXCLUDED.eci,
            nci = EXCLUDED.nci,
            enodebid = EXCLUDED.enodebid,
            pci = EXCLUDED.pci,
            band_src = EXCLUDED.band_src,
            band_3gpp = EXCLUDED.band_3gpp,
            techno = EXCLUDED.techno,
            band_mhz = EXCLUDED.band_mhz,
            earfcn = EXCLUDED.earfcn,
            nr_arfcn = EXCLUDED.nr_arfcn,
            azimuth = EXCLUDED.azimuth,
            tilt = EXCLUDED.tilt,
            height = EXCLUDED.height,
            coverage = EXCLUDED.coverage,
            cell_class = EXCLUDED.cell_class,
            etat = EXCLUDED.etat,
            dor = EXCLUDED.dor,
            dr = EXCLUDED.dr,
            plaque = EXCLUDED.plaque,
            site_id = EXCLUDED.site_id,
            site_name = EXCLUDED.site_name,
            sector = EXCLUDED.sector,
            cell_op_leader = EXCLUDED.cell_op_leader,
            arcep_zone = EXCLUDED.arcep_zone,
            geom = EXCLUDED.geom,
            reference_import_id = EXCLUDED.reference_import_id
    """

    def rows_iter():
        nonlocal rows_read, snapshot_date
        for raw in reader:
            rows_read += 1
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
            if snapshot_date is None:
                sd = _s(row.get("snapshot_date"))
                if sd:
                    snapshot_date = sd
            rid = _s(row.get("id"))
            if not rid:
                rejected["missing_id"] += 1
                continue
            rat = _rat(row.get("rat"))
            if rat is None:
                rejected["bad_rat"] += 1
                continue
            eci = _s(row.get("sac_ci_eci"))
            nci = _s(row.get("nci"))
            if rat == "4G" and not eci:
                rejected["missing_eci"] += 1
                continue
            if rat == "5G" and not nci:
                rejected["missing_nci"] += 1
                continue
            lat = _f(row.get("latitude"))
            lng = _f(row.get("longitude"))
            if lat is None or lng is None:
                rejected["bad_position"] += 1
                continue
            if not (
                FRANCE_BBOX["lat_min"] <= lat <= FRANCE_BBOX["lat_max"]
                and FRANCE_BBOX["lng_min"] <= lng <= FRANCE_BBOX["lng_max"]
            ):
                rejected["bad_position"] += 1
                continue
            band_src = _s(row.get("band"))
            band_3gpp = BAND_MAP.get(band_src) if band_src else None
            if band_src and band_3gpp is None:
                bands_unmapped[band_src] += 1
            etat = _s(row.get("etat_fonctionnement"))
            if etat:
                etat_breakdown[etat] += 1
            # Zone ARCEP : LITTÉRAL depuis cat_arcep_code. Pas de .upper(),
            # pas de .strip() au-delà du _s() (déjà fait sur row). "(null)"
            # littéral et "" → NULL base, bucket `__null` dans le rapport.
            # Un comptage par bucket est fait sur TOUTES les lignes
            # chargées (loaded) → somme(arcep_breakdown.values()) == rows_loaded.
            raw_arcep = row.get("cat_arcep_code") or ""
            if raw_arcep in ARCEP_NULL_SOURCES:
                arcep_zone = None
                arcep_breakdown[ARCEP_NULL_BUCKET] += 1
            else:
                arcep_zone = raw_arcep  # littéral, pas de normalisation
                arcep_breakdown[arcep_zone] += 1
            by_rat[rat] += 1
            if eci:
                eci_set.add(eci)
            if nci:
                nci_set.add(nci)
            band_mhz, lte_earfcn, nr_arfcn = reference_channels(row, rat)
            yield {
                "id": rid,
                "snapshot_date": _s(row.get("snapshot_date")),
                "rat": rat,
                "vendor": _s(row.get("vendor")),
                "eci": eci,
                "nci": nci,
                "enodebid": _s(row.get("enodebid")),
                "pci": _i(row.get("pci")),
                "band_src": band_src,
                "band_3gpp": band_3gpp,
                "techno": _s(row.get("techno")),
                "band_mhz": band_mhz,
                "earfcn": lte_earfcn,
                "nr_arfcn": nr_arfcn,
                "azimuth": _f(row.get("azimuth")),
                "tilt": _f(row.get("tilt")),
                "height": _f(row.get("height")),
                "coverage": _s(row.get("coverage")),
                "cell_class": _s(row.get("cell_class")),
                "etat": etat,
                "dor": _s(row.get("nom_upr")),
                "dr": _s(row.get("nom_dr")),
                "plaque": _s(row.get("plaque_site")),
                "site_id": _s(row.get("id_site")),
                "site_name": _s(row.get("site_name")),
                "sector": _s(row.get("sector")),
                "cell_op_leader": _s(row.get("cell_op_leader")),
                "arcep_zone": arcep_zone,
                "lng": lng,
                "lat": lat,
                "reference_import_id": import_id,
            }

    # psycopg3 COPY : on ouvre une transaction unique, crée la table TEMP,
    # streame les rangs via write_row (pas de sérialisation CSV manuelle),
    # puis fait l'upsert en une passe. ~15 s pour 460 k lignes au lieu
    # de ~2 min avec executemany.
    raw_conn = db.connection().connection  # psycopg3 Connection
    with raw_conn.cursor() as cur:
        cur.execute(create_stg_sql)
        copy_sql = f"COPY cell_ref_stg ({', '.join(STG_COLUMNS)}) FROM STDIN"
        with cur.copy(copy_sql) as copy:
            for row in rows_iter():
                copy.write_row(tuple(row[c] for c in STG_COLUMNS))
                rows_loaded += 1
        cur.execute(upsert_sql)
    db.commit()

    text_stream.detach()  # avoid closing underlying stream twice

    report = ImportReport(
        rows_read=rows_read,
        rows_loaded=rows_loaded,
        rows_rejected=sum(rejected.values()),
        rejected_by_reason=dict(rejected),
        distinct_eci=len(eci_set),
        distinct_nci=len(nci_set),
        by_rat=dict(by_rat),
        bands_unmapped=dict(bands_unmapped),
        etat_breakdown=dict(etat_breakdown),
        arcep_breakdown=dict(arcep_breakdown),
        snapshot_date=snapshot_date,
    )

    # Trace the import run for provenance.
    db.execute(
        text(
            """
            INSERT INTO reference_import
                (id, filename, uploaded_at, actor, snapshot_date,
                 rows_read, rows_loaded, rows_rejected, status, report)
            VALUES
                (:id, :filename, :uploaded_at, :actor, :snapshot_date,
                 :rows_read, :rows_loaded, :rows_rejected, :status,
                 CAST(:report AS JSON))
            ON CONFLICT (id) DO UPDATE SET
                filename=EXCLUDED.filename,
                actor=EXCLUDED.actor,
                snapshot_date=EXCLUDED.snapshot_date,
                rows_read=EXCLUDED.rows_read,
                rows_loaded=EXCLUDED.rows_loaded,
                rows_rejected=EXCLUDED.rows_rejected,
                status=EXCLUDED.status,
                report=EXCLUDED.report
            """
        ),
        {
            "id": import_id,
            "filename": filename,
            "uploaded_at": datetime.now(timezone.utc),
            "actor": actor,
            "snapshot_date": snapshot_date,
            "rows_read": report.rows_read,
            "rows_loaded": report.rows_loaded,
            "rows_rejected": report.rows_rejected,
            "status": "completed" if rows_loaded else "empty",
            "report": report.model_dump_json(),
        },
    )
    db.commit()
    return report


class BodyTooLarge(Exception):
    pass


def spool_upload(file_obj: IO[bytes], out: IO[bytes], max_bytes: int = MAX_BODY_BYTES) -> int:
    """Copy upload into a size-bounded buffer. Shouts if the limit is crossed."""
    read = 0
    while True:
        chunk = file_obj.read(1024 * 1024)
        if not chunk:
            break
        read += len(chunk)
        if read > max_bytes:
            raise BodyTooLarge(f"Upload > {max_bytes} octets")
        out.write(chunk)
    out.seek(0)
    return read
