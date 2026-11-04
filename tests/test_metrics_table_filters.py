from app.routes.metrics_v3 import _apply_intrinsic_rat, _lean_table_allowed


CELLMEAS = [{"event": "CELLMEAS", "cell_type_filter": {"system": 7, "raw_cell_type": 0}}]
CQI = [{"event": "CQI", "cell_type_filter": {"system": 7, "raw_cell_type": 3}}]
CHI = [{"event": "CHI", "base_code": "chi_ch", "cell_type_filter": None}]
EVENT = [{"event": "RRC", "base_code": "evt_rrc", "cell_type_filter": None}]
LTE_CELLMEAS = [{
    "event": "CELLMEAS", "base_code": "cell_rsrp",
    "cell_display": {"system": "LTE", "raw_cell_type": 0},
}]
LTE_CHI = [{
    "event": "CHI", "base_code": "cell_band",
    "cell_display": {"system": "LTE", "raw_cell_type": 2},
}]


def test_lean_table_is_only_used_for_an_unfiltered_capture():
    assert _lean_table_allowed(True, CELLMEAS, {"capture_id": "capture"})
    assert _lean_table_allowed(True, CQI, {"capture_id": "capture"})
    assert _lean_table_allowed(True, CHI, {"capture_id": "capture"})
    assert _lean_table_allowed(True, [*CELLMEAS, *CHI], {"capture_id": "capture"})
    for filters in (
        {"capture_id": "capture", "rat": ["LTE"]},
        {"capture_id": "capture", "operator": ["Free"], "operator_mode": "selected"},
        {"capture_id": "capture", "band": ["1800"]},
    ):
        assert not _lean_table_allowed(True, CELLMEAS, filters)


def test_lean_table_remains_closed_for_other_contracts():
    assert not _lean_table_allowed(False, CELLMEAS, {"capture_id": "capture"})
    assert not _lean_table_allowed(True, [], {"capture_id": "capture"})
    assert not _lean_table_allowed(True, CQI, {"capture_id": "capture", "rat": ["LTE"]})
    assert not _lean_table_allowed(True, EVENT, {"capture_id": "capture"})
    assert not _lean_table_allowed(True, [*CELLMEAS, *EVENT], {"capture_id": "capture"})


def test_intrinsic_rat_makes_browser_lte_nr_table_filter_lean():
    selected, filters = _apply_intrinsic_rat(
        [*LTE_CELLMEAS, *LTE_CHI],
        {"capture_id": "capture", "rat": ["LTE", "NR"]},
    )

    assert selected == [*LTE_CELLMEAS, *LTE_CHI]
    assert filters == {"capture_id": "capture"}
    assert _lean_table_allowed(True, selected, filters)


def test_intrinsic_rat_keeps_only_requested_systems():
    selected, filters = _apply_intrinsic_rat(
        LTE_CELLMEAS,
        {"capture_id": "capture", "rat": ["NR"]},
    )

    assert selected == []
    assert filters == {"capture_id": "capture"}
    assert not _lean_table_allowed(True, selected, filters)


def test_intrinsic_rat_does_not_remove_unproven_or_other_filters():
    untyped = [{"event": "CHI", "base_code": "chi_ch", "cell_display": None}]
    original = {"capture_id": "capture", "rat": ["LTE", "NR"]}
    assert _apply_intrinsic_rat(untyped, original) == (untyped, original)

    selected, filters = _apply_intrinsic_rat(
        LTE_CELLMEAS,
        {"capture_id": "capture", "rat": ["LTE"], "band": ["1800"]},
    )
    assert selected == LTE_CELLMEAS
    assert filters == {"capture_id": "capture", "band": ["1800"]}
    assert not _lean_table_allowed(True, selected, filters)
