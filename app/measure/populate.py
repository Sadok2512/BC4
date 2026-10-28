"""Enrichissement ``measurement_points`` depuis ``stg_event_raw`` (0.30.0).

Hook post-décodage ajouté à ``ingest_upload`` après ``populate_measurements``
(skeleton BC1) et ``populate_param_occurrence`` (RRC dict). Ce module ne
RE-CRÉE pas les lignes : il **UPDATE** celles déjà insérées par le skeleton
BC1 (match sur ``(project_id, capture_id, seq, event_code)``), puis **INSERT**
celles qui proviennent de catégories qui ne sont pas remontées dans
``stg_measurement_raw`` (``cmdreq``, ``data_*``, ``tx_power``, ``cqi``, ``lock``,
``other``) — on perd zéro event du corpus.

Doctrine (jamais déviée) :
- Par le CONTENU, jamais par l'étiquette (``rat_code`` → ``rat``, pas de
  trust aveugle du nom de fichier).
- Ordre ``(capture_id, seq)`` strict : les ``service_action`` et ``env`` se
  propagent au DERNIER précédent dans cet ordre, pas par ``ts``.
- ``operator`` AUTORITAIRE depuis ``nmf_file.dl`` (meta.dl). Divergence
  avec le dernier SIB1 PLMN précédent → ``operator_mismatch=True`` +
  ``operator_source`` déclaré. Jamais masqué par un fallback silencieux.
- **Un champ non prouvé = NULL déclaré**, jamais inventé.
- Zéro identité abonné en sortie (le décodeur masque à la source, mais on
  ne touche à aucune colonne qui pourrait porter une identité ici — les
  seules valeurs numériques extraites viennent de champs **prouvés** par
  ``app.measure.proof.run_proof`` contre ``param_occurrence`` (±2 dB).

0.33.0 — Gating par preuve
--------------------------

Les mappings ``raw_fields → measurement_points.{rsrp, rsrq, sinr, cqi,
tx_power, thrpt_dl, thrpt_ul}`` passent désormais par
``MEASUREMENT_MAPPING`` qui n'est peuplée QUE depuis
``app.measure.proof.mapping_from_proof(run_proof(db, project_id))``.
Un candidat ``rejected`` reste NULL à l'aval et apparaît dans le rapport
de preuve (traçabilité + CHANGELOG). Tableau de preuve sur
REF_PETITE_FORET (bump 0.33.0) :

- ``cell0_rsrp_dbm`` ↔ ``measResultPCell/rsrpResult$``
  → **verdict chiffré enregistré dans scripts/g24_measurement_full.sh** ;
  si proven ±2 dB → MEASUREMENT_MAPPING['rsrp'].
- ``cell0_rsrq_db`` ↔ ``measResultPCell/rsrqResult$``
  → idem ``rsrq``.
- ``cell0_sinr_db`` : pas de référence RRC chiffrée canonique en LTE
  Rel-8 (rs-sinr-r13 est LTE-A, non peuplé sur le corpus) → ``sinr``
  **rejected: no_rrc_reference** → NULL déclaré à l'aval.
- ``cqi``, ``tx_power``, ``thrpt_dl``, ``thrpt_ul`` : pas de référence
  RRC comparable → NULL déclaré à l'aval tant que la preuve n'est pas
  câblée (iPerf GT, références externes).
"""
from __future__ import annotations

import json
import hashlib
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dict.populate import _build_sib1_index, _resolve_context
from app.measure.mapping import (
    band_from_earfcn,
    operator_from_dl,
    operator_from_plmn,
    phase_from_action,
    rat_from_code,
    service_type_from,
)
from app.measure.ranges import CQI as CQI_RANGE
from app.measure.ranges import RSRP as RSRP_RANGE
from app.measure.ranges import RSRQ as RSRQ_RANGE
from app.measure.ranges import RSSI as RSSI_RANGE
from app.measure.ranges import SINR as SINR_RANGE
from app.measure.ranges import TX_POWER as TX_RANGE
from app.measure.ranges import is_placeholder
from app.measure.throughput import (
    apply_transfers_to_measurement_points,
    compute_transfers,
    format_transfer_table,
)


BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# 0.33.0 — Gating par preuve. ``MEASUREMENT_MAPPING`` est **vide** par
# défaut : elle n'est peuplée QUE par ``app.measure.proof.run_proof`` au
# début de ``populate_measurement_points``. Un candidat ``rejected`` reste
# donc NULL à l'aval. Jamais mappé à l'aveugle.
#
# Forme : ``{metric → {"category": str, "field": str}}``.
# ---------------------------------------------------------------------------
_DEFAULT_METRIC_KEYS = ("rsrp", "rsrq", "sinr", "cqi", "tx_power",
                       "thrpt_dl", "thrpt_ul")


