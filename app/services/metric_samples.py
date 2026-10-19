"""Stage E: only explicitly proven cN definitions; never infer a field.

All event families below retain data tokens as cN in the canonical decoder.
Indices 0..3 are structural/header tokens and not accepted as measurements.
No definition is installed until its page/field proof is reviewed.
"""
from sqlalchemy import text
EVENTS=('PHRATE','PHRATEU','MACRATE','MACRATEU','RLCRATE','RLCRATEU',
        'PDCPRATED','PDCPRATEU','PLAID','PLAIU','CQI','MIMOMEAS','TXPC',
        'DCI','BSR','PMI','CSI','TAD','RTPJITTER')
POPULATE_SQL='''INSERT INTO metric_sample(project_id,capture_id,seq,metric_code,raw_event_id,raw_value,value)
SELECT r.project_id,r.capture_id,r.seq,d.code,r.id,r.raw_fields->>('c'||d.field_index),
 (r.raw_fields->>('c'||d.field_index))::double precision*d.scale
FROM stg_event_raw r JOIN metric_def d ON d.event_code=r.event_code
WHERE r.project_id=:pid AND r.event_code=ANY(:events)
 AND (d.tech='BOTH' OR d.tech=r.system)
 AND r.raw_fields->>('c'||d.field_index) ~ '^[+-]?[0-9]+([.][0-9]+)?([eE][+-]?[0-9]+)?$'
ON CONFLICT(project_id,capture_id,seq,metric_code) DO UPDATE
 SET raw_event_id=excluded.raw_event_id,raw_value=excluded.raw_value,value=excluded.value'''

def populate_metric_samples(db,project_id):
    definitions=db.execute(text('SELECT count(*) FROM metric_def')).scalar_one()
    if not definitions:return {'definitions':0,'written':0,'reason':'no_proven_metric_definitions'}
    result=db.execute(text(POPULATE_SQL),{'pid':project_id,'events':list(EVENTS)})
    return {'definitions':definitions,'written':result.rowcount}
