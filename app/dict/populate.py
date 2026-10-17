"""Populate `param_occurrence` depuis `stg_event` d'un projet.

Idempotent : UNIQUE `(project_id, stg_event_id, path)` + `ON CONFLICT
DO NOTHING`. Rejouer un populate ne crée pas de doublon.

Rattachement SIB1 → event : ordre canonique `(capture_id, seq)`. Pour
chaque event d'une capture, on cherche le DERNIER SIB1 vu dans la même
capture avec `seq <= event.seq`. Fallback global sur la dernière vue
SIB1 par `(freq, pci)` si aucun SIB1 n'a précédé — cohérent avec la
logique de l'archive.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dict.conversions import convert
from app.dict.decode import (
    DENY,
    band_from_earfcn,
    iter_params_from_event,
    path_matches_deny,
)

log = logging.getLogger("app.dict.populate")

# ---------------------------------------------------------------------------
# Importation de `bc4_enrich` (PLMN FR → opérateur, ARFCN → bande NR).
# On duplique la logique de résolution de `app/ingest/nmf.py::_import_enrich`
# pour ne pas introduire de cycle d'imports.
# ---------------------------------------------------------------------------
_ENRICH_CANDIDATES = [
    os.environ.get("BC4_NMF_DECODER_PATH"),
    "/opt/nmf_decoder",
    "/home/devmat/nmf_decoder",
    "/home/devmat/BC4/decoder",
]


def _import_enrich() -> Any | None:
    try:
        import bc4_enrich  # type: ignore[import-not-found]
        return bc4_enrich
    except Exception:
        pass
    for root in _ENRICH_CANDIDATES:
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


_ENRICH = _import_enrich()


def _plmn_to_operator(plmn: str) -> str | None:
    if _ENRICH is None:
        return None
    return _ENRICH.PLMN_TO_OPERATOR.get(plmn)


def _band_from_freq(freq: Any, system: str) -> str | None:
    """Préférence : bc4_enrich (tables étendues) → fallback archive (LTE)."""
    if _ENRICH is not None:
        try:
            b = _ENRICH.band_from_freq(freq, system)
            if b:
                return b
        except Exception:
            pass
    if system == "LTE":
        return band_from_earfcn(freq)
    return None


def _extract_sib1(system: str, payload_hex: str | None) -> dict:
    """Décode un SIB1 LTE ou NR → `{plmns:set, cells:list}`. Dérivé de
    `bc4_enrich._extract_sib1` : on prend juste la face publique indirecte
    via `detect_context` sur un event unique (le plus simple et le plus
    robuste si bc4_enrich 1.x évolue)."""
    if _ENRICH is None or not payload_hex:
        return {"plmns": set(), "cells": []}
    try:
        return _ENRICH._extract_sib1(payload_hex, system)
    except Exception:
        return {"plmns": set(), "cells": []}


# ---------------------------------------------------------------------------
# Rattachement operator/band par event (capture_id, seq)
# ---------------------------------------------------------------------------
def _build_sib1_index(rows: list) -> dict:
    """À partir d'une liste de tuples (id, capture_id, seq, system, message,
    freq, pci, payload_hex), extrait pour chaque capture la liste des SIB1
    rencontrés (triée par seq) : {(capture_id, system): [(seq, operator,
    band, plmn), ...]}. Deux systems distincts (LTE/NR) peuvent coexister
    dans une même capture — on indexe par (capture_id, system).

    Également : `last_by_cell` = {(freq, pci) : (operator, band)} — fallback
    pour un event sans SIB1 précédent dans sa capture.
    """
    _SIB1 = ("SystemInformationBlockType1", "SIB1", "SystemInformation1")

    sib1_per_cap: dict[tuple[str, str], list[tuple[int, str | None, str | None, str | None]]] = defaultdict(list)
    last_by_cell: dict[tuple[str, str], tuple[str | None, str | None]] = {}

    for r in rows:
        msg = (r.message or "")
        if not any(mk in msg for mk in _SIB1):
            continue
        system = (r.system or "").upper()
        if system not in {"LTE", "NR"}:
            continue
        parsed = _extract_sib1(system, r.payload_hex)
        plmns = parsed.get("plmns") or set()
        if not plmns:
            continue
        # SIB1 porte en principe 1 PLMN principal (plmn-IdentityList[0]).
        # On prend l'ordre d'insertion si set, à défaut arbitraire — ce qui
        # importe c'est que le mapping opérateur reste honnête.
        plmn = sorted(plmns)[0]
        op = _plmn_to_operator(plmn)
        band = _band_from_freq(r.freq, system)
        sib1_per_cap[(str(r.capture_id), system)].append((int(r.seq), op, band, plmn))
        if r.freq is not None and r.pci is not None:
            last_by_cell[(str(r.freq), str(r.pci))] = (op, band)

    # Tri par seq pour recherche binaire éventuelle (ici liste linéaire,
    # suffisant pour les volumes attendus).
    for k, v in sib1_per_cap.items():
        v.sort(key=lambda t: t[0])

    return {"per_cap": sib1_per_cap, "last_by_cell": last_by_cell}


def _resolve_context(
    sib1_idx: dict,
    capture_id: str,
    seq: int,
    system: str,
    freq: Any,
    pci: Any,
) -> tuple[str | None, str | None]:
    """Retourne `(operator, band)` du dernier SIB1 vu avant cet event
    (même capture + system). À défaut : fallback via `(freq, pci)`.
    """
    arr = sib1_idx["per_cap"].get((str(capture_id), system)) or []
    # Dernier SIB1 avec seq <= event.seq
    cand = None
    for s, op, b, _plmn in arr:
        if s <= seq:
            cand = (op, b)
        else:
            break
    if cand is not None:
        op, band = cand
        # Band : si le SIB1 n'a pas fourni de band, on dérive de la freq.
        if not band:
            band = _band_from_freq(freq, system)
        return op, band
    # Fallback cell globale
    if freq is not None and pci is not None:
        hit = sib1_idx["last_by_cell"].get((str(freq), str(pci)))
        if hit is not None:
            op, band = hit
            if not band:
                band = _band_from_freq(freq, system)
            return op, band
    return None, _band_from_freq(freq, system)


# ---------------------------------------------------------------------------
# Sérialisation `value` (brut) et deny-list final sur path
# ---------------------------------------------------------------------------
def _value_to_text(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return str(val)
    try:
        return json.dumps(val, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(val)


# ---------------------------------------------------------------------------
# Populate principal
# ---------------------------------------------------------------------------
BATCH_SIZE = 1000


# 0.36.0 — Backfill `stg_event.system` par le CONTENU
# ---------------------------------------------------------------------------
# Certains décodages (NMF anciens, décodeur 2.0.0 en amont d'un patch
# ultérieur) laissent `stg_event.system IS NULL` sur des RRCSM dont le
# message + canal sont pourtant typés sans ambiguïté. Sans correctif, le
# filtre `system IN ('LTE','NR')` ci-dessous les écarte → param_occurrence
# reste vide pour ce projet. On déduit la techno DU MESSAGE (pas de
# l'étiquette fichier) et on backfill in-place avant le scan. Idempotent.
#
# Règles (par le CONTENU) :
# - Suffixe ` message` ou ` IE` ou prefix `RadioBearerConfig` → NR
#   (convention du décodeur BC4 pour les messages/IE NR aplatis).
# - Prefix `RRCConnection*` → LTE (nommage LTE Rel-8 strict).
# - Prefix `SystemInformation` → LTE (NR utilise `SIB1`/`SIB2` directement).
# - Messages partagés LTE/NR mais présents dans un corpus manifestement
#   LTE (Paging, MeasurementReport sans suffixe, SecurityModeCommand,
#   UECapabilityInformation) → LTE par défaut.
# - Sinon : on ne touche pas (reste NULL, sera skippé par populate).
_BACKFILL_SYSTEM_SQL = """
UPDATE stg_event
SET system = CASE
    WHEN message LIKE '%% message'       THEN 'NR'
    WHEN message LIKE '%% IE'            THEN 'NR'
    WHEN message LIKE 'RadioBearerConfig%%' THEN 'NR'
    WHEN message LIKE 'RRCConnection%%'  THEN 'LTE'
    WHEN message LIKE 'SystemInformation%%' THEN 'LTE'
    WHEN message IN (
        'Paging', 'MeasurementReport',
        'SecurityModeCommand', 'UECapabilityInformation'
    ) THEN 'LTE'
    ELSE system
