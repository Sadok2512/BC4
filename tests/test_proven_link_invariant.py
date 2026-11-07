import orjson
import pytest

from app.kpi.map_cell_links import (
    enrich_metric_role_serving_links,
    enrich_probable_serving_links,
    enrich_radio_links,
    metric_serving_identity,
)
from app.kpi.probable_link_materialized import apply_materialized


class _Result:
    def __init__(self, *, scalar=None, rows=()):
        self.scalar = scalar
        self.rows = rows

    def scalar_one(self):
        return self.scalar

    def scalar_one_or_none(self):
        return self.scalar

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class _MaterializedDb:
    def __init__(self, state, rows=()):
        self.results = iter([
            _Result(scalar="ref-v1"),
            _Result(scalar=state),
            *([_Result(rows=rows)] if state == "ref-v1" else []),
        ])

    def execute(self, *_args, **_kwargs):
        return next(self.results)


class _NoIdentityDb:
    def execute(self, *_args, **_kwargs):
        return _Result(rows=[])


class _CrossEventMetricDb:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "ORDER BY uploaded_at" in sql:
            return _Result(scalar="ref-v1")
        if "FROM nmf_probable_cell_link_state" in sql:
            return _Result(scalar="ref-v1")
        if "seq=ANY(:seqs)" in sql:
            return _Result(rows=[])
        if "WITH targets AS" in sql:
            return _Result(rows=[{
                "seq": 205,
                "link_payload": orjson.dumps(self.payload).decode(),
            }])
        raise AssertionError(sql)


class _ServingRowsDb:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, statement, params=None):
        assert "project_id=:pid AND capture_id=:cap" in str(statement)
        assert params == {"pid": "project", "cap": "capture"}
        return _Result(rows=self.rows)


class _ServingLookup:
    def match(self, system, bands, pci, lat, lng):
        assert (system, bands, pci) == (7, (1800,), 195)
        assert (lat, lng) == (50.363, 3.037)
        return ({
            "id": "cell-ref-195",
            "site_id": "site-1",
            "site_name": "Serving",
            "lat": 50.37,
            "lng": 3.04,
        }, 850.0, 1, "band_pci_nearest", None)


@pytest.mark.parametrize(
    ("state", "rows"),
    [
        ("stale-ref", ()),
        ("ref-v1", ()),
        ("ref-v1", ({
            "seq": 1,
            "link_payload": orjson.dumps({
                "serving_link": None,
                "neighbour_links": [],
                "nr_anchor_link": None,
            }).decode(),
        },)),
    ],
    ids=["stale-cache", "fresh-missing-row", "fresh-row"],
)
def test_every_materialized_path_preserves_upstream_proven_serving(state, rows):
    point = {"seq": 1, "serving_cell_ref_id": "cell-ref-proven"}

    apply_materialized(_MaterializedDb(state, rows), "project", "capture", [point])

    assert point["serving_cell_ref_id"] == "cell-ref-proven"
    assert point["confidence"] == "proven"
    assert point["link_method"] == "earfcn_pci"


def test_live_enrichment_early_return_preserves_upstream_proven_serving():
    point = {"seq": 1, "serving_cell_ref_id": "cell-ref-proven"}

    enrich_radio_links(_NoIdentityDb(), "project", "capture", [point])

    assert point["serving_cell_ref_id"] == "cell-ref-proven"
    assert point["confidence"] == "proven"
    assert point["link_method"] == "earfcn_pci"


def test_materialized_cache_does_not_borrow_pcell_for_cross_event_metric():
    db = _CrossEventMetricDb(None)
    point = {
        "seq": 205,
        "_second": 12,
        "lat": 50.363,
        "lng": 3.037,
    }

    assert apply_materialized(db, "project", "capture", [point]) is True

    assert "probable_serving_cell_ref_id" not in point
    assert not any("WITH targets AS" in sql for sql, _ in db.calls)


def test_mac_roles_map_to_their_own_cellmeas_identity_enum():
    assert metric_serving_identity({
        "event": "MACRATE", "cell_type_filter": {"system": 7, "raw_cell_type": 0}
    }) == (0, "PCell")
    assert metric_serving_identity({
        "event": "MACRATE", "cell_type_filter": {"system": 7, "raw_cell_type": 1}
    }) == (10, "SCell 1")
    assert metric_serving_identity({
        "event": "MACRATEU", "cell_type_filter": {"system": 7, "raw_cell_type": 4}
    }) == (13, "SCell 4")
    assert metric_serving_identity({
        "event": "CELLMEAS", "cell_type_filter": {"system": 7, "raw_cell_type": 1}
    }) == (None, None)


class _RoleIdentityDb:
    def execute(self, statement, params=None):
        sql = str(statement)
        assert "COUNT(DISTINCT (i.cell_arfcn,i.cell_pci))=1" in sql
        assert params["cell_types"] == [10]
        return _Result(rows=[{
            "target_seq": 205, "cell_type": 10,
            "cell_arfcn": 1300, "cell_pci": 195,
        }])


def test_scell_metric_link_uses_scell_identity_and_exposes_role():
    point = {
        "seq": 205, "_second": 12, "_identity_cell_type": 10,
        "_cell_role": "SCell 1", "lat": 50.363, "lng": 3.037,
    }
    enrich_metric_role_serving_links(
        _RoleIdentityDb(), "project", "capture", [point], _ServingLookup()
    )
    assert point["serving_cell_role"] == "SCell 1"
    assert point["serving_cell_arfcn"] == 1300
    assert point["probable_serving_cell_ref_id"] == "cell-ref-195"


def test_live_links_follow_only_preceding_identity_in_same_second():
    db = _ServingRowsDb([
        {"second": 12, "seq": 200, "cell_ch": 1300, "cell_pci": 195},
        # This future identity must not be selected for point seq 205.
        {"second": 12, "seq": 210, "cell_ch": 1300, "cell_pci": 196},
    ])
    point = {
        "seq": 205,
        "_second": 12,
        "lat": 50.363,
        "lng": 3.037,
    }

    enrich_probable_serving_links(
        db, "project", "capture", [point], _ServingLookup()
    )

    assert point["probable_serving_cell_ref_id"] == "cell-ref-195"
    assert point["probable_serving_pci"] == 195
