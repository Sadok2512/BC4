from pathlib import Path

from app.kpi.cell_identity import _enum_values_sql
from app.kpi.metrics_catalog_v4 import _is_physical_neighbour


def test_enum_values_cover_injective_storage_ranges():
    values = _enum_values_sql()
    assert "(7,2,1165)" in values
    assert "(9,1000,9751)" in values


def test_semantic_loader_uses_materialized_physical_identity():
    source = Path("app/kpi/metrics_v3.py").read_text()
    loader = source[source.index("def _load_semantic_cell"):source.index("def load(")]
    assert "JOIN nmf_cell_identity i" in loader
    assert "i.cell_arfcn=:cell_arfcn" in loader
    assert "i.cell_pci=:cell_pci" in loader
    assert "row_number() OVER" not in loader


def test_series_route_forwards_physical_cell_filters():
    source = Path("app/routes/metrics.py").read_text()
    route = source[source.index("def series("):source.index("EVENT_SQL =")]
    assert "cell_pci:int|None=Query(None,ge=0)" in route
    assert "cell_arfcn:int|None=Query(None,ge=0)" in route
    assert "cell_pci=cell_pci" in route
    assert "cell_arfcn=cell_arfcn" in route


def test_only_content_defined_cellmeas_neighbours_expand_by_radio_identity():
    assert _is_physical_neighbour("CELLMEAS", 7, 1)
    assert _is_physical_neighbour("CELLMEAS", 7, 2)
    assert _is_physical_neighbour("CELLMEAS", 9, 1000)
    assert _is_physical_neighbour("CELLMEAS", 9, 1001)
    assert _is_physical_neighbour("CELLMEAS", 9, 1002)
    assert not _is_physical_neighbour("CELLMEAS", 7, 0)
    assert not _is_physical_neighbour("CELLMEAS", 7, 10)
    assert not _is_physical_neighbour("MIMOMEAS", 7, 1)
