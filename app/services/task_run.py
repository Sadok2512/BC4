"""Deterministic task reconstruction. Order is always capture_id,seq, never ts."""
import math
import uuid
from decimal import Decimal, InvalidOperation
from bisect import bisect_left
from statistics import mean
from urllib.parse import urlsplit
from sqlalchemy import text
from app.services.task_privacy import command_xml

EVENT_SQL="""SELECT capture_id,seq,event_code,raw_fields FROM stg_event_raw
 WHERE project_id=:pid AND event_code IN ('CMDREQ','DAA','DRATE','DCOMP','DSUMMARY','AQDL')
 ORDER BY capture_id,seq"""

def number(value):
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None

def integer(value):
    try:
        return int(str(value))
    except (TypeError,ValueError):return None

def seconds(value):
    try:
        h,m,s=value.split(':');v=Decimal(h)*3600+Decimal(m)*60+Decimal(s);return v if v.is_finite() else None
    except (TypeError,ValueError,AttributeError,InvalidOperation):return None

def stable(*parts):return str(uuid.uuid5(uuid.NAMESPACE_URL,':'.join(map(str,parts))))

def metadata(fields):
    result={};action=fields.get('service_action','')
    try:
        root=command_xml(fields.get('payload_b64'))
        allowed={'Direction','Address','NumberOfThreads','MaximeDuration','CallDuration'}
        for e in root.iter():
            if e.tag in allowed:result[e.tag]=e.attrib.get('All') or e.text
    except Exception:pass
    kind='VOICE' if 'Call' in action else 'PING' if 'Ping' in action else 'OTHER'
    if action.startswith('StartHTTP'):
        # XML Direction 1 = HTTP download; 0 = upload. Unknown stays OTHER.
        kind='HTTP_UL' if action in ('StartHTTPUL','StartHTTPUpload') else 'HTTP_DL' if result.get('Direction')=='1' else 'OTHER'
    host=None
    if kind.startswith('HTTP') and result.get('Address'):
        host=urlsplit('//' + result['Address'].split('://')[-1]).hostname
    return dict(task_type=kind,host=host,threads=integer(result.get('NumberOfThreads')),
        max_duration_s=number(result.get('MaximeDuration')),call_duration_s=number(result.get('CallDuration')))

