"""SQL projections of decoded observations; no legacy positional radio extraction."""
from sqlalchemy import text
from .schema import fields

ALIASES={'rsrp':'cell_rsrp','rsrq':'cell_rsrq','rssi':'cell_rssi','sinr':'ci_rs_snr','cqi':'cqi_wb_cqi_0',
         'tx_power':'txpc_pusch_tx_power','pci':'cell_pci','earfcn':'cell_ch','band':'cell_band',
         'thr_dl':'app_dl_bitrate','thr_ul':'app_ul_bitrate','mos':'aqdl_mos','ta':'tad_ta'}

def source_sql(code):
    f=fields()[code];table='nmf_event_group' if f['group'] else 'nmf_event_deep'
    extra=' AND d.set_index=0' if f['group'] else ''
    if f.get('weight'):
        from .schema import column
        weight=column(f['code'].split('.')[0]+'.'+f['weight'])
        base=f"FROM nmf_event_group d JOIN nmf_capture c USING(project_id,capture_id) WHERE d.project_id=:pid AND c.decode_level='deep' AND d.{code} IS NOT NULL AND d.{weight}>0"
        if f['agg']=='dominant':
            deep=f"SELECT DISTINCT ON(capture_id,seq) capture_id,seq,value FROM (SELECT d.capture_id,d.seq,d.{code}::double precision value,sum(d.{weight}) w {base} GROUP BY d.capture_id,d.seq,d.{code}) ranked ORDER BY capture_id,seq,w DESC,value"
        else:deep=f"SELECT d.capture_id,d.seq,sum(d.{code}*d.{weight})/sum(d.{weight}) value {base} GROUP BY d.capture_id,d.seq"
        return '('+deep+f") UNION ALL SELECT d.capture_id,d.seq,d.{code}::double precision value FROM nmf_event_light d JOIN nmf_capture c USING(project_id,capture_id) WHERE d.project_id=:pid AND c.decode_level='light' AND d.{code} IS NOT NULL"
    return f'''SELECT d.capture_id,d.seq,d.{code}::double precision AS value FROM {table} d
      JOIN nmf_capture c USING(project_id,capture_id) WHERE d.project_id=:pid AND c.decode_level='deep'{extra} AND d.{code} IS NOT NULL
      UNION ALL SELECT d.capture_id,d.seq,d.{code}::double precision AS value FROM nmf_event_light d
      JOIN nmf_capture c USING(project_id,capture_id) WHERE d.project_id=:pid AND c.decode_level='light' AND d.{code} IS NOT NULL'''

def observations(db,pid):
    result={}
    for alias,code in ALIASES.items():
        if alias not in ('rsrp','rsrq','rssi','sinr','cqi','tx_power','earfcn','pci','band','thr_dl','thr_ul','mos'):continue
        for row in db.execute(text(source_sql(code)),{'pid':pid}).mappings():
            result.setdefault((row['capture_id'],row['seq']),{})[alias]=row['value']
    return result

def refresh_projections(db,pid):
    """Keep existing geographic/context rows; replace radio values from the sole decoded source."""
    values=observations(db,pid)
    db.execute(text('''UPDATE measurement_points m SET rsrp=NULL,rsrq=NULL,rssi=NULL,sinr=NULL,cqi=NULL,tx_power=NULL
        WHERE m.project_id=:pid AND m.event_code IS NOT NULL AND EXISTS
        (SELECT 1 FROM nmf_capture c WHERE c.project_id=m.project_id AND c.capture_id=m.capture_id)'''),{'pid':pid})
    rows=[]
    for (cap,seq),v in values.items():
        if not any(k in v for k in ('rsrp','rsrq','rssi','sinr','cqi','tx_power')):continue
        rows.append(dict(pid=pid,cap=cap,seq=seq,**{k:v.get(k) for k in ('rsrp','rsrq','rssi','sinr','cqi','tx_power')}))
    if rows:db.execute(text('''UPDATE measurement_points SET rsrp=:rsrp,rsrq=:rsrq,rssi=:rssi,sinr=:sinr,cqi=:cqi,tx_power=:tx_power
        WHERE project_id=:pid AND capture_id=:cap AND seq=:seq'''),rows)
    return {'observations':len(values),'updated_sequences':len(rows)}
