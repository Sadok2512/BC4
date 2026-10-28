"""Module d'ingestion NMF — B1-ingest.

Rôle :
- streamer un upload NMF depuis la requête HTTP vers un fichier disque borné
  (jamais tout en mémoire) ;
- hasher (sha256) à la volée pour la clé d'idempotence (`project_id, sha256`);
- déléguer le décodage au module canonique **`bc4_decoder`** quand il est
  disponible (chemins listés plus bas) ; celui-ci expose
  `decode_nmf_file(path) -> Iterator[dict]` et `DECODER_VERSION`
  (dicts PLATS, pas d'objet `Capture`) ;
- si le décodeur n'est pas disponible, le fichier est marqué `status=error`
  avec `error_msg="decoder_unavailable: <détail>"` — rien n'est inventé, zéro
  event injecté. L'écart est **déclaré ouvert**, pas masqué.

Deny-list : le décodeur canonique masque déjà les identités À LA SOURCE (IMSI
/IMEI 15 chiffres → jeton, payload SIP retiré, MAC masquées). `payload_hex`
de signalisation n'est JAMAIS masqué (il doit rester intègre pour le
décodage ASN.1 aval). `_strip_identity()` défensif reste appliqué sur les
clés top-level, en complément et non en remplacement.

Ordre canonique : les events sont insérés avec `(capture_id, seq)` tel que
produits par le décodeur. Aucune comparaison ou tri par `ts` ici.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json as _json_module
import os
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import IO, Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import NmfFile, Project
from app.services.task_privacy import redact_command
from app.nmf_decoder.privacy import redact_raw

# ---------------------------------------------------------------------------
# Limites & chemins
# ---------------------------------------------------------------------------

MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB par fichier NMF
SPOOL_THRESHOLD = 32 * 1024 * 1024       # bascule disque au-delà de 32 MiB
BATCH_SIZE = 1000

# 0.30.0 — Dossier persistant du .nmf source. Volume Docker nommé
# `bc4_nmf_source` monté sur `/var/lib/bc4/nmf-source` (défaut), surchargeable
# via `BC4_NMF_SOURCE_DIR`. Idempotent : si le fichier existe déjà sous
# `<source_dir>/<project_id>/<nmf_file_id>.nmf`, on ne recopie pas.
NMF_SOURCE_DIR = os.environ.get("BC4_NMF_SOURCE_DIR", "/var/lib/bc4/nmf-source")

# Deny-list : jamais recopiée vers stg_event, même si le décodeur l'expose.
IDENTITY_KEYS: set[str] = {
    "imsi", "msisdn", "imei", "imeisv", "tmsi", "s_tmsi", "stmsi",
    "guti", "mtmsi", "m_tmsi", "ptmsi", "p_tmsi", "subscriber_id",
}

# Chemins candidats pour le décodeur NMF. On essaie dans l'ordre.
# `BC4_NMF_DECODER_PATH` peut pointer vers un dossier qui expose
# `bc4_decoder.py`. À défaut : rien, écart déclaré.
_DECODER_CANDIDATES = [
    os.environ.get("BC4_NMF_DECODER_PATH"),
    "/opt/nmf_decoder",
    "/home/devmat/nmf_decoder",
    "/home/devmat/BC4/decoder",
]

_DECODER_MODULE = "bc4_decoder"


class BodyTooLarge(Exception):
    pass


@dataclass
class DecoderHandle:
    """Résultat de la résolution du décodeur NMF."""

    available: bool
    version: str
    reason: str | None = None            # motif si non dispo
    decoder: Any | None = None           # module `bc4_decoder` chargé


# ---------------------------------------------------------------------------
# Résolution du décodeur
# ---------------------------------------------------------------------------


def resolve_decoder() -> DecoderHandle:
    """Cherche `bc4_decoder.py` dans les chemins candidats.

    Retourne un `DecoderHandle` honnête :
    - `available=True` + module chargé + `version` = `DECODER_VERSION` lu
      directement dans le module importé (`"bc4-decoder 1.0.0"`) ;
    - `available=False` + motif, sans jamais planter.

    Aucune heuristique : si le fichier n'est pas trouvé, l'écart est
    rapporté (`decoder_unavailable`), pas comblé.
    """
    tried: list[str] = []
    for root in _DECODER_CANDIDATES:
        if not root:
            continue
        tried.append(root)
        mod_path = os.path.join(root, f"{_DECODER_MODULE}.py")
        if not os.path.isfile(mod_path):
            continue
        try:
            if root not in sys.path:
                sys.path.insert(0, root)
            # On force un import frais si un homonyme a été chargé depuis
            # un autre chemin lors d'un précédent appel.
            if _DECODER_MODULE in sys.modules:
                existing = sys.modules[_DECODER_MODULE]
                existing_file = getattr(existing, "__file__", None) or ""
                if os.path.realpath(existing_file) != os.path.realpath(mod_path):
                    del sys.modules[_DECODER_MODULE]
            mod = importlib.import_module(_DECODER_MODULE)
        except Exception as e:  # pragma: no cover — surface honnête
            return DecoderHandle(
                available=False,
                version="unavailable",
                reason=f"import_error: {e!r} (root={root})",
            )
        if not hasattr(mod, "decode_nmf_file"):
            return DecoderHandle(
                available=False,
                version="unavailable",
                reason=f"decoder_contract: {_DECODER_MODULE}.decode_nmf_file missing (root={root})",
            )
        version = getattr(mod, "DECODER_VERSION", None) or "unknown"
        return DecoderHandle(
            available=True,
            version=str(version),
            decoder=mod,
        )
    return DecoderHandle(
        available=False,
        version="unavailable",
        reason=f"decoder_not_found: tried {tried}",
    )


# ---------------------------------------------------------------------------
# Upload streaming + hash
# ---------------------------------------------------------------------------


def _extract_utc_offset_min(path: str) -> int | None:
    """Lit `#UT` dans les premiers KB de l'en-tête NMF et renvoie la col 1
    (NFF 2.19 : "UTC_to_local" en minutes, signe `local - UTC`).

    Pas de dépendance au décodeur externe : scan direct, format latin-1.
    Jamais inventé : si `#UT` absent ou valeur non-entière, renvoie `None`.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(32 * 1024).decode("latin-1", errors="replace")
    except OSError:
        return None
    for line in head.splitlines():
        if not line.startswith("#"):
            # Les headers sont tous en tête avant les events.
            break
        if not line.startswith("#UT"):
            continue
        # Format attendu : `#UT,,,120,120` — f[0]=tag, f[1..2]=vides,
        # f[3]=UTC_to_local, f[4]=UTC_to_timestamp (NFF 2.19 cols 1 et 2).
        f = line.split(",")
        if len(f) <= 3:
            return None
        raw = f[3].strip().strip('"')
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def spool_and_hash(
    src: IO[bytes],
    dst: IO[bytes],
    max_bytes: int = MAX_FILE_BYTES,
) -> tuple[int, str]:
    """Copie `src` → `dst` en streaming, retourne (taille, sha256_hex).

    Lève `BodyTooLarge` si la taille dépasse `max_bytes`.
    """
    h = hashlib.sha256()
    size = 0
    while True:
        chunk = src.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise BodyTooLarge(f"NMF > {max_bytes} octets")
        h.update(chunk)
        dst.write(chunk)
    dst.seek(0)
    return size, h.hexdigest()


