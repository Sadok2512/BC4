"""Deterministic procedure reconstruction from projected NMF evidence.

The engine is deliberately independent from SQL and FastAPI.  Inputs are
capture-local events already ordered by ``seq``.  It never joins captures,
uses timestamps for ordering, or turns a missing terminal event into a
failure.  A truncated procedure remains ``UNKNOWN``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Iterable, Literal


ProcedureResult = Literal[
    "ATTEMPT",
    "SUCCESS",
    "FAILURE",
    "ABNORMAL_RELEASE",
    "DROP",
    "TIMEOUT",
    "UNKNOWN",
]
EvidenceLevel = Literal["PROVEN", "PROBABLE", "UNKNOWN"]


@dataclass(frozen=True)
class EvidenceEvent:
    seq: int
    code: str
    source_id: str
    rat: str | None = None
    message: str | None = None
    time: str | None = None
    t_rel_s: float | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Procedure:
    procedure_id: str
    project_id: str
    capture_id: str
    ue_key: str
    session_key: str
    rat: str
    procedure_type: str
    start_seq: int
    end_seq: int | None
    start_time: str | None
    end_time: str | None
    duration_ms: float | None
    source_pci: int | None
    source_arfcn: int | None
    target_pci: int | None
    target_arfcn: int | None
    bearer_id: int | None
    ebi: int | None
    qci: int | None
    qfi: int | None
    five_qi: int | None
    s_nssai: str | None
    result: ProcedureResult
    failure_cause: str | None
    evidence_level: EvidenceLevel
    source_event_ids: tuple[str, ...]
    latitude: float | None = None
    longitude: float | None = None
    gps_seq: int | None = None

    def as_dict(self) -> dict[str, Any]:
        value = dict(self.__dict__)
        value["source_event_ids"] = list(self.source_event_ids)
        return value


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _duration(start: EvidenceEvent, end: EvidenceEvent | None) -> float | None:
    if end is None or start.t_rel_s is None or end.t_rel_s is None:
        return None
    value = (end.t_rel_s - start.t_rel_s) * 1000
    return round(value, 3) if value >= 0 else None


def _identity(project_id: str, capture_id: str, kind: str, seq: int) -> str:
    return sha256(f"procedure-v1:{project_id}:{capture_id}:{kind}:{seq}".encode()).hexdigest()[:32]


def _ue_key(project_id: str, capture_id: str) -> str:
    # Capture-scoped and anonymised.  Never correlates subscribers across files.
    return "capture-" + sha256(f"{project_id}:{capture_id}".encode()).hexdigest()[:16]


def _make(
    project_id: str,
    capture_id: str,
    kind: str,
    start: EvidenceEvent,
    end: EvidenceEvent | None,
    result: ProcedureResult,
    evidence: EvidenceLevel,
    *,
    cause: str | None = None,
    events: Iterable[EvidenceEvent] = (),
    rat: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> Procedure:
    # Location and cell context belong to the observed start event. Procedure-
    # specific attributes may override them, but an omitted attrs mapping must
    # not silently discard real evidence loaded from that event.
    attrs = {**start.attrs, **(attrs or {})}
    chain = [start, *events]
    if end is not None and all(event.source_id != end.source_id for event in chain):
        chain.append(end)
    return Procedure(
        procedure_id=_identity(project_id, capture_id, kind, start.seq),
        project_id=project_id,
        capture_id=capture_id,
        ue_key=_ue_key(project_id, capture_id),
        session_key=f"{capture_id}:{kind}:{start.seq}",
        rat=(rat or start.rat or "UNKNOWN").upper(),
        procedure_type=kind,
        start_seq=start.seq,
        end_seq=end.seq if end else None,
        start_time=start.time,
        end_time=end.time if end else None,
        duration_ms=_duration(start, end),
        source_pci=_int(attrs.get("source_pci")),
        source_arfcn=_int(attrs.get("source_arfcn")),
        target_pci=_int(attrs.get("target_pci")),
        target_arfcn=_int(attrs.get("target_arfcn")),
        bearer_id=_int(attrs.get("bearer_id")),
        ebi=_int(attrs.get("ebi")),
        qci=_int(attrs.get("qci")),
        qfi=_int(attrs.get("qfi")),
        five_qi=_int(attrs.get("five_qi")),
        s_nssai=attrs.get("s_nssai"),
        result=result,
        failure_cause=cause,
        evidence_level=evidence,
        source_event_ids=tuple(dict.fromkeys(event.source_id for event in chain)),
        latitude=attrs.get("latitude"),
        longitude=attrs.get("longitude"),
        gps_seq=_int(attrs.get("gps_seq")),
    )


def _message_chains(
    project_id: str,
    capture_id: str,
    events: list[EvidenceEvent],
    *,
    kind_by_rat: dict[str, str],
    start_names: set[str],
    success_names: set[str],
    failure_names: set[str],
) -> list[Procedure]:
    active: dict[str, EvidenceEvent] = {}
    result: list[Procedure] = []
    for event in events:
        rat = (event.rat or "UNKNOWN").upper()
        name = event.message or event.code
        if name in start_names:
            previous = active.pop(rat, None)
            if previous is not None:
                result.append(
                    _make(
                        project_id,
                        capture_id,
                        kind_by_rat.get(rat, kind_by_rat["UNKNOWN"]),
                        previous,
                        None,
                        "UNKNOWN",
                        "PROVEN",
                        cause="repeated_attempt_before_terminal",
                        rat=rat,
                    )
                )
            active[rat] = event
            continue
        if rat not in active:
            continue
        start = active[rat]
        kind = kind_by_rat.get(rat, kind_by_rat["UNKNOWN"])
        if name in success_names:
            result.append(_make(project_id, capture_id, kind, start, event, "SUCCESS", "PROVEN", rat=rat))
            active.pop(rat, None)
        elif name in failure_names:
            result.append(
                _make(
                    project_id,
                    capture_id,
                    kind,
                    start,
                    event,
                    "FAILURE",
                    "PROVEN",
                    cause=name,
                    rat=rat,
                )
            )
            active.pop(rat, None)
    for rat, start in active.items():
        result.append(
            _make(
                project_id,
                capture_id,
                kind_by_rat.get(rat, kind_by_rat["UNKNOWN"]),
                start,
                None,
                "UNKNOWN",
                "PROVEN",
                cause="capture_boundary_missing_terminal",
                rat=rat,
            )
        )
    return result


def _rrc(project_id: str, capture_id: str, events: list[EvidenceEvent]) -> list[Procedure]:
    setup = _message_chains(
        project_id,
        capture_id,
        events,
        kind_by_rat={"LTE": "lte_rrc_setup", "NR": "nr_rrc_setup", "UNKNOWN": "rrc_setup_unknown_rat"},
        start_names={"RRCConnectionRequest", "RRCSetupRequest"},
        success_names={"RRCConnectionSetupComplete", "RRCSetupComplete"},
        failure_names={"RRCConnectionReject", "RRCReject"},
    )
    reestablishment = _message_chains(
        project_id,
        capture_id,
        events,
        kind_by_rat={
            "LTE": "lte_rrc_reestablishment",
            "NR": "nr_rrc_reestablishment",
            "UNKNOWN": "rrc_reestablishment_unknown_rat",
        },
        start_names={"RRCConnectionReestablishmentRequest", "RRCReestablishmentRequest"},
        success_names={"RRCConnectionReestablishmentComplete", "RRCReestablishmentComplete"},
        failure_names={"RRCConnectionReestablishmentReject", "RRCReestablishmentReject"},
    )
    # A reestablishment attempt is evidence of a preceding radio failure, but
    # without an explicit RLF report/T310/T311 it is never PROVEN RLF.
    rlf = []
    for event in events:
        if (event.message or event.code) not in {
            "RRCConnectionReestablishmentRequest",
            "RRCReestablishmentRequest",
        }:
            continue
        cause = next(
            (value for path, value in event.attrs.items() if "reestablishmentCause" in path),
            None,
        )
        rlf.append(
            _make(
                project_id,
                capture_id,
                "lte_rlf_probable" if (event.rat or "").upper() == "LTE" else "nr_rlf_probable",
                event,
                event,
                "FAILURE",
                "PROBABLE",
                cause=str(cause or "reestablishment_without_explicit_rlf_report"),
            )
        )
    return setup + reestablishment + rlf


def _nas(project_id: str, capture_id: str, events: list[EvidenceEvent]) -> list[Procedure]:
    attach = _message_chains(
        project_id,
        capture_id,
        events,
        kind_by_rat={"LTE": "lte_nas_attach", "UNKNOWN": "lte_nas_attach", "NR": "lte_nas_attach"},
        start_names={"ATTACH_REQUEST"},
        success_names={"ATTACH_COMPLETE"},
        failure_names={"ATTACH_REJECT"},
    )
    registration = _message_chains(
        project_id,
        capture_id,
        events,
        kind_by_rat={"NR": "nr_registration", "UNKNOWN": "nr_registration", "LTE": "nr_registration"},
        start_names={"REGISTRATION_REQUEST"},
        success_names={"REGISTRATION_ACCEPT", "REGISTRATION_COMPLETE"},
        failure_names={"REGISTRATION_REJECT"},
    )
    return attach + registration


def _rach(project_id: str, capture_id: str, events: list[EvidenceEvent]) -> list[Procedure]:
    result = []
    for event in events:
        if event.code != "RACHI":
            continue
        # Decoder schema 1.9.0 validates these fields for LTE system code 7.
        if _int(event.attrs.get("system_code")) != 7 or event.attrs.get("rach_result") is None:
            continue
        raw = _int(event.attrs.get("rach_result"))
        outcome: ProcedureResult = "SUCCESS" if raw == 1 else "FAILURE"
        result.append(
            _make(
                project_id,
                capture_id,
                "lte_rach",
                event,
                event,
                outcome,
                "PROVEN",
                cause=None if outcome == "SUCCESS" else f"rachi.rach_result={raw}",
                rat="LTE",
            )
        )
    return result


def _handover(project_id: str, capture_id: str, events: list[EvidenceEvent]) -> list[Procedure]:
    by_seq = {event.seq: event for event in events if event.code != "NMF_PAIR_HO"}
    result = []
    for pair in (event for event in events if event.code == "NMF_PAIR_HO"):
        start_seq = _int(pair.attrs.get("seq_start"))
        if start_seq is None or start_seq not in by_seq:
            continue
        start = by_seq[start_seq]
        end_seq = _int(pair.attrs.get("seq_end"))
        end = by_seq.get(end_seq) if end_seq is not None else None
        source_arfcn = _int(start.attrs.get("source_arfcn"))
        target_arfcn = _int(start.attrs.get("target_arfcn"))
        if source_arfcn is None or target_arfcn is None:
            kind = "lte_ho_unknown_frequency"
        elif source_arfcn == target_arfcn:
            kind = "lte_ho_intra_frequency"
        else:
            kind = "lte_ho_inter_frequency"
        pair_outcome = str(pair.attrs.get("outcome") or "").lower()
        outcome: ProcedureResult
        evidence: EvidenceLevel = "PROVEN"
        cause = pair.attrs.get("cause")
        if pair_outcome == "ok" and end is not None and end.code == "HOS":
            outcome = "SUCCESS"
        elif pair_outcome == "fail":
            outcome = "FAILURE"
        else:
            outcome = "UNKNOWN"
        attrs = {
            "source_pci": start.attrs.get("source_pci"),
            "source_arfcn": source_arfcn,
            "target_pci": start.attrs.get("target_pci"),
            "target_arfcn": target_arfcn,
            "latitude": start.attrs.get("latitude"),
            "longitude": start.attrs.get("longitude"),
            "gps_seq": start.attrs.get("gps_seq"),
        }
        result.append(
            _make(
                project_id,
                capture_id,
                kind,
                start,
                end,
                outcome,
                evidence,
                cause=str(cause) if cause else None,
                rat="LTE",
                attrs=attrs,
            )
        )
    return result


def _eps_bearer(project_id: str, capture_id: str, events: list[EvidenceEvent]) -> list[Procedure]:
    active: list[EvidenceEvent] = []
    result = []
    for event in events:
        if event.code == "PBA" and _int(event.attrs.get("system_code")) == 7:
            active.append(event)
        elif event.code in {"PBC", "PBF"} and active:
            start = active.pop(0)
            success = event.code == "PBC"
            cause_value = event.attrs.get("esm_cause")
            result.append(
                _make(
                    project_id,
                    capture_id,
                    "lte_eps_bearer_setup",
                    start,
                    event,
                    "SUCCESS" if success else "FAILURE",
                    "PROVEN",
                    cause=None if success else f"esm_cause={cause_value if cause_value is not None else 'unknown'}",
                    rat="LTE",
                    attrs={
                        "bearer_id": event.attrs.get("bearer_id"),
                        "ebi": event.attrs.get("bearer_id"),
                        "qci": event.attrs.get("qci"),
                    },
                )
            )
    for start in active:
        result.append(
            _make(
                project_id,
                capture_id,
                "lte_eps_bearer_setup",
                start,
                None,
                "UNKNOWN",
                "PROVEN",
                cause="capture_boundary_missing_terminal",
                rat="LTE",
            )
        )
    return result


def _ims(project_id: str, capture_id: str, events: list[EvidenceEvent]) -> list[Procedure]:
    registration = _message_chains(
        project_id,
        capture_id,
        events,
        kind_by_rat={"LTE": "ims_registration", "NR": "ims_registration", "UNKNOWN": "ims_registration"},
        start_names={"SIPREGA"},
        success_names={"SIPREGC"},
        failure_names=set(),
    )
    # SIP call setup is supported only when the actual INVITE flow is present.
    call = _message_chains(
        project_id,
        capture_id,
        events,
        kind_by_rat={"LTE": "volte_call_setup", "NR": "vonr_call_setup", "UNKNOWN": "voice_call_setup_unknown_rat"},
        start_names={"INVITE"},
        success_names={"200 OK (INVITE)"},
        failure_names={"CANCEL", "408 Request Timeout", "480 Temporarily Unavailable", "486 Busy Here", "500 Server Internal Error", "503 Service Unavailable"},
    )
    return registration + call


def _endc(project_id: str, capture_id: str, events: list[EvidenceEvent]) -> list[Procedure]:
    result = []
    for event in events:
        if (event.message or event.code) != "SCGFailureInformationNR":
            continue
        cause = next(
            (value for path, value in event.attrs.items() if "failureType" in path),
            None,
        )
        result.append(
            _make(
                project_id,
                capture_id,
                "endc_scg_failure",
                event,
                event,
                "FAILURE",
                "PROVEN",
                cause=str(cause or "SCGFailureInformationNR"),
                rat="EN-DC",
            )
        )
    return result


def reconstruct_procedures(
    project_id: str,
    capture_id: str,
    events: Iterable[EvidenceEvent],
) -> list[Procedure]:
    ordered = sorted(events, key=lambda event: event.seq)
    procedures = [
        *_rrc(project_id, capture_id, ordered),
        *_nas(project_id, capture_id, ordered),
        *_rach(project_id, capture_id, ordered),
        *_handover(project_id, capture_id, ordered),
        *_eps_bearer(project_id, capture_id, ordered),
        *_ims(project_id, capture_id, ordered),
        *_endc(project_id, capture_id, ordered),
    ]
    return sorted(procedures, key=lambda procedure: (procedure.start_seq, procedure.procedure_type))