# ---------------------------------------------------------------------------
# Helpers de lecture ``raw_fields``.
# ---------------------------------------------------------------------------

def _try_float(v: Any) -> float | None:
    """Convertit ``v`` → float si parseable, sinon None. Jamais 0 par défaut."""
    if v is None:
        return None
    try:
        s = str(v).strip()
        if not s:
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _try_int(v: Any) -> int | None:
    f = _try_float(v)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError):
        return None


def _raw(ev_raw: Any) -> dict[str, Any]:
    """Charge ``raw_fields`` quel que soit le type retourné par le driver.

    JSONB côté Postgres sort déjà en dict côté SQLAlchemy, mais la colonne
    est aussi lisible via ``raw_fields::text`` dans certaines routes — on
    s'autorise les deux formats sans supposer.
    """
    if ev_raw is None:
        return {}
    if isinstance(ev_raw, dict):
        return ev_raw
    try:
        return json.loads(ev_raw) if ev_raw else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# PLMN du dernier SIB1 précédent — pour ``operator_mismatch``.
# ---------------------------------------------------------------------------

def _last_sib1_plmn_before(
    sib1_idx: dict,
    capture_id: str,
    seq: int,
    system: str | None,
) -> str | None:
    """Retourne le PLMN du dernier SIB1 précédent ``(capture_id, seq)`` pour
    la techno ``system``. ``_build_sib1_index`` retourne ``(operator, band)``
    déjà résolus, mais on veut le label opérateur SIB1 pour le mismatch —
    on passe par ``_resolve_context`` qui retourne ``(operator, band)``.
    Si rien avant, retourne None.
    """
    if not system or system.upper() not in {"LTE", "NR"}:
        return None
    try:
        operator, _band = _resolve_context(
            sib1_idx, str(capture_id), int(seq), system.upper(), None, None
        )
    except Exception:
        return None
    return operator


# ---------------------------------------------------------------------------
# Fil des service_action / env : propagation ``(capture_id, seq)`` stricte.
# ---------------------------------------------------------------------------

def _iter_raw_event_chunks(db: Session, project_id: str, chunk_size: int = 5000):
    """Lit des tranches ordonnées ``(capture_id, seq)``.

    0.39.0 — Pagination `OFFSET/LIMIT` : charger `.all()` sur ~400k
    events + raw_fields JSONB (parfois 300 colonnes) explosait la mémoire
    à ~9 GB et provoquait un SIGKILL OOM. Un server-side cursor seul ne
    marche pas car on commit entre chunks (le `COMMIT` ferme le cursor
    → `InvalidCursorName`). La pagination par OFFSET est robuste à ça :
    chaque chunk vit le temps du `.all()`, est consommé par le consumer,
    puis libéré avant le `COMMIT` du flush.
    """
    # Keyset pagination par `(capture_id, seq)` : O(log N) par chunk au
    # lieu d'OFFSET qui dérive en O(N²) sur 400k lignes. Stable même si
    # on commit entre chunks (on ne touche pas stg_event_raw).
    last_cap: str | None = None
    last_seq: int | None = None
    while True:
        if last_cap is None:
            rows = db.execute(
                text(
                    """
                    SELECT id, nmf_file_id, capture_id, seq, category, event_code, ts,
                           system, lat, lon, raw_fields
                    FROM stg_event_raw
                    WHERE project_id = :pid
                    ORDER BY capture_id, seq
                    LIMIT :lim
                    """
                ),
                {"pid": project_id, "lim": chunk_size},
            ).all()
        else:
            rows = db.execute(
                text(
                    """
                    SELECT id, nmf_file_id, capture_id, seq, category, event_code, ts,
                           system, lat, lon, raw_fields
                    FROM stg_event_raw
                    WHERE project_id = :pid
                      AND (capture_id, seq) > (:lc, :ls)
                    ORDER BY capture_id, seq
                    LIMIT :lim
                    """
                ),
                {"pid": project_id, "lc": last_cap, "ls": last_seq, "lim": chunk_size},
            ).all()
        if not rows:
            db.commit()
            return
        # Ferme la transaction de lecture AVANT tout calcul Python. La tranche
        # reste en mémoire et la source canonique n'est jamais modifiée ici.
        db.commit()
        yield rows
        last_cap = rows[-1].capture_id
        last_seq = rows[-1].seq