# ---------------------------------------------------------------------------
# Décodage effectif
# ---------------------------------------------------------------------------


def _strip_identity(ev: dict) -> dict:
    """Retire tout champ TOP-LEVEL nommé comme une identité d'abonné.

    Défense en profondeur : le décodeur canonique n'expose pas ces clés,
    mais on garde ce filet pour résister à une évolution amont. On ne
    touche JAMAIS `payload_hex` (le décodeur en garantit l'intégrité pour
    l'analyse ASN.1 aval ; un masquage textuel y corromprait les octets).
    """
    return {k: v for k, v in ev.items() if k.lower() not in IDENTITY_KEYS}


@dataclass
class DecodeResult:
    captures: int
    # Events de SIGNALISATION (category=="signalling"). Vont dans
    # `stg_event` et alimentent le dictionnaire RRC via populate.py.
    events: list[dict] = field(default_factory=list)
    # 0.24.0 (BC1) — Events MESURE + DÉBIT (``measurement`` / ``throughput``
    # dans la terminologie 1.1.0). Vont dans `stg_measurement_raw`.
    # 0.30.0 — Avec le décodeur 2.0.0, cette liste n'est plus alimentée
    # directement (les catégories sont plus granulaires) ; `populate_measurements`
    # BC1 est quand même appelé via les lignes CELLMEAS copiées depuis
    # `stg_event_raw` (voir ``_mirror_cellmeas_into_stg_measurement_raw``).
    measurements: list[dict] = field(default_factory=list)
    # 0.30.0 — Events NON-signalling tous catégorisés (``cellmeas``,
    # ``cmdreq``, ``data_action``, ``data_request``, ``data_summary``,
    # ``tx_power``, ``cqi``, ``lock``, ``gps``, ``other``). Vont dans
    # ``stg_event_raw``. Chaque dict porte ``raw_fields`` **dict**
    # (nom prouvé → valeur).
    raw_events: list[dict] = field(default_factory=list)
    gps_count: int = 0
    operators: dict[str, int] = field(default_factory=dict)  # PLMN → compteur
    technos: dict[str, int] = field(default_factory=dict)
    # 0.30.0 — meta file-level (header `#...`).
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def decode_nmf_file(path: str, handle: DecoderHandle) -> DecodeResult:
    """Décode un NMF via ``bc4_decoder.decode_nmf_file_full`` (2.0.0).

    Fallback explicite sur ``decode_nmf_file`` (1.0.0) si la nouvelle porte
    n'est pas exposée — l'écart est **déclaré** via ``error`` et on continue
    avec les events signalling seuls (backcompat).

    Jamais de valeurs inventées : décodeur indisponible ou crash →
    ``DecodeResult`` avec ``error`` renseigné + compteurs à 0.
    """
    if not handle.available:
        return DecodeResult(
            captures=0,
            events=[],
            gps_count=0,
            error=f"decoder_unavailable: {handle.reason}",
        )

    try:
        decode_full_fn = getattr(handle.decoder, "decode_nmf_file_full", None)
        decode_legacy_fn = getattr(handle.decoder, "decode_nmf_file", None)
        if decode_full_fn is None and decode_legacy_fn is None:
            return DecodeResult(
                captures=0,
                events=[],
                gps_count=0,
                error="decoder_contract: ni decode_nmf_file_full ni decode_nmf_file",
            )

        meta: dict[str, Any] = {}
        if decode_full_fn is not None:
            blob = decode_full_fn(path)
            meta = blob.get("meta") or {}
            meta["device_name"] = None  # #DN identity is never persisted.
            events_iter: Iterable[dict] = blob.get("events") or []
        else:
            # Fallback 1.0.0 — tout vient en signalling.
            events_iter = decode_legacy_fn(path)
    except Exception as e:
        return DecodeResult(
            captures=0,
            events=[],
            gps_count=0,
            error=f"decoder_crash: {e!r}",
        )

    events: list[dict] = []
    raw_events: list[dict] = []
    gps = 0
    operators: dict[str, int] = {}
    technos: dict[str, int] = {}
    capture_ids: set[str] = set()

    try:
        for ev in events_iter:
            # Dicts plats, voir docstring décodeur 2.0.0 (section events).
            ev = _strip_identity(dict(ev))
            cap_id = ev.get("capture_id")
            if cap_id is None:
                return DecodeResult(
                    captures=len(capture_ids),
                    events=events,
                    raw_events=raw_events,
                    gps_count=gps,
                    operators=operators,
                    technos=technos,
                    meta=meta,
                    error="decoder_contract: event sans capture_id",
                )
            capture_ids.add(str(cap_id))
            seq = ev.get("seq")
            if seq is None:
                return DecodeResult(
                    captures=len(capture_ids),
                    events=events,
                    raw_events=raw_events,
                    gps_count=gps,
                    operators=operators,
                    technos=technos,
                    meta=meta,
                    error="decoder_contract: event sans seq",
                )
            lat = ev.get("lat")
            lon = ev.get("lon")
            # N1 — n_gps = COUNT(event_code='GPS'), pas lignes-avec-coords.
            # Avant N1 : chaque event qui portait lat/lon (y compris
            # positions héritées fix précédent dans certains décodeurs)
            # comptait → inflation. Désormais seuls les events GPS true
            # (code 'GPS') incrémentent le compteur.
            if _s(ev.get("event_code")) == "GPS" and lat is not None and lon is not None:
                gps += 1
            plmn = ev.get("plmn")
            if plmn:
                operators[str(plmn)] = operators.get(str(plmn), 0) + 1
            system = ev.get("system")
            if system:
                technos[str(system)] = technos.get(str(system), 0) + 1

            # Dispatch par catégorie décodeur 2.0.0.
            category = ev.get("category") or "signalling"
            if category == "signalling":
                events.append(
                    {
                        "capture_id": str(cap_id),
                        "seq": int(seq),
                        "ts": _s(ev.get("ts")),
                        "event_code": _s(ev.get("event_code")),
                        "system": _s(system),
                        "channel": _s(ev.get("channel")),
                        "direction": _s(ev.get("direction")),
                        "message": _s(ev.get("message")),
                        "freq": _s(ev.get("freq")),
                        "pci": _s(ev.get("pci")),
                        "payload_hex": _s(ev.get("payload_hex")),
                        "lat": float(lat) if lat is not None else None,
                        "lon": float(lon) if lon is not None else None,
                    }
                )
            else:
                # Décodeur 2.0.0 : raw_fields est un DICT nommé (fallback cN).
                # Décodeur 1.1.0 (BC1 ancien) : raw_fields est une list[str].
                # Dans le second cas, on l'adapte en dict ``{"c0": v0, ...}``
                # pour normaliser avec le schéma stg_event_raw.
                rf = ev.get("raw_fields")
                if isinstance(rf, dict):
                    raw_fields_dict = {k: (None if v is None else str(v)) for k, v in rf.items()}
                elif isinstance(rf, list):
                    raw_fields_dict = {
                        f"c{i}": (None if v is None else str(v))
                        for i, v in enumerate(rf)
                    }
                else:
                    raw_fields_dict = {}
                # Nemo non-RRC system is column 4 only; never search other positions.
                system = {"7":"LTE","8":"LTE","9":"NR","5":"UMTS","1":"GSM"}.get(raw_fields_dict.get("rat_code") or raw_fields_dict.get("c3"))
                raw_events.append(
                    {
                        "capture_id": str(cap_id),
                        "seq": int(seq),
                        "ts": _s(ev.get("ts")),
                        "event_code": _s(ev.get("event_code")) or "UNKNOWN",
                        "category": category,
                        "system": _s(system),
                        "lat": float(lat) if lat is not None else None,
                        "lon": float(lon) if lon is not None else None,
                        "raw_fields": raw_fields_dict,
                    }
                )
    except Exception as e:
        return DecodeResult(
            captures=len(capture_ids),
            events=events,
            raw_events=raw_events,
            gps_count=gps,
            operators=operators,
            technos=technos,
            meta=meta,
            error=f"decoder_iter_error: {e!r}",
        )

    return DecodeResult(
        captures=len(capture_ids),
        events=events,
        raw_events=raw_events,
        gps_count=gps,
        operators=operators,
        technos=technos,
        meta=meta,
    )


