from app.kpi.metrics_catalog_v4 import (
    _catalog_leaf_system,
    _cell_role_for_tree,
    _cell_relation_for_tree,
    _is_physical_neighbour,
    _technical_cell_label,
    _tree_metric_label,
    cell_type_selector,
    parse_cell_type_selector,
)


def test_null_field_system_inherits_released_catalog_technology():
    nodes = {
        "tech_LTE": {
            "node_id": "tech_LTE", "node_type": "tech", "label": "LTE",
            "parent_id": None,
        },
        "event": {
            "node_id": "event", "node_type": "event", "label": "PHRATE",
            "parent_id": "tech_LTE",
        },
    }
    leaf = {
        "node_id": "leaf", "parent_id": "event", "field_system": None,
        "event": "PHRATE", "metric_id": "phrate_pdsch_bitrate_0@0",
    }

    assert _catalog_leaf_system(nodes, leaf) == 7
    assert _catalog_leaf_system(nodes, {**leaf, "field_system": 9}) == 9


def test_cell_role_is_semantic_enum_not_storage_or_physical_identity():
    assert _cell_role_for_tree("CELLMEAS", 7, 0) == "PCell"
    assert _cell_role_for_tree("CELLMEAS", 7, 1) == "Listed LTE neighbour"
    assert _cell_role_for_tree("CELLMEAS", 7, 10) == "SCell 1"
    assert _cell_role_for_tree("CELLMEAS", 9, 199) == "PSCell"
    assert _cell_role_for_tree("CELLMEAS", 9, 1000) == "Listed NR neighbour"


def test_cell_relation_uses_event_system_and_raw_enum_not_display_text():
    assert _cell_relation_for_tree("CELLMEAS", 7, 0) == "serving"
    assert _cell_relation_for_tree("CELLMEAS", 7, 10) == "serving"
    assert _cell_relation_for_tree("CELLMEAS", 7, 1) == "neighbour"
    assert _cell_relation_for_tree("CELLMEAS", 9, 199) == "serving"
    assert _cell_relation_for_tree("CELLMEAS", 9, 1000) == "neighbour"
    assert _cell_relation_for_tree("MIMOMEAS", 7, 0) == "serving"
    assert _cell_relation_for_tree("CELLMEAS", 7, 999) is None


def test_detected_lte_cellmeas_type_is_a_physical_neighbour():
    assert _is_physical_neighbour("CELLMEAS", 7, 2)
    assert not _is_physical_neighbour("PHRATE", 7, 2)


def test_technical_label_is_display_metadata_not_a_selector():
    assert _technical_cell_label("LTE", "serving", "RSRP", "SCell 1") == (
        "LTE_Serving_RSRP_SCell1"
    )
    assert _technical_cell_label("LTE", "neighbour", "RSRQ", "Cell 1") == (
        "LTE_Neighbor_RSRQ_Cell1"
    )


def test_public_selector_round_trips_system_and_raw_cell_type():
    for system, raw in ((7, 0), (7, 10), (9, 199), (9, 1000)):
        selector = cell_type_selector(system, raw)
        assert parse_cell_type_selector(selector) == (system, raw)
    assert parse_cell_type_selector("1675:196") is None


def test_metric_label_only_removes_redundant_trailing_technology():
    assert _tree_metric_label("RSRP (LTE) @ Serving") == "RSRP"
    assert _tree_metric_label("SS-RSRP (NR) @ SCG PSCell") == "SS-RSRP"
    assert _tree_metric_label("NR-ARFCN @ PCell") == "NR-ARFCN"
