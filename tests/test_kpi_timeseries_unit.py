"""Unit tests for the generic Metric vs Time engine.

These tests exercise the resolution and refusal paths of
``kpi_time_series()`` without hitting the database — the mock DB only
answers deterministically to the queries that the engine issues on each
branch. The AVAILABLE path (which requires decoded data) is covered by
the live guard G1 against a real capture.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi import HTTPException
import pytest

from app.routes import kpi_timeseries as ts_mod


# ---------------------------------------------------------------------------
# Minimal fakes
# ---------------------------------------------------------------------------


class _FakeProject:
    pass


class _FakeDB:
    """Fake Session that returns pre-canned rows for each test case.

    ``exec_rows`` maps a substring of the SQL to the mapping rows to
    return. ``get(Project, pid)`` controls project resolution.
    """

    def __init__(self, *, project_exists: bool = True, exec_rows: dict[str, list[dict[str, Any]]] | None = None):
        self._project = _FakeProject() if project_exists else None
        self._exec_rows = exec_rows or {}

    def get(self, _model: Any, _pid: str) -> Any:
        return self._project

    def execute(self, sql, params=None):  # noqa: ARG002
        text = str(sql)
        rows: list[dict[str, Any]] = []
        for key, value in self._exec_rows.items():
            if key in text:
                rows = value
                break

        class _Result:
            def __init__(self, rows_: list[dict[str, Any]]):
                self._rows = rows_

            def mappings(self):
                return self

            def first(self):
                return self._rows[0] if self._rows else None

            def all(self):
                return list(self._rows)

            def scalar(self):
                return self._rows[0]["value"] if self._rows else False

            def scalar_one(self):
                return bool(self._rows)

        return _Result(rows)

    def commit(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Resolution refusals
# ---------------------------------------------------------------------------


def test_project_missing_returns_404():
    db = _FakeDB(project_exists=False)
    with pytest.raises(HTTPException) as exc:
        ts_mod.kpi_time_series(
            project_id="TEST-project",
            capture_id="TEST-capture",
            code="LTE_DL_BLER",
            max_points=5000,
            db=db,
        )
    assert exc.value.status_code == 404


def test_unknown_kpi_code_returns_unavailable():
    db = _FakeDB(project_exists=True)
    resp = ts_mod.kpi_time_series(
        project_id="TEST-project",
        capture_id="TEST-capture",
        code="NOT_A_REAL_KPI_CODE_XYZ",
        max_points=5000,
        db=db,
    )
    assert resp["status"] == "UNAVAILABLE"
    assert resp["reason"] == "unknown_kpi_code"
    assert resp["points"] == []
    assert resp["n_total"] == 0
    assert resp["x_axis"]["unit"] == "s"


def test_calculated_kpi_without_direct_metric_returns_unavailable():
    """A KPI whose rule is e.g. ``param_message_eq`` has no direct
    temporal mapping. Must declare UNAVAILABLE with explicit reason —
    never fabricate a series."""
    db = _FakeDB(project_exists=True)

    # Inject a fake catalog entry with a non-nmf_metric rule.
    fake_entry = {
        "code": "FAKE_CALCULATED",
        "name": "Fake Calculated KPI",
        "unit": None,
        "available_check": {"kind": "param_message_eq", "arg": "RRCConnectionSetup"},
    }
    with patch.object(ts_mod, "catalog_v2_resolve", return_value="FAKE_CALCULATED"), \
         patch.object(ts_mod, "catalog_v2_get", return_value=fake_entry):
        resp = ts_mod.kpi_time_series(
            project_id="TEST-project",
            capture_id="TEST-capture",
            code="FAKE_CALCULATED",
            max_points=5000,
            db=db,
        )
    assert resp["status"] == "UNAVAILABLE"
    assert "no_direct_metric_mapping" in resp["reason"]
    assert "param_message_eq" in resp["reason"]
    assert resp["points"] == []


def test_nmf_metric_absent_from_catalog_returns_unavailable():
    """nmf_metric rule but ``arg`` is not in metric_catalog(db)."""
    db = _FakeDB(project_exists=True)
    fake_entry = {
        "code": "FAKE_NMF_UNMAPPED",
        "name": "Fake unmapped NMF",
        "unit": "%",
        "available_check": {"kind": "nmf_metric", "arg": "nonexistent_field_abcd"},
    }
    with patch.object(ts_mod, "catalog_v2_resolve", return_value="FAKE_NMF_UNMAPPED"), \
         patch.object(ts_mod, "catalog_v2_get", return_value=fake_entry), \
         patch.object(ts_mod, "metric_catalog", return_value={}):
        resp = ts_mod.kpi_time_series(
            project_id="TEST-project",
            capture_id="TEST-capture",
            code="FAKE_NMF_UNMAPPED",
            max_points=5000,
            db=db,
        )
    assert resp["status"] == "UNAVAILABLE"
    assert "metric_not_in_nmf_catalog" in resp["reason"]
    assert resp["evidence"]["metric_code_nmf"] == "nonexistent_field_abcd"


def test_capture_not_decoded_returns_unavailable():
    """nmf_metric rule, metric exists in catalog, but the capture has
    no ``nmf_capture`` row for this project → UNAVAILABLE
    ``capture_not_decoded_for_project``."""
    db = _FakeDB(project_exists=True, exec_rows={})
    fake_entry = {
        "code": "LTE_DL_BLER",
        "name": "LTE DL BLER",
        "unit": "%",
        "available_check": {"kind": "nmf_metric", "arg": "pdsch_bler"},
    }

    from app.kpi.metrics import Metric
    fake_metric = Metric(
        label="PDSCH BLER",
        unit="%",
        source_table="nmf_event_deep",
        source_column="pdsch_bler",
        tech="LTE",
        kind="numeric",
        sql="SELECT 1 AS capture_id,1 AS seq,1 AS value",
    )
    with patch.object(ts_mod, "catalog_v2_resolve", return_value="LTE_DL_BLER"), \
         patch.object(ts_mod, "catalog_v2_get", return_value=fake_entry), \
         patch.object(ts_mod, "metric_catalog", return_value={"pdsch_bler": fake_metric}):
        resp = ts_mod.kpi_time_series(
            project_id="TEST-project",
            capture_id="TEST-capture",
            code="LTE_DL_BLER",
            max_points=5000,
            db=db,
        )
    assert resp["status"] == "UNAVAILABLE"
    assert resp["reason"] == "capture_not_decoded_for_project"


# ---------------------------------------------------------------------------
# Contract-shape sanity
# ---------------------------------------------------------------------------


def test_axes_always_declare_unit_s_for_x():
    """Rule n°2 BC4 : no silent fallback, no missing unit on the axes."""
    db = _FakeDB(project_exists=True)
    resp = ts_mod.kpi_time_series(
        project_id="TEST-project",
        capture_id="TEST-capture",
        code="NOT_A_REAL_KPI_CODE_XYZ",
        max_points=5000,
        db=db,
    )
    assert resp["x_axis"]["field"] == "capture_time_s"
    assert resp["x_axis"]["unit"] == "s"
    assert "y_axis" in resp
