"""Database adapter for the capture-local procedure engine."""

from __future__ import annotations

from bisect import bisect_right
from decimal import Decimal, InvalidOperation
import json
from threading import RLock
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .engine import EvidenceEvent, Procedure, reconstruct_procedures


SUPPORTED_MARKERS = (
    "RACHI",
    "HOA",
    "HOS",
    "HOI",
    "PBA",
    "PBC",
    "PBD",
    "PBF",
    "SIPREGA",
    "SIPREGC",
    "SIPREGD",
)

SUPPORTED_MESSAGES = (
    "RRCConnectionRequest",
    "RRCConnectionSetupComplete",
    "RRCConnectionReject",
    "RRCSetupRequest",
    "RRCSetupComplete",
    "RRCReject",
    "RRCConnectionReestablishmentRequest",
    "RRCConnectionReestablishmentComplete",
    "RRCConnectionReestablishmentReject",
    "RRCReestablishmentRequest",
    "RRCReestablishmentComplete",
    "RRCReestablishmentReject",
    "ATTACH_REQUEST",
    "ATTACH_COMPLETE",
    "ATTACH_REJECT",
    "REGISTRATION_REQUEST",
    "REGISTRATION_ACCEPT",
    "REGISTRATION_COMPLETE",
    "REGISTRATION_REJECT",
    "SCGFailureInformationNR",
    "INVITE",
    "CANCEL",
    "408 Request Timeout",
    "480 Temporarily Unavailable",
    "486 Busy Here",
    "500 Server Internal Error",
    "503 Service Unavailable",
)

# Procedure reconstruction is deterministic for a decoded capture. KPI panels
# request several leaves concurrently, so rebuilding the same evidence chain
# once per leaf would multiply the SQL and CPU cost. The key includes the
# capture's decode stamp and record count; a re-import/deep decode naturally
# creates a new entry. Cache remains process-local, bounded and contains no raw
# payload beyond the already-anonymised Procedure rows.
_CACHE_LOCK = RLock()
_PROCEDURE_CACHE: dict[tuple[Any, ...], tuple[Procedure, ...]] = {}
_CACHE_LIMIT = 128


def _rows(db: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(text(sql), params).mappings()]


def _seconds(value: str | None) -> Decimal | None:
    try:
        hour, minute, second = value.split(":")
        return Decimal(hour) * 3600 + Decimal(minute) * 60 + Decimal(second)
    except (AttributeError, ValueError, InvalidOperation):
        return None


def _origin_seconds(db: Session, project_id: str, capture_id: str) -> Decimal:
    value = db.execute(
        text(
            """SELECT ts FROM (
                 (SELECT seq,ts FROM stg_event_raw
                  WHERE project_id=:project_id AND capture_id=:capture_id
                  ORDER BY project_id,capture_id,seq LIMIT 1)
                 UNION ALL
                 (SELECT seq,ts FROM stg_event
                  WHERE project_id=:project_id AND capture_id=:capture_id
                  ORDER BY project_id,capture_id,seq LIMIT 1)
               ) origins ORDER BY seq LIMIT 1"""
        ),
        {"project_id": project_id, "capture_id": capture_id},
    ).scalar_one_or_none()
    origin = _seconds(value)
    if origin is None:
        raise HTTPException(409, {"code": "CAPTURE_CLOCK_INVALID", "message": "Capture has no valid timestamp."})
    return origin


def _relative(value: str | None, origin: Decimal) -> float | None:
    seconds = _seconds(value)
    if seconds is None or seconds < origin:
        return None
    return float(seconds - origin)


