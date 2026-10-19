"""Scoped, transactional LTE CELLMEAS enrichment using the stored global proof.
No deletion, no new profile, no NR mapping; caller owns the transaction.
"""
from sqlalchemy import text
from app.measure.ranges import RSRP, RSRQ, RSSI, SINR, is_placeholder
from app.measure.mapping import band_from_earfcn
from app.services.task_run import number, integer

FIELDS={'rsrp':RSRP,'rsrq':RSRQ,'rssi':RSSI,'sinr':SINR}

def gated(raw,field,rng):
    value=number(raw.get(field)) if field else None
    return value if value is not None and not is_placeholder(value) and rng.contains(value) else None

def enrich_lte_cellmeas(db,pid,captures):
    if not captures:raise ValueError('Explicit capture scope is required')
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),{'key':'populate:'+pid})
    profiles=db.execute(text("""SELECT DISTINCT ON(metric) metric,field,verdict,id,n_pairs
        FROM cellmeas_profile WHERE project_id=:pid AND capture_id IS NULL
        AND metric IN ('rsrp','rsrq','rssi','sinr') AND verdict='proven'
        ORDER BY metric,created_at DESC,id DESC"""),{'pid':pid}).mappings().all()
    mapping={p['metric']:p['field'] for p in profiles}
    if not mapping.get('rsrp'):raise ValueError('No proven global LTE RSRP profile')
    rows=db.execute(text("""SELECT m.id,r.raw_fields FROM stg_event_raw r JOIN measurement_points m
        ON m.project_id=r.project_id AND m.capture_id=r.capture_id AND m.seq=r.seq AND m.event_code=r.event_code
        WHERE r.project_id=:pid AND r.capture_id=ANY(:captures) AND r.event_code='CELLMEAS' AND r.system='LTE'
        ORDER BY r.capture_id,r.seq"""),{'pid':pid,'captures':captures}).mappings().all()
    changes=[]
    for row in rows:
        raw=row['raw_fields'];earfcn=integer(raw.get('cell0_earfcn'))
        changes.append(dict(id=row['id'],**{metric:gated(raw,mapping.get(metric),rng) for metric,rng in FIELDS.items()},
                            earfcn=earfcn,band=band_from_earfcn(earfcn) if earfcn is not None else None))
    if changes:
        db.execute(text("""UPDATE measurement_points SET rsrp=:rsrp,rsrq=:rsrq,rssi=:rssi,sinr=:sinr,
            rat='LTE',tech='LTE',earfcn=:earfcn,band=COALESCE(:band,band) WHERE id=:id"""),changes)
    assert_lte_enriched(db,pid,captures)
    return {'captures':captures,'updated':len(changes),'profile_scope':'global LTE; no capture-specific proof',
            'profiles':[dict(p) for p in profiles]}

def assert_lte_enriched(db,pid,captures=None):
    clause=' AND r.capture_id=ANY(:captures)' if captures is not None else ''
    rows=db.execute(text("""SELECT r.capture_id,count(*) missing FROM stg_event_raw r
        LEFT JOIN measurement_points m ON m.project_id=r.project_id AND m.capture_id=r.capture_id
        AND m.seq=r.seq AND m.event_code='CELLMEAS'
        WHERE r.project_id=:pid AND r.event_code='CELLMEAS' AND r.system='LTE'
        AND (m.id IS NULL OR m.rat IS DISTINCT FROM 'LTE')"""+clause+' GROUP BY r.capture_id'),
        {'pid':pid,**({'captures':captures} if captures is not None else {})}).mappings().all()
    if rows:raise RuntimeError('CELLMEAS enrichment incomplete: '+str([dict(r) for r in rows]))
