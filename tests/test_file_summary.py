from app.services.file_summary import summarize_file


def row(seq, event, fields=None, system=None, kind="ue"):
    return {"capture_id": "cap", "kind": kind, "seq": seq, "event_code": event,
            "system": system, "raw_fields": fields or {}}


def test_summary_uses_command_window_and_preserves_zero():
    events = [
        row(10, "CMDREQ", {"service_action": "StartHTTPTransfer"}),
        row(11, "DRATE", {"c6": "10000000"}),
        row(12, "PDCPRATED", {"c5": "0"}, "LTE"),
        row(13, "DAA"),
        row(14, "RACHI", {"c8": "1", "c9": "0", "c11": "0"}),
        row(15, "DCOMP"),
        row(16, "CMDCOMP"),
        row(17, "DRATE", {"c6": "900000000"}),
    ]
    result = summarize_file({"id": "f", "filename": "f.nmf"}, events, {"DRATE", "PDCPRATED", "RACHI"})
    cells = result["cells"]
    assert cells["task"]["value"] == "HTTP_DL"
    assert cells["task"]["n"] == 1
    assert cells["dl_total"]["value"] == 10.0
    assert cells["dl_total"]["n"] == 1
    assert cells["dl_lte"]["value"] == 0.0
    assert cells["rach_fail"]["value"] == 0
    assert cells["rach_fail"]["n"] == 1
    assert cells["session_fail"]["value"] == 0
    assert cells["session_fail"]["n"] == 1


def test_scanner_has_only_task():
    result = summarize_file(
        {"id": "f", "filename": "scan.nmf"},
        [row(1, "OFDMSCAN", kind="scanner")],
        set(),
    )
    assert result["cells"]["task"]["value"] == "Scanner"
    assert all(cell["value"] is None for key, cell in result["cells"].items() if key != "task")


def test_missing_failure_source_is_unavailable_not_zero():
    events = [
        row(1, "CMDREQ", {"service_action": "VoiceCallStart"}),
        row(2, "CAA"),
        row(3, "CAD"),
        row(4, "CMDCOMP"),
    ]
    cells = summarize_file({"id": "f", "filename": "voice.nmf"}, events, {"CAA", "CAD"})["cells"]
    assert cells["call_setup_fail"]["value"] is None
    assert cells["call_setup_fail"]["reason"] == "no CAF in file"
    assert cells["voice_drop"]["value"] == 1
    assert cells["voice_drop"]["n"] == 1


def test_duplicate_persisted_rows_are_counted_once_by_capture_and_seq():
    events = [
        row(1, "CMDREQ", {"service_action": "VoiceCallStart"}),
        row(1, "CMDREQ", {"service_action": "VoiceCallStart"}),
        row(2, "CAA"), row(2, "CAA"),
        row(3, "CAD"), row(3, "CAD"),
        row(4, "CMDCOMP"), row(4, "CMDCOMP"),
    ]
    cells = summarize_file({"id": "f", "filename": "voice.nmf"}, events, {"CAA", "CAD"})["cells"]
    assert cells["task"]["n"] == 1
    assert cells["voice_drop"]["value"] == 1
    assert cells["voice_drop"]["n"] == 1


def test_radio_only_file_uses_documented_phrate_lte_fallback():
    events = [
        row(1, "CELLMEAS", {}, "LTE"),
        row(2, "PHRATE", {"c4": "2", "c5": "1000000"}, "LTE"),
        row(3, "PHRATE", {"c4": "2", "c5": "3000000"}, "LTE"),
        row(4, "PHRATE", {"c4": "3", "c5": "9000000"}, "LTE"),
    ]
    cells = summarize_file(
        {"id": "f", "filename": "radio.nmf"}, events, {"PHRATE"}
    )["cells"]
    assert cells["task"]["value"] is None
    assert cells["dl_total"] == {
        "value": 2.0, "n": 2, "max": 3.0, "unit": "Mbit/s",
        "source_event": "PHRATE", "reason": None,
    }
    assert cells["dl_lte"] == cells["dl_total"]
    assert cells["dl_nr"]["value"] is None
    assert cells["ul_total"]["value"] is None
