from app.routes.metrics_v3 import _lean_table_allowed


CELLMEAS = [{"event": "CELLMEAS", "cell_type_filter": {"system": 7, "raw_cell_type": 0}}]


def test_lean_table_is_only_used_for_an_unfiltered_capture():
    assert _lean_table_allowed(True, CELLMEAS, {"capture_id": "capture"})
    for filters in (
        {"capture_id": "capture", "rat": ["LTE"]},
        {"capture_id": "capture", "operator": ["Free"], "operator_mode": "selected"},
        {"capture_id": "capture", "band": ["1800"]},
    ):
        assert not _lean_table_allowed(True, CELLMEAS, filters)


def test_lean_table_remains_closed_for_other_contracts():
    assert not _lean_table_allowed(False, CELLMEAS, {"capture_id": "capture"})
    assert not _lean_table_allowed(True, [], {"capture_id": "capture"})
    assert not _lean_table_allowed(
        True,
        [{"event": "CQI", "cell_type_filter": {"system": 7, "raw_cell_type": 0}}],
        {"capture_id": "capture"},
    )
