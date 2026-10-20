"""Closed analytics predicates over existing, proven attribution. No identity payloads."""
from app.measure.mapping import DL_TO_OPERATOR


def context_sql():
    # File #DL remains authoritative, exactly as measure.mapping.operator_from_dl.
    values = ','.join(f"('{key}','{value}')" for key, value in DL_TO_OPERATOR.items())
    dims = ('operator','band','tech','rat','service_type','phase','env','dep','ecgi','ecgi_source')
    projected = ','.join(f'CASE WHEN count(DISTINCT {k})=1 THEN min({k}) END AS {k}' for k in dims)
    return f"""WITH mp AS (
      SELECT capture_id,seq,{projected} FROM measurement_points
      WHERE project_id=:pid AND (CAST(:ctx_cap AS text) IS NULL OR capture_id=:ctx_cap)
      GROUP BY capture_id,seq
    ), raw AS (
      SELECT capture_id,seq,nmf_file_id,system FROM stg_event_raw WHERE project_id=:pid
        AND (CAST(:ctx_cap AS text) IS NULL OR capture_id=:ctx_cap)
      UNION SELECT capture_id,seq,nmf_file_id,system FROM stg_event WHERE project_id=:pid
        AND (CAST(:ctx_cap AS text) IS NULL OR capture_id=:ctx_cap)
    ), file_op AS (
      SELECT r.capture_id,r.seq,CASE WHEN count(DISTINCT r.system)=1 THEN min(r.system) END system,CASE WHEN count(DISTINCT d.operator)=1 THEN min(d.operator) END operator
      FROM raw r JOIN nmf_file n ON n.id=r.nmf_file_id AND n.project_id=:pid
      LEFT JOIN (VALUES {values}) d(dl,operator) ON d.dl=upper(trim(n.dl)) GROUP BY r.capture_id,r.seq
    ), rrc AS (
      SELECT e.capture_id,e.seq,CASE WHEN count(DISTINCT p.operator)=1 THEN min(p.operator) END operator
      FROM stg_event e JOIN param_occurrence p ON p.project_id=e.project_id AND p.stg_event_id=e.id
      WHERE e.project_id=:pid AND (CAST(:ctx_cap AS text) IS NULL OR e.capture_id=:ctx_cap)
      GROUP BY e.capture_id,e.seq
    ) SELECT coalesce(f.capture_id,m.capture_id) capture_id,coalesce(f.seq,m.seq) seq,
      coalesce(f.operator,m.operator,r.operator) operator,{','.join('m.'+k for k in dims if k!='operator')}
      FROM file_op f FULL JOIN mp m USING(capture_id,seq)
      LEFT JOIN rrc r ON r.capture_id=coalesce(f.capture_id,m.capture_id) AND r.seq=coalesce(f.seq,m.seq)"""


def predicate(f, alias='c'):
    parts=[]; params={}
    if f.get('operator_mode') == 'none': parts.append('FALSE')
    for key,col in {'operator':'operator','band':'band','rat':'rat','tech':'tech','service_type':'service_type','phase':'phase','env':'env','dep':'dep'}.items():
        if f.get(key):
            parts.append(f'{alias}.{col}=ANY(:filter_{key})');params['filter_'+key]=list(f[key])
    geo=[]
    for key,col in {'dor':'dor','dr':'dr','plaque':'plaque','arcep':'arcep_zone','commune':'commune','insee':'insee'}.items():
        if f.get(key):geo.append(f'g.{col}=ANY(:filter_{key})');params['filter_'+key]=list(f[key])
    if geo:parts.append(f"{alias}.ecgi_source='sib1_strict_capture_earfcn' AND EXISTS(SELECT 1 FROM cell_ref g WHERE g.eci={alias}.ecgi AND "+' AND '.join(geo)+')')
    return ' AND '.join(parts) or 'TRUE',params


def attributed_source(sql, f, *, light=False):
    condition,params=predicate(f)
    if light and condition != 'TRUE': condition += light_guard(f)
    return 'WITH context AS ('+context_sql()+') SELECT s.*,c.operator FROM ('+sql+') s LEFT JOIN context c USING(capture_id,seq) WHERE '+condition,params


def source_predicate(table, f):
    """Filters for the two established aggregate sources; no population joins."""
    if table == 'measurement_points':
        condition,params=predicate(f,'measurement_points')
    else:
        condition='FALSE' if f.get('operator_mode')=='none' else 'TRUE';params={}
        if f.get('operator'):
            condition+=' AND param_occurrence.operator=ANY(:filter_operator)';params['filter_operator']=list(f['operator'])
        rest={k:v for k,v in f.items() if k not in ('operator','operator_mode','capture_id')}
        sub,sp=predicate(rest,'m');params.update(sp)
        if sub!='TRUE':condition+=' AND EXISTS(SELECT 1 FROM stg_event e JOIN measurement_points m ON m.project_id=e.project_id AND m.capture_id=e.capture_id AND m.seq=e.seq WHERE e.id=param_occurrence.stg_event_id AND e.project_id=:pid AND '+sub+')'
    if f.get('capture_id'):
        params['filter_capture_id']=f['capture_id']
        condition+=(' AND measurement_points.capture_id=:filter_capture_id' if table=='measurement_points' else ' AND EXISTS(SELECT 1 FROM stg_event e WHERE e.project_id=:pid AND e.id=param_occurrence.stg_event_id AND e.capture_id=:filter_capture_id)')
    return condition,params


def light_guard(f):
    return """ AND (NOT EXISTS (SELECT 1 FROM nmf_capture nc WHERE nc.project_id=:pid AND nc.capture_id=s.capture_id AND nc.decode_level='light') OR NOT EXISTS (
          SELECT 1 FROM nmf_event_light l JOIN stg_event_raw r
            ON r.project_id=l.project_id AND r.capture_id=l.capture_id AND r.event_code=l.event_code AND r.seq BETWEEN l.seq AND l.seq_last
          LEFT JOIN context lc ON lc.capture_id=r.capture_id AND lc.seq=r.seq
          WHERE l.project_id=:pid AND l.capture_id=s.capture_id AND l.seq=s.seq
            AND NOT coalesce(("""+predicate(f,'lc')[0]+"""),FALSE)))"""


def validate_operators(db,pid,f):
    from fastapi import HTTPException
    from sqlalchemy import text
    selected=f.get('operator',[])
    if f.get('operator_mode')=='none' and selected:
        raise HTTPException(422,{'reason':'contradictory_operator_selection'})
    if not selected:return
    allowed=set(db.execute(text('SELECT DISTINCT operator FROM measurement_points WHERE project_id=:pid AND operator IS NOT NULL UNION SELECT DISTINCT operator FROM param_occurrence WHERE project_id=:pid AND operator IS NOT NULL'),{'pid':pid}).scalars())
    if any(op not in allowed for op in selected):
        raise HTTPException(422,{'reason':'unknown_project_operator','allowed':sorted(allowed)})


class QueryTrace:
    """Record the actual aggregate SQL and parameters for replay, not reconstructed SQL."""
    def __init__(self, db):
        self.db=db
        self.queries=[]

    def __getattr__(self, name):
        return getattr(self.db,name)

    def execute(self, statement, params=None, *args, **kwargs):
        self.queries.append({'sql':str(statement),'params':params or {}})
        return self.db.execute(statement,params,*args,**kwargs)