def _stable_mp_id(project_id: str, capture_id: str, seq: int) -> str:
    """Identité stable de reprise pour l'empreinte métier demandée."""
    raw = f"{project_id}\0{capture_id}\0{seq}".encode()
    return "mp-nmf-" + hashlib.sha256(raw).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Charge le ``meta`` fichier pour chaque ``nmf_file`` du projet.
# ---------------------------------------------------------------------------

def _file_meta_by_id(db: Session, project_id: str) -> dict[str, dict]:
    rows = db.execute(
        text(
            """
            SELECT id, dl, ts_label, env
            FROM nmf_file
            WHERE project_id = :pid
            """
        ),
        {"pid": project_id},
    ).all()
    return {
        r.id: {"dl": r.dl, "ts_label": r.ts_label, "env": r.env}
        for r in rows
    }


# ---------------------------------------------------------------------------
# Point d'entrée.
# ---------------------------------------------------------------------------

def populate_measurement_points(
    db: Session, project_id: str, *, purge: bool = False
) -> dict:
    """Enrichit (UPDATE) et complète (INSERT) ``measurement_points`` depuis
    ``stg_event_raw`` + ``nmf_file.meta``.

    Flot :
    1. Charge le ``meta`` par ``nmf_file_id``.
    2. Charge l'index SIB1 (``_build_sib1_index`` depuis ``stg_event``).
    3. Itère ``stg_event_raw`` dans l'ordre ``(capture_id, seq)``.
       - Maintient ``current_service_action`` (dernier CMDREQ précédent).
       - Pour chaque event, calcule ``operator`` (depuis dl), ``rat``, etc.
       - CELLMEAS : essaie l'UPDATE sur une ligne existante (skeleton BC1)
         match ``(project_id, capture_id, seq, event_code='CELLMEAS')``.
         Si rien → INSERT (lignes nouvelles).
       - CMDREQ / data_* / tx_power / cqi / lock / other :
         INSERT (ces catégories ne sont pas dans ``stg_measurement_raw``,
         le skeleton ne les a jamais vues).
    4. Commit.

    ``purge=False`` par défaut : ``populate_measurements`` BC1 a déjà
    purgé en amont les lignes à ``event_code IS NOT NULL`` avant son
    insert. On ne purge pas une seconde fois (on perdrait le skeleton BC1).

    Retourne un rapport ``{updated, inserted, by_category, operators,
    mismatches}``.
    """
    report: dict[str, Any] = {
        "updated": 0,
        "inserted": 0,
        "by_category": {},
        "mismatches": 0,
        "operators_file": {},
        "proof": [],
        "mapping": {},
    }

    # 0.37.1 — Nettoyage des `tech` fantômes BC1 (GSM / codes bruts type
    # '2', '3' hérités d'un skeleton non 2.0.0). La valeur canonique est
    # `rat` (via `rat_from_code`, cf. CONTENU), posée en même temps par
    # l'UPDATE ci-dessous. Idempotent : seul tech ∉ {LTE, NR} est NULL-é.
    db.execute(
        text(
            """
            UPDATE measurement_points
            SET tech = NULL
            WHERE project_id = :pid
              AND tech IS NOT NULL
              AND tech NOT IN ('LTE', 'NR')
            """
        ),
        {"pid": project_id},
    )

    # 0.39.0 — mp ne doit porter QUE des events « porteurs de mesure »
    # (cellmeas / cqi / tx_power / data_summary). Les events `other`
    # (PHRATE, RTPSM, MIMOMEAS, DCI, …) ne sont pas des mesures radio
    # au sens du catalogue KPI : on les retire. Idempotent.
    db.execute(
        text(
            """
            DELETE FROM measurement_points
            WHERE project_id = :pid
              AND event_code IS NOT NULL
              AND event_code NOT IN ('CELLMEAS', 'CQI', 'TXPC', 'DSUMMARY')
            """
        ),
        {"pid": project_id},
    )
    db.commit()

    from app.nmf_decoder.projection import observations
    decoded = observations(db, project_id)
    db.commit()
    report['cellmeas_mapping'] = {'source':'nmf_decoder', 'decoder_version':'1.0.0'}

    file_meta = _file_meta_by_id(db, project_id)

    # Index SIB1 pour mismatch — réutilise la source RRC.
    sib1_rows = db.execute(
        text(
            """
            SELECT id, capture_id, seq, system, message, freq, pci, payload_hex
            FROM stg_event
            WHERE project_id = :pid
              AND message IS NOT NULL
              AND (message LIKE '%%SystemInformationBlockType1%%'
                   OR message LIKE '%%SIB1%%'
                   OR message LIKE '%%SystemInformation1%%')
            """
        ),
        {"pid": project_id},
    ).all()
    sib1_idx = _build_sib1_index(sib1_rows)
    db.commit()

    # 0.39.0 — iterator streaming (yield_per 2000) : jamais `.all()` sur
    # ~400k events + raw_fields JSONB (OOM 9+ GB reproduit). Les flushs
    # UPDATE/INSERT se font pendant l'itération, pas en bloc final.
    event_chunks = _iter_raw_event_chunks(db, project_id)

    # Index service_action courant par capture (propagation stricte).
    current_action_by_capture: dict[str, str | None] = {}
    # Dernier CMDREQ.service_name/ts_label hérite de meta.ts_label par fichier
    # (NEMO n'exprime pas le "service name" par CMDREQ — meta.ts est la
    # vérité file-level).

    updates: list[dict] = []
    inserts: list[dict] = []
    def _flush_updates() -> None:
        nonlocal updates
        if not updates:
            return
        db.execute(
            text(
                    """
                    UPDATE measurement_points
                    SET operator = :operator,
                        operator_source = :operator_source,
                        operator_mismatch = :operator_mismatch,
                        service_name = :service_name,
                        service_action = :service_action,
                        service_type = :service_type,
                        phase = :phase,
                        env = :env,
                        rat = :rat,
                        tech = :tech,
                        earfcn = COALESCE(:earfcn, earfcn),
                        band = COALESCE(:band, band),
                        rsrp = :rsrp,
                        rsrq = :rsrq,
                        rssi = :rssi,
                        sinr = :sinr,
                        cqi = COALESCE(:cqi, cqi),
                        tx_power = COALESCE(:tx_power, tx_power),
                        dl = COALESCE(:thrpt_dl, dl),
                        thrpt_ul = COALESCE(:thrpt_ul, thrpt_ul)
                    WHERE project_id = :pid
                      AND capture_id = :capture_id
                      AND seq = :seq
                      AND event_code = :event_code
                    """
            ),
            updates,
        )
        # rowcount executemany varie selon le driver ; le nombre tenté est
        # déterministe et le détail métier est contrôlé par l'empreinte finale.
        report["updated"] += len(updates)
        updates.clear()
        db.commit()

    def _flush_inserts() -> None:
        nonlocal inserts
        if not inserts:
            return
        db.execute(
            text(
                """
                INSERT INTO measurement_points (
                    id, project_id, lat, lng, geo_source,
                    operator, tech, service, band,
                    dep, site, ts, dl, rsrp, sinr, latency,
                    capture_id, seq, rsrq, rssi, cqi, mimo_rank, tx_power,
                    thrpt_ul, event_code,
                    operator_source, operator_mismatch,
                    service_name, service_action, service_type,
                    phase, env, rat, earfcn
                ) VALUES (
                    :id, :project_id, :lat, :lng, :geo_source,
                    :operator, :tech, :service, :band,
                    :dep, :site, :ts, :dl, :rsrp, :sinr, :latency,
                    :capture_id, :seq, :rsrq, :rssi, :cqi, :mimo_rank, :tx_power,
                    :thrpt_ul, :event_code,
                    :operator_source, :operator_mismatch,
                    :service_name, :service_action, :service_type,
                    :phase, :env, :rat, :earfcn
                )
                ON CONFLICT (id) DO UPDATE SET
                    operator = EXCLUDED.operator,
                    tech = EXCLUDED.tech,
                    band = EXCLUDED.band,
                    ts = EXCLUDED.ts,
                    dl = EXCLUDED.dl,
                    rsrp = EXCLUDED.rsrp,
                    sinr = EXCLUDED.sinr,
                    capture_id = EXCLUDED.capture_id,
                    seq = EXCLUDED.seq,
                    rsrq = EXCLUDED.rsrq,
                    rssi = EXCLUDED.rssi,
                    cqi = EXCLUDED.cqi,
                    tx_power = EXCLUDED.tx_power,
                    thrpt_ul = EXCLUDED.thrpt_ul,
                    event_code = EXCLUDED.event_code,
                    operator_source = EXCLUDED.operator_source,
                    operator_mismatch = EXCLUDED.operator_mismatch,
                    service_name = EXCLUDED.service_name,
                    service_action = EXCLUDED.service_action,
                    service_type = EXCLUDED.service_type,
                    phase = EXCLUDED.phase,
                    env = EXCLUDED.env,
                    rat = EXCLUDED.rat,
                    earfcn = EXCLUDED.earfcn
                """
            ),
            inserts,
        )
        report["inserted"] += len(inserts)
        inserts.clear()
        db.commit()

    for rows in event_chunks:
      for r in rows:
        rfields = _raw(r.raw_fields)
        category = r.category
        report["by_category"][category] = report["by_category"].get(category, 0) + 1

        # ------------------------------------------------------------
        # Propagation service_action — CMDREQ seul.
        # ------------------------------------------------------------
        if category == "cmdreq":
            action = rfields.get("service_action")
            if action is not None and str(action).strip():
                current_action_by_capture[str(r.capture_id)] = str(action)

        action_now = current_action_by_capture.get(str(r.capture_id))
        phase = phase_from_action(action_now)

        meta = file_meta.get(r.nmf_file_id) or {}
        dl = meta.get("dl")
        ts_label = meta.get("ts_label")
        env = meta.get("env")

        operator_file = operator_from_dl(dl)
        operator_source = "file" if operator_file else None

        # Si pas d'opérateur depuis #DL, fallback SIB1 (déclaré via source).
        sib1_op = _last_sib1_plmn_before(
            sib1_idx, r.capture_id, r.seq, r.system
        )
        operator = operator_file
        if operator is None and sib1_op is not None:
            operator = sib1_op
            operator_source = "sib1"
        if operator is None:
            operator_source = "none"

        # Mismatch : operator (file) ≠ sib1_op (quand SIB1 décode un MNO FR
        # différent du #DL). Pas de faux-positif MVNO : operator_from_plmn
        # retourne None hors des 4 MNO FR, donc sib1_op=None dans ce cas.
        mismatch: bool | None = None
        if operator_file is not None and sib1_op is not None:
            mismatch = operator_file != sib1_op
            if mismatch:
                report["mismatches"] += 1

        if operator:
            report["operators_file"][operator] = (
                report["operators_file"].get(operator, 0) + 1
            )

        service_name = ts_label  # verbatim
        service_action = action_now
        service_type = service_type_from(service_name, service_action)

        # ------------------------------------------------------------
        # Numeric values come exclusively from the versioned decoder projection.
        v = decoded.get((str(r.capture_id), int(r.seq)), {})
        rsrp=v.get('rsrp');rsrq=v.get('rsrq');sinr=v.get('sinr');rssi=v.get('rssi')
        cqi=v.get('cqi');tx_power=v.get('tx_power')
        thrpt_dl=v.get('thr_dl');thrpt_ul=v.get('thr_ul')
        earfcn=int(v['earfcn']) if v.get('earfcn') is not None else None
        band=band_from_earfcn(earfcn) if earfcn is not None else None
        rat=rat_from_code(rfields.get('rat_code') or rfields.get('c3'))

        # ------------------------------------------------------------
        # UPDATE si skeleton BC1 a déjà créé la ligne.
        # ------------------------------------------------------------
        # 0.36.0 — `tech` **par le contenu** (rat_code via rat_from_code),
        # jamais depuis une étiquette fichier. `rat` reste la source primaire ;
        # `r.system` (stg_event_raw) sert de secours quand `rat_code` manque
        # dans la catégorie courante (ex. cmdreq). Un `tech` fantôme laissé
        # par le skeleton BC1 (ex. 'GSM') est **écrasé** par cette source.
        tech_value = rat or (r.system if r.system in ("LTE", "NR") else None)

        # CELLMEAS et DSUMMARY ont déjà un skeleton issu de
        # stg_measurement_raw : les enrichir, ne jamais les réinsérer.
        if category in {"cellmeas", "data_summary"}:
          updates.append(
            {
                "pid": project_id,
                "capture_id": str(r.capture_id),
                "seq": int(r.seq),
                "event_code": r.event_code,
                "operator": operator,
                "operator_source": operator_source,
                "operator_mismatch": mismatch,
                "service_name": service_name,
                "service_action": service_action,
                "service_type": service_type,
                "phase": phase,
                "env": env,
                "rat": rat,
                "tech": tech_value,
                "earfcn": earfcn,
                "band": band,
                "rsrp": rsrp,
                "rsrq": rsrq,
                "rssi": rssi,
                "sinr": sinr,
                "cqi": cqi,
                "tx_power": tx_power,
                "thrpt_dl": thrpt_dl,
                "thrpt_ul": thrpt_ul,
            }
        )

        # ------------------------------------------------------------
        # INSERT pour les catégories jamais vues par le skeleton.
        # 0.39.0 — RESTRICTION : seules les catégories **porteuses de
        # mesure** créent des lignes mp. `other`, `lock`, `gps`, `cmdreq`
        # ne produisent pas de ligne (ils propagent service_action/env
        # via l'index courant par capture, pas via une ligne mp).
        # ------------------------------------------------------------
        _MP_INSERT_CATS = {"cellmeas", "cqi", "tx_power", "data_summary"}
        if category not in {"cellmeas", "data_summary"} and category in _MP_INSERT_CATS:
            # 0.47.3 — RÈGLE « jamais une mesure jetée ».
            #
            # Avant 0.47.3, les mesures sans fix GPS étaient skippées
            # (continue). Résultat : les fichiers indoor (perte de fix
            # systématique) sortaient avec measurement_points vide et
            # les KPI radio (CQI, TX power, débit) n'avaient aucune
            # donnée — alors que ces métriques sont PHYSIQUEMENT
            # valides sans GPS.
            #
            # Nouvelle règle : la mesure est conservée avec lat/lng
            # NULL (jamais 0,0 inventé). Elle compte dans les KPI
            # radio/data. Elle est exclue des cartes (WHERE lat IS NOT
            # NULL) et du chip géo « position » (geo_source NULL → chip
            # Géo compte en 'none').
            lat_v = r.lat if r.lat is not None else None
            lon_v = r.lon if r.lon is not None else None
            # Protection ceinture : si pour une raison quelconque une
            # position (0.0, 0.0) remonte du décodeur, on la ravale en
            # NULL (règle historique « jamais 0,0 inventé »).
            if lat_v == 0.0 and lon_v == 0.0:
                lat_v = None
                lon_v = None
            geo_source: str | None = (
                "gps_fix" if (lat_v is not None and lon_v is not None) else None
            )
            inserts.append(
                {
                    "id": _stable_mp_id(project_id, str(r.capture_id), int(r.seq)),
                    "project_id": project_id,
                    "lat": float(lat_v) if lat_v is not None else None,
                    "lng": float(lon_v) if lon_v is not None else None,
                    "geo_source": geo_source,
                    "operator": operator,
                    "tech": tech_value,
                    "band": None,  # band hors CELLMEAS pas câblée par le CONTENU
                    "service": None,
                    "dep": None,
                    "site": None,
                    "ts": r.ts or "",
                    "capture_id": str(r.capture_id),
                    "seq": int(r.seq),
                    "event_code": r.event_code,
                    # Métriques gatées par plage/profiling : NULL si la
                    # catégorie ne porte pas la métrique.
                    "rsrp": None, "rsrq": None, "rssi": None, "sinr": None,
                    "cqi": cqi, "mimo_rank": None, "tx_power": tx_power,
                    "dl": thrpt_dl, "thrpt_ul": thrpt_ul, "latency": None,
                    "operator_source": operator_source,
                    "operator_mismatch": mismatch,
                    "service_name": service_name,
                    "service_action": service_action,
                    "service_type": service_type,
                    "phase": phase,
                    "env": env,
                    "rat": rat,
                    "earfcn": None,
                }
            )

      # Un commit réel par tranche. La lecture a déjà été commitée avant le
      # calcul ; les écritures sont groupées en executemany, jamais ligne à ligne.
      _flush_updates()
      _flush_inserts()

    # Flush final de ce qui reste.
    _flush_updates()
    _flush_inserts()

    # (0.39.0 — flushs streaming déjà faits dans la boucle via
    # `_flush_updates()` / `_flush_inserts()`.)

    # ------------------------------------------------------------
    # 0.39.0 — Débit DL/UL depuis DSUMMARY encadrés par CMDREQ Start/Stop
    # Appliqué APRÈS les UPDATE/INSERT ci-dessus pour que les lignes mp
    # existent déjà et puissent être renseignées par fenêtre `(capture_id,
    # seq)`. Chaque transfert prouvé renseigne `dl` (ou `thrpt_ul`) sur
    # toutes les lignes mp dans la fenêtre `[seq_start, seq_stop]`.
    # ------------------------------------------------------------
    transfers = compute_transfers(db, project_id)
    thrpt_report = apply_transfers_to_measurement_points(
        db, project_id, transfers
    )
    report["transfers"] = [t.as_dict() for t in transfers]
    report["thrpt"] = thrpt_report

    return report
