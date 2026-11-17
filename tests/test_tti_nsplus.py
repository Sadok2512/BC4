from app.kpi.metrics import metric_catalog
from app.kpi.metrics_catalog_v4 import _append_tti_nsplus_metrics
from app.kpi.metrics_v3 import _table_group_key, definitions
from app.nmf_decoder.decoder import decode
from app.nmf_decoder.native import native_row


LINE = (
    'TTI_NSPLUS,15:19:38.623,,7,29,780,9,0,,7,16,28,1,2,0,"LTE"'
)


def test_tti_nsplus_decodes_the_ns8_per_tb_contract():
    record = decode(
        LINE, format_version="2.59", capture_id="tti-capture", seq=41
    )

    assert record.event_code == "TTI_NSPLUS"
    assert record.system == 7
    assert record.decode_status == "ok"
    assert record.reasons == []
    assert record.values == {
        "tti_frame_idx": 29,
        "tti_sfn": 780,
        "tti_subfn": 9,
        "tti_carrier": 0,
        "tti_rnti": None,
        "tti_mcs": 7,
        "tti_prb": 16,
        "tti_tbs_bytes": 28,
        "tti_crc_ok": 1,
        "tti_harq_id": 2,
        "tti_rv": 0,
        "tti_rat": "LTE",
    }


def test_tti_nsplus_is_retained_in_compact_light_storage():
    record = decode(
        LINE, format_version="2.59", capture_id="tti-capture", seq=41
    )
    record.t_rel_s = 0.001
    row = native_row("project", record, {})

    assert row["partial"] is False
    assert row["values"]["tti_mcs"] == 7
    assert row["values"]["tti_tbs_bytes"] == 28
    assert row["values"]["tti_rat"] == "LTE"


def test_tti_metrics_are_queryable_and_keep_raw_table_rows():
    defs = definitions()
    catalog = metric_catalog(None)

    assert defs["tti_mcs"]["native_tti"] is True
    assert defs["tti_crc_ok"]["enum_values"] == {0: "FAIL", 1: "OK"}
    assert catalog["tti_tbs_bytes"].unit == "byte"
    assert "tti_rnti" not in catalog
    assert "tti_rat" not in catalog
    assert _table_group_key(
        defs["tti_mcs"], {"seq": 123}, 17, table_only=True
    ) == (123, None, None)


def test_tti_catalog_branch_is_content_gated_and_excludes_rnti():
    class Result:
        @staticmethod
        def scalar():
            return 3278

    class Session:
        @staticmethod
        def execute(statement, parameters):
            assert parameters["pid"] == "project"
            return Result()

    nodes = [{"node_id": "cat_LTE_allocation_mcs"}]
    metrics = []
    _append_tti_nsplus_metrics(
        Session(), "project", (), {}, nodes, metrics, {}
    )

    assert next(node for node in nodes if node["node_id"] == "ev_tti_nsplus")["n"] == 3278
    assert next(item for item in metrics if item["code"] == "tti_mcs")["n_in_project"] == 3278
    assert {item["code"] for item in metrics}.isdisjoint({"tti_rnti", "tti_rat"})