def _s(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# ---------------------------------------------------------------------------
# Persistance
# ---------------------------------------------------------------------------


def _persist_source_file(tmp_path: str, project_id: str, nmf_file_id: str) -> str | None:
    """Copie le ``.nmf`` du tempfile vers ``NMF_SOURCE_DIR/<project_id>/<nmf_file_id>.nmf``.

    Idempotent : si la destination existe déjà, on ne recopie pas (le même
    ``nmf_file_id`` ne doit arriver qu'une fois ; en cas d'erreur système
    on garde ce qui est là). Retourne le chemin absolu de la copie, ou
    ``None`` si l'écriture échoue (ingestion continue, écart déclaré sur
    ``NmfFile.error_msg``).
    """
    try:
        dest_dir = os.path.join(NMF_SOURCE_DIR, project_id)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f"{nmf_file_id}.nmf")
        if not os.path.exists(dest):
            shutil.copyfile(tmp_path, dest)
        return dest
    except OSError:
        return None


def ingest_upload(
    db: Session,
    project: Project,
    stream: IO[bytes],
    filename: str,
    handle: DecoderHandle,
    *, populate: bool = True, parsing_snapshot: dict[str, Any] | None = None,
) -> NmfFile:
    """Ingère UN upload : stream → disque → hash → idempotence → décode →
    stg_event. Retourne le `NmfFile` persisté (toujours : succès, erreur,
    ou doublon idempotent — dans tous les cas l'appelant voit l'état réel)."""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".nmf") as tmp:
        tmp_path = tmp.name
        try:
            size, sha = spool_and_hash(stream, tmp)
        except BodyTooLarge:
            os.unlink(tmp_path)
            raise

    try:
        # Idempotence : si (project_id, sha256) existe déjà, on renvoie l'existant.
        existing = (
            db.query(NmfFile)
            .filter(NmfFile.project_id == project.id, NmfFile.sha256 == sha)
            .one_or_none()
        )
        if existing is not None:
            # Idempotent uploads also upgrade missing Light data, without re-ingesting RRC/staging.
            from app.nmf_decoder.store import decode_capture
            caps=db.execute(text('SELECT DISTINCT capture_id FROM stg_event_raw WHERE project_id=:pid AND nmf_file_id=:fid'),{'pid':project.id,'fid':existing.id}).scalars().all()
            for cap in caps:
                decode_capture(
                    db, project.id, cap,
                    (parsing_snapshot or {}).get('decode_level', project.parse_decode_level),
                    parsing_snapshot=parsing_snapshot,
                )
            db.commit()
            return existing

        nmf_id = uuid.uuid4().hex[:16]
        # 0.30.0 — persiste le .nmf source AVANT de fermer le tempfile.
        # Jamais fatal : si l'écriture échoue, on continue sans source_path
        # (déclaré via `error_msg`, pas inventé).
        source_path = _persist_source_file(tmp_path, project.id, nmf_id)

        nmf = NmfFile(
            id=nmf_id,
            project_id=project.id,
            filename=filename,
            size_bytes=size,
            sha256=sha,
            uploaded_at=datetime.now(timezone.utc),
            status="decoding",
            decoder_version=handle.version if handle.available else "unavailable",
            error_msg=None if source_path else "source_path_write_failed",
            n_captures=0,
            n_events=0,
            n_gps=0,
            source_path=source_path,
        )
        db.add(nmf)
        db.flush()  # pour disposer de nmf.id en FK avant les inserts stg_event

        result = decode_nmf_file(tmp_path, handle)

        # 0.30.0 — meta file-level (header `#...` + env depuis le nom).
        if result.meta:
            m = result.meta
            nmf.dl = m.get("dl")
            nmf.ts_label = m.get("ts")
            # 0.33.0 — Fallback env **déclaré** : le décodeur dérive `env`
            # depuis `os.path.basename(path)`, or ici `path` est le tempfile
            # anonyme (`/tmp/tmpXXXXXX.nmf`) qui ne contient pas
            # `incar`/`indoor`. On rejoue la même règle (par le CONTENU,
            # littéral présent) sur le `filename` original de l'upload.
            # Jamais inventé : si ni le décodeur ni le filename ne portent
            # le littéral, `env` reste NULL déclaré.
            env_decoded = m.get("env")
            if env_decoded is None and filename:
                base = os.path.basename(filename).lower()
                if "incar" in base:
                    env_decoded = "incar"
                elif "indoor" in base:
                    env_decoded = "indoor"
            nmf.env = env_decoded
            # start_at = concat start_time + start_date si dispo, verbatim.
            start_time = m.get("start_time")
            start_date = m.get("start_date")
            if start_time and start_date:
                nmf.start_at = f"{start_date} {start_time}"
            elif start_time:
                nmf.start_at = start_time
            elif start_date:
                nmf.start_at = start_date
            nmf.device_sw = m.get("device_sw")
            nmf.device_name = m.get("device_name")
            nmf.product = m.get("product")
            nmf.imei_present = bool(m.get("imei_present")) if m.get("imei_present") is not None else None
            nmf.imsi_present = bool(m.get("imsi_present")) if m.get("imsi_present") is not None else None
            # 0.75.0 — #UT col 1 (NFF 2.19 "UTC_to_local", minutes, signe
            # local-UTC). Lu directement depuis l'en-tête du fichier source :
            # le décodeur externe n'expose pas ce champ dans `meta`, et les
            # events `#UT` ne sont jamais persistés dans `nmf_event_*`.
            # Jamais inventé : si l'en-tête n'a pas de `#UT`, reste NULL.
            nmf.utc_offset_min = _extract_utc_offset_min(tmp_path)

        if result.error:
            nmf.status = "error"
            nmf.error_msg = result.error
            # Les comptes réels sont rapportés tels quels (zéro ou partiels).
            nmf.n_captures = result.captures
            nmf.n_events = len(result.events)
            nmf.n_gps = result.gps_count
            db.commit()
            return nmf

        if result.events:
            # Insertion par lots. `project_id` est copié explicitement sur
            # chaque event ; `nmf_file_id` idem — scoping dur par projet.
            rows: list[dict] = []
            for e in result.events:
                rows.append(
                    {
                        "project_id": project.id,
                        "nmf_file_id": nmf.id,
                        "capture_id": e["capture_id"],
                        "seq": e["seq"],
                        "ts": e["ts"],
                        "event_code": e["event_code"],
                        "system": e["system"],
                        "channel": e["channel"],
                        "direction": e["direction"],
                        "message": e["message"],
                        "freq": e["freq"],
                        "pci": e["pci"],
                        "payload_hex": e["payload_hex"],
                        "lat": e["lat"],
                        "lon": e["lon"],
                    }
                )
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                db.execute(
                    text(
                        """
                        INSERT INTO stg_event (
                            project_id, nmf_file_id, capture_id, seq, ts,
                            event_code, system, channel, direction, message,
                            freq, pci, payload_hex, lat, lon
                        ) VALUES (
                            :project_id, :nmf_file_id, :capture_id, :seq, :ts,
                            :event_code, :system, :channel, :direction, :message,
                            :freq, :pci, :payload_hex, :lat, :lon
                        )
                        """
                    ),
                    batch,
                )

        # 0.30.0 — Stream TOUT ce qui n'est pas signalling dans `stg_event_raw`
        # avec `raw_fields` **dict** nommé (fallback cN sur les positions
        # non prouvées). Backcompat BC1 : on miroite aussi les catégories
        # CELLMEAS (plus data_summary, pertinentes pour le skeleton MP) dans
        # `stg_measurement_raw` **au format list[str]** pour ne pas casser
        # la route `/measurements/raw` et `populate_measurements` BC1.
        if result.raw_events:
            raw_rows: list[dict] = []
            mirror_rows: list[dict] = []
            for ev in result.raw_events:
                raw_rows.append(
                    {
                        "project_id": project.id,
                        "nmf_file_id": nmf.id,
                        "capture_id": ev["capture_id"],
                        "seq": ev["seq"],
                        "ts": ev["ts"],
                        "event_code": ev["event_code"],
                        "category": ev["category"],
                        "system": ev["system"],
                        "lat": ev["lat"],
                        "lon": ev["lon"],
                        "raw_fields": _json_module.dumps(redact_raw(ev["event_code"],ev["raw_fields"])),
                    }
                )
                # Mirror BC1 : CELLMEAS → stg_measurement_raw (category='measurement')
                # pour que `populate_measurements` crée les skeleton MP et que
                # `populate_measurement_points` puisse UPDATE dessus.
                if ev["category"] == "cellmeas":
                    # Reconstruit une list[str] sérialisée pour la table BC1.
                    rf_dict = ev["raw_fields"] or {}
                    rf_list = [v if v is not None else "" for v in rf_dict.values()]
                    mirror_rows.append(
                        {
                            "project_id": project.id,
                            "nmf_file_id": nmf.id,
                            "capture_id": ev["capture_id"],
                            "seq": ev["seq"],
                            "ts": ev["ts"],
                            "event_code": ev["event_code"],
                            "category": "measurement",
                            "system": ev["system"],
                            "lat": ev["lat"],
                            "lon": ev["lon"],
                            "raw_fields": _json_module.dumps(rf_list),
                        }
                    )
                elif ev["category"] == "data_summary":
                    rf_dict = ev["raw_fields"] or {}
                    rf_list = [v if v is not None else "" for v in rf_dict.values()]
                    mirror_rows.append(
                        {
                            "project_id": project.id,
                            "nmf_file_id": nmf.id,
                            "capture_id": ev["capture_id"],
                            "seq": ev["seq"],
                            "ts": ev["ts"],
                            "event_code": ev["event_code"],
                            "category": "throughput",
                            "system": ev["system"],
                            "lat": ev["lat"],
                            "lon": ev["lon"],
                            "raw_fields": _json_module.dumps(rf_list),
                        }
                    )
            for i in range(0, len(raw_rows), BATCH_SIZE):
                batch = raw_rows[i : i + BATCH_SIZE]
                db.execute(
                    text(
                        """
                        INSERT INTO stg_event_raw (
                            project_id, nmf_file_id, capture_id, seq,
                            category, event_code, ts, system, lat, lon, raw_fields
                        ) VALUES (
                            :project_id, :nmf_file_id, :capture_id, :seq,
                            :category, :event_code, :ts, :system, :lat, :lon,
                            CAST(:raw_fields AS JSONB)
                        )
                        """
                    ),
                    batch,
                )
            for i in range(0, len(mirror_rows), BATCH_SIZE):
                batch = mirror_rows[i : i + BATCH_SIZE]
                db.execute(
                    text(
                        """
                        INSERT INTO stg_measurement_raw (
                            project_id, nmf_file_id, capture_id, seq, ts,
                            event_code, category, system, lat, lon, raw_fields
                        ) VALUES (
                            :project_id, :nmf_file_id, :capture_id, :seq, :ts,
                            :event_code, :category, :system, :lat, :lon,
                            CAST(:raw_fields AS JSONB)
                        )
                        """
                    ),
                    batch,
                )
            # Alimente le flag "measurements" du résultat pour que la logique
            # de populate ci-dessous soit déclenchée comme en 0.24.0 BC1.
            result.measurements = mirror_rows

        # Staging complet et source_path doivent être visibles avant le parsing
        # potentiellement long. decode_capture ferme ensuite sa propre lecture
        # de métadonnées avant de parcourir le fichier.
        db.commit()
        from app.nmf_decoder.store import decode_capture
        for cap in sorted({ev["capture_id"] for ev in result.raw_events}):
            decode_capture(
                db, project.id, cap,
                (parsing_snapshot or {}).get('decode_level', project.parse_decode_level),
                parsing_snapshot=parsing_snapshot,
            )

        nmf.status = "done"
        nmf.n_captures = result.captures
        nmf.n_events = len(result.events)
        nmf.n_gps = result.gps_count
        # Accumulation des PLMN vus (comptage réel event-par-event).
        # bc4_decoder 1.0.0 n'expose pas `plmn` → `operators` est vide ;
        # cette branche existe pour quand une source PLMN sera câblée.
        if result.operators:
            acc = dict(project.operators_plmn or {})
            for plmn, n in result.operators.items():
                acc[plmn] = int(acc.get(plmn, 0)) + int(n)
            project.operators_plmn = acc
        db.commit()

        # 0.24.0 Keystone — Peuple `measurement_points` depuis
        # `stg_measurement_raw` fraîchement inséré. Idempotent (purge
        # les anciens points mesure du projet, préserve les seeds B0).
        # Appelé après le commit stg_event pour que `_build_sib1_index`
        # ait accès aux SIB1 à jour. Erreur ici → NMF reste `done` mais
        # un warning est émis (pas de rollback d'ingestion).
        if populate and result.measurements:
            try:
                from app.services.populate_measurements import populate_measurements
                populate_measurements(db, project.id, purge=True)
            except Exception as exc:
                # Journalisé mais non-fatal — l'ingestion staging a réussi.
                nmf.error_msg = f"populate_measurements_warning: {exc!r}"
                db.commit()
        # 0.30.0 — Enrichissement MP depuis `stg_event_raw` + meta fichier.
        # UPDATE sur les skeleton rows (CELLMEAS) et INSERT pour les autres
        # catégories (CMDREQ, data_*, tx_power, cqi, lock, other).
        # Appelé APRÈS le skeleton BC1 pour profiter des lignes insérées.
        if populate and result.raw_events:
            try:
                from app.measure.populate import populate_measurement_points
                populate_measurement_points(db, project.id, purge=False)
            except Exception as exc:
                # Journalisé mais non-fatal — staging raw + skeleton BC1
                # ont réussi, l'enrichissement 2.0.0 reste rejouable via
                # `scripts/backfill_measurements.py` (idempotent).
                nmf.error_msg = (
                    (nmf.error_msg + " | " if nmf.error_msg else "")
                    + f"populate_measurement_points_warning: {exc!r}"
                )
                db.commit()
        return nmf
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


