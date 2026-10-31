from datetime import datetime

from pydantic import BaseModel


class ImportReport(BaseModel):
    rows_read: int
    rows_loaded: int
    rows_rejected: int
    rejected_by_reason: dict[str, int]
    distinct_eci: int
    distinct_nci: int
    by_rat: dict[str, int]
    bands_unmapped: dict[str, int]
    etat_breakdown: dict[str, int]
    # Zone ARCEP (0.7.1) : comptage par libellé source LITTÉRAL depuis
    # `cat_arcep_code`. Le bucket NULL (source "" ou "(null)") est exposé
    # sous la clé explicite `"__null"` (NULL non-sérialisable comme clé
    # JSON). somme(arcep_breakdown.values()) == rows_loaded.
    arcep_breakdown: dict[str, int]
    snapshot_date: str | None


class CellReferenceJobAccepted(BaseModel):
    job_id: str
    status: str
    filename: str
    source_bytes: int


class CellReferenceJob(BaseModel):
    job_id: str
    filename: str
    uploaded_at: datetime
    status: str
    progress_percent: int
    rows_read: int
    rows_loaded: int
    rows_rejected: int
    report: ImportReport | None = None
    error: dict | None = None


class ReferenceImportEntry(BaseModel):
    id: str
    filename: str
    uploaded_at: str
    actor: str
    snapshot_date: str | None
    rows_read: int
    rows_loaded: int
    rows_rejected: int
    status: str
    report: ImportReport


class CellSummaryBucket(BaseModel):
    key: str
    count: int


class CellSummary(BaseModel):
    total: int
    by_rat: list[CellSummaryBucket]
    by_band_3gpp: list[CellSummaryBucket]
    by_dor: list[CellSummaryBucket]
    by_dr: list[CellSummaryBucket]
    # Zone ARCEP (0.7.1) : comptage GROUP BY sur `cell_ref.arcep_zone`.
    # Les lignes à NULL sont déclarées sous la clé `N/D` (comme les
    # autres buckets `_bucket()` déjà en place) — jamais remplacées par 0.
    arcep_breakdown: list[CellSummaryBucket]
