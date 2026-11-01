from app.procedures.catalog import BY_CODE, aggregate, catalog_tree
from app.procedures.engine import EvidenceEvent, reconstruct_procedures
from app.procedures import service


PID = "project"
CAP = "capture"


def event(seq, code, *, message=None, rat="LTE", attrs=None, time=None):
    return EvidenceEvent(
        seq=seq,
        code=code,
        source_id=f"event:{seq}",
        rat=rat,
        message=message,
        time=time or f"00:00:{seq:02d}",
        t_rel_s=float(seq),
        attrs=attrs or {},
    )


def test_rrc_results_keep_unknown_out_of_rate_denominator():
    rows = reconstruct_procedures(
        PID,
        CAP,
        [
            event(1, "RRCSM", message="RRCConnectionRequest"),
            event(2, "RRCSM", message="RRCConnectionSetupComplete"),
            event(3, "RRCSM", message="RRCConnectionRequest"),
            event(4, "RRCSM", message="RRCConnectionReject"),
            event(5, "RRCSM", message="RRCConnectionRequest"),
        ],
    )
    setup = [row for row in rows if row.procedure_type == "lte_rrc_setup"]
    assert [row.result for row in setup] == ["SUCCESS", "FAILURE", "UNKNOWN"]
    summary = aggregate(BY_CODE["PROC_LTE_RRC_SETUP_SUCCESS_RATE"], rows)
    assert summary["attempts"] == 3
    assert summary["success"] == 1
    assert summary["failures"] == 1
    assert summary["unknown"] == 1
    assert summary["denominator"] == 2
    assert summary["excluded"] == 1
    assert summary["value"] == 50.0


def test_repeated_attempt_is_not_double_counted_as_success():
    rows = reconstruct_procedures(
        PID,
        CAP,
        [
            event(1, "RRCSM", message="RRCConnectionRequest"),
            event(2, "RRCSM", message="RRCConnectionRequest"),
            event(3, "RRCSM", message="RRCConnectionSetupComplete"),
        ],
    )
    setup = [row for row in rows if row.procedure_type == "lte_rrc_setup"]
    assert [(row.start_seq, row.result) for row in setup] == [(1, "UNKNOWN"), (2, "SUCCESS")]
    assert len({row.procedure_id for row in setup}) == 2


def test_measurement_report_is_never_handover_attempt():
    rows = reconstruct_procedures(PID, CAP, [event(1, "RRCSM", message="MeasurementReport")])
    assert not [row for row in rows if "ho_" in row.procedure_type]


