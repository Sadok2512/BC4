from app.routes.metrics import MetricCatalogResponse


def test_catalog_response_accepts_active_catalog_kinds_and_structural_proof_null():
    payload = {
        "catalogue_version": "2.68.2",
        "title": "Metrics",
        "header": "Metrics",
        "metrics": [
            {
                "code": "lte_ho_attempts",
                "label": "HO Attempts",
                "unit": "count",
                "source_table": "nmf_event_deep",
                "source_tables": ["nmf_event_deep"],
                "source_column": None,
                "tech": "LTE",
                "kind": "KPI",
                "n_in_project": 126,
                "decoder_version": "1.11.2",
                "event": None,
                "category_label": "Mobility",
                "cell_scoped": False,
                "cells": [],
                "cell_options": [],
                "attributes": [],
                "proof": "catalog-2.68.2",
                "available": True,
                "event_code": None,
            }
        ],
        "nodes": [
            {
                "node_id": "lte",
                "order": 0,
                "label": "LTE",
                "node_type": "tech",
                "proof": None,
                "availability_status": "not_available",
            }
        ],
        "decoder_version": "1.11.2",
        "reason": "from_catalog_release",
    }
    parsed = MetricCatalogResponse.model_validate(payload)
    assert parsed.metrics[0].kind == "KPI"
    assert parsed.nodes[0].proof is None


def test_catalog_response_accepts_simple_tree_contract():
    payload = {
        "catalogue_version": "2.68.5",
        "title": "Metrics",
        "header": "Metrics",
        "metrics": [],
        "nodes": [],
        "simple_tree": [
            {
                "tech": "LTE",
                "theme": "2 · Débit DL",
                "kpi": "THP_DL_CA_TOTAL",
                "label": "Débit DL total CA",
                "families": ["lte_thp_dl_ca_total"],
                "unit": "Mbit/s",
                "status": "ok",
            }
        ],
    }
    parsed = MetricCatalogResponse.model_validate(payload)
    assert parsed.simple_tree[0].kpi == "THP_DL_CA_TOTAL"
