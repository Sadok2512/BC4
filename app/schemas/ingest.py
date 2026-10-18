"""Schémas Pydantic pour l'ingestion NMF (B1-ingest).

Chaque champ est renvoyé 1:1 à partir d'un comptage réel. `null` n'est jamais
remplacé par 0 — un fichier en échec se déclare `status=error` et porte un
`error_msg`, jamais masqué. `gps_coverage_pct` reste `None` si aucun event n'a
été produit (division par zéro honnête → None).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ProjectIngestStatus = Literal["draft", "importing", "ready", "error"]
NmfFileStatus = Literal["pending", "decoding", "done", "error"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class PerimeterView(BaseModel):
    """Agrégat géo issu de la jointure cells Orange ↔ `cell_ref` (0.12.0).
    Les listes sont vides quand `cell_ref` ne couvre aucune cellule
    Orange observée — déclaré par `zone_source='none'`, pas une erreur."""

    cells_total: int
    cells_orange: int
    cells_other: int
    cells_joined: int
    cells_orange_unjoined: int
    join_rate_pct: float | None
    dors: list[str]
    drs: list[str]
    plaques: list[str]
    sites: list[str]
    arcep_zones: list[str]
    coverage: list[str]
    label: str
    zone_source: Literal["cell_ref_exact", "none"]


class ProjectIngestView(BaseModel):
    """Représentation d'un projet dans l'optique ingestion. Les colonnes
    résumé sont nulles tant qu'aucun NMF n'a été ingéré."""

    id: str
    name: str
    created_at: str | None
    actor: str | None
    status: ProjectIngestStatus
    # PLMN → compteur d'events vus. Le libellé opérateur (Orange/SFR/…)
    # dépend d'une table PLMN non livrée en B1-ingest (écart ouvert).
    operators: dict[str, int] | None
    technos: dict[str, int] | None    # techno → compteur events
    n_captures: int | None
    n_events: int | None
    gps_coverage_pct: float | None
    # Périmètre (0.12.0) : null tant qu'aucune cellule n'a été jointe
    # (écart déclaré, pas 0). La UI affiche « N/D » dans ce cas.
    perimeter: PerimeterView | None = None


class NmfFileEntry(BaseModel):
    filename: str
    status: NmfFileStatus
    n_captures: int
    n_events: int
    n_gps: int
    decoder_version: str | None
    error_msg: str | None


class NmfImportReport(BaseModel):
    files_received: int
    files_done: int
    files_error: int
    by_file: list[NmfFileEntry]
    n_captures: int
    n_events: int
    gps_coverage_pct: float | None   # None si aucun event — jamais 0 par défaut
    operators_seen: dict[str, int]   # PLMN → opérateur → n events
    technos_seen: dict[str, int]


class NmfImportJobView(BaseModel):
    id: str
    project_id: str
    status: Literal['queued', 'decoding', 'finalizing', 'done', 'error']
    files_total: int
    files_done: int
    files_error: int
    by_file: list[NmfFileEntry]
    error_msg: str | None
    report: NmfImportReport | None
