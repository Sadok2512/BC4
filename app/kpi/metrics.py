"""Closed, audited metric sources. No user-supplied SQL identifiers.

NR CELLMEAS positions and TAD units are unproven: intentionally not exposed.
Counts describe non-null observations, not task-paired radio samples.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Metric:
    label: str
    unit: str
    source_table: str
    source_column: str
    tech: str
    kind: str
    sql: str

def metric_catalog(db):
    from app.nmf_decoder.schema import fields
    from app.nmf_decoder.projection import source_sql, ALIASES
    result={}
    for code,f in fields().items():
        if f.get('metric') is False or f.get('agg') is None:continue
        sql=source_sql(code);unit=f['unit']
        if unit=='bit/s':
            unit='Mbit/s';sql='SELECT capture_id,seq,value/1000000.0 AS value FROM ('+sql+') raw'
        kind='categorical' if f.get('agg')=='dominant' else 'numeric'
        result[code]=Metric(f['label'],unit,'nmf_event_group' if f['group'] else 'nmf_event_deep',code,
            'BOTH' if f['event'] in ('DRATE','AQDL','RTPJITTER','PPPRATE') else 'LTE',kind,sql)
    for alias,code in ALIASES.items():
        if code in result:result[alias]=result[code]
    return result
