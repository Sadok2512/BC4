import json

import pytest

from app.kpi.display_names import EXPECTED_ROWS, load_display_names
from scripts.catalog import bootstrap_catalog_release as bootstrap


def _leaf(metric_id, event, cell_type, label, **extra):
    return {
        "node_type": "leaf",
        "node_id": f"lf_{metric_id.replace('@', '_')}",
        "metric_id": metric_id,
        "event": event,
        "cell_type": cell_type,
        "label": label,
        "displayed": True,
        **extra,
    }


def test_supplied_display_names_are_complete_and_unique():
    names = load_display_names()
    assert len(names) == EXPECTED_ROWS
    assert len({row.display_code for row in names.values()}) == EXPECTED_ROWS
    assert not [
        row.metric_id
        for row in names.values()
        if row.display_code.endswith("_") or row.short_name.endswith("_")
    ]


def test_prepare_full_names_uses_structural_content(monkeypatch, tmp_path):
    source = tmp_path / "catalog_2.68.2.json"
    target = tmp_path / "catalog_2.68.3.json"
    source.write_text(json.dumps({
        "catalog_version": "2.68.2",
        "nodes": [
            _leaf("phrate_ch@0", "PHRATE", 0, "Ch @ PCell", kind="KPI", unit="earfcn"),
            _leaf("plaid_modulation@0", "PLAID", 0, "opaque", kind="DIMENSION"),
            _leaf("plaiu_percentage@199", "PLAIU", 199,
                  "Percentage (bloc UMTS FDD) @ PSCell", field_system=9),
            _leaf("cellmeas_ch@3", "CELLMEAS", 3, "Ch @ cell type 3"),
            _leaf("plaiu_avg_ul_tbs@0", "PLAIU", 0, "Avg UL TBS @ PCell"),
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(
        bootstrap,
        "catalog_file_path",
        lambda version: source if version == "2.68.2" else target,
    )

    bootstrap.prepare_full_names_patch("2.68.2", "2.68.3")
    leaves = {
        node["metric_id"]: node
        for node in json.loads(target.read_text(encoding="utf-8"))["nodes"]
    }
    assert leaves["phrate_ch@0"]["kind"] == "DIMENSION"
    assert leaves["phrate_ch@0"]["unit"] == ""
    assert leaves["plaid_modulation@0"]["kind"] == "KPI_CATEGORICAL"
    assert "bloc NR" in leaves["plaiu_percentage@199"]["label"]
    assert leaves["cellmeas_ch@3"]["tree_visible"] is False
    assert leaves["plaiu_avg_ul_tbs@0"]["alias_of"] == "plaiu_ul_tbs_avg"


def test_prepare_full_names_requires_next_patch():
    with pytest.raises(ValueError, match="PATCH suivant"):
        bootstrap.prepare_full_names_patch("2.68.2", "2.69.0")


def test_catalog_2683_policy_has_no_foreign_bloc_residual():
    payload = json.loads(bootstrap.catalog_file_path("2.68.3").read_text(encoding="utf-8"))
    policy = payload["catalog_full_names_policy"]
    assert policy["classification_uses_labels"] is False
    assert policy["hidden_cell_type_3_4"] == 2
    assert policy["hidden_unprojected_tbs_aliases"] == 7
