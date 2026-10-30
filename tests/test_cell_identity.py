from pathlib import Path

from app.kpi.cell_identity import _enum_values_sql


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
