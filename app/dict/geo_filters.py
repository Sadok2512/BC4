"""RRC geography from existing, unambiguous strict cell associations only.

Reuse the established (project, capture, EARFCN, RAT) ECGI evidence. Never
join by timestamp, across captures, or by PCI alone. EXISTS prevents repeated
cell-reference rows or measurement samples from multiplying occurrences.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException

GEO_LABELS = {"dor": "DOR", "plaque": "Plaque", "arcep_zone": "Zone ARCEP"}

GEO_CTE = """
WITH strict_cells AS MATERIALIZED (
    SELECT capture_id, earfcn, COALESCE(rat, tech) AS system, MIN(ecgi) AS ecgi
    FROM measurement_points
    WHERE project_id = :pid AND ecgi IS NOT NULL
      AND ecgi_source = 'sib1_strict_capture_earfcn'
      AND capture_id IS NOT NULL AND earfcn IS NOT NULL
    GROUP BY capture_id, earfcn, COALESCE(rat, tech)
    HAVING COUNT(DISTINCT ecgi) = 1
), rrc_geo AS MATERIALIZED (
    SELECT DISTINCT e.id AS event_id, cr.dor, cr.plaque, cr.arcep_zone
    FROM stg_event e
    JOIN strict_cells s ON s.capture_id = e.capture_id AND s.system = e.system
      AND s.earfcn = CASE WHEN e.freq ~ '^[0-9]{1,9}$' THEN e.freq::integer END
    JOIN cell_ref cr ON cr.eci = s.ecgi
    WHERE e.project_id = :pid
)
"""


def geographic_options(db: Session, project_id: str) -> dict:
    rows = db.execute(text(GEO_CTE + """
        SELECT DISTINCT g.dor, g.plaque, g.arcep_zone
        FROM rrc_geo g
        WHERE EXISTS (SELECT 1 FROM param_occurrence po
                      WHERE po.project_id = :pid AND po.stg_event_id = g.event_id)
    """), {"pid": project_id}).fetchall()
    dimensions = []
    for index, (key, label) in enumerate(GEO_LABELS.items()):
        options = sorted({row[index] for row in rows if row[index] and row[index].strip()})
        dimensions.append({
            "key": key, "label": label, "available": bool(options),
            "options": options, "count": len(options),
            "reason": None if options else (
                f"Aucune liaison ECGI stricte et non ambiguë vers {label} dans cell_ref "
                "pour les événements RRC de ce projet (même capture, fréquence et technologie)."
            ),
        })
    return {"project_id": project_id, "geographic": dimensions}


def geographic_scope(db: Session, project_id: str, filters: dict[str, tuple[str, ...]] | None):
    """Bound parameters, OR within each filter, AND on the same cell across filters."""
    active = {key: tuple(sorted(set(values))) for key, values in (filters or {}).items() if values}
    if not active:
        return "", "", {}
    available = {d["key"]: d for d in geographic_options(db, project_id)["geographic"]}
    clauses, params = [], {}
    for key, values in active.items():
        dimension = available.get(key)
        if not dimension or not dimension["available"]:
            raise HTTPException(422, detail={"code": "GEOGRAPHIC_FILTER_UNAVAILABLE", "message": dimension["reason"] if dimension else "Filtre géographique inconnu"})
        if not set(values).issubset(dimension["options"]):
            raise HTTPException(422, detail={"code": "GEOGRAPHIC_VALUE_UNAVAILABLE", "message": f"Valeur {dimension['label']} absente du projet ; actualisez les filtres."})
        clauses.append(f"g.{key} = ANY(:geo_{key})")
        params[f"geo_{key}"] = list(values)
    predicate = " AND EXISTS (SELECT 1 FROM rrc_geo g WHERE g.event_id = param_occurrence.stg_event_id AND " + " AND ".join(clauses) + ")"
    return GEO_CTE, predicate, params
