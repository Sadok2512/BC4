import json

import pytest

from scripts.catalog import bootstrap_catalog_release as bootstrap


def test_prepare_nr_labels_minor_uses_content_and_preserves_leaves(monkeypatch, tmp_path):
    source = tmp_path / "catalog_2.57.0.json"
    target = tmp_path / "catalog_2.58.0.json"
    source.write_text(
        json.dumps(
            {
                "catalog_version": "2.57.0",
                "nodes": [
                    {
                        "node_type": "leaf",
                        "node_id": "lte",
                        "parent_id": "ev_cellmeas",
                        "event": "CELLMEAS",
                        "cell_type": 0,
                        "field_system": 7,
                        "label": "RSRP (bloc LTE) @ Serving",
                    },
                    {
                        "node_type": "leaf",
                        "node_id": "nr",
                        "parent_id": "ev_cellmeas",
                        "event": "CELLMEAS",
                        "cell_type": 100,
                        "field_system": 9,
                        "label": "RSRP (bloc NR) @ SCG SCell 0",
                    },
                    {
                        "node_type": "leaf",
                        "node_id": "mimo-lte",
                        "parent_id": "ev_mimomeas",
                        "event": "MIMOMEAS",
                        "cell_type": 10,
                        "field_system": None,
                        "label": "Measured system @ SCell 1",
                    },
                    {
                        "node_type": "leaf",
                        "node_id": "mimo-nr",
                        "parent_id": "ev_mimomeas",
                        "event": "MIMOMEAS",
                        "cell_type": 1,
                        "field_system": None,
                        "label": "Measured system @ SCell 1",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        bootstrap,
        "catalog_file_path",
        lambda version: source if version == "2.57.0" else target,
    )

    bootstrap.prepare_nr_labels_minor("2.57.0", "2.58.0")

    result = json.loads(target.read_text(encoding="utf-8"))
    leaves = result["nodes"]
    assert [leaf["node_id"] for leaf in leaves] == [
        "lte",
        "nr",
        "mimo-lte",
        "mimo-nr",
    ]
    assert [leaf["label"] for leaf in leaves] == [
        "RSRP (LTE) @ Serving",
        "RSRP (NR) @ SCG SCell 0",
        "Measured system (LTE) @ SCell 1",
        "Measured system (NR) @ SCell 1",
    ]
    assert [leaf["field_system"] for leaf in leaves] == [7, 9, None, None]
    assert [leaf["label_system"] for leaf in leaves] == [7, 9, 7, 9]
    assert result["catalog_label_policy"]["label_fields_used_for_classification"] is False


def test_prepare_nr_labels_minor_rejects_non_minor_target():
    with pytest.raises(ValueError, match="MINOR suivant"):
        bootstrap.prepare_nr_labels_minor("2.57.0", "2.57.1")


def test_catalog_258_preserves_every_257_leaf_and_has_unique_labels():
    source = json.loads(bootstrap.catalog_file_path("2.57.0").read_text(encoding="utf-8"))
    target = json.loads(bootstrap.catalog_file_path("2.58.0").read_text(encoding="utf-8"))
    source_leaves = [node for node in source["nodes"] if node.get("node_type") == "leaf"]
    target_leaves = [node for node in target["nodes"] if node.get("node_type") == "leaf"]

    assert {node["node_id"] for node in target_leaves} == {
        node["node_id"] for node in source_leaves
    }
    assert len(target_leaves) == len(source_leaves)
    labels = [(node.get("parent_id"), node["label"]) for node in target_leaves]
    assert len(labels) == len(set(labels))


def test_catalog_258_cell_measurement_labels_are_system_explicit():
    payload = json.loads(bootstrap.catalog_file_path("2.58.0").read_text(encoding="utf-8"))
    leaves = [
        node
        for node in payload["nodes"]
        if node.get("node_type") == "leaf" and node.get("event") in {"CELLMEAS", "MIMOMEAS"}
    ]
    assert leaves
    assert all(node.get("label_system") in {7, 9} for node in leaves)
    assert all(
        (" (LTE)" in node["label"])
        if node["label_system"] == 7
        else (" (NR)" in node["label"])
        for node in leaves
    )


def test_catalog_258_repeated_dci_blocks_have_unique_visual_labels():
    payload = json.loads(bootstrap.catalog_file_path("2.58.0").read_text(encoding="utf-8"))
    dci = [
        node
        for node in payload["nodes"]
        if node.get("node_type") == "leaf" and node.get("event") == "DCI"
    ]
    for parameter in ("#Variables", "CCE aggregation"):
        labels = [node["label"] for node in dci if node["label"].startswith(parameter)]
        assert labels
        assert len(labels) == len(set(labels))