def reconstruct(rows,pid):
    tasks=[];current=None
    def close():
        if current is None:return
        t=current;reasons=[]
        if t['seq_daa'] is None:reasons.append('missing_DAA')
        if t['seq_dcomp'] is None:reasons.append('missing_DCOMP')
        t['duration_s']=float(t['_end']-t['_start']) if t['_end'] is not None and t['_start'] is not None else None
        if t['duration_s'] is None or t['duration_s']<=0:reasons.append('invalid_duration')
        prev=None
        integrated=0.0; integration_valid=True; previous_time=0.0
        for s in t['_samples']:
            s['capture_time_s']=float(s['_time']) if s['_time'] is not None else None
            s['t_rel_s']=float(s.pop('_time')-t['_start']) if s['_time'] is not None and t['_start'] is not None else None
            if s['t_rel_s'] is None or s['t_rel_s']<0 or (prev is not None and s['t_rel_s']<=prev):reasons.append('invalid_task_time')
            if s['t_rel_s'] is not None:prev=s['t_rel_s']
            if s['bps'] is None or s['bps']<0:reasons.append('invalid_DRATE')
            dt=s['t_rel_s']-previous_time if s['t_rel_s'] is not None else None
            if dt is None or dt<=0 or s['bps'] is None or s['bps']<0:integration_valid=False
            else:integrated+=s['bps']*dt/8
            if s['t_rel_s'] is not None:previous_time=s['t_rel_s']
        if t['task_type'].startswith('HTTP') and not t['_samples'] and not (t['bytes_dcomp'] is not None and t['duration_s'] is not None and t['duration_s']>0):reasons.append('missing_DRATE_and_fallback')
        if t['task_type'].startswith('HTTP') and t['bytes_dcomp'] is None:reasons.append('missing_DCOMP_bytes')
        counters=[s['bytes_cum'] for s in t['_samples'] if s['bytes_cum'] is not None]
        if any(b<a for a,b in zip(counters,counters[1:])):reasons.append('nonmonotonic_DRATE_bytes')
        gap = bool(t['_samples'] and integration_valid and t['bytes_dcomp'] is not None and
                   t['bytes_dcomp']>0 and abs(integrated-t['bytes_dcomp'])/t['bytes_dcomp']>.05)
        if gap:reasons.append('DRATE_integral_DCOMP_gap_gt_5pct')
        if t['_samples'] and not integration_valid:reasons.append('invalid_DRATE_interval')
        t['mos_aqdl']=mean(t['_mos']) if t['_mos'] else None
        t['status']=('partial' if gap else 'incomplete') if reasons else 'ok';t['reason']=';'.join(sorted(set(reasons))) or None
        for key in ('_start','_end'):
            if t[key] is not None:t[key]=float(t[key])
        tasks.append(t)
    for r in rows:
        cap=r['capture_id'];seq=r['seq'];ev=r['event_code'];f=r['raw_fields']
        if current and current['capture_id']!=cap:close();current=None
        action=f.get('service_action','')
        start=ev=='CMDREQ' and (action.startswith('StartHTTP') or action in ('VoiceCallStart','ReceiveCallStart','StartPing'))
        if start:
            if current:close()
            current=dict(id=stable(pid,cap,seq),project_id=pid,capture_id=cap,seq_start=seq,seq_end=seq,
                seq_daa=None,seq_dcomp=None,bytes_dcomp=None,operator=None,band=None,tech=None,
                _start=None,_end=None,_samples=[],_mos=[],**metadata(f))
        if not current:continue
        t=current;t['seq_end']=seq
        if ev=='DAA' and t['seq_daa'] is None:t['seq_daa']=seq;t['_start']=seconds(f.get('ts'))
        if ev=='DCOMP' and t['seq_dcomp'] is None:t['seq_dcomp']=seq;t['_end']=seconds(f.get('ts'));t['bytes_dcomp']=integer(f.get('c10'))
        if ev=='AQDL' and number(f.get('c4')) is not None:t['_mos'].append(number(f['c4']))
        if ev=='DRATE':t['_samples'].append(dict(id=stable(t['id'],seq),task_id=t['id'],seq=seq,_time=seconds(f.get('ts')),bps=number(f.get('_ul_bps') if t['task_type']=='HTTP_UL' else f.get('c6')),bytes_cum=integer(f.get('c8'))))
    close();return tasks

def load_tasks(db,pid,captures=None):
    from app.nmf_decoder.projection import source_sql
    decoded={}
    for code in ('app_dl_bitrate','app_ul_bitrate','app_dl_bytes','aqdl_mos'):
        for r in db.execute(text(source_sql(code)),{'pid':pid}).mappings():
            decoded.setdefault((r['capture_id'],r['seq']),{})[code]=r['value']
    rows=[]
    event_sql=EVENT_SQL if captures is None else EVENT_SQL.replace(' ORDER BY', ' AND capture_id=ANY(:captures) ORDER BY')
    for r in db.execute(text(event_sql),{'pid':pid,'captures':captures}).mappings():
        row=dict(r);f=dict(row['raw_fields']);v=decoded.get((row['capture_id'],row['seq']),{})
        if row['event_code']=='DRATE':
            f['c6']=v.get('app_dl_bitrate');f['c8']=v.get('app_dl_bytes');f['_ul_bps']=v.get('app_ul_bitrate')
        if row['event_code']=='AQDL':f['c4']=v.get('aqdl_mos')
        row['raw_fields']=f;rows.append(row)
    return reconstruct(rows,pid)

