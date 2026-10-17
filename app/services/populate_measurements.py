"""Peuple `measurement_points` à partir de `stg_measurement_raw` (0.24.0).

Keystone Phase 2 **skeleton** : on ne peuple QUE l'armature géographique
(capture_id, seq, ts, system, operator, band, lat, lng, event_code) à
partir des events `measurement` + `throughput` captés par le décodeur
1.1.0. Les COLONNES MÉTRIQUES (rsrp, rsrq, sinr, cqi, mimo_rank,
tx_power, thrpt_ul, dl) **restent NULL** tant que Phase 1
(mapping champ→métrique par preuve + validation croisée RRC) n'a pas
été faite. Un champ non prouvé = NULL, jamais 0, jamais inventé.

Attribution opérateur/bande : **réutilise VERBATIM** `_build_sib1_index`
et `_resolve_context` depuis `app.dict.populate` — même source de
vérité que le dictionnaire RRC. Pas de divergence possible.

Idempotent : chaque appel `populate_measurements(db, project_id)`
re-dérive l'ensemble depuis `stg_measurement_raw`, en PURGE les lignes
`measurement_points` dérivées de mesures (identifiées par
`event_code IS NOT NULL AND source rrc_mp = False`) et re-insère.
"""

from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dict.populate import _build_sib1_index, _resolve_context


BATCH_SIZE = 1000


def populate_measurements(db: Session, project_id: str, *, purge: bool = True) -> dict:
    """Retourne un rapport `{inserted, by_event_code, by_operator, by_system}`.

    - `purge=True` : supprime les lignes `measurement_points` déjà dérivées
      de mesures pour ce projet (identifiées par `event_code IS NOT NULL`).
      Les lignes B0 seedées (`event_code IS NULL`) sont PRÉSERVÉES.
    """
    # 1) Construit l'index SIB1 depuis `stg_event` du projet.
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

    # 2) Purge des lignes mesure existantes (préserve seeds B0).
    if purge:
        db.execute(
            text(
                "DELETE FROM measurement_points "
                "WHERE project_id = :pid AND event_code IS NOT NULL"
            ),
            {"pid": project_id},
        )

    # 3) Itère les events mesure. Les colonnes `freq`/`pci` ne sont pas
    #    dans stg_measurement_raw (elles vivraient dans raw_fields —
    #    mapping Phase 1). Donc fallback `last_by_cell` ne fonctionne
    #    pas ici — seul le SIB1 precedent (par capture, system, seq) marche.
    #    C'est acceptable : les SIB1 sont semés assez densément.
    meas_rows = db.execute(
        text(
            """
            SELECT id, capture_id, seq, ts, event_code, system, lat, lon
            FROM stg_measurement_raw
            WHERE project_id = :pid
            ORDER BY capture_id, seq
            """
        ),
        {"pid": project_id},
    ).all()

    inserted = 0
    by_code: dict[str, int] = {}
    by_op: dict[str, int] = {"non attribué": 0}
    by_sys: dict[str, int] = {}
    rows_batch: list[dict] = []

    for r in meas_rows:
        system = (r.system or "").upper() if r.system else None
        operator, band = (None, None)
        if system in {"LTE", "NR"}:
            # Résolution par SIB1 précédent — `freq=None, pci=None` ici
            # car on ne les stocke pas (encore). La résolution tombe sur
            # None si pas de SIB1 avant, ce qui donnera "non attribué".
            operator, band = _resolve_context(
                sib1_idx, str(r.capture_id), int(r.seq), system, None, None,
            )

        # Comptages pour rapport.
        by_code[r.event_code] = by_code.get(r.event_code, 0) + 1
        by_op_key = operator if operator else "non attribué"
        by_op[by_op_key] = by_op.get(by_op_key, 0) + 1
        if system:
            by_sys[system] = by_sys.get(system, 0) + 1

        # 0.47.3 — Règle « jamais une mesure jetée ».
        #
        # Avant 0.47.3, les points sans GPS étaient forgés 0,0 puis
        # skippés en bloc par le filtre `lat not in (0.0, None)`.
        # Résultat : fichiers indoor → measurement_points vide, KPI
        # radio/data perdus. Nouveau comportement :
        #   - lat/lng NULL si le GPS manque (jamais 0,0 inventé).
        #   - geo_source renseigne l'origine ('gps_fix' si position,
        #     NULL si indoor/perte de fix).
        #   - La ligne mp est conservée : les KPI radio comptent.
        has_gps = r.lat is not None and r.lon is not None and not (r.lat == 0.0 and r.lon == 0.0)
        rows_batch.append(
            {
                "id": f"mp-{uuid.uuid4().hex[:12]}",
                "project_id": project_id,
                "lat": float(r.lat) if has_gps else None,
                "lng": float(r.lon) if has_gps else None,
                "geo_source": "gps_fix" if has_gps else None,
                "operator": operator,
                "tech": system,  # LTE / NR / None
                "band": band,
                # service/dep/site : non applicables aux mesures NMF (concepts B0).
                "service": None,
                "dep": None,
                "site": None,
                "ts": r.ts or "",  # ts NOT NULL — vide si absent (jamais inventé)
                "capture_id": str(r.capture_id),
                "seq": int(r.seq),
                "event_code": r.event_code,
                # Toutes les métriques restent NULL — Phase 1 à faire.
                "rsrp": None, "rsrq": None, "rssi": None, "sinr": None,
                "cqi": None, "mimo_rank": None, "tx_power": None,
                "dl": None, "thrpt_ul": None, "latency": None,
            }
        )

    # 0.47.3 — plus de filtre « skip si pas de GPS ». Toutes les mesures
    # entrent en mp (lat/lng NULL pour les indoor).

    # 4) Insert batch.
    inserted = len(rows_batch)
    for i in range(0, inserted, BATCH_SIZE):
        batch = rows_batch[i : i + BATCH_SIZE]
        db.execute(
            text(
                """
                INSERT INTO measurement_points (
                    id, project_id, lat, lng, geo_source,
                    operator, tech, service, band,
                    dep, site, ts, dl, rsrp, sinr, latency,
                    capture_id, seq, rsrq, rssi, cqi, mimo_rank, tx_power,
                    thrpt_ul, event_code
                ) VALUES (
                    :id, :project_id, :lat, :lng, :geo_source,
                    :operator, :tech, :service, :band,
                    :dep, :site, :ts, :dl, :rsrp, :sinr, :latency,
                    :capture_id, :seq, :rsrq, :rssi, :cqi, :mimo_rank, :tx_power,
                    :thrpt_ul, :event_code
                )
                """
            ),
            batch,
        )
    db.commit()

    return {
        "inserted": inserted,
        "by_event_code": by_code,
        "by_operator": by_op,
        "by_system": by_sys,
    }
