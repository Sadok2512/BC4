"""Moteur de preuves — validate_comparison + lineage (0.25.0).

Pour toute comparaison affichée dans la réponse de l'Assistant, le
moteur ÉMET un **verdict de comparabilité** basé sur l'alignement des
plans, pas sur l'égalité littérale des dénominateurs (correctif 1 du
cahier des charges).

Trois verdicts :
- `COMPARABLE` : même dataset, mêmes mesures, mêmes dimensions, même
  period, filtres orthogonaux (ex. 2 opérateurs sur même bande).
- `COMPARABLE_WITH_LIMITATIONS` : alignement structurel OK mais ≥ 1
  warning (dénominateurs très différents, dataset partiel, mesure
  non-recomposable utilisée sur sous-groupes).
- `NOT_COMPARABLE` : mesures différentes, datasets différents, périodes
  disjointes, ou mesure incompatible avec la question.

Chaque verdict porte sa `reason` lisible.

Lineage : pour un `result_id`, retrouve le plan + dataset d'origine
depuis un cache en mémoire (par request-id Flask-style). Au-delà de
la vie de la requête, le lineage est reconstruit depuis le journal
technique (pas implémenté dans ce lot — journal structuré est un lot
observabilité séparé).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.assistant.catalog import MEASURES
from app.assistant.engine import AnalyticalResult


Verdict = Literal["COMPARABLE", "COMPARABLE_WITH_LIMITATIONS", "NOT_COMPARABLE"]


@dataclass
class ComparabilityVerdict:
    verdict: Verdict
    reason: str
    denominators: dict[str, int]  # result_id → denominator (pour affichage UI)


def validate_comparison(results: list[AnalyticalResult]) -> ComparabilityVerdict:
    """Vérifie si une liste de résultats analytiques est comparable.

    Au minimum 2 résultats requis. Compare les plans (pas uniquement
    les sorties — un plan identique sur 2 projets différents reste
    comparable si on explicite le scope).
    """
    if len(results) < 2:
        return ComparabilityVerdict(
            verdict="NOT_COMPARABLE",
            reason="Au moins 2 résultats requis pour une comparaison.",
            denominators={r.result_id: r.denominator for r in results},
        )

    denominators = {r.result_id: r.denominator for r in results}
    warnings: list[str] = []

    # 1) Même dataset ?
    datasets = {r.dataset for r in results}
    if len(datasets) > 1:
        return ComparabilityVerdict(
            verdict="NOT_COMPARABLE",
            reason=f"Datasets différents : {sorted(datasets)}. Les mesures ne sont pas définies sur le même espace.",
            denominators=denominators,
        )

    # 2) Mesures et dimensions alignées ?
    measure_sets = [tuple(sorted((r.plan.get("measures") or ["count"]))) for r in results]
    dim_sets = [tuple(sorted(r.plan.get("dimensions") or [])) for r in results]
    if len(set(measure_sets)) > 1:
        return ComparabilityVerdict(
            verdict="NOT_COMPARABLE",
            reason=f"Mesures différentes : {set(measure_sets)}. Comparaison sans sens.",
            denominators=denominators,
        )
    if len(set(dim_sets)) > 1:
        return ComparabilityVerdict(
            verdict="NOT_COMPARABLE",
            reason=f"Dimensions différentes : {set(dim_sets)}. Les regroupements ne couvrent pas la même sémantique.",
            denominators=denominators,
        )

    # 3) Période (date_range) alignée ?
    periods = {(r.date_range.get("start"), r.date_range.get("end")) for r in results}
    if len(periods) > 1:
        return ComparabilityVerdict(
            verdict="NOT_COMPARABLE",
            reason=f"Périodes de projet différentes : {sorted(periods)}.",
            denominators=denominators,
        )

    # 4) Dénominateurs très déséquilibrés ?
    non_zero = [d for d in denominators.values() if d > 0]
    if non_zero:
        max_d = max(non_zero)
        min_d = min(non_zero)
        if min_d > 0 and max_d / min_d >= 10:
            warnings.append(
                f"dénominateurs déséquilibrés (max={max_d}, min={min_d}, ratio={max_d/min_d:.1f}×) : "
                "la lecture relative reste honnête mais la représentativité des petits groupes est faible."
            )
    if 0 in denominators.values():
        warnings.append("dénominateur nul pour au moins un sous-groupe (n=0) — la mesure est déclarée indisponible pour ce groupe, jamais invent ée.")

    # 5) Mesures non-recomposables utilisées sur sous-groupes ?
    for r in results:
        for m in r.plan.get("measures") or []:
            if m in MEASURES and not MEASURES[m]["recomposable"] and len(r.plan.get("dimensions") or []) >= 2:
                warnings.append(
                    f"result_id={r.result_id}: mesure {m!r} non-recomposable sur ≥ 2 dimensions — "
                    "la moyenne/percentile est calculée directement, pas recomposée (pas de biais)."
                )

    # 6) Warnings signalés par le moteur à l'exécution.
    for r in results:
        for w in r.warnings:
            if w not in warnings:
                warnings.append(w)

    if warnings:
        return ComparabilityVerdict(
            verdict="COMPARABLE_WITH_LIMITATIONS",
            reason="Alignement structurel OK ; limites : " + " | ".join(warnings),
            denominators=denominators,
        )
    return ComparabilityVerdict(
        verdict="COMPARABLE",
        reason="Même dataset, mêmes mesures, mêmes dimensions, même période — comparaison honnête.",
        denominators=denominators,
    )


def lineage_for_result(result: AnalyticalResult) -> dict[str, Any]:
    """Résumé lineage pour affichage côté UI / sources."""
    plan = result.plan
    return {
        "result_id": result.result_id,
        "dataset": result.dataset,
        "dimensions": plan.get("dimensions") or [],
        "measures": plan.get("measures") or ["count"],
        "filters_applied": result.filters_applied,
        "denominator": result.denominator,
        "n_returned": result.n,
        "date_range": result.date_range,
        "warnings": result.warnings,
    }
