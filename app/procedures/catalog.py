"""Procedure KPI catalogue and certified aggregate definitions."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any, Literal

from .engine import Procedure


Measure = Literal["attempts", "success", "failures", "unknown", "rate", "duration_mean"]


@dataclass(frozen=True)
class ProcedureKpi:
    code: str
    name: str
    technology: str
    family: str
    procedure_types: tuple[str, ...]
    measure: Measure
    unit: str
    description: str
    certified: bool = True
    unavailable_reason: str | None = None
    minimum_evidence: str = "PROVEN"
    map_supported: bool = False


def _series(
    prefix: str,
    label: str,
    technology: str,
    family: str,
    procedure_types: tuple[str, ...],
    *,
    duration: bool = True,
    map_supported: bool = False,
    minimum_evidence: str = "PROVEN",
) -> list[ProcedureKpi]:
    description = f"{label}, reconstructed from ordered source events."
    rows = [
        ProcedureKpi(f"{prefix}_ATTEMPTS", f"{label} Attempts", technology, family, procedure_types, "attempts", "count", description, minimum_evidence=minimum_evidence, map_supported=map_supported),
        ProcedureKpi(f"{prefix}_SUCCESS", f"{label} Success", technology, family, procedure_types, "success", "count", description, minimum_evidence=minimum_evidence, map_supported=map_supported),
        ProcedureKpi(f"{prefix}_FAILURES", f"{label} Failures", technology, family, procedure_types, "failures", "count", description, minimum_evidence=minimum_evidence, map_supported=map_supported),
        ProcedureKpi(f"{prefix}_UNKNOWN", f"{label} Unknown", technology, family, procedure_types, "unknown", "count", description, minimum_evidence="UNKNOWN", map_supported=map_supported),
        ProcedureKpi(f"{prefix}_SUCCESS_RATE", f"{label} Success Rate", technology, family, procedure_types, "rate", "%", description, minimum_evidence=minimum_evidence, map_supported=map_supported),
    ]
    if duration:
        rows.append(ProcedureKpi(f"{prefix}_DURATION", f"{label} Duration", technology, family, procedure_types, "duration_mean", "ms", description, minimum_evidence=minimum_evidence))
    return rows


def _unsupported(
    code: str,
    name: str,
    technology: str,
    family: str,
    reason: str,
) -> ProcedureKpi:
    return ProcedureKpi(
        code,
        name,
        technology,
        family,
        (),
        "attempts",
        "N/A",
        reason,
        certified=False,
        unavailable_reason=reason,
    )


CATALOG: tuple[ProcedureKpi, ...] = tuple(
    [
        *_series("PROC_LTE_RRC_SETUP", "LTE RRC Setup", "LTE", "Accessibility", ("lte_rrc_setup",)),
        *_series("PROC_LTE_RRC_REEST", "LTE RRC Reestablishment", "LTE", "Accessibility", ("lte_rrc_reestablishment",), map_supported=True),
        *_series("PROC_LTE_RACH", "LTE RACH", "LTE", "Accessibility", ("lte_rach",), duration=False, map_supported=True),
        *_series("PROC_LTE_NAS_ATTACH", "LTE NAS Attach", "LTE", "Accessibility", ("lte_nas_attach",)),
        *_series("PROC_LTE_EPS_BEARER", "LTE EPS Bearer Setup", "LTE", "E-RAB / Bearer", ("lte_eps_bearer_setup",)),
        *_series("PROC_LTE_HO_INTRA", "LTE Intra-frequency HO", "LTE", "Mobility", ("lte_ho_intra_frequency",), map_supported=True),
        *_series("PROC_LTE_HO_INTER", "LTE Inter-frequency HO", "LTE", "Mobility", ("lte_ho_inter_frequency",), map_supported=True),
        ProcedureKpi(
            "PROC_LTE_RLF_PROBABLE_COUNT",
            "LTE Probable RLF",
            "LTE",
            "Mobility",
            ("lte_rlf_probable",),
            "failures",
            "count",
            "Reestablishment evidence without an explicit RLF report/T310/T311.",
            minimum_evidence="PROBABLE",
            map_supported=True,
        ),
        *_series("PROC_NR_RRC_SETUP", "NR RRC Setup", "NR", "Accessibility", ("nr_rrc_setup",)),
        *_series("PROC_NR_RRC_REEST", "NR RRC Reestablishment", "NR", "Accessibility", ("nr_rrc_reestablishment",), map_supported=True),
        *_series("PROC_NR_REGISTRATION", "NR Registration", "NR", "Accessibility", ("nr_registration",)),
        ProcedureKpi(
            "PROC_ENDC_SCG_FAILURES",
            "EN-DC SCG Failures",
            "EN-DC",
            "SCG",
            ("endc_scg_failure",),
            "failures",
            "count",
            "Explicit SCGFailureInformationNR messages.",
            map_supported=True,
        ),
        *_series("PROC_IMS_REGISTRATION", "IMS Registration", "Voice", "IMS", ("ims_registration",)),
        *_series("PROC_VOLTE_CALL_SETUP", "VoLTE Call Setup", "Voice", "VoLTE", ("volte_call_setup",)),
        *_series("PROC_VONR_CALL_SETUP", "VoNR Call Setup", "Voice", "VoNR", ("vonr_call_setup",)),
        _unsupported("PROC_LTE_RRC_RESUME", "LTE RRC Resume", "LTE", "Accessibility", "No LTE RRC Resume event is projected in the certified witnesses."),
        _unsupported("PROC_LTE_SERVICE_REQUEST", "LTE Service Request", "LTE", "Accessibility", "SERVICE_REQUEST attempts are present but no certified terminal response contract is projected."),
        _unsupported("PROC_LTE_ERAB_SETUP", "LTE E-RAB Setup", "LTE", "E-RAB / Bearer", "No S1AP E-RAB identity or validated RABA/RABC/RABD field contract is available; EPS bearer is not relabelled E-RAB."),
        _unsupported("PROC_LTE_ERAB_ABNORMAL_RELEASE", "LTE E-RAB Abnormal Releases", "LTE", "E-RAB / Bearer", "Normal and abnormal E-RAB releases cannot be separated without a validated S1AP/RAB cause contract."),
        _unsupported("PROC_LTE_ERAB_DROP_RATE", "LTE E-RAB Drop Rate", "LTE", "E-RAB / Bearer", "The eligible established E-RAB population and abnormal release evidence are not certified."),
        _unsupported("PROC_LTE_ERAB_QCI", "LTE E-RAB per QCI", "LTE", "E-RAB / Bearer", "QCI alone does not prove E-RAB setup and the RAB markers have no validated QCI projection."),
        _unsupported("PROC_LTE_HO_IRAT", "LTE Inter-RAT HO", "LTE", "Mobility", "The target RAT is not projected by the HOA witness contract."),
        _unsupported("PROC_LTE_HO_FAILURE_RATE", "LTE HO Failure Rate", "LTE", "Mobility", "No explicit HO failure terminal is present in the certified witnesses."),
        _unsupported("PROC_LTE_RLF_RATE", "LTE RLF Rate", "LTE", "Mobility", "Only probable RLF evidence exists; no certified eligible denominator is available."),
        _unsupported("PROC_LTE_DATA_STALL", "LTE Data Stall", "LTE", "Data", "No certified data-stall state machine is projected; throughput samples alone are insufficient."),
        _unsupported("PROC_NR_RRC_RESUME", "NR RRC Resume", "NR", "Accessibility", "No NR RRC Resume event is projected in the certified witnesses."),
        _unsupported("PROC_NR_SERVICE_REQUEST", "NR Service Request", "NR", "Accessibility", "No certified NR service request terminal contract is projected."),
        _unsupported("PROC_NR_RLF_RATE", "NR RLF Rate", "NR", "Mobility", "No explicit NR RLF report and no certified eligible denominator are available."),
        _unsupported("PROC_NR_PDU_SESSION_SETUP", "NR PDU Session Establishment", "NR", "PDU Session", "No projected 5GSM PDU Session request/accept/reject messages are present."),
        _unsupported("PROC_NR_PDU_SESSION_RELEASE", "NR PDU Session Abnormal Release", "NR", "PDU Session", "No projected PDU Session release cause contract is present."),
        _unsupported("PROC_NR_QOS_FLOW_SETUP", "NR QoS Flow Setup", "NR", "QoS / 5QI", "No projected QFI/5QI QoS flow signaling is present."),
        _unsupported("PROC_NR_QOS_FLOW_MODIFICATION", "NR QoS Flow Modification", "NR", "QoS / 5QI", "No projected QFI/5QI QoS flow signaling is present."),
        _unsupported("PROC_NR_QOS_FLOW_RELEASE", "NR QoS Flow Release", "NR", "QoS / 5QI", "No projected QFI/5QI QoS flow signaling is present."),
        _unsupported("PROC_NR_HO", "NR-NR Handover", "NR", "Mobility", "No explicit NR handover command/complete/failure contract is projected."),
        _unsupported("PROC_NR_LTE_IRAT", "NR-LTE Inter-RAT Handover", "NR", "Mobility", "No explicit target RAT handover contract is projected."),
        _unsupported("PROC_NR_CONDITIONAL_HO", "NR Conditional Handover", "NR", "Mobility", "No conditional handover execution evidence is projected."),
        _unsupported("PROC_SLICE_REQUESTED_NSSAI", "Requested NSSAI", "NR", "Network Slicing", "No NSSAI/S-NSSAI parameter is projected in the witnesses."),
        _unsupported("PROC_SLICE_ALLOWED_NSSAI", "Allowed NSSAI", "NR", "Network Slicing", "No NSSAI/S-NSSAI parameter is projected in the witnesses."),
        _unsupported("PROC_SLICE_REJECTED_NSSAI", "Rejected NSSAI", "NR", "Network Slicing", "No NSSAI/S-NSSAI parameter is projected in the witnesses."),
        _unsupported("PROC_SLICE_ADMISSION", "Slice Admission", "NR", "Network Slicing", "Requested/Allowed NSSAI alone would not prove admission; neither is projected."),
        _unsupported("PROC_SLICE_PDU_SESSION", "PDU Session per Slice", "NR", "Network Slicing", "Neither S-NSSAI nor PDU Session signaling is projected."),
        _unsupported("PROC_ENDC_SGNB_ADDITION", "EN-DC SgNB Addition", "EN-DC", "SCG", "SCELL/SCELLMOD existence is insufficient without validated SgNB addition result fields."),
        _unsupported("PROC_ENDC_SGNB_MODIFICATION", "EN-DC SgNB Modification", "EN-DC", "SCG", "SCELLMOD layout/result is not independently validated for the witness format."),
        _unsupported("PROC_ENDC_SGNB_RELEASE", "EN-DC SgNB Release", "EN-DC", "SCG", "No explicit normal/abnormal SgNB release contract is projected."),
        _unsupported("PROC_ENDC_PSCELL_CHANGE", "EN-DC PSCell Change", "EN-DC", "Mobility", "No explicit PSCell change command/result contract is projected."),
        _unsupported("PROC_VOLTE_DROP", "VoLTE Call Drop", "Voice", "VoLTE", "No INVITE-established call followed by an abnormal SIP/bearer release is present."),
        _unsupported("PROC_VOLTE_QCI1", "VoLTE QCI 1 Bearer", "Voice", "VoLTE", "QCI 1 alone is not proof of VoLTE and no certified call correlation is present."),
        _unsupported("PROC_VOLTE_SRVCC", "VoLTE SRVCC", "Voice", "VoLTE", "No certified SRVCC attempt/success/failure signaling is projected."),
        _unsupported("PROC_VONR_DROP", "VoNR Call Drop", "Voice", "VoNR", "No certified VoNR call flow is projected."),
        _unsupported("PROC_VONR_5QI1", "VoNR 5QI 1 QoS Flow", "Voice", "VoNR", "No 5QI/QFI flow signaling is projected and 5QI 1 alone would be insufficient."),
        _unsupported("PROC_VONR_EPS_FALLBACK", "VoNR EPS Fallback", "Voice", "VoNR", "No certified EPS fallback attempt/result signaling is projected."),
    ]
)

BY_CODE = {definition.code: definition for definition in CATALOG}


def _evidence_rank(level: str) -> int:
    return {"UNKNOWN": 0, "PROBABLE": 1, "PROVEN": 2}.get(level, 0)


def aggregate(definition: ProcedureKpi, procedures: list[Procedure]) -> dict[str, Any]:
    if not definition.certified:
        return {
            "code": definition.code,
            "status": "NOT_CERTIFIED",
            "reason": definition.unavailable_reason,
            "value": None,
            "attempts": 0,
            "success": 0,
            "failures": 0,
            "unknown": 0,
            "denominator": None,
            "excluded": 0,
        }
    selected = [p for p in procedures if p.procedure_type in definition.procedure_types]
    if not selected:
        return {
            "code": definition.code,
            "status": "UNAVAILABLE",
            "reason": "No matching procedure evidence in the selected capture scope.",
            "value": None,
            "attempts": 0,
            "success": 0,
            "failures": 0,
            "unknown": 0,
            "denominator": None,
            "excluded": 0,
        }
    minimum = _evidence_rank(definition.minimum_evidence)
    eligible_evidence = [p for p in selected if _evidence_rank(p.evidence_level) >= minimum]
    success = sum(p.result == "SUCCESS" for p in eligible_evidence)
    failures = sum(p.result in {"FAILURE", "ABNORMAL_RELEASE", "DROP", "TIMEOUT"} for p in eligible_evidence)
    unknown = sum(p.result in {"ATTEMPT", "UNKNOWN"} for p in eligible_evidence)
    denominator = success + failures
    excluded = len(selected) - denominator
    durations = [p.duration_ms for p in eligible_evidence if p.duration_ms is not None and p.result == "SUCCESS"]
    if definition.measure == "attempts":
        value: float | int | None = len(eligible_evidence)
    elif definition.measure == "success":
        value = success
    elif definition.measure == "failures":
        value = failures
    elif definition.measure == "unknown":
        value = unknown
    elif definition.measure == "rate":
        value = round(100 * success / denominator, 6) if denominator else None
    else:
        value = round(mean(durations), 3) if durations else None
    reason = None
    if definition.measure == "rate" and not denominator:
        reason = "No certified eligible denominator; rate is N/A."
    return {
        "code": definition.code,
        "status": "AVAILABLE",
        "reason": reason,
        "value": value,
        "attempts": len(eligible_evidence),
        "success": success,
        "failures": failures,
        "unknown": unknown,
        "denominator": denominator if definition.measure == "rate" else None,
        "excluded": excluded,
    }


def catalog_tree(procedures: list[Procedure]) -> dict[str, Any]:
    technologies: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for definition in CATALOG:
        summary = aggregate(definition, procedures)
        item = {
            "code": definition.code,
            "name": definition.name,
            "description": definition.description,
            "unit": definition.unit,
            "procedure_types": list(definition.procedure_types),
            "measure": definition.measure,
            "minimum_evidence": definition.minimum_evidence,
            "status": summary["status"],
            "reason": summary["reason"],
            "available": summary["status"] == "AVAILABLE",
            "map_supported": definition.map_supported,
            "counts": {
                "attempts": summary["attempts"],
                "success": summary["success"],
                "failures": summary["failures"],
                "unknown": summary["unknown"],
            },
        }
        technologies.setdefault(definition.technology, {}).setdefault(definition.family, []).append(item)
    return {
        "tree": [
            {
                "technology": technology,
                "families": [
                    {"family": family, "kpis": items}
                    for family, items in families.items()
                ],
            }
            for technology, families in technologies.items()
        ]
    }
