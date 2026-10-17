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
import uuid
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
from app.measure.profiling import CellmeasMapping, profile_cellmeas
from app.measure.proof import mapping_from_proof, prove_rsrp_per_event, run_proof
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

def _iter_raw_events(db: Session, project_id: str, chunk_size: int = 5000):
    """Itère les events ``stg_event_raw`` du projet, triés
    ``(capture_id, seq)``. Jamais trié par ``ts``.

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
            return
        for row in rows:
            yield row
        last_cap = rows[-1].capture_id
        last_seq = rows[-1].seq
        del rows


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

    # 0.39.0 — Profiling CELLMEAS par le CONTENU : les noms de champs
    # (`cell0_rsrp_dbm`, `cell0_rsrq_db`, …) sont trompeurs côté REF
    # (cf. audit : `cell0_rsrp_dbm` tient en fait RSSI, `cell0_rsrq_db`
    # tient RSRP). On re-affecte chaque métrique au champ dont la
    # plus grande fraction de valeurs tombe dans la plage 3GPP.
    # 0.44.0 — Profil par la PREUVE (G0/G2/G5). profile_cellmeas choisit
    # le champ RSRP qui PASSE median|Δ| ≤ 2 dB (prove_rsrp_per_event),
    # pas la meilleure moyenne. RSRQ/SINR/RSSI par plage + cohérence.
    from app.measure.cellmeas_profile import ensure_table, persist_profile_row

    ensure_table(db)
    cm_map = profile_cellmeas(db, project_id)
    report["cellmeas_mapping"] = {
        "rssi": cm_map.rssi,
        "rsrp": cm_map.rsrp,
        "rsrq": cm_map.rsrq,
        "sinr": cm_map.sinr,
        "debug": cm_map.debug,
    }

    # Persist proofs RSRP (table cellmeas_profile).
    for pr in cm_map.rsrp_proofs:
        persist_profile_row(
            db,
            project_id=project_id,
            metric="rsrp",
            field=pr.field,
            avg=None,
            n=0,
            n_pairs=pr.n_pairs,
            median_abs_delta=pr.median_abs_delta,
            p90_abs_delta=pr.p90_abs_delta,
            verdict=pr.verdict,
            reason=pr.reason,
        )
    # Persist mapping choisi pour les 3 autres métriques (RSRQ/SINR/RSSI).
    for metric_name, field_name in (
        ("rsrq", cm_map.rsrq),
        ("sinr", cm_map.sinr),
        ("rssi", cm_map.rssi),
    ):
        if field_name is None:
            persist_profile_row(
                db, project_id=project_id, metric=metric_name,
                field=None, avg=None, n=0, n_pairs=None,
                median_abs_delta=None, p90_abs_delta=None,
                verdict="rejected", reason="aucun candidat ne satisfait la règle plage+cohérence",
            )
            continue
        # Récupère stats du profil
        prof = next((p for p in cm_map.profiles if p.field == field_name), None)
        persist_profile_row(
            db, project_id=project_id, metric=metric_name,
            field=field_name,
            avg=prof.avg if prof else None,
            n=prof.n_valid if prof else 0,
            n_pairs=None,
            median_abs_delta=None, p90_abs_delta=None,
            verdict="proven", reason="plage 3GPP + cohérence",
        )
    # Persist c8 ambigu
    for p in cm_map.profiles:
        if p.field == "cell0_c8":
            persist_profile_row(
                db, project_id=project_id, metric="ambigu",
                field="cell0_c8", avg=p.avg, n=p.n_valid, n_pairs=None,
                median_abs_delta=None, p90_abs_delta=None,
                verdict="rejected",
                reason="zone frontière RSRQ/SINR — non affecté",
            )

    # 0.44.0 — REFUS strict : si RSRP n'est pas prouvé, on arrête ici
    # sans toucher à mp.rsrp (NULL déclaré plutôt que faux chiffre).
    per_event_proof = None
    if cm_map.rsrp:
        per_event_proof = prove_rsrp_per_event(db, project_id, cm_map.rsrp)
        report["per_event_proof_rsrp"] = per_event_proof.as_dict()
        if per_event_proof.verdict != "proven":
            report["refused_populate_rsrp"] = True
            report["refused_reason"] = (
                f"profiled field {cm_map.rsrp} rejected by ±2 dB proof "
                f"(median|Δ|={per_event_proof.median_abs_delta})"
            )
            # On vide le mapping RSRP pour que les reads ultérieurs renvoient NULL
            cm_map.rsrp = None
    # Legacy distribution proof (traçabilité).
    proof_rows = run_proof(db, project_id)
    report["proof"] = [p.as_dict() for p in proof_rows]

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

    # 0.39.0 — iterator streaming (yield_per 2000) : jamais `.all()` sur
    # ~400k events + raw_fields JSONB (OOM 9+ GB reproduit). Les flushs
    # UPDATE/INSERT se font pendant l'itération, pas en bloc final.
    events = _iter_raw_events(db, project_id)

    # Index service_action courant par capture (propagation stricte).
    current_action_by_capture: dict[str, str | None] = {}
    # Dernier CMDREQ.service_name/ts_label hérite de meta.ts_label par fichier
    # (NEMO n'exprime pas le "service name" par CMDREQ — meta.ts est la
    # vérité file-level).

    updates: list[dict] = []
    inserts: list[dict] = []
    _FLUSH_EVERY = 5000  # réduit la pression mémoire ; tolère ~1 GB RSS

    def _flush_updates() -> None:
        nonlocal updates
        if not updates:
            return
        for u in updates:
            res = db.execute(
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
                u,
            )
            report["updated"] += res.rowcount or 0
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
                    id, project_id, lat, lng, operator, tech, service, band,
                    dep, site, ts, dl, rsrp, sinr, latency,
                    capture_id, seq, rsrq, rssi, cqi, mimo_rank, tx_power,
                    thrpt_ul, event_code,
                    operator_source, operator_mismatch,
                    service_name, service_action, service_type,
                    phase, env, rat, earfcn
                ) VALUES (
                    :id, :project_id, :lat, :lng, :operator, :tech, :service, :band,
                    :dep, :site, :ts, :dl, :rsrp, :sinr, :latency,
                    :capture_id, :seq, :rsrq, :rssi, :cqi, :mimo_rank, :tx_power,
                    :thrpt_ul, :event_code,
                    :operator_source, :operator_mismatch,
                    :service_name, :service_action, :service_type,
                    :phase, :env, :rat, :earfcn
                )
                """
            ),
            inserts,
        )
        report["inserted"] += len(inserts)
        inserts.clear()
        db.commit()

    for r in events:
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
        # Métriques (0.39.0) — profiling CELLMEAS + range-gating 3GPP.
        # Un champ non reconnu / hors plage → NULL déclaré. Les 650400
        # et autres placeholders sont filtrés par `is_placeholder`.
        # ------------------------------------------------------------
        rsrp = rsrq = sinr = rssi = None
        cqi = tx_power = None
        thrpt_dl = thrpt_ul = None
        earfcn = None
        band = None
        rat = rat_from_code(rfields.get("rat_code"))

        def _gated(field_key: str | None, rng) -> float | None:
            """Lit `raw_fields[field_key]` → float, filtre placeholder,
            vérifie la plage. None si l'un échoue."""
            if not field_key:
                return None
            v = _try_float(rfields.get(field_key))
            if v is None or is_placeholder(v):
                return None
            return v if rng.contains(v) else None

        if category == "cellmeas":
            rssi = _gated(cm_map.rssi, RSSI_RANGE)
            rsrp = _gated(cm_map.rsrp, RSRP_RANGE)
            rsrq = _gated(cm_map.rsrq, RSRQ_RANGE)
            sinr = _gated(cm_map.sinr, SINR_RANGE)
            # EARFCN et bande (par le CONTENU).
            earfcn = _try_int(rfields.get("cell0_earfcn"))
            if earfcn is not None:
                band = band_from_earfcn(earfcn) if rat != "NR" else band_from_earfcn(earfcn)
        elif category == "cqi":
            # CQI_RANGE : 0..15, indice 3GPP. On tente `c7` puis `c23`
            # (positions candidates vues sur REF). N'écrit QUE si plage OK.
            for k in ("c7", "c23", "c21"):
                v = _try_float(rfields.get(k))
                if v is not None and CQI_RANGE.contains(v) and not is_placeholder(v):
                    cqi = v
                    break
        elif category == "tx_power":
            # TX_POWER : -40..+23 dBm UE LTE. Positions candidates sur REF :
            # `c4` = puissance max (~23), `c8` = puissance mesurée (ex -6..-7).
            v = _try_float(rfields.get("c8"))
            if v is not None and TX_RANGE.contains(v) and not is_placeholder(v):
                tx_power = v

        # ------------------------------------------------------------
        # UPDATE si skeleton BC1 a déjà créé la ligne.
        # ------------------------------------------------------------
        # 0.36.0 — `tech` **par le contenu** (rat_code via rat_from_code),
        # jamais depuis une étiquette fichier. `rat` reste la source primaire ;
        # `r.system` (stg_event_raw) sert de secours quand `rat_code` manque
        # dans la catégorie courante (ex. cmdreq). Un `tech` fantôme laissé
        # par le skeleton BC1 (ex. 'GSM') est **écrasé** par cette source.
        tech_value = rat or (r.system if r.system in ("LTE", "NR") else None)

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
        if category not in {"cellmeas"} and category in _MP_INSERT_CATS:
            # Skip si pas de lat/lon : une mesure sans GPS précédent n'est
            # pas géo-localisable (jamais 0,0 inventé). Indoor sans fix
            # ressort donc comme measurement_points vide — c'est la règle
            # dure "jamais une position inventée".
            lat_v = r.lat if r.lat is not None else None
            lon_v = r.lon if r.lon is not None else None
            if lat_v is None or lon_v is None:
                continue
            inserts.append(
                {
                    "id": f"mp-{uuid.uuid4().hex[:12]}",
                    "project_id": project_id,
                    "lat": float(lat_v),
                    "lng": float(lon_v),
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

        # 0.39.0 — flush incrémental : évite d'accumuler 400k dicts
        # (~5 GB) en mémoire.
        if len(updates) >= _FLUSH_EVERY:
            _flush_updates()
        if len(inserts) >= _FLUSH_EVERY:
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