def test_handover_uses_explicit_pair_and_source_target_cells():
    rows = reconstruct_procedures(
        PID,
        CAP,
        [
            event(
                10,
                "HOA",
                attrs={"source_arfcn": 1675, "source_pci": 196, "target_arfcn": 3350, "target_pci": 30},
            ),
            event(11, "HOS"),
            event(10, "NMF_PAIR_HO", attrs={"seq_start": 10, "seq_end": 11, "outcome": "ok"}),
        ],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.procedure_type == "lte_ho_inter_frequency"
    assert row.result == "SUCCESS"
    assert row.source_arfcn == 1675 and row.source_pci == 196
    assert row.target_arfcn == 3350 and row.target_pci == 30
    assert row.source_event_ids == ("event:10", "event:11")


def test_lte_rach_requires_validated_lte_result():
    rows = reconstruct_procedures(
        PID,
        CAP,
        [
            event(1, "RACHI", attrs={"system_code": 7, "rach_result": 1}),
            event(2, "RACHI", attrs={"system_code": 7, "rach_result": 2}),
            event(3, "RACHI", rat="NR", attrs={"system_code": 8, "rach_result": None}),
        ],
    )
    rach = [row for row in rows if row.procedure_type == "lte_rach"]
    assert [row.result for row in rach] == ["SUCCESS", "FAILURE"]


def test_eps_bearer_distinguishes_setup_failure_and_unknown():
    rows = reconstruct_procedures(
        PID,
        CAP,
        [
            event(1, "PBA", attrs={"system_code": 7}),
            event(2, "PBC", attrs={"system_code": 7, "bearer_id": 5, "qci": 9}),
            event(3, "PBA", attrs={"system_code": 7}),
            event(4, "PBF", attrs={"system_code": 7, "esm_cause": 27}),
            event(5, "PBA", attrs={"system_code": 7}),
        ],
    )
    bearer = [row for row in rows if row.procedure_type == "lte_eps_bearer_setup"]
    assert [row.result for row in bearer] == ["SUCCESS", "FAILURE", "UNKNOWN"]
    assert bearer[0].ebi == 5 and bearer[0].qci == 9
    assert bearer[1].failure_cause == "esm_cause=27"


def test_reestablishment_creates_separate_probable_rlf_evidence():
    request = event(
        1,
        "RRCSM",
        message="RRCConnectionReestablishmentRequest",
        attrs={"x/reestablishmentCause": "otherFailure"},
    )
    rows = reconstruct_procedures(
        PID,
        CAP,
        [request, event(2, "RRCSM", message="RRCConnectionReestablishmentComplete")],
    )
    reest = next(row for row in rows if row.procedure_type == "lte_rrc_reestablishment")
    rlf = next(row for row in rows if row.procedure_type == "lte_rlf_probable")
    assert reest.result == "SUCCESS" and reest.evidence_level == "PROVEN"
    assert rlf.result == "FAILURE" and rlf.evidence_level == "PROBABLE"
    assert rlf.failure_cause == "otherFailure"


def test_scg_failure_requires_explicit_message_and_preserves_cause():
    rows = reconstruct_procedures(
        PID,
        CAP,
        [
            event(
                1,
                "RRCSM",
                message="SCGFailureInformationNR",
                attrs={"failureReport/failureType-r15": "randomAccessProblem"},
            )
        ],
    )
    assert len(rows) == 1
    assert rows[0].procedure_type == "endc_scg_failure"
    assert rows[0].result == "FAILURE"
    assert rows[0].failure_cause == "randomAccessProblem"


def test_capture_identity_is_isolated_and_anonymised():
    evidence = [event(1, "RRCSM", message="RRCConnectionRequest")]
    first = reconstruct_procedures(PID, "capture-a", evidence)[0]
    second = reconstruct_procedures(PID, "capture-b", evidence)[0]
    assert first.ue_key != second.ue_key
    assert "capture-a" not in first.ue_key
    assert first.procedure_id != second.procedure_id


def test_zero_denominator_is_na_not_zero_percent():
    rows = reconstruct_procedures(
        PID,
        CAP,
        [event(1, "RRCSM", message="RRCConnectionRequest")],
    )
    summary = aggregate(BY_CODE["PROC_LTE_RRC_SETUP_SUCCESS_RATE"], rows)
    assert summary["value"] is None
    assert summary["denominator"] == 0
    assert "N/A" in summary["reason"]


def test_capture_cache_is_decode_stamp_scoped(monkeypatch):
    service._PROCEDURE_CACHE.clear()
    stamp = [PID, CAP, "decoder-1", "schema-1", "decoded-at", "deep-at", 2]
    calls = {"load": 0}

    def load(*_args):
        calls["load"] += 1
        return [event(1, "RRCSM", message="RRCConnectionRequest")]

    monkeypatch.setattr(service, "_capture_stamp", lambda *_args: tuple(stamp))
    monkeypatch.setattr(service, "load_events", load)
    monkeypatch.setattr(service, "_stored", lambda *_args: [])
    monkeypatch.setattr(service, "_persist", lambda *_args: None)

    class FakeDb:
        def execute(self, *_args, **_kwargs):
            return None

    db = FakeDb()
    assert len(service.procedures_for_capture(db, PID, CAP)) == 1
    assert len(service.procedures_for_capture(db, PID, CAP)) == 1
    assert calls["load"] == 1

    stamp[-1] = 3
    assert len(service.procedures_for_capture(db, PID, CAP)) == 1
    assert calls["load"] == 2
    service._PROCEDURE_CACHE.clear()


def test_catalog_declares_canonical_replacement_without_label_matching():
    catalog = catalog_tree([])
    items = {
        item["code"]: item
        for technology in catalog["tree"]
        for family in technology["families"]
        for item in family["kpis"]
    }
    assert items["PROC_LTE_RRC_SETUP_SUCCESS_RATE"]["replaces_code"] == "LTE_RRC_SETUP_SR"
    assert items["PROC_LTE_EPS_BEARER_SUCCESS_RATE"]["replaces_code"] is None