_ORANGE_PLMN = "20801"


def _compute_perimeter(db: Session, cells: list[dict]) -> dict:
    """Jointure cells Orange (plmn=20801) ↔ `cell_ref` → agrégat géo.

    Pour chaque cellule :
      - LTE : `cell_id` matché contre `cell_ref.eci`
      - NR  : `cell_id` matché contre `cell_ref.nci`
    Ne touche QUE l'opérateur Orange (seul PLMN couvert par `cell_ref`).
    Les autres PLMN sont comptés mais pas joints — déclarés ouverts.

    Retour (JSON stocké dans `project.perimeter`) :
    ```
    {
      "cells_total":            int,     # cells vues en SIB1
      "cells_orange":           int,     # dont plmn=20801
      "cells_other":            int,     # dont plmn != 20801 (non attribuables)
      "cells_joined":           int,     # Orange joints à cell_ref
      "cells_orange_unjoined":  int,     # Orange sans ligne cell_ref
      "join_rate_pct":          float|None,  # cells_joined/cells_orange*100
      "dors":                   [str],   # DOR distincts rencontrés
      "drs":                    [str],   # DR distincts
      "plaques":                [str],   # plaques distinctes
      "sites":                  [str],   # sites distincts
      "arcep_zones":            [str],   # catégories ARCEP distinctes
      "coverage":               [str],   # ex. ["outdoor","indoor"]
      "label":                  str,     # résumé lisible ("DR Paris, DR Lyon")
      "zone_source":            "cell_ref_exact" | "none",
    }
    ```
    `null` reste `null` — la UI affiche « N/D », jamais `0`.
    """
    cells_total = len(cells)
    orange = [c for c in cells if c.get("plmn") == _ORANGE_PLMN]
    other = cells_total - len(orange)
    if not orange:
        # Aucune cellule Orange : perimeter restera non attribué.
        return {
            "cells_total": cells_total,
            "cells_orange": 0,
            "cells_other": other,
            "cells_joined": 0,
            "cells_orange_unjoined": 0,
            "join_rate_pct": None,
            "dors": [],
            "drs": [],
            "plaques": [],
            "sites": [],
            "arcep_zones": [],
            "coverage": [],
            "label": "N/D",
            "zone_source": "none",
        }

    lte_ids = tuple({c["cell_id"] for c in orange if c["rat"] == "LTE"})
    nr_ids = tuple({c["cell_id"] for c in orange if c["rat"] == "NR"})
    rows: list = []
    if lte_ids:
        rows.extend(
            db.execute(
                text(
                    "SELECT dor, dr, plaque, site_id, site_name, arcep_zone, coverage, eci "
                    "FROM cell_ref WHERE rat='4G' AND eci = ANY(:ids)"
                ),
                {"ids": list(lte_ids)},
            ).all()
        )
    if nr_ids:
        rows.extend(
            db.execute(
                text(
                    "SELECT dor, dr, plaque, site_id, site_name, arcep_zone, coverage, nci "
                    "FROM cell_ref WHERE rat='5G' AND nci = ANY(:ids)"
                ),
                {"ids": list(nr_ids)},
            ).all()
        )
    joined_ids = {r[-1] for r in rows}
    cells_joined = len(joined_ids)
    cells_orange_unjoined = len({c["cell_id"] for c in orange}) - cells_joined

    def _distinct(idx: int) -> list[str]:
        out = sorted({str(r[idx]) for r in rows if r[idx]})
        return out

    dors = _distinct(0)
    drs = _distinct(1)
    plaques = _distinct(2)
    sites_sorted = sorted({str(r[4]) for r in rows if r[4]})
    arcep = _distinct(5)
    coverage = _distinct(6)

    label_parts = drs or plaques or dors or ["N/D"]
    label = ", ".join(label_parts[:5]) + (f" (+{len(label_parts) - 5})" if len(label_parts) > 5 else "")

    join_rate = (
        round(100.0 * cells_joined / len(orange), 2) if orange else None
    )

    return {
        "cells_total": cells_total,
        "cells_orange": len(orange),
        "cells_other": other,
        "cells_joined": cells_joined,
        "cells_orange_unjoined": cells_orange_unjoined,
        "join_rate_pct": join_rate,
        "dors": dors,
        "drs": drs,
        "plaques": plaques,
        "sites": sites_sorted,
        "arcep_zones": arcep,
        "coverage": coverage,
        "label": label if rows else "N/D",
        "zone_source": "cell_ref_exact" if rows else "none",
    }