def radio_index(rows):
    bycap={}
    for row in rows:bycap.setdefault(row['capture_id'],[]).append(dict(row))
    return {cap:(ms,[m['seq'] for m in ms]) for cap,ms in bycap.items()}

def preceding_radio(index,cap,seq):
    ms,ss=index.get(cap,([],[]));i=bisect_left(ss,seq)-1
    if i<0:return {}
    previous_rows=ms[bisect_left(ss,ss[i]):i+1]
    fields=('rsrp','rsrq','sinr','cqi','earfcn','rat','operator','band','tech')
    if len({tuple(row.get(k) for k in fields) for row in previous_rows})>1:return {}
    return ms[i]

def populate_tasks(db,pid,captures=None):
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),{'key':'tasks:'+pid})
    tasks=load_tasks(db,pid,captures)
    # Deterministic upserts preserve source staging and all observed DRATE rows.
    radio=[dict(row) for row in db.execute(text("""SELECT capture_id,seq,event_code,rsrp,rsrq,sinr,cqi,earfcn,rat,operator,band,tech
        FROM measurement_points WHERE project_id=:pid AND seq IS NOT NULL
        AND (event_code='CELLMEAS' OR (event_code='CQI' AND cqi IS NOT NULL))
        ORDER BY capture_id,seq,id"""),{'pid':pid}).mappings()]
    cellmeas=radio_index(row for row in radio if row['event_code']=='CELLMEAS')
    cqi=radio_index(row for row in radio if row['event_code']=='CQI')
    count=0
    for t in tasks:
        contexts={k:set() for k in ('operator','band','tech')}
        for sample in t['_samples']:
            # Select the preceding CELLMEAS even when its validated metrics are NULL.
            # CQI has its own event stream and provenance; it cannot hide CELLMEAS.
            m=preceding_radio(cellmeas,t['capture_id'],sample['seq'])
            q=preceding_radio(cqi,t['capture_id'],sample['seq'])
            sample.update({k:m.get(k) for k in ('rsrp','rsrq','sinr','earfcn','rat')})
            sample.update(mp_seq=m.get('seq'),seq_gap=sample['seq']-m['seq'] if m else None,pci=None,
                          cqi=q.get('cqi'),cqi_seq=q.get('seq'),cqi_seq_gap=sample['seq']-q['seq'] if q else None)
            for k in ('operator','band','tech'):
                if m.get(k) is not None:contexts[k].add(m[k])
        for k,values in contexts.items():t[k]=next(iter(values)) if len(values)==1 else None
        row={k:v for k,v in t.items() if not k.startswith('_')}
        cols=list(row); updates=','.join(f'{k}=EXCLUDED.{k}' for k in cols if k!='id')
        db.execute(text(f"INSERT INTO task_run ({','.join(cols)}) VALUES ({','.join(':'+k for k in cols)}) ON CONFLICT(id) DO UPDATE SET {updates}"),row)
        db.execute(text('DELETE FROM task_sample WHERE task_id=:id AND NOT (seq=ANY(:seqs))'),{'id':t['id'],'seqs':[s['seq'] for s in t['_samples']]})
        for s in t['_samples']:
            row={k:v for k,v in s.items() if not k.startswith('_')};cols=list(row)
            db.execute(text(f"INSERT INTO task_sample ({','.join(cols)}) VALUES ({','.join(':'+k for k in cols)}) ON CONFLICT(id) DO UPDATE SET "+','.join(f'{k}=EXCLUDED.{k}' for k in cols if k!='id')),row);count+=1
    db.execute(text('DELETE FROM task_run WHERE project_id=:pid AND NOT (id=ANY(:ids))'+(' AND capture_id=ANY(:captures)' if captures is not None else '')),{'pid':pid,'ids':[t['id'] for t in tasks],'captures':captures})
    return {'tasks':len(tasks),'samples':count,'incomplete':sum(t['status']=='incomplete' for t in tasks)}
