from app.ingest.nmf import _nff250_category
from app.nmf_decoder import DECODER_VERSION
from app.nmf_decoder.decoder import decode
from app.nmf_decoder.schema import schemas


def test_decoder_version_and_complete_lte_plaiu_schema():
    assert DECODER_VERSION == "1.9.0"
    schema = schemas()["PLAIU"]
    assert schema["spec_version"] == "2.50"
    assert schema["schema_version"] == "1.9.0"
    assert schema["header"][-1]["code"] == "plaiu.cell_type"
    assert schema["header"][-1]["enum"] == list(range(32))
    assert [field["code"] for field in schema["groups"][0]["fields"]] == [
        "plaiu.percentage", "plaiu.rank", "plaiu.mod0", "plaiu.mcs0",
        "plaiu.mod1", "plaiu.mcs1", "plaiu.n_rep", "plaiu.tbs0", "plaiu.tbs1",
    ]
    assert [field["code"] for field in schema["groups"][1]["fields"]] == [
        "plaiu.prb_percentage", "plaiu.prbs", "plaiu.scs",
    ]


def test_plaiu_nff250_record_is_fully_named():
    # NFF 2.50 LTE: header width 5, one PLA set of width 9, one PRB set
    # of width 3, and one PRB-index set of width 2.
    line = (
        "PLAIU,12:34:56.000,,7,5,1000,50,100,200,5,"
        "1,9,100,1,4,31,3,30,2,1024,512,"
        "1,3,100,50,600,"
        "1,2,75,12"
    )
    record = decode(line, format_version="2.50")
    assert record.decode_status == "ok"
    assert record.values["plaiu_cell_type"] == 5
    assert not [code for code in record.field_codes if code.startswith("unk_")]
    assert record.groups[0]["values"]["plaiu_n_rep"] == 2
    assert record.groups[0]["values"]["plaiu_tbs1"] == 512
    assert record.groups[1]["values"]["plaiu_scs"] == 600


def test_top_three_other_codes_are_classified_by_nff_content():
    assert _nff250_category("PHRATE", "other") == "throughput"
    assert _nff250_category("PLAID", "other") == "measurement"
    assert _nff250_category("MACRATE", "other") == "throughput"
    assert _nff250_category("UNKNOWN", "other") == "other"
    assert _nff250_category("PHRATE", "custom") == "custom"
