"""Read-only source projection; procedure cache is rebuilt deterministically."""
from bisect import bisect_left
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
import re
from threading import Lock
from sqlalchemy import text
from fastapi import HTTPException
from app.routes.metrics import clock
from app.routes.tasks import project
from app.dict.decode import DENY, resolve_pdu
from .procedures import reconstruct

PROTOCOLS = ('RRC LTE', 'RRC NR', 'NAS', 'Événements Nemo', 'MAC-RACH')
MARKERS = ('RRA','RRC','RRD','HOA','HOS','CAA','CAC','CAD','DAA','DAC','DAD','RACHI','CREL','MEI','PBA','PBC','PBD','GAA','GAC','GAD')
SENSITIVE = re.compile(r'rnti|guti|tmsi|imsi|imei|msisdn|phone|subscriber|ue.identity|randomValue|dedicated.*nas', re.I)
PDU_LOCK = Lock()
SOURCE_SQL = '''SELECT s.seq,s.id AS event_id,s.event_code,s.system AS technology,s.direction,s.message AS message_name,
 s.pci,CASE WHEN s.payload_hex ~ '^[0-9A-Fa-f]+$' THEN length(s.payload_hex)/2 END AS size_bytes,
 EXISTS(SELECT 1 FROM param_occurrence p WHERE p.project_id=s.project_id AND p.stg_event_id=s.id AND NOT COALESCE(p.is_identifier,false)) AS has_tree,
 'stg_event' AS source
 FROM stg_event s WHERE s.project_id=:pid AND s.capture_id=:cap
 AND s.event_code IN ('RRCSM','L3SM') AND s.system IN ('LTE','NR')
 UNION ALL
 SELECT r.seq,NULL,r.event_code,NULL,NULL,r.event_code,NULL,NULL,false,'nmf_event_deep'
 FROM stg_event_raw r JOIN nmf_capture c USING(project_id,capture_id)
 WHERE r.project_id=:pid AND r.capture_id=:cap AND r.event_code=ANY(:markers) AND c.decode_level='deep'
 AND EXISTS(SELECT 1 FROM nmf_event_deep d WHERE d.project_id=r.project_id AND d.capture_id=r.capture_id AND d.seq=r.seq)
 UNION ALL
 SELECT d.seq,NULL,d.event_code,NULL,NULL,d.event_code,NULL,NULL,false,'nmf_event_light'
 FROM nmf_event_light d JOIN nmf_capture c USING(project_id,capture_id)
 WHERE d.project_id=:pid AND d.capture_id=:cap AND c.decode_level='light' AND d.event_code=ANY(:markers)
 ORDER BY seq'''


def query(db, sql, params):
    return [dict(r) for r in db.execute(text(sql), params).mappings()]


def capture(db, pid, cap):
    project(db,pid)
    rows=query(db,'''SELECT DISTINCT n.id,n.filename,n.env FROM nmf_file n JOIN stg_event_raw r ON r.nmf_file_id=n.id
        WHERE r.project_id=:pid AND r.capture_id=:cap''',dict(pid=pid,cap=cap))
    if len(rows)!=1:raise HTTPException(404,'capture_not_found_or_ambiguous')
    return rows[0]


