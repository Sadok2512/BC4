"""KPI catalog + per-project status (0.35.0).

Table de vérité versionnée en code (pas en DB). Toute modification du
catalogue passe par une PR + un bump SemVer (voir CHANGELOG). Discipline
héritée de `app.assistant.catalog` : jamais de valeur inventée, jamais
de rate calculé tant que le contrat tentative/réussite n'est pas certifié,
jamais de métrique mesure déclarée AVAILABLE si `measurement_points` est
NULL sur la colonne.
"""

from app.kpi.catalog import (
    CATALOG,
    FAMILIES_ORDER,
    KPI_BY_CODE,
    KPI_CATALOG_VERSION,
    KpiDef,
    Nature,
    Status,
)

__all__ = [
    "CATALOG",
    "FAMILIES_ORDER",
    "KPI_BY_CODE",
    "KPI_CATALOG_VERSION",
    "KpiDef",
    "Nature",
    "Status",
]
