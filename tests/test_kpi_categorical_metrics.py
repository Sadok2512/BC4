from app.kpi.metrics_v3 import (
    EVENT_FIELD_CODES,
    MARKER_FIELD_CODES,
    NUMERIC_EVENT_FIELDS,
    definitions,
    parse_selection,
)
from app.routes.metrics import sample


def test_all_event_fields_have_direct_series_definitions():
    defs = definitions()
    # 61 catalog leaves = 54 base fields + four extra CQI cell variants +
    # three CELLMEAS cell leaves already present in the decoder catalogue.
    assert len(EVENT_FIELD_CODES) == 54
    assert EVENT_FIELD_CODES <= defs.keys()
    for code in EVENT_FIELD_CODES:
        metric = parse_selection(code, defs)
        assert metric["kind"] == (
            "numeric" if code in NUMERIC_EVENT_FIELDS else "categorical"
        )
        assert metric["source_column"] == code
        assert metric["event"]


def test_categorical_markers_are_bounded_without_fabricating_values():
    points = [
        {"seq": seq, "t_rel_s": float(seq), "value": str(seq % 3)}
        for seq in range(20)
    ]
    selected, sampling = sample(points, 5, "categorical_marker")
    assert len(selected) == 5
    assert selected == [points[0], points[4], points[8], points[12], points[16]]
    assert sampling["method"] == "categorical_markers_ordinal"
    assert all(point in points for point in selected)


def test_cell_identifiers_use_marker_sampling():
    defs = definitions()
    assert {"cell_ch", "cell_pci"} <= MARKER_FIELD_CODES
    assert defs["cell_ch"]["marker_series"] is True
    assert defs["cell_pci"]["marker_series"] is True
