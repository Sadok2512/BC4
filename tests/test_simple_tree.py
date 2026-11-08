from pathlib import Path

from app.kpi.simple_tree import load_simple_leaves, load_simple_tree


def test_certified_simple_tree_has_71_unique_kpi_and_unique_leaf_names():
    rows = load_simple_tree()
    leaves = load_simple_leaves()
    assert len(rows) == 71
    assert len({(row.tech, row.kpi) for row in rows}) == 71
    assert len({leaf.simple_name for leaf in leaves.values()}) == len(leaves)
    assert {row.tech for row in rows} == {"LTE", "NR"}


def test_requested_derived_kpis_are_closed_and_open_sources_stay_open():
    rows = {(row.tech, row.kpi): row for row in load_simple_tree()}
    assert rows["LTE", "THP_DL_CA_TOTAL"].families == ("lte_thp_dl_ca_total",)
    assert rows["LTE", "CA_NB_SCELLS"].families == ("lte_ca_nb_scells",)
    assert rows["LTE", "HO_FAILURE"].families == ("lte_ho_failure",)
    assert rows["LTE", "REEST_HO_FAILURE"].families == ("lte_reest_ho_failure",)
    assert rows["LTE", "REEST_RECONFIG_FAILURE"].families == (
        "lte_reest_reconfig_failure",
    )
    assert rows["LTE", "REEST_REJECTED"].families == ("lte_reest_rejected",)
    assert rows["LTE", "RRC_SETUP_FAILURE"].families == ("lte_rrc_setup_failure",)
    assert rows["LTE", "THP_UL_MAC"].status == "open"
    assert rows["LTE", "BLER_UL"].status == "open"


def test_failure_detector_metrics_have_explicit_simple_tree_leaves():
    leaves = load_simple_leaves()
    expected = {
        "lte_ho_failure": ("LTE_HO_FAILURE", "LTE", "HO_FAILURE"),
        "lte_reest_ho_failure": (
            "LTE_REEST_HO_FAILURE",
            "LTE",
            "REEST_HO_FAILURE",
        ),
        "lte_reest_reconfig_failure": (
            "LTE_REEST_RECONFIG_FAILURE",
            "LTE",
            "REEST_RECONFIG_FAILURE",
        ),
        "lte_reest_rejected": ("LTE_REEST_REJECTED", "LTE", "REEST_REJECTED"),
        "lte_rrc_setup_failure": (
            "LTE_RRC_SETUP_FAILURE",
            "LTE",
            "RRC_SETUP_FAILURE",
        ),
    }
    assert {
        metric_id: (
            leaves[metric_id].simple_name,
            leaves[metric_id].tech,
            leaves[metric_id].kpi,
        )
        for metric_id in expected
    } == expected


def test_ca_queries_are_capture_seq_ordered_and_never_timestamp_ordered():
    source = Path("app/kpi/metrics_v3.py").read_text(encoding="utf-8")
    start = source.index("if m['base_code'] in {'lte_thp_dl_ca_total'")
    end = source.index("elif m.get('cell_type_filter')", start)
    block = source[start:end]
    assert "GROUP BY capture_id,seq_first" in block
    assert "ORDER BY capture_id,seq_first" in block
    assert " ts" not in block.lower()
