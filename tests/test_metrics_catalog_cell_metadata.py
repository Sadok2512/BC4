from app.kpi.metrics_catalog_v4 import (
    _cell_role_for_tree,
    _tree_metric_label,
    cell_type_selector,
    parse_cell_type_selector,
)


def test_cell_role_is_semantic_enum_not_storage_or_physical_identity():
    assert _cell_role_for_tree("CELLMEAS", 7, 0) == "PCell"
    assert _cell_role_for_tree("CELLMEAS", 7, 1) == "Listed LTE neighbour"
    assert _cell_role_for_tree("CELLMEAS", 7, 10) == "SCell 1"
    assert _cell_role_for_tree("CELLMEAS", 9, 199) == "PSCell"
    assert _cell_role_for_tree("CELLMEAS", 9, 1000) == "Listed NR neighbour"


def test_public_selector_round_trips_system_and_raw_cell_type():
    for system, raw in ((7, 0), (7, 10), (9, 199), (9, 1000)):
        selector = cell_type_selector(system, raw)
        assert parse_cell_type_selector(selector) == (system, raw)
    assert parse_cell_type_selector("1675:196") is None


def test_metric_label_only_removes_redundant_trailing_technology():
    assert _tree_metric_label("RSRP (LTE) @ Serving") == "RSRP"
    assert _tree_metric_label("SS-RSRP (NR) @ SCG PSCell") == "SS-RSRP"
    assert _tree_metric_label("NR-ARFCN @ PCell") == "NR-ARFCN"
