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
                "source_column": "event_code",
                "tech": "LTE",
                "kind": "KPI",
                "n_in_project": 126,
                "decoder_version": "1.11.2",
                "event": "HOA",
                "category_label": "Mobility",
                "cell_scoped": False,
                "cells": [],
                "cell_options": [],
                "attributes": [],
                "proof": "catalog-2.68.2",
                "available": True,
            }
        ],
        "nodes": [
            {
                "node_id": "lte",
                "order": 0,
                "label": "LTE",
                "node_type": "tech",
                "proof": None,
            }
        ],
        "decoder_version": "1.11.2",
        "reason": "from_catalog_release",
    }
    parsed = MetricCatalogResponse.model_validate(payload)
    assert parsed.metrics[0].kind == "KPI"
    assert parsed.nodes[0].proof is None
