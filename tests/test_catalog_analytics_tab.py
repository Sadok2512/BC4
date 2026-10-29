import json

import pytest

from app.schemas.project_kpi import KpiCatalogItem
from app.kpi.catalog_v2 import ENTRIES, analytics_tab_for_nature
from app.routes.metrics import _with_analytics_tabs
from scripts.catalog import bootstrap_catalog_release as bootstrap


def test_prepare_analytics_minor_classifies_every_leaf_without_labels(monkeypatch, tmp_path):
    source = tmp_path / "catalog_2.56.2.json"
    target = tmp_path / "catalog_2.57.0.json"
    source.write_text(
        json.dumps(
            {
                "catalog_version": "2.56.2",
                "nodes": [
                    {"node_type": "leaf", "node_id": "a", "label": "Success rate"},
                    {"node_type": "leaf", "node_id": "b", "label": "RSRP"},
                    {"node_type": "event", "node_id": "parent", "label": "RSRP"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        bootstrap,
        "catalog_file_path",
        lambda version: source if version == "2.56.2" else target,
    )

    bootstrap.prepare_analytics_minor("2.56.2", "2.57.0")

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["catalog_version"] == "2.57.0"
    assert [node.get("analytics_tab") for node in payload["nodes"]] == [
        "metrics",
        "metrics",
        None,
    ]


def test_prepare_analytics_minor_rejects_non_minor_target():
    with pytest.raises(ValueError, match="MINOR suivant"):
        bootstrap.prepare_analytics_minor("2.56.2", "2.56.3")


def test_kpi_catalog_item_requires_explicit_analytics_tab():
    common = {
        "code": "LTE_RSRP",
        "name": "RSRP",
        "nature": "Measured metric",
        "unit": "dBm",
        "source": "measurement_points.rsrp",
        "status": "AVAILABLE",
        "reason": None,
    }
    item = KpiCatalogItem(**common, analytics_tab="metrics")
    assert item.analytics_tab == "metrics"
    with pytest.raises(Exception):
        KpiCatalogItem(**common)


def test_every_kpi_catalog_nature_has_an_explicit_tab():
    classified = [analytics_tab_for_nature(entry["nature"]) for entry in ENTRIES]
    assert len(classified) == len(ENTRIES)
    assert set(classified) == {"kpi", "metrics"}
    with pytest.raises(ValueError, match="sans analytics_tab"):
        analytics_tab_for_nature("future nature")


def test_cached_metrics_payload_gets_the_rolling_contract_in_memory():
    payload = {
        "nodes": [
            {"node_type": "category", "node_id": "c"},
            {"node_type": "leaf", "node_id": "old"},
            {"node_type": "leaf", "node_id": "new", "analytics_tab": "metrics"},
        ]
    }
    assert _with_analytics_tabs(payload)["nodes"] == [
        {"node_type": "category", "node_id": "c"},
        {"node_type": "leaf", "node_id": "old", "analytics_tab": "metrics"},
        {"node_type": "leaf", "node_id": "new", "analytics_tab": "metrics"},
    ]
