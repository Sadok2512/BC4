"""KPI statistics over the same closed decoded source as capture metrics."""
from sqlalchemy import text
from app.nmf_decoder.projection import source_sql
from app.nmf_decoder.schema import fields

def available(db,pid,code):
    if code not in fields():return False
    return bool(db.execute(text('SELECT EXISTS(SELECT 1 FROM ('+source_sql(code)+') s)'),{'pid':pid}).scalar())

def stats(db,pid,code,group_cols,operators):
    if code not in fields() or any(c not in ('operator','band') for c in group_cols):
        raise ValueError('unsupported_decoded_metric_group')
    # Capture context is used only when unambiguous. No radio value is interpolated.
    source='''WITH context AS (SELECT capture_id,
        CASE WHEN count(DISTINCT operator)=1 THEN min(operator) END operator,
        CASE WHEN count(DISTINCT band)=1 THEN min(band) END band
        FROM measurement_points WHERE project_id=:pid GROUP BY capture_id),
        observations AS (SELECT s.value,c.operator,c.band FROM ('''+source_sql(code)+''') s
        LEFT JOIN context c USING(capture_id)) '''
    condition=' WHERE operator=ANY(:operators)' if operators else ''
    aggregate='count(*) n,percentile_cont(0.1) WITHIN GROUP(ORDER BY value) p10,percentile_cont(0.5) WITHIN GROUP(ORDER BY value) p50,percentile_cont(0.9) WITHIN GROUP(ORDER BY value) p90'
    params={'pid':pid,'operators':list(operators)}
    total=dict(db.execute(text(source+'SELECT '+aggregate+' FROM observations'+condition),params).mappings().one())
    cols=','.join(group_cols)
    groups=[dict(r) for r in db.execute(text(source+'SELECT '+cols+','+aggregate+' FROM observations'+condition+' GROUP BY '+cols+' ORDER BY '+cols),params).mappings()]
    return total,groups
