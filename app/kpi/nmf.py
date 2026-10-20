"""KPI statistics over the same closed decoded source as capture metrics."""
from sqlalchemy import text
from app.nmf_decoder.projection import source_sql
from app.nmf_decoder.schema import fields

def available(db,pid,code):
    if code not in fields():return False
    return bool(db.execute(text('SELECT EXISTS(SELECT 1 FROM ('+source_sql(code)+') s)'),{'pid':pid}).scalar())

def stats(db,pid,code,group_cols,operators,filters=None):
    from app.kpi.population import context_sql, predicate, light_guard
    if code not in fields() or any(c not in ('operator','band') for c in group_cols):
        raise ValueError('unsupported_decoded_metric_group')
    f={**(filters or {}),'operator':list(operators)}
    condition,params=predicate(f)
    if condition!='TRUE' and db.execute(text("SELECT EXISTS(SELECT 1 FROM nmf_capture WHERE project_id=:pid AND decode_level='light' AND (CAST(:ctx_cap AS text) IS NULL OR capture_id=:ctx_cap))"),{'pid':pid,'ctx_cap':f.get('capture_id')}).scalar():condition+=light_guard(f)
    if f.get('capture_id'):
        condition+=' AND s.capture_id=:ctx_cap'
    source='WITH context AS MATERIALIZED ('+context_sql()+'), measured AS MATERIALIZED (SELECT * FROM ('+source_sql(code)+') raw WHERE CAST(:ctx_cap AS text) IS NULL OR capture_id=:ctx_cap), observations AS (SELECT s.value,c.operator,c.band FROM measured s LEFT JOIN context c USING(capture_id,seq) WHERE '+condition+') '
    aggregate='count(*) n,percentile_cont(0.1) WITHIN GROUP(ORDER BY value) p10,percentile_cont(0.5) WITHIN GROUP(ORDER BY value) p50,percentile_cont(0.9) WITHIN GROUP(ORDER BY value) p90'
    params.update(pid=pid,ctx_cap=f.get('capture_id'))
    total=dict(db.execute(text(source+'SELECT '+aggregate+' FROM observations'),params).mappings().one())
    cols=','.join(group_cols)
    groups=[dict(r) for r in db.execute(text(source+'SELECT '+cols+','+aggregate+' FROM observations GROUP BY '+cols+' ORDER BY '+cols),params).mappings()] if cols else ([total] if total['n'] else [])
    return total,groups
