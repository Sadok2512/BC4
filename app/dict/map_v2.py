"""Traceable RRC occurrences, never site positions or temporal interpolation."""
from collections import Counter
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.dict.geo_filters import geographic_scope

COLORS = {"Orange": "#FF7900", "SFR": "#E2001A", "Bouygues": "#009FE3", "Free": "#7C8794"}


def build_map(db: Session, project_id: str, keys: list[str], *, technology=None,
              operators=(), bands=(), geographic=None, limit=5000):
    cte, geo, params = geographic_scope(db, project_id, geographic)
    params.update(pid=project_id, keys=keys, limit=limit)
    scope = "param_occurrence.project_id = :pid AND param_key = ANY(:keys)" + geo
    # Only decoded values exposed by the distribution, not identifiers or UE-report KPI redirects.
    scope += " AND COALESCE(value_converted, value) IS NOT NULL AND origin IS DISTINCT FROM 'ue_report'"
    if technology:
        scope += " AND param_occurrence.system = :technology"
        params['technology'] = technology
    if operators:
        scope += " AND COALESCE(operator, 'N/D') = ANY(:operators)"
        params['operators'] = list(operators)
    if bands:
        scope += " AND COALESCE(band, 'N/D') = ANY(:bands)"
        params['bands'] = list(bands)
    source = """ FROM param_occurrence
        LEFT JOIN stg_event e ON e.id = param_occurrence.stg_event_id
            AND e.project_id = param_occurrence.project_id
            AND e.system = param_occurrence.system
        WHERE """ + scope
    valid = """e.capture_id IS NOT NULL AND e.seq IS NOT NULL
        AND e.lat BETWEEN -90 AND 90 AND e.lon BETWEEN -180 AND 180"""
    totals = db.execute(text(cte + "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE " + valid + ") AS mapped" + source), params).mappings().one()
    rows = db.execute(text(cte + """SELECT param_occurrence.id::text AS occurrence_id,
        e.id::text AS event_id, e.capture_id, e.seq, e.nmf_file_id,
        param_key, display_name, param_occurrence.path, param_occurrence.system AS technology,
        operator, band, value AS value_raw, value_converted, unit_converted AS unit,
        e.lat, e.lon
        """ + source + " AND " + valid + " ORDER BY e.capture_id, e.seq, param_occurrence.id LIMIT :limit"), params).mappings().all()
    points = []
    for row in rows:
        point = dict(row)
        point['source'] = f"stg_event:{point['event_id']} / param_occurrence:{point['occurrence_id']}"
        point['coordinate_source'] = 'stg_event'
        point['operator_color'] = COLORS.get(point['operator'], '#CBD5E1')
        points.append(point)
    counts = Counter(p['operator'] or 'N/D' for p in points)
    return {
        'project_id': project_id, 'points': points,
        'total_occurrences': totals['total'], 'geolocated_occurrences': totals['mapped'],
        'returned_occurrences': len(points), 'truncated': totals['mapped'] > len(points),
        'limit': limit,
        'operators': [{'name': op, 'count': count, 'color': COLORS.get(op, '#CBD5E1')} for op, count in sorted(counts.items())],
        'reason': None if points else 'Aucune occurrence sélectionnée ne possède de coordonnées valides dans son événement source.',
    }
