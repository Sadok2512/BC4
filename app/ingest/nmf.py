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
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import IO, Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import NmfFile, Project

# ---------------------------------------------------------------------------
# Limites & chemins
# ---------------------------------------------------------------------------

MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB par fichier NMF
SPOOL_THRESHOLD = 32 * 1024 * 1024       # bascule disque au-delà de 32 MiB
BATCH_SIZE = 1000

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
    events: list[dict] = field(default_factory=list)   # events aplatis prêts à insérer
    gps_count: int = 0
    operators: dict[str, int] = field(default_factory=dict)  # PLMN → compteur
    technos: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def decode_nmf_file(path: str, handle: DecoderHandle) -> DecodeResult:
    """Décode un fichier NMF via `bc4_decoder.decode_nmf_file`. Itère un
    flux de dicts PLATS (voir contrat du décodeur, docstring du module
    canonique). Jamais de valeurs inventées : si le décodeur est indisponible
    ou plante, on retourne un `DecodeResult` avec `error` renseigné et des
    compteurs à 0.
    """
    if not handle.available:
        return DecodeResult(
            captures=0,
            events=[],
            gps_count=0,
            error=f"decoder_unavailable: {handle.reason}",
        )

    try:
        decode_fn = getattr(handle.decoder, "decode_nmf_file", None)
        if decode_fn is None:
            return DecodeResult(
                captures=0,
                events=[],
                gps_count=0,
                error="decoder_contract: bc4_decoder.decode_nmf_file missing",
            )
        events_iter: Iterable[dict] = decode_fn(path)
    except Exception as e:
        return DecodeResult(
            captures=0,
            events=[],
            gps_count=0,
            error=f"decoder_crash: {e!r}",
        )

    events: list[dict] = []
    gps = 0
    operators: dict[str, int] = {}
    technos: dict[str, int] = {}
    capture_ids: set[str] = set()

    try:
        for ev in events_iter:
            # Dicts plats : capture_id, seq, ts, event_code, system,
            # direction, message, channel, freq, pci, payload_hex, lat, lon.
            ev = _strip_identity(dict(ev))
            cap_id = ev.get("capture_id")
            if cap_id is None:
                # Sécurité : le décodeur canonique garantit `capture_id`
                # non-null. On déclarerait l'écart plutôt que de l'inventer.
                return DecodeResult(
                    captures=len(capture_ids),
                    events=events,
                    gps_count=gps,
                    operators=operators,
                    technos=technos,
                    error="decoder_contract: event sans capture_id",
                )
            capture_ids.add(str(cap_id))
            seq = ev.get("seq")
            if seq is None:
                return DecodeResult(
                    captures=len(capture_ids),
                    events=events,
                    gps_count=gps,
                    operators=operators,
                    technos=technos,
                    error="decoder_contract: event sans seq",
                )
            lat = ev.get("lat")
            lon = ev.get("lon")
            if lat is not None and lon is not None:
                gps += 1
            # PLMN non exposé par bc4_decoder 1.0.0 → `operators` reste
            # vide (écart ouvert déclaré au CHANGELOG). On ne devine pas.
            plmn = ev.get("plmn")
            if plmn:
                operators[str(plmn)] = operators.get(str(plmn), 0) + 1
            system = ev.get("system")
            if system:
                technos[str(system)] = technos.get(str(system), 0) + 1
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
    except Exception as e:
        return DecodeResult(
            captures=len(capture_ids),
            events=events,
            gps_count=gps,
            operators=operators,
            technos=technos,
            error=f"decoder_iter_error: {e!r}",
        )

    return DecodeResult(
        captures=len(capture_ids),
        events=events,
        gps_count=gps,
        operators=operators,
        technos=technos,
    )


def _s(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# ---------------------------------------------------------------------------
# Persistance
# ---------------------------------------------------------------------------


def ingest_upload(
    db: Session,
    project: Project,
    stream: IO[bytes],
    filename: str,
    handle: DecoderHandle,
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
            return existing

        nmf = NmfFile(
            id=uuid.uuid4().hex[:16],
            project_id=project.id,
            filename=filename,
            size_bytes=size,
            sha256=sha,
            uploaded_at=datetime.now(timezone.utc),
            status="decoding",
            decoder_version=handle.version if handle.available else "unavailable",
            error_msg=None,
            n_captures=0,
            n_events=0,
            n_gps=0,
        )
        db.add(nmf)
        db.flush()  # pour disposer de nmf.id en FK avant les inserts stg_event

        result = decode_nmf_file(tmp_path, handle)

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


def refresh_project_summary(db: Session, project: Project) -> None:
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
    if enrich["operators"]:
        project.operators = enrich["operators"]
    if enrich["bands"]:
        project.bands = enrich["bands"]
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
    if project.n_captures_ingest is not None:
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
