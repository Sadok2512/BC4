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
    # CI has its own measured sequence; do not put it on an interpolated CELLMEAS row.
    ci_sql=source_sql('ci_rs_snr')
    ci=db.execute(text("SELECT r.capture_id,r.seq,r.ts,r.lat,r.lon,n.dl,v.value FROM ("+ci_sql+") v JOIN stg_event_raw r ON r.project_id=:pid AND r.capture_id=v.capture_id AND r.seq=v.seq AND r.event_code='CI' JOIN nmf_file n ON n.id=r.nmf_file_id"),{'pid':pid}).mappings().all()
    from app.measure.mapping import operator_from_dl
    import hashlib
    inserts=[]
    for r in ci:
        op=operator_from_dl(r['dl']);lat=r['lat'];lon=r['lon']
        if lat==0 and lon==0:lat=lon=None
        inserts.append(dict(id='nmf-ci-'+hashlib.sha256(f"{pid}:{r['capture_id']}:{r['seq']}".encode()).hexdigest()[:24],pid=pid,cap=r['capture_id'],seq=r['seq'],ts=r['ts'] or '',lat=lat,lon=lon,sinr=r['value'],operator=op,source='file' if op else 'none',geo='gps_fix' if lat is not None and lon is not None else None))
    if inserts:db.execute(text("""INSERT INTO measurement_points(id,project_id,capture_id,seq,ts,lat,lng,sinr,operator,operator_source,geo_source,event_code,tech,rat)
        VALUES(:id,:pid,:cap,:seq,:ts,:lat,:lon,:sinr,:operator,:source,:geo,'CI','LTE','LTE')
        ON CONFLICT(id) DO UPDATE SET sinr=excluded.sinr,operator=excluded.operator,operator_source=excluded.operator_source"""),inserts)
    rows=[]
    for (cap,seq),v in values.items():
        if not any(k in v for k in ('rsrp','rsrq','rssi','sinr','cqi','tx_power')):continue
        rows.append(dict(pid=pid,cap=cap,seq=seq,**{k:v.get(k) for k in ('rsrp','rsrq','rssi','sinr','cqi','tx_power')}))
    if rows:db.execute(text('''UPDATE measurement_points SET rsrp=:rsrp,rsrq=:rsrq,rssi=:rssi,sinr=:sinr,cqi=:cqi,tx_power=:tx_power
        WHERE project_id=:pid AND capture_id=:cap AND seq=:seq'''),rows)
    # Restore capture context for CELLMEAS skeleton rows that predate enrichment.
    # The closed cell schema is LTE-only; a validated PCI/channel is independent
    # of whether RSRP happened to be present on that observation.
    from app.measure.mapping import band_from_earfcn
    context=[]
    for (cap,seq),v in values.items():
        if not any(k in v for k in ('pci','earfcn','rsrp','rsrq','rssi')):continue
        earfcn=int(v['earfcn']) if v.get('earfcn') is not None else None
        context.append(dict(pid=pid,cap=cap,seq=seq,earfcn=earfcn,band=band_from_earfcn(earfcn) if earfcn is not None else None))
    if context:db.execute(text("""UPDATE measurement_points SET rat='LTE',tech='LTE',earfcn=:earfcn,band=:band
        WHERE project_id=:pid AND capture_id=:cap AND seq=:seq AND event_code='CELLMEAS'"""),context)
    return {'observations':len(values),'updated_sequences':len(rows)}

def metric_counts(db,pid):
    """Count capture-second observations from the canonical Light projection.

    Light is populated for every decoded capture, including captures whose
    detailed rows are also retained.  Reading it once avoids the former wide
    ``COUNT(DISTINCT ...)`` scan over the repeated Deep group table, which
    could spill to disk and made the catalogue endpoint unbounded.
    """
    codes=list(fields())
    expressions=[f'count(d.{code}) AS {code}' for code in codes]
    row=db.execute(text('SELECT '+','.join(expressions)+
        ' FROM nmf_event_light d WHERE d.project_id=:pid'),{'pid':pid}).mappings().one()
    result={code:int(n or 0) for code,n in row.items()}
    sources={code:['nmf_event_light'] for code,n in result.items() if n}
    return result,sources
