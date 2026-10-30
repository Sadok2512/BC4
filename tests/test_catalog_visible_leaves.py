import copy
import json

import pytest

from scripts.catalog import bootstrap_catalog_release as bootstrap


def source_payload() -> dict:
    return {
        "catalog_version": "2.58.0",
        "nodes": [{"node_id": "leaf", "node_type": "leaf"}],
        "analytics_series_decisions": [
            {
                "code": code,
                "event": event,
                "visible": False,
                "decision": "removed_until_series_supported",
                "reason": reason,
            }
            for code, event, reason in bootstrap.ANALYTICS_SERIES_REMOVALS
        ],
    }


def test_prepare_visible_leaves_unmasks_exact_supported_set(monkeypatch, tmp_path):
    payload = source_payload()
    source = tmp_path / "catalog_2.58.0.json"
    target = tmp_path / "catalog_2.59.0.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        bootstrap,
        "catalog_file_path",
        lambda version: source if version == "2.58.0" else target,
    )

    bootstrap.prepare_visible_leaves_minor("2.58.0", "2.59.0")

    result = json.loads(target.read_text(encoding="utf-8"))
    rows = result["analytics_series_decisions"]
    assert result["catalog_version"] == "2.59.0"
    assert len(rows) == len(bootstrap.ANALYTICS_SERIES_REMOVALS) == 61
    assert all(row["visible"] is True for row in rows)
    assert {row["decision"] for row in rows} == {"visible_series_supported"}
    assert {row["support_commit"] for row in rows} == {"12ff6f0"}
    assert result["analytics_visibility_policy"]["label_fields_used"] is False


def test_prepare_visible_leaves_rejects_partial_source(monkeypatch, tmp_path):
    payload = source_payload()
    payload["analytics_series_decisions"].pop()
    source = tmp_path / "catalog_2.58.0.json"
    target = tmp_path / "catalog_2.59.0.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        bootstrap,
        "catalog_file_path",
        lambda version: source if version == "2.58.0" else target,
    )

    with pytest.raises(ValueError, match="décisions de séries inattendues"):
        bootstrap.prepare_visible_leaves_minor("2.58.0", "2.59.0")


def test_prepare_visible_leaves_does_not_touch_other_decisions(monkeypatch, tmp_path):
    payload = source_payload()
    other = {
        "code": "unrelated",
        "event": "OTHER",
        "visible": False,
        "decision": "product_hidden",
        "reason": "unrelated",
    }
    payload["analytics_series_decisions"].append(copy.deepcopy(other))
    source = tmp_path / "catalog_2.58.0.json"
    target = tmp_path / "catalog_2.59.0.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        bootstrap,
        "catalog_file_path",
        lambda version: source if version == "2.58.0" else target,
    )

    bootstrap.prepare_visible_leaves_minor("2.58.0", "2.59.0")

    result = json.loads(target.read_text(encoding="utf-8"))
    assert result["analytics_series_decisions"][-1] == other


def test_prepare_visible_leaves_requires_next_minor():
    with pytest.raises(ValueError, match="MINOR suivant"):
        bootstrap.prepare_visible_leaves_minor("2.58.0", "2.58.1")
