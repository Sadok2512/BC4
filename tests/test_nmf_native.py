from app.nmf_decoder.decoder import Record
from app.nmf_decoder.native import native_row


def record(seq, t, code="CI", tokens=None):
    return Record(code, "capture-a", seq, 7, "2.62", t_rel_s=t, tokens=tokens or [])


def test_previous_fix_is_capture_local_and_bounded():
    state = {}
    fix = record(1, 10.0, "GPS", ["GPS", "00:00:10", "0", "2.3", "48.8"])
    exact = native_row("p", fix, state)
    inherited = native_row("p", record(2, 10.5), state)
    outside = native_row("p", record(3, 11.01), state)
    other_capture = record(1, 10.5); other_capture.capture_id = "capture-b"
    no_cross_capture = native_row("p", other_capture, {})

    assert (exact["position_source"], exact["position_gap_s"]) == ("exact", 0.0)
    assert (inherited["position_source"], inherited["position_gap_s"]) == ("previous_fix", 0.5)
    assert outside["position_source"] is None
    assert outside["position_reason"] == "fix_gap_exceeded"
    assert no_cross_capture["position_source"] is None
    assert no_cross_capture["position_reason"] == "no_previous_fix"
