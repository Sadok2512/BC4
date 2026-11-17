from app.measure.operator_context import OperatorContext, resolve_operator_context


def test_operator_context_uses_first_proof_for_capture_preamble():
    timeline = [OperatorContext(100, "Free", "LTE")]
    assert resolve_operator_context(timeline, 10, "LTE") == ("Free", "sib1_next")


def test_operator_context_keeps_network_transitions():
    timeline = [
        OperatorContext(100, "Free", "LTE"),
        OperatorContext(200, "Orange", "LTE"),
        OperatorContext(250, "Free", "LTE"),
    ]
    assert resolve_operator_context(timeline, 225, "LTE") == ("Orange", "sib1")
    assert resolve_operator_context(timeline, 260, "LTE") == ("Free", "sib1")


def test_nr_uses_proven_lte_anchor_when_nr_sib1_is_absent():
    timeline = [OperatorContext(100, "Bouygues", "LTE")]
    assert resolve_operator_context(timeline, 150, "NR") == ("Bouygues", "lte_anchor")


def test_empty_timeline_stays_explicitly_unavailable():
    assert resolve_operator_context([], 10, "LTE") == (None, "none")
