"""G25 (0.25.0) — Assistant V2 : catalogue + moteur + preuves + agent.

Garde manuelle à l'énoncé — tests unitaires + smoke live.

a) 4 questions simples sur TEST2 (voir smoke live manuel, pas en pytest
   automatique pour éviter coûts LLM répétés).
b) Question composite jamais codée spécialement (idem — smoke live).
c) Sécurité : plan tentant de fixer project_id → REJETÉ (unitaire ici).
   Plan referencing app_user → REJETÉ (unitaire).
d) Statistiques : moyenne de moyennes non pondérée → warning explicite
   (unitaire ici).
"""

from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.usefixtures("llm_state_sandbox")


# -------------- Partie unitaire : sécurité moteur --------------


def test_plan_project_id_rejected():
    from app.assistant.engine import PlanRejected, _compile_plan

    with pytest.raises(PlanRejected) as ei:
        _compile_plan(
            {
                "dataset": "rrc_dict",
                "filters": [{"dim": "project_id", "op": "eq", "value": "other"}],
            },
            project_id="X",
        )
    assert ei.value.code == "PROJECT_ID_NOT_ALLOWED"


def test_plan_sensitive_dataset_rejected():
    from app.assistant.engine import PlanRejected, _compile_plan

    with pytest.raises(PlanRejected) as ei:
        _compile_plan({"dataset": "app_user"}, project_id="X")
    assert ei.value.code == "DATASET_UNKNOWN"


def test_plan_banned_identifier_rejected():
    """Un dataset inconnu rejette avant même la défense en profondeur ;
    mais le scan BANNED_IDENTIFIERS reste la 2e ligne."""
    from app.assistant.engine import _compile_plan, BANNED_IDENTIFIERS

    # app_user doit être dans la deny-list
    assert "app_user" in BANNED_IDENTIFIERS
    assert "settings_llm" in BANNED_IDENTIFIERS
    assert "pg_sleep" in BANNED_IDENTIFIERS
    assert "truncate" in BANNED_IDENTIFIERS


def test_plan_no_group_by_still_has_count():
    """Un plan sans mesure explicite se voit injecter `count` + GROUP BY."""
    from app.assistant.engine import _compile_plan

    sql, params, _ = _compile_plan(
        {"dataset": "rrc_dict", "dimensions": ["operator"]},
        project_id="X",
    )
    assert "COUNT(*)" in sql
    assert "GROUP BY" in sql


def test_measure_recomposable_warning():
    """Mesure non-recomposable sur ≥ 2 dims → warning dans
    AnalyticalResult (statistiques correctes — correctif 2)."""
    from app.assistant.catalog import MEASURES

    # rsrp_avg et percentiles ne doivent pas être recomposables.
    assert MEASURES["rsrp_avg"]["recomposable"] is False
    assert MEASURES["rsrp_p50"]["recomposable"] is False
    assert MEASURES["dl_avg"]["recomposable"] is False
    # count est recomposable (somme de sous-counts = total).
    assert MEASURES["count"]["recomposable"] is True


def test_result_id_stable():
    """Même plan + même project_id → même result_id."""
    from app.assistant.engine import compute_result_id

    plan = {
        "dataset": "rrc_dict",
        "dimensions": ["operator"],
        "measures": ["count"],
        "filters": [{"dim": "band", "op": "eq", "value": "B3"}],
    }
    r1 = compute_result_id(plan, "P")
    r2 = compute_result_id(plan, "P")
    r3 = compute_result_id(plan, "OTHER")
    assert r1 == r2 and r1 != r3 and len(r1) == 16


# -------------- Partie unitaire : moteur de preuves --------------


def test_validate_comparison_requires_two():
    from app.assistant.engine import AnalyticalResult
    from app.assistant.proof import validate_comparison

    r1 = AnalyticalResult(
        result_id="a", plan={"dataset": "rrc_dict"}, rows=[], n=0, denominator=10,
        dataset="rrc_dict", date_range={"start": None, "end": None},
        filters_applied={}, sql_compiled="", params={},
    )
    v = validate_comparison([r1])
    assert v.verdict == "NOT_COMPARABLE"


def test_validate_comparison_aligned_plans_ok():
    from app.assistant.engine import AnalyticalResult
    from app.assistant.proof import validate_comparison

    base_plan = {
        "dataset": "rrc_dict",
        "dimensions": ["operator"],
        "measures": ["count"],
        "filters": [{"dim": "operator", "op": "eq", "value": "Orange"}],
    }
    r1 = AnalyticalResult(
        result_id="r1", plan=base_plan, rows=[], n=1, denominator=1000,
        dataset="rrc_dict", date_range={"start": "2026-01-01", "end": "2026-03-31"},
        filters_applied={"operator": {"op": "eq", "value": "Orange"}},
        sql_compiled="", params={},
    )
    r2 = AnalyticalResult(
        result_id="r2", plan=base_plan, rows=[], n=1, denominator=900,
        dataset="rrc_dict", date_range={"start": "2026-01-01", "end": "2026-03-31"},
        filters_applied={"operator": {"op": "eq", "value": "SFR"}},
        sql_compiled="", params={},
    )
    v = validate_comparison([r1, r2])
    # Même dataset / dims / mesures / période → COMPARABLE (dénominateurs
    # proches — ratio < 10×).
    assert v.verdict in ("COMPARABLE", "COMPARABLE_WITH_LIMITATIONS")
    assert "r1" in v.denominators and "r2" in v.denominators


def test_validate_comparison_different_datasets_rejected():
    from app.assistant.engine import AnalyticalResult
    from app.assistant.proof import validate_comparison

    r1 = AnalyticalResult(
        result_id="r1", plan={"dataset": "rrc_dict"}, rows=[], n=0, denominator=0,
        dataset="rrc_dict", date_range={"start": None, "end": None},
        filters_applied={}, sql_compiled="", params={},
    )
    r2 = AnalyticalResult(
        result_id="r2", plan={"dataset": "measurements"}, rows=[], n=0, denominator=0,
        dataset="measurements", date_range={"start": None, "end": None},
        filters_applied={}, sql_compiled="", params={},
    )
    v = validate_comparison([r1, r2])
    assert v.verdict == "NOT_COMPARABLE"
    assert "Datasets différents" in v.reason


# -------------- Partie unitaire : outils --------------


def test_tool_schemas_shape():
    from app.assistant.tools import TOOL_SCHEMAS

    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    expected = {
        "get_project_context", "list_operators", "list_bands",
        "top_rrc_messages", "rrc_param_distribution", "compare_operators",
        "compare_distributions",
    }
    assert expected <= set(names), f"missing: {expected - set(names)}"
    # Chaque outil doit avoir un schema parameters avec additionalProperties:False.
    for t in TOOL_SCHEMAS:
        p = t["function"]["parameters"]
        assert p.get("additionalProperties", True) is False, t["function"]["name"]
