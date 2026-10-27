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