def _detect_enrich_context(db: Session, project_id: str) -> dict:
    """Rejoue les events déjà insérés dans `stg_event` et passe par
    `bc4_enrich.detect_context`. Zéro second décode du `.nmf` : on
    exploite ce que `bc4_decoder` a persisté. Si `bc4_enrich` n'est pas
    résoluble (binding décodeur absent), on renvoie un contexte vide —
    déclaré, pas comblé par heuristique."""
    try:
        handle = resolve_decoder()
    except Exception:
        return {"operators": [], "bands": [], "technos": [], "plmns": []}
    enrich_mod = _import_enrich(handle)
    if enrich_mod is None:
        return {"operators": [], "bands": [], "technos": [], "plmns": []}

    rows = db.execute(
        text(
            "SELECT system, message, freq, payload_hex "
            "FROM stg_event WHERE project_id = :pid AND system IN ('LTE','NR')"
        ),
        {"pid": project_id},
    ).all()
    events = [
        {"system": r.system, "message": r.message, "freq": r.freq, "payload_hex": r.payload_hex}
        for r in rows
    ]
    return enrich_mod.detect_context(events)


def _import_enrich(_handle):
    """Importe `bc4_enrich` depuis le même répertoire que `bc4_decoder`.
    Retourne None en cas d'absence (déclaré, pas inventé)."""
    try:
        import bc4_enrich  # type: ignore[import-not-found]
        return bc4_enrich
    except Exception:
        pass
    # Fallback : charger depuis les candidats connus du décodeur.
    for root in [os.environ.get("BC4_NMF_DECODER_PATH"), *_DECODER_CANDIDATES]:
        if not root or root in sys.path:
            continue
        if os.path.isfile(os.path.join(root, "bc4_enrich.py")):
            sys.path.insert(0, root)
            try:
                import bc4_enrich  # type: ignore[import-not-found]
                return bc4_enrich
            except Exception:
                continue
    return None


