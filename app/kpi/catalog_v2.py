"""Catalogue KPI v2 chargé depuis ``catalog_v2.json`` (0.40.0).

Le JSON est **généré** à partir du xlsx utilisateur par
``scripts/import_kpi_catalog_v2.py``. Le runtime ne charge PAS openpyxl
— seul l'importer en a besoin. Toute modification du catalogue passe
par un ré-import (bump du ``source_xlsx_sha256``).

Discipline :
- Les 208 entrées xlsx sont réduites à ``canonical_count`` KPI canoniques
  + une liste d'alias (``LTE_RRC_SR`` → ``LTE_RRC_SETUP_SR`` etc.).
- Chaque entrée porte sa règle d'``available_check`` ; le calcul du
  statut par projet est fait côté ``service_v2.compute_status``.
- Aucun chiffre n'est fabriqué ici. Les codes dont la règle n'est pas
  prouvée côté décodeur sont déclarés ``always_unavailable`` /
  ``always_unvalidated`` avec une raison explicite — jamais inventés.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal


# Chargement unique au module import.
_JSON_PATH = Path(__file__).parent / "catalog_v2.json"
if not _JSON_PATH.exists():
    raise RuntimeError(
        f"catalog_v2.json introuvable à {_JSON_PATH}. "
        "Lance scripts/import_kpi_catalog_v2.py pour le générer."
    )

with _JSON_PATH.open("r", encoding="utf-8") as _f:
    _DATA: dict[str, Any] = json.load(_f)


CATALOG_V2_VERSION: str = _DATA["catalog_version"]
SOURCE_XLSX_NAME: str = _DATA["source_xlsx"]
SOURCE_XLSX_SHA256: str = _DATA["source_xlsx_sha256"]
TOTAL_INPUT_ROWS: int = _DATA["total_input_rows"]
CANONICAL_COUNT: int = _DATA["canonical_count"]
ALIASES_COUNT: int = _DATA["aliases_count"]
NORMALIZATIONS: list[str] = list(_DATA.get("normalizations", []))
ALIASES_REPORT: list[dict[str, str]] = list(_DATA.get("aliases", []))

# Map alias → canonical (résolution d'un code côté lecture).
ALIAS_TO_CANONICAL: dict[str, str] = {
    a["alias"]: a["canonical"]
    for a in ALIASES_REPORT
    if a["alias"] != a["canonical"]
}

# Entries indexées par code canonique.
ENTRIES: list[dict[str, Any]] = list(_DATA["entries"])
CATALOG_V2: dict[str, dict[str, Any]] = {e["code"]: e for e in ENTRIES}


Status = Literal["AVAILABLE", "PENDING", "UNVALIDATED", "UNAVAILABLE", "NOT_APPLICABLE"]
Techno = Literal["LTE", "NR", "ENDC", "AGGREGATE", "UNKNOWN"]
AnalyticsTab = Literal["kpi", "metrics"]

ANALYTICS_TAB_BY_NATURE: dict[str, AnalyticsTab] = {
    "KPI calculé": "kpi",
    "Compteur": "kpi",
    "Métrique mesurée": "metrics",
}


def analytics_tab_for_nature(nature: str) -> AnalyticsTab:
    """Return the catalog-owned tab and fail closed on an unknown nature."""
    try:
        return ANALYTICS_TAB_BY_NATURE[nature]
    except KeyError as exc:
        raise ValueError(f"nature KPI sans analytics_tab : {nature!r}") from exc


def resolve(code: str) -> str | None:
    """Résout un code (canonique ou alias) vers un code canonique
    présent dans le catalogue. ``None`` si inconnu."""
    if code in CATALOG_V2:
        return code
    canon = ALIAS_TO_CANONICAL.get(code)
    if canon and canon in CATALOG_V2:
        return canon
    return None


def get(code: str) -> dict[str, Any] | None:
    """Récupère l'entrée canonique associée à ``code`` (ou None)."""
    c = resolve(code)
    if c is None:
        return None
    return CATALOG_V2[c]


# Ordre d'affichage côté UI (Techno → Famille → KPI).
TECHNO_ORDER: tuple[Techno, ...] = ("LTE", "NR", "ENDC", "AGGREGATE")

FAMILIES_ORDER: tuple[str, ...] = (
    "Accessibilité",
    "Rétention",
    "Mobilité",
    "Qualité radio",
    "MIMO",
    "Carrier Aggregation",
    "SCG",
    "DL",
    "UL",
    "Débit applicatif",
    "DMS DL",
    "DMS UL",
    "Latence",
    "Data",
    "Sessions",
    "Bearers",
    "Voix",
    "Usage",
)


def _famrank(fam: str) -> int:
    try:
        return FAMILIES_ORDER.index(fam)
    except ValueError:
        return len(FAMILIES_ORDER)


def _techrank(t: str) -> int:
    try:
        return TECHNO_ORDER.index(t)  # type: ignore[arg-type]
    except ValueError:
        return len(TECHNO_ORDER)


def sorted_entries() -> list[dict[str, Any]]:
    """Retourne les entrées canoniques triées (Techno → Famille → code)."""
    return sorted(
        ENTRIES,
        key=lambda e: (_techrank(e["techno"]), _famrank(e["family"]), e["code"]),
    )


# ---------------------------------------------------------------------------
# Service scope — déclaration de non-applicabilité.
# ---------------------------------------------------------------------------


def is_in_service_scope(entry: dict[str, Any], services: tuple[str, ...]) -> bool:
    """Vrai si l'entrée est applicable à au moins un des services demandés.

    Convention : ``service_scope`` vide = applicable à TOUS les services
    (familles transverses — Qualité radio, Mobilité, Accessibilité…).
    Un filtre vide côté appelant = pas de filtrage.
    """
    scope = entry.get("service_scope") or []
    if not services:
        return True  # pas de filtre demandé → tout passe
    if not scope:
        return True  # scope vide = transverse
    return any(s in scope for s in services)


def not_applicable_reason(entry: dict[str, Any], services: tuple[str, ...]) -> str:
    scope = entry.get("service_scope") or []
    return (
        f"KPI {entry['code']} applicable aux services {scope!r} ; "
        f"service(s) demandé(s) : {list(services)!r}. "
        "Jamais un n=0 muet — l'écart est déclaré."
    )
