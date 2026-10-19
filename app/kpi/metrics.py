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

METRICS = {}
for code, label, unit, tech, kind in [
    ('rsrp','RSRP','dBm','BOTH','numeric'),('rsrq','RSRQ','dB','BOTH','numeric'),
    ('sinr','SINR','dB','BOTH','numeric'),('cqi','CQI','index','BOTH','numeric'),
    ('rssi','RSSI','dBm','BOTH','numeric'),('tx_power','Puissance TX','dBm','BOTH','numeric'),
    ('mimo_rank','Rang MIMO','index','BOTH','numeric'),
    ('earfcn','EARFCN LTE','index','LTE','numeric'),
    ('band','Bande','état','BOTH','categorical'),('rat','RAT','état','BOTH','categorical'),
    ('latency','Latence','ms','BOTH','numeric'),
]:
    gate = " AND rat='LTE'" if code == 'earfcn' else ''
    METRICS[code] = Metric(label, unit, 'measurement_points', code, tech, kind,
        f'SELECT capture_id,seq,{code} AS value FROM measurement_points WHERE project_id=:pid AND {code} IS NOT NULL'+gate)
METRICS['pci'] = Metric('PCI LTE','index','stg_event_raw','raw_fields.cell0_pci','LTE','categorical',
    "SELECT capture_id,seq,raw_fields->>'cell0_pci' AS value FROM stg_event_raw WHERE project_id=:pid AND event_code='CELLMEAS' AND system='LTE' AND raw_fields->>'cell0_pci' ~ '^[0-9]+$'")
for code, direction in [('thr_dl','HTTP_DL'),('thr_ul','HTTP_UL')]:
    METRICS[code] = Metric('Débit '+('DL' if code=='thr_dl' else 'UL'),'Mbit/s','task_sample','bps','BOTH','numeric',
        "SELECT t.capture_id,s.seq,s.bps/1000000.0 AS value FROM task_sample s JOIN task_run t ON t.id=s.task_id WHERE t.project_id=:pid AND t.task_type='"+direction+"' AND s.bps IS NOT NULL")
METRICS['mos'] = Metric('MOS AQDL','index','stg_event_raw','raw_fields.c4','BOTH','numeric',
    "SELECT capture_id,seq,CAST(raw_fields->>'c4' AS double precision) AS value FROM stg_event_raw WHERE project_id=:pid AND event_code='AQDL' AND raw_fields->>'c4' ~ '^[0-9]+([.][0-9]+)?$'")
