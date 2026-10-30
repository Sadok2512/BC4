import json

import pytest

from scripts.catalog import bootstrap_catalog_release as bootstrap


def _leaf(node_id, metric_id, event, cell_type, label, **extra):
    return {
        "node_type": "leaf",
        "node_id": node_id,
        "metric_id": metric_id,
        "event": event,
        "cell_type": cell_type,
        "cell_label": label.split(" @ ")[-1],
        "label": label,
        "displayed": True,
        **extra,
    }


def test_prepare_scell5plus_uses_event_cell_content(monkeypatch, tmp_path):
    source = tmp_path / "catalog_2.59.0.json"
    target = tmp_path / "catalog_2.60.0.json"
    source.write_text(json.dumps({
        "catalog_version": "2.59.0",
        "n_leaves": 3,
        "n_leaves_displayed": 3,
        "nodes": [
            _leaf("lf_dci_count_c4", "dci_count@4", "DCI", 4,
                  "DCI count @ SCell 4"),
            _leaf("lf_cellmeas_rsrp_c4", "cellmeas_rsrp@4", "CELLMEAS", 4,
                  "RSRP (LTE) @ SCell 4", field_system=7, label_system=7),
            _leaf("lf_mimomeas_rsrp_c13", "mimomeas_rsrp@13", "MIMOMEAS", 13,
                  "RSRP/P (LTE) @ SCell 4", field_system=7, label_system=7),
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(
        bootstrap, "catalog_file_path",
        lambda version: source if version == "2.59.0" else target,
    )

    bootstrap.prepare_scell5plus_minor("2.59.0", "2.60.0")

    result = json.loads(target.read_text(encoding="utf-8"))
    by_id = {node["node_id"]: node for node in result["nodes"]}
    assert by_id["lf_dci_count_c6"]["cell_type"] == 6
    assert by_id["lf_dci_count_c6"]["field_system"] == 7
    assert by_id["lf_cellmeas_rsrp_c5"]["cell_type"] == 14
    assert by_id["lf_cellmeas_rsrp_c5"]["cell_label"] == "SCell 5 (raw 14)"
    assert by_id["lf_mimomeas_rsrp_c15"]["cell_type"] == 15
    assert by_id["lf_mimomeas_rsrp_c15"]["label"] == "RSRP/P (LTE) @ SCell 6"
    assert result["n_leaves"] == result["n_leaves_displayed"] == 9
    assert result["catalog_scell_policy"]["label_fields_used_for_selection"] is False


def test_prepare_scell5plus_requires_next_minor():
    with pytest.raises(ValueError, match="MINOR suivant"):
        bootstrap.prepare_scell5plus_minor("2.59.0", "2.59.1")


def test_catalog_260_adds_only_cloned_scell_families():
    source = json.loads(bootstrap.catalog_file_path("2.59.0").read_text(encoding="utf-8"))
    target = json.loads(bootstrap.catalog_file_path("2.60.0").read_text(encoding="utf-8"))
    source_by_id = {node["node_id"]: node for node in source["nodes"]}
    target_by_id = {node["node_id"]: node for node in target["nodes"]}

    assert all(target_by_id[node_id] == node for node_id, node in source_by_id.items())
    templates = [
        node for node in source["nodes"]
        if node.get("node_type") == "leaf"
        and (node.get("cell_type") == 4
             or (node.get("event") == "MIMOMEAS" and node.get("cell_type") == 13))
    ]
    added = set(target_by_id) - set(source_by_id)
    assert len(added) == 2 * len(templates)
    added_leaves = [target_by_id[node_id] for node_id in added]
    assert all(node["analytics_tab"] == "metrics" for node in added_leaves)
    assert all("SCell 5" in node["label"] or "SCell 6" in node["label"]
               for node in added_leaves)
    assert len(target_by_id) == len(target["nodes"])
