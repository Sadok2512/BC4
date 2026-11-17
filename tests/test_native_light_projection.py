from datetime import datetime, timezone
from types import SimpleNamespace

from app.nmf_decoder.projection import source_sql
from app.nmf_decoder import store
from app.kpi import cell_identity
from app.kpi.metrics_catalog_v4 import _column_for_leaf
from app.schemas.ingest import NmfFileEntry
from app.services.import_report import enrich_file_entries


def test_header_projection_reads_native_values_and_keeps_legacy_fallback():
    sql = source_sql('pdsch_bler')
    assert "d.values->>'pdsch_bler'" in sql
    assert 'FROM nmf_event_light_native d' in sql
    assert 'FROM nmf_event_light d' in sql
    assert 'NOT EXISTS (' in sql


def test_group_projection_reads_native_group_zero():
    sql = source_sql('cell_rsrp')
    assert "g.item->2->>'cell_rsrp'" in sql
    assert "g.item->>0='cells'" in sql
    assert '(g.item->>1)::integer=0' in sql


def test_cell_identity_materializer_reads_native_groups():
    source = open(cell_identity.__file__, encoding='utf-8').read()
    assert 'FROM nmf_event_light_native n' in source
    assert "g.item->2->>'cell_ch'" in source
    assert 'NOT EXISTS (' in source


def test_durable_report_entries_are_enriched_from_committed_capture_facts():
    uploaded = datetime(2026, 11, 17, 13, 48, 32, tzinfo=timezone.utc)
    file = SimpleNamespace(id='file-id', sha256='sha', uploaded_at=uploaded)

    class Query:
        def filter(self, *args): return self
        def all(self): return [file]

    class Result:
        def all(self): return [('file-id', 'capture-b', 7), ('file-id', 'capture-a', 5)]

    class DB:
        def query(self, model): return Query()
        def execute(self, statement, params): return Result()

    entry = NmfFileEntry(
        filename='sample.nmf', size_bytes=1, sha256='sha', status='done',
        n_captures=2, n_events=3, n_gps=0, decoder_version='test',
        error_msg=None,
    )
    enriched = enrich_file_entries(DB(), 'project', [entry])[0]
    assert enriched.capture_ids == ['capture-b', 'capture-a']
    assert enriched.n_records == 12
    assert enriched.imported_at == '2026-11-17T13:48:32Z'


def test_released_phrate_selector_maps_to_native_decoder_column():
    assert _column_for_leaf({"metric_id": "phrate_pdsch_bitrate_0@0"}) == "pdsch_bitrate_cw0"


def test_light_decode_materializes_the_legacy_compatibility_projection():
    source = open(store.__file__, encoding='utf-8').read()
    assert 'write_light(db,pid,cap,light,persist=True)' in source