def result_id(pid,cap,rows,params):
    return sha256(json.dumps([pid,cap,params,rows],sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()[:32]


def population(db,pid,cap, persist=True):
    meta=capture(db,pid,cap)
    times,_,_=clock(db,pid,cap)
    rows=query(db,SOURCE_SQL,dict(pid=pid,cap=cap,markers=list(MARKERS)))
    for r in rows:
        r['protocol']=('RRC '+r['technology']) if r['event_code']=='RRCSM' else 'NAS' if r['event_code']=='L3SM' else 'MAC-RACH' if r['event_code']=='RACHI' else 'Événements Nemo'
        r['direction']={'1':'UL','2':'DL'}.get(r['direction'])
        r['t_rel_s']=times.get(r['seq'])
        r['capture_id']=cap
        # Imported names only, never arbitrary payloads or unk_ strings.
        r['message_name']=r['message_name'] or r['event_code']
        if r['protocol']=='NAS':r['has_tree']=False
        r['ecgi']=None
        r['procedure_id']=None
    cells=query(db,"""SELECT r.seq,m.ecgi FROM stg_event_raw r LEFT JOIN measurement_points m
       ON m.project_id=r.project_id AND m.capture_id=r.capture_id AND m.seq=r.seq
       AND m.event_code='CELLMEAS' AND m.ecgi_source='sib1_strict_capture_earfcn'
       WHERE r.project_id=:pid AND r.capture_id=:cap AND r.event_code='CELLMEAS' ORDER BY r.seq""",dict(pid=pid,cap=cap))
    for r in rows:
        cell=previous(cells,r['seq'])
        r['ecgi']=str(cell['ecgi']) if cell and cell['ecgi'] is not None else None
    procedures=reconstruct(pid,cap,rows)
    if procedures and persist:
        db.execute(text('''INSERT INTO signaling_procedure(id,project_id,capture_id,type,technology,seq_start,seq_end,duration_ms,outcome,cause,boundary_seqs)
          VALUES(:id,:project_id,:capture_id,:type,:technology,:seq_start,:seq_end,:duration_ms,:outcome,:cause,:boundary_seqs)
          ON CONFLICT(id) DO UPDATE SET seq_end=excluded.seq_end,duration_ms=excluded.duration_ms,
          outcome=excluded.outcome,cause=excluded.cause,boundary_seqs=excluded.boundary_seqs'''),procedures)
        db.commit()
    for r in rows:
        matches=[p for p in procedures if r['seq'] in p['boundary_seqs'] or
                 (p['seq_end'] is not None and p['seq_start']<=r['seq']<=p['seq_end'] and
                  (p['technology'] is None or p['technology']==r['technology']))]
        # Overlapping sessions are explicitly plural, never silently overwritten.
        r['procedure_ids']=[p['id'] for p in matches]
        r['procedure_id']=matches[-1]['id'] if matches else None
    return rows,procedures,meta,times


def filtered(rows,protocols=None,direction=None,q=None,procedure=None,technology=None,from_s=None,to_s=None):
    selected=protocols.split(',') if protocols is not None else list(PROTOCOLS)
    if any(p not in PROTOCOLS for p in selected if p):raise HTTPException(422,{'allowed':PROTOCOLS})
    return [r for r in rows if r['protocol'] in selected and
      (direction is None or (r['direction'] or 'unknown')==direction) and
      (not q or q.casefold() in r['message_name'].casefold()) and
      (not procedure or procedure in r['procedure_ids']) and
      (not technology or r['technology']==technology) and
      (from_s is None or r['t_rel_s'] is not None and r['t_rel_s']>=from_s) and
      (to_s is None or r['t_rel_s'] is not None and r['t_rel_s']<=to_s)]


def previous(rows,seq):
    index=bisect_left([r['seq'] for r in rows],seq)-1
    return rows[index] if index>=0 else None


def gps_points(db,pid,cap,rows,meta):
    indoor=(meta['env'] or '').lower()=='indoor'
    gps=query(db,"""SELECT seq,lat,lon AS lng FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap
       AND event_code='GPS' AND lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180
       AND NOT(lat=0 AND lon=0) ORDER BY seq""",dict(pid=pid,cap=cap)) if not indoor else []
    points=[]
    for r in rows:
        g=previous(gps,r['seq'])
        points.append(dict(seq=r['seq'],t_rel_s=r['t_rel_s'],protocol=r['protocol'],lat=g['lat'] if g else None,lng=g['lng'] if g else None,
                           gps_seq=g['seq'] if g else None,seq_gap=r['seq']-g['seq'] if g else None))
    return points,indoor


def context(db,pid,cap,seq):
    from app.nmf_decoder.projection import source_sql
    values={}
    for name,code,unit in [('rsrp','cell_rsrp','dBm'),('rsrq','cell_rsrq','dB'),('sinr','ci_rs_snr','dB'),('cqi','cqi_wb_cqi_0','index'),('bler_mac','mac_dl_bler','%'),('band','cell_band','index'),('pci','cell_pci','index')]:
        event={'sinr':'CI','cqi':'CQI','bler_mac':'MACRATE'}.get(name,'CELLMEAS')
        previous_event=query(db,"SELECT seq FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap AND event_code=:event AND seq<:seq ORDER BY seq DESC LIMIT 1",dict(pid=pid,cap=cap,event=event,seq=seq))
        source_seq=previous_event[0]['seq'] if previous_event else None
        sql='SELECT seq,value FROM ('+source_sql(code)+') v WHERE capture_id=:cap AND seq=:source_seq'
        found=query(db,sql,dict(pid=pid,cap=cap,source_seq=source_seq)) if source_seq is not None else []
        r=found[0] if found else None
        values[name]=dict(value=float(r['value']) if r else None,unit=unit,source=code,seq=source_seq,seq_gap=seq-source_seq if source_seq is not None else None)
    gps=query(db,"SELECT seq,raw_fields->>'c9' AS velocity FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap AND seq<:seq AND event_code='GPS' ORDER BY seq DESC LIMIT 1",dict(pid=pid,cap=cap,seq=seq))
    speed=None
    if gps:
        try:
            number=float(gps[0]['velocity'])
            if math.isfinite(number) and number>=0:speed=number
        except (TypeError,ValueError):pass
    values['speed']=dict(value=speed,unit='km/h',source='GPS NFF 2.19 Parameters #7, col10 / raw c9',seq=gps[0]['seq'] if gps else None,seq_gap=seq-gps[0]['seq'] if gps else None)
    cell=query(db,"""SELECT seq,ecgi,band FROM measurement_points WHERE project_id=:pid AND capture_id=:cap AND seq=:cellseq
        AND event_code='CELLMEAS' AND ecgi_source='sib1_strict_capture_earfcn' LIMIT 1""",dict(pid=pid,cap=cap,cellseq=values['pci']['seq']))
    return values,cell[0] if cell else None


def contains_identity(value):
    if isinstance(value,dict):return any(DENY.search(str(k)) or SENSITIVE.search(str(k)) or contains_identity(v) for k,v in value.items())
    if isinstance(value,(tuple,list)):
        if isinstance(value,tuple) and len(value)==2 and isinstance(value[0],str) and (DENY.search(value[0]) or SENSITIVE.search(value[0])):return True
        return any(contains_identity(v) for v in value)
    return False


def details(db,pid,cap,seq):
    events=query(db,'SELECT id,event_code,system,channel,direction,message,payload_hex FROM stg_event WHERE project_id=:pid AND capture_id=:cap AND seq=:seq',dict(pid=pid,cap=cap,seq=seq))
    parameters=[];hex_value=None;reason='Absence d’identité non certifiée : hexadécimal masqué.'
    if events and events[0]['event_code']=='RRCSM':
        event=events[0]
        ps=query(db,'SELECT path,value,param_key,is_identifier FROM param_occurrence WHERE project_id=:pid AND stg_event_id=:id ORDER BY id',dict(pid=pid,id=event['id']))
        parameters=[dict(path=p['path'],value=p['value'],param_key=p['param_key']) for p in ps if not p['is_identifier'] and not DENY.search(p['path']) and not SENSITIVE.search(p['path'])]
        with PDU_LOCK:
            try:
                pdu=resolve_pdu(event['system'],event['channel'],event['direction'],event['message'])
                if pdu is not None and event['payload_hex']:
                    pdu.from_uper(bytes.fromhex(event['payload_hex']))
                    if contains_identity(pdu.get_val()):reason='Identité ou conteneur sensible présent : hexadécimal masqué.'
                    else:hex_value=event['payload_hex'];reason=None
            except Exception:
                reason='Décodage incomplet : absence d’identité non certifiée, hexadécimal masqué.'
    elif events:reason='NAS : seul le nom du message est exposé.'
    tree={}
    for p in parameters:
        node=tree
        for part in p['path'].split('/'):
            node=node.setdefault(part,{})
        node['$value']=p['value']
    return dict(tree=tree,parameters=parameters,text='\n'.join(p['path']+' = '+str(p['value']) for p in parameters),hex=hex_value,hex_reason=reason,
                tree_source='BC1 param_occurrence (sanitized)',tree_route_gap='No per-message BC1 tree endpoint in current OpenAPI')