def _capture_exists(db: Session, project_id: str, capture_id: str) -> None:
    exists = db.execute(
        text(
            """SELECT 1 FROM nmf_capture
               WHERE project_id=:project_id AND capture_id=:capture_id"""
        ),
        {"project_id": project_id, "capture_id": capture_id},
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(404, {"code": "CAPTURE_NOT_FOUND", "message": "Capture not found in project."})


def _capture_stamp(db: Session, project_id: str, capture_id: str) -> tuple[Any, ...]:
    row = db.execute(
        text(
            """SELECT decoder_version,schema_version,decoded_at,deep_decoded_at,n_records
               FROM nmf_capture
               WHERE project_id=:project_id AND capture_id=:capture_id"""
        ),
        {"project_id": project_id, "capture_id": capture_id},
    ).one_or_none()
    if row is None:
        raise HTTPException(404, {"code": "CAPTURE_NOT_FOUND", "message": "Capture not found in project."})
    return (project_id, capture_id, *row)


def _engine_version(stamp: tuple[Any, ...]) -> str:
    values = [value.isoformat() if hasattr(value, "isoformat") else str(value) for value in stamp[2:]]
    # The GPS projection is part of derived procedure data. Changing this
    # generation tag invalidates v1 rows that legitimately had null geometry.
    return "procedure-v1-gps|" + "|".join(values)


def _stored(db: Session, project_id: str, capture_id: str, engine_version: str) -> list[Procedure]:
    rows = _rows(
        db,
        """SELECT id,project_id,capture_id,ue_key,session_key,technology,type,
                  seq_start,seq_end,start_time,end_time,duration_ms,
                  source_pci,source_arfcn,target_pci,target_arfcn,bearer_id,ebi,qci,qfi,five_qi,s_nssai,
                  result,failure_cause,evidence_level,source_event_ids,latitude,longitude,gps_seq
           FROM signaling_procedure
           WHERE project_id=:project_id AND capture_id=:capture_id
             AND engine_version=:engine_version
           ORDER BY project_id,capture_id,seq_start,type,id""",
        {"project_id": project_id, "capture_id": capture_id, "engine_version": engine_version},
    )
    return [
        Procedure(
            procedure_id=row["id"],
            project_id=row["project_id"],
            capture_id=row["capture_id"],
            ue_key=row["ue_key"],
            session_key=row["session_key"],
            rat=row["technology"],
            procedure_type=row["type"],
            start_seq=row["seq_start"],
            end_seq=row["seq_end"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration_ms=row["duration_ms"],
            source_pci=row["source_pci"],
            source_arfcn=row["source_arfcn"],
            target_pci=row["target_pci"],
            target_arfcn=row["target_arfcn"],
            bearer_id=row["bearer_id"],
            ebi=row["ebi"],
            qci=row["qci"],
            qfi=row["qfi"],
            five_qi=row["five_qi"],
            s_nssai=row["s_nssai"],
            result=row["result"],
            failure_cause=row["failure_cause"],
            evidence_level=row["evidence_level"],
            source_event_ids=tuple(row["source_event_ids"] or []),
            latitude=row["latitude"],
            longitude=row["longitude"],
            gps_seq=row["gps_seq"],
        )
        for row in rows
    ]


def _persist(
    db: Session,
    project_id: str,
    capture_id: str,
    engine_version: str,
    procedures: tuple[Procedure, ...],
) -> None:
    db.execute(
        text(
            """DELETE FROM signaling_procedure
               WHERE project_id=:project_id AND capture_id=:capture_id
                 AND engine_version LIKE 'procedure-v1|%'"""
        ),
        {"project_id": project_id, "capture_id": capture_id},
    )
    if procedures:
        db.execute(
            text(
                """INSERT INTO signaling_procedure(
                     id,project_id,capture_id,type,technology,seq_start,seq_end,duration_ms,outcome,cause,boundary_seqs,
                     ue_key,session_key,start_time,end_time,source_pci,source_arfcn,target_pci,target_arfcn,
                     bearer_id,ebi,qci,qfi,five_qi,s_nssai,result,failure_cause,evidence_level,
                     source_event_ids,latitude,longitude,gps_seq,engine_version)
                   VALUES(
                     :procedure_id,:project_id,:capture_id,:procedure_type,:rat,:start_seq,:end_seq,:duration_ms,
                     :outcome,:failure_cause,:boundary_seqs,:ue_key,:session_key,:start_time,:end_time,
                     :source_pci,:source_arfcn,:target_pci,:target_arfcn,:bearer_id,:ebi,:qci,:qfi,:five_qi,:s_nssai,
                     :result,:failure_cause,:evidence_level,CAST(:source_event_ids AS jsonb),:latitude,:longitude,
                     :gps_seq,:engine_version)"""
            ),
            [
                {
                    **procedure.as_dict(),
                    "outcome": (
                        "ok"
                        if procedure.result == "SUCCESS"
                        else "incomplete"
                        if procedure.result in {"ATTEMPT", "UNKNOWN"}
                        else "fail"
                    ),
                    "boundary_seqs": list(
                        dict.fromkeys(
                            [
                                procedure.start_seq,
                                *([procedure.end_seq] if procedure.end_seq is not None else []),
                            ]
                        )
                    ),
                    "source_event_ids": json.dumps(list(procedure.source_event_ids)),
                    "engine_version": engine_version,
                }
                for procedure in procedures
            ],
        )
    db.commit()


def _gps_index(db: Session, project_id: str, capture_id: str) -> tuple[list[int], list[dict[str, Any]]]:
    points = _rows(
        db,
        """SELECT seq,lat,lon AS longitude FROM stg_event_raw
           WHERE project_id=:project_id AND capture_id=:capture_id
             AND event_code='GPS' AND lat BETWEEN -90 AND 90
             AND lon BETWEEN -180 AND 180 AND NOT (lat=0 AND lon=0)
           ORDER BY project_id,capture_id,seq""",
        {"project_id": project_id, "capture_id": capture_id},
    )
    return [int(point["seq"]) for point in points], points


def _position(sequences: list[int], points: list[dict[str, Any]], seq: int) -> dict[str, Any]:
    index = bisect_right(sequences, seq) - 1
    if index < 0:
        return {}
    point = points[index]
    return {
        "latitude": float(point["lat"]),
        "longitude": float(point["longitude"]),
        "gps_seq": int(point["seq"]),
    }


def load_events(db: Session, project_id: str, capture_id: str) -> list[EvidenceEvent]:
    _capture_exists(db, project_id, capture_id)
    origin = _origin_seconds(db, project_id, capture_id)
    gps_sequences, gps_points = _gps_index(db, project_id, capture_id)

    staged = _rows(
        db,
        """SELECT s.id,s.seq,s.event_code,s.system,s.message,s.ts,
                  COALESCE(
                    jsonb_object_agg(p.path,COALESCE(p.value_converted,p.value))
                    FILTER (WHERE p.id IS NOT NULL), '{}'::jsonb
                  ) AS attrs
           FROM stg_event s
           LEFT JOIN param_occurrence p
             ON p.project_id=s.project_id AND p.stg_event_id=s.id
           WHERE s.project_id=:project_id AND s.capture_id=:capture_id
             AND s.event_code IN ('RRCSM','L3SM','SIPSM')
             AND s.message=ANY(:messages)
           GROUP BY s.id,s.seq,s.event_code,s.system,s.message,s.ts
           ORDER BY s.project_id,s.capture_id,s.seq""",
        {"project_id": project_id, "capture_id": capture_id, "messages": list(SUPPORTED_MESSAGES)},
    )
    events = [
        EvidenceEvent(
            seq=int(row["seq"]),
            code=str(row["event_code"]),
            source_id=f"stg_event:{row['id']}",
            rat=row["system"],
            message=row["message"],
            time=row["ts"],
            t_rel_s=_relative(row["ts"], origin),
            attrs={
                **dict(row["attrs"] or {}),
                # Use the capture's last published GPS fix at or before the
                # message sequence. This is the same real-position rule used
                # for marker records; no interpolation or inferred location.
                **_position(gps_sequences, gps_points, int(row["seq"])),
            },
        )
        for row in staged
    ]

    markers = _rows(
        db,
        """SELECT r.id AS raw_id,r.system AS raw_system,d.seq,d.event_code,d.system AS system_code,
                  d.ts,d.t_rel_s,d.rra_est_cause,d.rrd_rrc_rel_status,d.rrd_rrc_rel_cause,
                  d.rrf_rrc_rej_status,d.rrre_re_est_status,d.rrre_re_est_cause,
                  d.rachi_rach_result,d.rachi_rach_reason,d.rachi_preambles_failures,
                  d.hoa_ch_number,d.hoa_pci,d.hoa_att_ch,d.hoa_att_pci,d.hoa_hoa_type,
                  d.pba_pb_type,d.pbc_pb_id,d.pbc_linked_pb_id,d.pbc_pb_qci,
                  d.pbd_esm_cause,d.pbf_esm_cause
           FROM nmf_event_deep d
           JOIN stg_event_raw r ON r.project_id=d.project_id
             AND r.capture_id=d.capture_id AND r.seq=d.seq AND r.event_code=d.event_code
           WHERE d.project_id=:project_id AND d.capture_id=:capture_id
             AND d.event_code=ANY(:markers)
           ORDER BY d.project_id,d.capture_id,d.seq""",
        {"project_id": project_id, "capture_id": capture_id, "markers": list(SUPPORTED_MARKERS)},
    )
    for row in markers:
        attrs = {
            "system_code": row["system_code"],
            "establishment_cause": row["rra_est_cause"],
            "release_status": row["rrd_rrc_rel_status"],
            "release_cause": row["rrd_rrc_rel_cause"],
            "reject_status": row["rrf_rrc_rej_status"],
            "reestablishment_status": row["rrre_re_est_status"],
            "reestablishment_cause": row["rrre_re_est_cause"],
            "rach_result": row["rachi_rach_result"],
            "rach_reason": row["rachi_rach_reason"],
            "rach_preamble_failures": row["rachi_preambles_failures"],
            "source_arfcn": row["hoa_ch_number"],
            "source_pci": row["hoa_pci"],
            "target_arfcn": row["hoa_att_ch"],
            "target_pci": row["hoa_att_pci"],
            "handover_type": row["hoa_hoa_type"],
            "packet_bearer_type": row["pba_pb_type"],
            "bearer_id": row["pbc_pb_id"],
            "linked_bearer_id": row["pbc_linked_pb_id"],
            "qci": row["pbc_pb_qci"],
            "esm_cause": row["pbd_esm_cause"] if row["event_code"] == "PBD" else row["pbf_esm_cause"],
            **_position(gps_sequences, gps_points, int(row["seq"])),
        }
        events.append(
            EvidenceEvent(
                seq=int(row["seq"]),
                code=str(row["event_code"]),
                source_id=f"stg_event_raw:{row['raw_id']}",
                rat=row["raw_system"],
                time=row["ts"],
                t_rel_s=float(row["t_rel_s"]) if row["t_rel_s"] is not None else _relative(row["ts"], origin),
                attrs=attrs,
            )
        )

    pairs = _rows(
        db,
        """SELECT seq_start,seq_end,seq_hoi,outcome,cause,duration_nemo_ms
           FROM nmf_event_pair
           WHERE project_id=:project_id AND capture_id=:capture_id AND type='ho'
           ORDER BY project_id,capture_id,seq_start""",
        {"project_id": project_id, "capture_id": capture_id},
    )
    for pair in pairs:
        events.append(
            EvidenceEvent(
                seq=int(pair["seq_start"]),
                code="NMF_PAIR_HO",
                source_id=f"nmf_event_pair:ho:{pair['seq_start']}",
                rat="LTE",
                t_rel_s=None,
                attrs=dict(pair),
            )
        )
    return sorted(events, key=lambda event: (event.seq, event.code, event.source_id))


def procedures_for_capture(db: Session, project_id: str, capture_id: str) -> list[Procedure]:
    stamp = _capture_stamp(db, project_id, capture_id)
    engine_version = _engine_version(stamp)
    with _CACHE_LOCK:
        cached = _PROCEDURE_CACHE.get(stamp)
        if cached is not None:
            return list(cached)
        stored = _stored(db, project_id, capture_id, engine_version)
        if stored:
            _PROCEDURE_CACHE[stamp] = tuple(stored)
            return stored
        # Cross-worker single flight. The second check after acquiring the
        # transaction-scoped lock observes rows written by the winning worker.
        lock_key = f"{project_id}:{capture_id}:procedure-v1"
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": lock_key})
        stored = _stored(db, project_id, capture_id, engine_version)
        if stored:
            db.commit()
            _PROCEDURE_CACHE[stamp] = tuple(stored)
            return stored
        procedures = tuple(
            reconstruct_procedures(project_id, capture_id, load_events(db, project_id, capture_id))
        )
        _persist(db, project_id, capture_id, engine_version, procedures)
        if len(_PROCEDURE_CACHE) >= _CACHE_LIMIT:
            _PROCEDURE_CACHE.pop(next(iter(_PROCEDURE_CACHE)))
        # Remove stale generations for the same project/capture before insert.
        for key in [key for key in _PROCEDURE_CACHE if key[:2] == stamp[:2]]:
            _PROCEDURE_CACHE.pop(key, None)
        _PROCEDURE_CACHE[stamp] = procedures
        return list(procedures)


def procedures_for_scope(db: Session, project_id: str, capture_ids: list[str]) -> list[Procedure]:
    result: list[Procedure] = []
    for capture_id in dict.fromkeys(capture_ids):
        result.extend(procedures_for_capture(db, project_id, capture_id))
    return result