END
WHERE project_id = :pid
  AND event_code = 'RRCSM'
  AND system IS NULL
  AND message IS NOT NULL
"""


def _backfill_stg_event_system(db: Session, project_id: str) -> int:
    """Déduit `stg_event.system` depuis `message` quand il est NULL. Retourne
    le nombre de lignes mises à jour (0 si rien à faire — idempotent)."""
    res = db.execute(text(_BACKFILL_SYSTEM_SQL), {"pid": project_id})
    n = res.rowcount or 0
    if n:
        db.commit()
    return n


def populate_param_occurrence(
    db: Session,
    project_id: str,
    purge: bool = True,
) -> dict:
    """Peuple `param_occurrence` pour un projet.

    Args
    ----
    purge
        Si True (défaut), purge d'abord toutes les lignes du projet pour
        garantir un état déterministe (évite les lignes orphelines si
        la deny-list évolue). L'UNIQUE constraint reste utilisée côté
        ON CONFLICT DO NOTHING pour la robustesse.

    Retour
    ------
    dict de stats réelles :
        {
          "project_id": str,
          "events_scanned": int,
          "events_decoded_ok": int,
          "events_decoded_err": int,
          "n_params_written": int,
          "n_params_denied": int,
          "errors": {reason: count},
        }
    """
    stats = {
        "project_id": project_id,
        "events_scanned": 0,
        "events_decoded_ok": 0,
        "events_decoded_err": 0,
        "n_params_written": 0,  # compté APRÈS commit via SELECT COUNT(*)
        "n_params_queued": 0,   # tentés (hors deny)
        "n_params_denied": 0,
        "errors": defaultdict(int),
    }

    if purge:
        db.execute(
            text("DELETE FROM param_occurrence WHERE project_id = :pid"),
            {"pid": project_id},
        )
        db.commit()

    # 0.36.0 — Backfill `system` NULL avant scan. Déclaré via `stats`.
    stats["system_backfilled"] = _backfill_stg_event_system(db, project_id)

    # Lecture complète des events RRCSM du projet, ordre canonique.
    rows = db.execute(
        text(
            """
            SELECT id, capture_id, seq, system, channel, direction, message,
                   freq, pci, payload_hex, lat, lon
            FROM stg_event
            WHERE project_id = :pid
              AND event_code = 'RRCSM'
              AND payload_hex IS NOT NULL
              AND system IN ('LTE','NR')
            ORDER BY capture_id, seq
            """
        ),
        {"pid": project_id},
    ).all()

    stats["events_scanned"] = len(rows)
    if not rows:
        stats["errors"] = dict(stats["errors"])
        return stats

    # 1) Index SIB1 → operator/band par (capture, system)
    sib1_idx = _build_sib1_index(rows)

    # 2) Parcours des events + aplatissement + insert batch
    batch: list[dict] = []

    def _flush():
        if not batch:
            return
        db.execute(
            text(
                """
                INSERT INTO param_occurrence (
                    project_id, stg_event_id, system, channel, message,
                    path, value, value_converted, unit_converted,
                    operator, band, lat, lon,
                    param_key, display_name, choice_of, discriminators,
                    origin, is_identifier, functional_group
                ) VALUES (
                    :project_id, :stg_event_id, :system, :channel, :message,
                    :path, :value, :value_converted, :unit_converted,
                    :operator, :band, :lat, :lon,
                    :param_key, :display_name, :choice_of,
                    CAST(:discriminators AS JSONB),
                    :origin, :is_identifier, :functional_group
                )
                ON CONFLICT (project_id, stg_event_id, path) DO NOTHING
                """
            ),
            batch,
        )
        batch.clear()

    for r in rows:
        system = (r.system or "").upper()
        # iter_params : décode l'event et applique la deny-list au walk
        n_before = len(batch)
        decoded_any = False
        error_seen = None
        try:
            params = list(
                iter_params_from_event(
                    system,
                    r.channel,
                    r.direction,
                    r.message,
                    r.payload_hex,
                )
            )
            decoded_any = True
        except Exception as e:
            error_seen = f"decode_crash: {e!r}"
            params = []

        if not decoded_any:
            stats["events_decoded_err"] += 1
            stats["errors"][error_seen or "decode_crash"] += 1
            continue

        # Vérifier le motif réel : si decode_event sort error, iter_params
        # retourne vide — on compte ok vs err séparément.
        # Pour distinguer : refait un check rapide par motif via la liste
        # vide + présence/absence de payload_hex (déjà filtré) + system.
        if not params:
            # Décodage « sans paramètre » : canal inconnu, skip, échec,
            # etc. On rapporte en bloc comme « sans output ». Pas d'erreur
            # fatale — nombre réel compté dans events_decoded_err.
            stats["events_decoded_err"] += 1
            stats["errors"]["no_params"] += 1
            continue

        stats["events_decoded_ok"] += 1

        op, band = _resolve_context(
            sib1_idx,
            str(r.capture_id),
            int(r.seq),
            system,
            r.freq,
            r.pci,
        )

        for path_str, raw in params:
            # Filet final deny-list (devrait être déjà filtré par walk).
            if DENY.search(path_str):
                stats["n_params_denied"] += 1
                continue
            # Conversion 3GPP (optionnelle)
            last_seg = path_str.rsplit("/", 1)[-1]
            conv = convert(last_seg, raw)
            if conv is not None:
                value_converted, unit_converted = conv
            else:
                value_converted, unit_converted = None, None

            # 0.45.0 — Dictionnaire v2 : enrichissement par ligne.
            from app.dict.enrich_v2 import enrich as _enrich_dict_v2
            import json as _json
            e2 = _enrich_dict_v2(path_str, r.message)
            batch.append(
                {
                    "project_id": project_id,
                    "stg_event_id": int(r.id),
                    "system": system,
                    "channel": r.channel,
                    "message": r.message,
                    "path": path_str,
                    "value": _value_to_text(raw),
                    "value_converted": value_converted,
                    "unit_converted": unit_converted,
                    "operator": op,
                    "band": band,
                    "lat": float(r.lat) if r.lat is not None else None,
                    "lon": float(r.lon) if r.lon is not None else None,
                    "param_key":        e2["param_key"],
                    "display_name":     e2["display_name"],
                    "choice_of":        e2["choice_of"],
                    "discriminators":   _json.dumps(e2["discriminators"]) if e2["discriminators"] else None,
                    "origin":           e2["origin"],
                    "is_identifier":    bool(e2["is_identifier"]),
                    "functional_group": e2["functional_group"],
                }
            )
            stats["n_params_queued"] += 1
            if len(batch) >= BATCH_SIZE:
                _flush()

        # (len(batch) décroît à chaque _flush — pas de comptabilité ici,
        # on compte en SQL après le commit final.)
        _ = n_before

    # Flush final
    _flush()

    db.commit()
    # Comptage réel après commit (ON CONFLICT peut avoir avalé des doublons).
    stats["n_params_written"] = int(
        db.execute(
            text("SELECT COUNT(*) FROM param_occurrence WHERE project_id = :pid"),
            {"pid": project_id},
        ).scalar()
        or 0
    )
    stats["errors"] = dict(stats["errors"])
    log.info(
        "populate_param_occurrence project=%s events=%d ok=%d err=%d params=%d denied=%d",
        project_id,
        stats["events_scanned"],
        stats["events_decoded_ok"],
        stats["events_decoded_err"],
        stats["n_params_written"],
        stats["n_params_denied"],
    )
    return stats