def refresh_project_summary(db: Session, project: Project, *, populate: bool = True, importing: bool = False) -> None:
    """Recalcule les colonnes résumé de `projects` à partir des comptes
    réels de `nmf_file` et `stg_event`. Aucun chiffre inventé.
    """
    files = db.query(NmfFile).filter(NmfFile.project_id == project.id).all()
    n_captures = sum(f.n_captures for f in files)
    n_events = sum(f.n_events for f in files)
    n_gps = sum(f.n_gps for f in files)

    # Operators & technos vus : relus en SQL direct sur stg_event (comptage
    # réel, pas un héritage d'étape intermédiaire).
    technos_rows = db.execute(
        text(
            """
            SELECT system, COUNT(*) AS n
            FROM stg_event
            WHERE project_id = :pid AND system IS NOT NULL
            GROUP BY system
            """
        ),
        {"pid": project.id},
    ).all()
    technos = {str(r[0]): int(r[1]) for r in technos_rows}

    # `operators_plmn` reste côté résumé en PLMN→opérateur si une table de
    # mapping PLMN est disponible. En B1-ingest on stocke juste les PLMN
    # vus avec un libellé "N/D" tant qu'aucune table n'est fournie — écart
    # ouvert déclaré au CHANGELOG. bc4_decoder 1.0.0 ne les expose pas
    # non plus → operators restera vide.

    gps_cov: float | None
    if n_events == 0:
        gps_cov = None  # pas de division par zéro silencieuse
    else:
        # part d'events qui portent un GPS (après rattachement du dernier GPS).
        with_gps = db.execute(
            text(
                "SELECT COUNT(*) FROM stg_event WHERE project_id = :pid AND lat IS NOT NULL AND lon IS NOT NULL"
            ),
            {"pid": project.id},
        ).scalar() or 0
        gps_cov = round(100.0 * int(with_gps) / n_events, 2)

    # Status d'ingestion : rouge dès qu'un fichier est en error, orange tant
    # qu'un fichier décode encore, vert sinon.
    status: str
    if any(f.status == "error" for f in files):
        status = "error"
    elif any(f.status in {"pending", "decoding"} for f in files):
        status = "importing"
    elif files:
        status = "ready"
    else:
        status = "draft"

    project.n_captures_ingest = n_captures
    project.n_events_ingest = n_events
    project.gps_coverage_pct = gps_cov
    project.technos_seen = technos
    if importing:
        status = "importing"
    project.status_ingest = status

    # Enrichissement Zod (0.11.0) : operators / bands / technologies.
    # On rejoue les events depuis `stg_event` (pas de second décode du
    # .nmf) et on passe par `bc4_enrich.detect_context` pour :
    #   - operators : PLMN SIB1 décodé via pycrate → opérateur (FR)
    #   - bands     : EARFCN/ARFCN → bande 3GPP (TS 36.101/38.101)
    #   - technos   : {LTE, NR} vraiment vus
    # `operators_plmn` reflète les PLMN SIB1 vus (bruts, pour trace).
    enrich = _detect_enrich_context(db, project.id)
    if enrich["technos"]:
        project.technologies = enrich["technos"]
    if enrich["bands"]:
        project.bands = enrich["bands"]
    # ----------------------------------------------------------------
    # Opérateurs (0.14.0, bc4-enrich 1.2.0) : doctrine « opérateur =
    # PLMN primaire du SIB1 ». Seuls les 11 PLMN MNO FR (Orange, SFR,
    # Bouygues, Free) sortent avec leur marque via
    # `operator_by_plmn`. Un PLMN hors table (MVNO, DOM-TOM, réseau
    # privé…) doit rester VISIBLE comme "PLMN <id> (non catalogué)"
    # plutôt que de disparaître en N/D. Format partagé avec le front
    # (OperatorChip 1.6.0 : couleur slate pour toute étiquette hors
    # des 4 MNO).
    # ----------------------------------------------------------------
    plmns_seen = list(enrich.get("plmns") or [])
    if plmns_seen:
        op_by_plmn = enrich.get("operator_by_plmn") or {}
        labels: list[str] = []
        for plmn in plmns_seen:
            op = op_by_plmn.get(plmn)
            if op is not None:
                labels.append(op)
            else:
                labels.append(f"PLMN {plmn} (non catalogué)")
        project.operators = sorted(set(labels))
    # operators_plmn : dict {plmn: 1} pour trace ; vide si aucun SIB1 décodé.
    project.operators_plmn = {p: 1 for p in enrich["plmns"]} or (project.operators_plmn or {})

    # ---------------------------------------------------------------
    # Périmètre (0.12.0) : jointure cells Orange (plmn=20801) ↔ cell_ref.
    # Un lecteur peut-il savoir OÙ un projet a été fait sans PLMN autre
    # qu'Orange ? Non — `cell_ref` ne couvre QU'Orange. Les cellules
    # non-Orange restent sans attribution géographique à ce stade
    # (déclaré, pas comblé par heuristique GPS).
    project.perimeter = _compute_perimeter(db, enrich.get("cells") or [])

    # ---------------------------------------------------------------
    # Miroitage B1-ingest -> B0 (0.11.1) : les projets ingérés via
    # `POST /projects` sortent avec les champs B0 (`captures`,
    # `technologies`, `operators`, `geography`, `departements`) vides
    # par construction. On aligne les deux conventions SANS écraser
    # les projets seedés B0 (Paris 2026 Q1 ne doit pas perdre ses
    # `operators=["Orange","SFR",...]`). Mirror conditionnel :
    #
    #   - captures      <- n_captures_ingest, si non None.
    #   - technologies  <- clés de technos_seen triées par -count,
    #                      si technos_seen est un dict non-vide.
    #                      FILTRÉ sur le vocabulaire Zod
    #                      `{LTE, NR, EN-DC}` (cohérent 0.10.0) —
    #                      technos_seen peut contenir d'autres clés
    #                      (p.ex. "UMTS") qui restent visibles sur
    #                      `GET /projects/{id}/ingest.technos_seen`
    #                      pour trace, mais ne polluent pas la liste
    #                      Zod `project.technologies`. Zéro invention :
    #                      si la techno n'a pas été vue au décodage,
    #                      elle n'apparaît pas.
    #   - operators     : non touché (operators_plmn={} tant que PLMN
    #                      n'est pas câblé → `operators` reste []).
    #                      Écart ouvert déclaré depuis 0.6.1.
    #   - geography /
    #     departements  : non touchés (nécessiteraient un reverse-
    #                      geocoding des `stg_event.lat/lon`, hors
    #                      scope de ce patch — écart ouvert déclaré).
    # ---------------------------------------------------------------
    # Mirror B1-ingest → B0 (fix bug 0.14.0) : `n_captures_ingest > 0`
    # au lieu de `is not None`. Un projet seedé B0 sans fichier NMF
    # ingéré a `n_captures_ingest = 0` (initialisé par la 1re ingestion
    # avortée ou par une migration), mais ses `captures` seedés (ex.
    # Paris 2.4M) doivent rester intacts. L'ancienne garde écrasait
    # `captures` à 0 au prochain `refresh_project_summary`.
    if project.n_captures_ingest is not None and project.n_captures_ingest > 0:
        project.captures = project.n_captures_ingest
    if isinstance(project.technos_seen, dict) and project.technos_seen:
        _ZOD_TECHS = {"LTE", "NR", "EN-DC"}
        project.technologies = [
            k for k in sorted(
                project.technos_seen.keys(),
                key=lambda k: -int(project.technos_seen[k]),
            )
            if k in _ZOD_TECHS
        ]

    # On reflète aussi le status Zod existant pour le front :
    # draft/importing → processing, ready → ready, error → failed.
    project.status = {
        "draft": "processing",
        "importing": "processing",
        "ready": "ready",
        "error": "failed",
    }[status]

    db.commit()

    if not populate:
        return

    # ---------------------------------------------------------------
    # Dictionnaire RRC complet (0.12.0) : décode les RRCSM aplatis
    # (LTE+NR) et peuple `param_occurrence`. Déclenché après le commit
    # du résumé pour que les comptes ingest soient cohérents en base.
    # L'appel est best-effort : si pycrate / bc4_decoder ne sont pas
    # disponibles, on log et on continue (le lot sera rejoué via le
    # script one-shot `scripts/populate_dict_for_all_projects.py`).
    # ---------------------------------------------------------------
    try:
        from app.dict.populate import populate_param_occurrence

        populate_param_occurrence(db, project.id, purge=True)
    except Exception as e:  # pragma: no cover — surface honnête
        import logging as _log
        _log.getLogger("app.ingest.nmf").warning(
            "populate_param_occurrence skipped: %r", e
        )

    # 0.33.0 — Re-run du gating par preuve APRÈS populate_param_occurrence.
    # Les appels per-file de populate_measurement_points voyaient
    # param_occurrence vide (populé seulement en fin de batch), donc la
    # preuve ±2 dB échouait systématiquement sur ``no_rrc_sample`` → les
    # métriques prouvables (rsrp, rsrq) restaient NULL. On rejoue
    # populate_measurement_points une fois que param_occurrence est à
    # jour, pour que MEASUREMENT_MAPPING se peuple et que l'UPDATE
    # COALESCE câble enfin rsrp/rsrq sur les lignes CELLMEAS déjà créées.
    try:
        from app.measure.populate import populate_measurement_points

        populate_measurement_points(db, project.id, purge=False)
    except Exception as e:  # pragma: no cover — surface honnête
        import logging as _log
        _log.getLogger("app.ingest.nmf").warning(
            "populate_measurement_points (post-RRC) skipped: %r", e
        )
        raise RuntimeError("CELLMEAS post-RRC enrichment incomplete") from e
