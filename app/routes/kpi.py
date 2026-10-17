from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import with_statement_timeout_60s
from app.models import KpiCatalogGroup, KpiRrcSummary

# 0.48.0 — statement_timeout 60 s (cf. project_kpi.router).
router = APIRouter(prefix="/kpi", tags=["kpi"], dependencies=[Depends(with_statement_timeout_60s)])


@router.get("/catalog")
def get_kpi_catalog(db: Session = Depends(get_db)) -> dict:
    groups = db.query(KpiCatalogGroup).order_by(KpiCatalogGroup.position).all()
    summary = db.query(KpiRrcSummary).one()
    return {
        "catalog": [{"group": g.name, "items": g.items} for g in groups],
        "kpi": {
            "name": summary.name,
            "description": summary.description,
            "value": summary.value,
            "delta": summary.delta,
            "samples": summary.samples,
            "techs": summary.techs,
            "unit": summary.unit,
            "byOp": summary.by_op,
        },
    }
