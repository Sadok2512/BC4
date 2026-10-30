from app.routes.settings_cell_ref import _normalize_header, _parse_csv
from app.services.cell_ref_ingest import reference_channels


def test_vendor_channel_headers_remain_distinct():
    assert _normalize_header("earfcn") == "band_mhz"
    assert _normalize_header("dl_earfcn") == "earfcn"
    assert _normalize_header("nr_arfcn") == "nr_arfcn"


def test_ambiguous_1800_is_not_merged_with_exact_earfcn():
    rows, warnings = _parse_csv(
        b"id,rat,earfcn,dl_earfcn,nr_arfcn\n"
        b"lte,LTE,1800,1800,\n"
        b"nr,NR,3500,,643392\n"
    )
    assert warnings == []
    assert rows == [
        {"id": "lte", "rat": "LTE", "band_mhz": "1800", "earfcn": "1800", "nr_arfcn": ""},
        {"id": "nr", "rat": "NR", "band_mhz": "3500", "earfcn": "", "nr_arfcn": "643392"},
    ]


def test_streaming_ingest_uses_the_three_authoritative_columns():
    assert reference_channels(
        {"earfcn": "1800", "dl_earfcn": "1800", "nr_arfcn": "643392"}, "4G"
    ) == (1800, 1800, None)
    assert reference_channels(
        {"earfcn": "3500", "dl_earfcn": "1300", "nr_arfcn": "643392"}, "5G"
    ) == (3500, None, 643392)
    assert reference_channels({"earfcn": "800", "dl_earfcn": ""}, "4G") == (800, None, None)
