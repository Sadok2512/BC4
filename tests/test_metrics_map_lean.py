import json

import pytest

from app.kpi import metrics_map
from app.routes import metrics_v3 as route


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self._rows


class _GpsDb:
    def execute(self, statement, params):
        assert "project_id=:pid AND capture_id=:cap" in str(statement)
        assert params == {"pid": "project-a", "cap": "capture-a"}
        return _Rows([{"seq": 7, "lat": 50.0, "lon": 3.0}])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_parallel_gps_read_is_capture_scoped(monkeypatch):
    monkeypatch.setattr(metrics_map, "SessionLocal", lambda: _GpsDb())

    assert metrics_map.load_gps_fixes_scoped("project-a", "capture-a") == [
        {"seq": 7, "lat": 50.0, "lon": 3.0}
    ]


def test_compact_map_point_is_lossless_and_drops_internal_null_fields():
    point = {
        "seq": 7, "lat": 50.0, "lng": 3.0, "code": "rsrp", "value": -95,
        "t_rel_s": 1.5, "tooltip": "RSRP", "_second": 1,
        "position_source": "exact", "serving_cell_ref_id": None,
        "serving_cell_lat": 50.1, "neighbour_links": [],
    }

    compact = route._compact_map_point(point)

    assert compact == {
        "seq": 7, "lat": 50.0, "lng": 3.0, "code": "rsrp", "value": -95,
        "t_rel_s": 1.5,
        "serving_cell_lat": 50.1,
    }


def test_dedicated_route_uses_lean_full_map_contract(monkeypatch):
    calls = {}

    class _Dataset:
        def __init__(self, _db, pid, cap, _filters, lo, hi, lean_series):
            calls["dataset"] = (pid, cap, lo, hi, lean_series)
            self.state = {"decoder_version": "1.9.0"}

        def load(self, metric, **kwargs):
            calls["load"] = kwargs
            return [{"seq": 10, "value": -95.0}]

    point = {
        "seq": 10, "lat": 50.0, "lng": 3.0, "code": "cell_rsrp@lte-type-0",
        "value": -95.0, "t_rel_s": 1.0, "tooltip": "RSRP",
        "position_source": "exact", "delta_seq": 0, "position_fix_seq": 10,
        "serving_cell_id": None, "serving_cell_seq": None,
        "serving_cell_ref_id": None, "serving_site_id": None,
        "serving_site_name": None, "serving_cell_lat": None,
        "serving_cell_lng": None, "serving_cell_source": None,
        "neighbour_links": [], "nr_anchor_link": None,
    }
    monkeypatch.setattr(route, "project", lambda *_: None)
    monkeypatch.setattr(route, "Dataset", _Dataset)
    monkeypatch.setattr(route, "definitions", lambda: {})
    monkeypatch.setattr(route, "parse_selection", lambda *_: {"selection": "metric"})
    monkeypatch.setattr(route, "load_gps_fixes_scoped", lambda *_: [{"seq": 10}])
    monkeypatch.setattr(route, "build_map_points", lambda *_args, **_kwargs: [point])

    response = route.metric_map(
        "project-a", "capture-a", "metric", from_seq=None, to_seq=None,
        f={}, db=object(), cell="all", attr=None, cell_pci=None, cell_arfcn=None,
    )
    payload = json.loads(response.body)

    assert calls["dataset"] == ("project-a", "capture-a", None, None, True)
    assert calls["load"]["include_total"] is False
    assert payload["total_points"] == 1
    assert payload["map_points"] == [point]
    assert "dataset;dur=" in response.headers["server-timing"]


@pytest.mark.parametrize(
    ("rats", "expected_loads", "expected_points"),
    [
        ([], 1, 1),
        (["LTE"], 1, 1),
        (["LTE", "NR"], 1, 1),
        (["NR"], 0, 0),
    ],
)
def test_semantic_map_rat_is_a_union_without_generic_context_scan(
    monkeypatch, rats, expected_loads, expected_points
):
    calls = {"loads": 0}

    class _Dataset:
        def __init__(self, _db, _pid, _cap, filters, _lo, _hi, lean_series):
            calls["filters"] = filters
            calls["lean_series"] = lean_series
            self.state = {"decoder_version": "1.9.0"}

        def load(self, _metric, **_kwargs):
            calls["loads"] += 1
            return [{"seq": 10, "value": -95.0}]

    metric = {
        "selection": "cell_rsrp@lte-type-0",
        "cell_display": {"system": "LTE", "raw_cell_type": 0},
    }
    point = {
        "seq": 10, "lat": 50.0, "lng": 3.0, "code": metric["selection"],
        "value": -95.0, "t_rel_s": 1.0, "tooltip": "RSRP",
        "position_source": "exact", "delta_seq": 0, "position_fix_seq": 10,
        "serving_cell_id": None, "serving_cell_seq": None,
        "serving_cell_ref_id": None, "serving_site_id": None,
        "serving_site_name": None, "serving_cell_lat": None,
        "serving_cell_lng": None, "serving_cell_source": None,
        "neighbour_links": [], "nr_anchor_link": None,
    }
    monkeypatch.setattr(route, "project", lambda *_: None)
    monkeypatch.setattr(route, "Dataset", _Dataset)
    monkeypatch.setattr(route, "definitions", lambda: {})
    monkeypatch.setattr(route, "parse_selection", lambda *_: metric)
    monkeypatch.setattr(route, "load_gps_fixes_scoped", lambda *_: [{"seq": 10}])
    monkeypatch.setattr(route, "build_map_points", lambda *_args, **_kwargs: [point])

    response = route.metric_map(
        "project-a", "capture-a", metric["selection"], from_seq=None, to_seq=None,
        f={"rat": rats} if rats else {}, db=object(), cell="all", attr=None,
        cell_pci=None, cell_arfcn=None,
    )
    payload = json.loads(response.body)

    assert calls["filters"] == {}
    assert calls["lean_series"] is True
    assert calls["loads"] == expected_loads
    assert payload["total_points"] == expected_points


def test_untyped_map_metric_keeps_rat_context_filter():
    selected = [{"selection": "untyped", "cell_display": None}]
    filters = {"rat": ["LTE", "NR"]}

    assert route._apply_intrinsic_map_rat(selected, filters) == (selected, filters)
