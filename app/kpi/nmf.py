"""KPI statistics over the same closed decoded source as capture metrics."""
from sqlalchemy import text
from app.nmf_decoder.projection import source_sql
from app.nmf_decoder.schema import fields

def available(db,pid,code):
    if code not in fields():return False
    return bool(db.execute(text('SELECT EXISTS(SELECT 1 FROM ('+source_sql(code)+') s)'),{'pid':pid}).scalar())

def stats(db,pid,code,group_cols,operators,filters=None,sql_override=None):
    # 0.64.1 — ``sql_override`` : permet au /aggregate route de passer la
    # ``metric.sql`` du ``metric_catalog`` (qui convertit déjà bit/s →
    # Mbit/s pour les débits). Sans override, on retombe sur
    # ``source_sql(code)`` brut (valeurs b/s).
    from app.kpi.population import context_sql, predicate
    if code not in fields() or any(c not in ('operator','band') for c in group_cols):
        raise ValueError('unsupported_decoded_metric_group')
    f={**(filters or {}),'operator':list(operators)}
    condition,params=predicate(f)
    params.update(pid=pid,ctx_cap=f.get('capture_id'))
    base_sql = sql_override if sql_override is not None else source_sql(code)
    measured='WITH measured AS MATERIALIZED (SELECT * FROM ('+base_sql+') raw WHERE CAST(:ctx_cap AS text) IS NULL OR capture_id=:ctx_cap)'
    has_light = condition!='TRUE' and db.execute(text("SELECT EXISTS(SELECT 1 FROM nmf_capture WHERE project_id=:pid AND decode_level='light' AND (CAST(:ctx_cap AS text) IS NULL OR capture_id=:ctx_cap))"),params).scalar()
    if condition=='TRUE' and not group_cols:
        source=measured+', observations AS (SELECT value FROM measured) '
    else:
        sequences='SELECT capture_id,seq FROM measured'
        rejected=""
        if has_light:
            # Check all constituent records before accepting an indivisible Light bucket.
            sequences+=" UNION SELECT r.capture_id,r.seq FROM measured s JOIN nmf_event_light l ON l.project_id=:pid AND l.capture_id=s.capture_id AND l.seq=s.seq JOIN stg_event_raw r ON r.project_id=l.project_id AND r.capture_id=l.capture_id AND r.event_code=l.event_code AND r.seq BETWEEN l.seq AND l.seq_last"
            rejected=", rejected_light AS MATERIALIZED (SELECT DISTINCT l.capture_id,l.seq FROM nmf_event_light l JOIN measured ms ON ms.capture_id=l.capture_id AND ms.seq=l.seq JOIN nmf_capture nc ON nc.project_id=l.project_id AND nc.capture_id=l.capture_id AND nc.decode_level='light' JOIN stg_event_raw r ON r.project_id=l.project_id AND r.capture_id=l.capture_id AND r.event_code=l.event_code AND r.seq BETWEEN l.seq AND l.seq_last LEFT JOIN context lc ON lc.capture_id=r.capture_id AND lc.seq=r.seq WHERE l.project_id=:pid AND NOT coalesce(("+predicate(f,'lc')[0]+"),FALSE))"
            condition+=' AND NOT EXISTS(SELECT 1 FROM rejected_light b WHERE b.capture_id=s.capture_id AND b.seq=s.seq)'
        source=measured+', context_sequences AS MATERIALIZED ('+sequences+'), context AS MATERIALIZED ('+context_sql(scoped=True)+')'+rejected+', observations AS MATERIALIZED (SELECT s.value,c.operator,c.band FROM measured s LEFT JOIN context c USING(capture_id,seq) WHERE '+condition+') '
    aggregate='count(*) n,percentile_cont(0.1) WITHIN GROUP(ORDER BY value) p10,percentile_cont(0.5) WITHIN GROUP(ORDER BY value) p50,percentile_cont(0.9) WITHIN GROUP(ORDER BY value) p90'
    cols=','.join(group_cols)
    if not cols:
        total=dict(db.execute(text(source+'SELECT '+aggregate+' FROM observations'),params).mappings().one())
        return total,([total] if total['n'] else [])
    rows=[dict(r) for r in db.execute(text(source+'SELECT '+cols+',GROUPING('+cols+') AS total_row,'+aggregate+' FROM observations GROUP BY GROUPING SETS ((),('+cols+')) ORDER BY '+cols),params).mappings()]
    total=next(r for r in rows if r['total_row'])
    groups=[{k:v for k,v in r.items() if k!='total_row'} for r in rows if not r['total_row']]
    return {k:total[k] for k in ('n','p10','p50','p90')},groups
