"""Construction du NmfImportReport à partir des comptes réels en base.

Ce service est volontairement hors de `app/routes/` : la règle G5 interdit
tout littéral numérique de donnée dans un handler. Les constantes de
pourcentage et de précision vivent ici, pas dans la route.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import NmfFile, Project
from app.schemas.ingest import NmfFileEntry, NmfImportReport

# Constantes de calcul & d'identité — centralisées, auditables.
_PCT_FACTOR = 100.0
_PCT_DECIMALS = 2
PROJECT_ID_LEN = 12   # longueur du suffixe uuid.hex[:N] pour les ids projet
ORIGIN_LNG = 0.0      # origine neutre tant qu'aucun NMF n'est ingéré
ORIGIN_LAT = 0.0


def build_import_report(
    db: Session,
    project: Project,
    entries: list[NmfFileEntry],
    files_received: int,
    files_done: int,
    files_error: int,
) -> NmfImportReport:
    """Agrégations SQL explicites — aucun chiffre dérivé sans comptage."""
    files = db.query(NmfFile).filter(NmfFile.project_id == project.id).all()
    n_captures = sum(f.n_captures for f in files)
    n_events = sum(f.n_events for f in files)
    n_gps_total = sum(f.n_gps for f in files)

    gps_cov: float | None
    if n_events == 0:
        # Pas de division par zéro silencieuse — jamais remplacée par 0.
        gps_cov = None
    else:
        gps_cov = round(_PCT_FACTOR * n_gps_total / n_events, _PCT_DECIMALS)

    technos_rows = db.execute(
        text(
            "SELECT system, COUNT(*) FROM stg_event "
            "WHERE project_id = :pid AND system IS NOT NULL GROUP BY system"
        ),
        {"pid": project.id},
    ).all()
    technos = {str(r[0]): int(r[1]) for r in technos_rows}

    operators_seen = dict(project.operators_plmn or {})

    return NmfImportReport(
        files_received=files_received,
        files_done=files_done,
        files_error=files_error,
        by_file=entries,
        n_captures=n_captures,
        n_events=n_events,
        gps_coverage_pct=gps_cov,
        operators_seen=operators_seen,
        technos_seen=technos,
    )
