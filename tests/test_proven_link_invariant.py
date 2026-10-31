import orjson
import pytest

from app.kpi.map_cell_links import enrich_radio_links
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
        return self.rows


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
