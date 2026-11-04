"""Read-only source projection; procedure cache is rebuilt deterministically."""
from bisect import bisect_left
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from decimal import Decimal
import re
from threading import Lock
from time import monotonic
from sqlalchemy import text
from fastapi import HTTPException
from app.routes.metrics import clock
from app.routes.tasks import project
from app.dict.decode import DENY, resolve_pdu
from .procedures import reconstruct, RULES
from .capture_cache import capture_stamp

PROTOCOLS = ('RRC LTE', 'RRC NR', 'NAS', 'Événements Nemo', 'MAC-RACH')
# 0.67.0 — layer slugs added alongside the human protocol labels (dual field).
LAYERS = ('rrc_lte', 'rrc_nr', 'nas', 'event', 'mac')
LAYER_FOR_PROTOCOL = dict(zip(PROTOCOLS, LAYERS))
MARKERS = ('RRA','RRC','RRD','RRF','RRRE','HOA','HOS','HOI','CAA','CAC','CAD','DAA','DAC','DAD','RACHI','CREL','MEI','PBA','PBC','PBD','PBF','GAA','GAC','GAD','LOCK','MARK','SCELLMOD','TUA','TUS','TUF','LUA','LUS','LUF')
SENSITIVE = re.compile(r'rnti|guti|tmsi|imsi|imei|msisdn|phone|subscriber|ue.identity|randomValue|dedicated.*nas', re.I)
PDU_LOCK = Lock()
_POPULATION_CACHE: dict[tuple[str, str, str], tuple[tuple, float, tuple]] = {}
_POPULATION_CACHE_LOCK = Lock()
_POPULATION_BUILD_LOCK = Lock()
SOURCE_SQL = '''SELECT s.seq,s.id AS event_id,s.event_code,s.system AS technology,s.direction,s.message AS message_name,
 s.pci,CASE WHEN s.payload_hex ~ '^[0-9A-Fa-f]+$' THEN length(s.payload_hex)/2 END AS size_bytes,
 EXISTS(SELECT 1 FROM param_occurrence p WHERE p.project_id=s.project_id AND p.stg_event_id=s.id AND NOT COALESCE(p.is_identifier,false)) AS has_tree,
 'stg_event' AS source, EXISTS(SELECT 1 FROM param_occurrence p WHERE p.project_id=s.project_id AND p.stg_event_id=s.id AND p.path LIKE '%mobilityControlInfo%') AS ho_reconfiguration
 FROM stg_event s WHERE s.project_id=:pid AND s.capture_id=:cap
 AND s.event_code IN ('RRCSM','L3SM') AND s.system IN ('LTE','NR')
 UNION ALL
 SELECT r.seq,NULL,r.event_code,NULL,NULL,r.event_code,NULL,NULL,false,'nmf_event_deep',false
 FROM stg_event_raw r JOIN nmf_capture c USING(project_id,capture_id)
 WHERE r.project_id=:pid AND r.capture_id=:cap AND r.event_code=ANY(:markers) AND c.decode_level='deep'
 AND EXISTS(SELECT 1 FROM nmf_event_deep d WHERE d.project_id=r.project_id AND d.capture_id=r.capture_id AND d.seq=r.seq)
 UNION ALL
 SELECT r.seq,NULL,r.event_code,NULL,NULL,r.event_code,NULL,NULL,false,'stg_event_raw / nmf_event_light',false
 FROM stg_event_raw r JOIN nmf_capture c USING(project_id,capture_id)
 WHERE r.project_id=:pid AND r.capture_id=:cap AND c.decode_level='light' AND r.event_code=ANY(:markers)
 AND EXISTS(SELECT 1 FROM nmf_event_light d WHERE d.project_id=r.project_id AND d.capture_id=r.capture_id AND d.event_code=r.event_code)
 ORDER BY seq'''


def query(db, sql, params):
    return [dict(r) for r in db.execute(text(sql), params).mappings()]


def radio_transition_attrs(code, detail=None, scg=None):
    """Project only decoder-certified source/target radio identities."""
    attrs = {}
    subtype = None
    if code in ('HOA', 'HOS') and detail:
        if detail.get('hoa_hoa_type') is not None:
            attrs['ho_type'] = int(detail['hoa_hoa_type'])
        for source, target in (
            ('hoa_pci', 'source_pci'), ('hoa_ch_number', 'source_earfcn'),
            ('hoa_att_pci', 'target_pci'), ('hoa_att_ch', 'target_earfcn'),
        ):
            if detail.get(source) is not None:
                attrs[target] = int(detail[source])
    elif code == 'SCELLMOD' and scg and scg.get('subtype'):
        subtype = scg['subtype']
        attrs['scellmod_subtype'] = subtype
        for source in ('added_pci', 'added_earfcn',
                       'removed_pci', 'removed_earfcn'):
            if scg.get(source) is not None:
                attrs[source] = int(scg[source])
        if subtype == 'PSCELL_CHANGE':
            attrs['source_pci'] = attrs.get('removed_pci')
            attrs['source_earfcn'] = attrs.get('removed_earfcn')
            attrs['target_pci'] = attrs.get('added_pci')
            attrs['target_earfcn'] = attrs.get('added_earfcn')
        elif subtype == 'SCG_ADD':
            attrs['target_pci'] = attrs.get('added_pci')
            attrs['target_earfcn'] = attrs.get('added_earfcn')
        else:  # SCG_RELEASE: the removed cell is the affected target.
            attrs['target_pci'] = attrs.get('removed_pci')
            attrs['target_earfcn'] = attrs.get('removed_earfcn')
    if attrs.get('target_pci') is not None:
        attrs['pci'] = attrs['target_pci']
        attrs['earfcn'] = attrs.get('target_earfcn')
        attrs['target_cell'] = {
            'pci': attrs['target_pci'], 'earfcn': attrs.get('target_earfcn'),
        }
    return subtype, attrs


def capture(db, pid, cap):
    project(db,pid)
    rows=query(db,'''SELECT DISTINCT n.id,n.filename,n.env FROM nmf_file n JOIN stg_event_raw r ON r.nmf_file_id=n.id
        WHERE r.project_id=:pid AND r.capture_id=:cap''',dict(pid=pid,cap=cap))
    if len(rows)!=1:raise HTTPException(404,'capture_not_found_or_ambiguous')
    return rows[0]


def result_id(pid,cap,rows,params):
    return sha256(json.dumps([pid,cap,params,rows],sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()[:32]


def _population_stamp(db, pid, cap) -> tuple:
    """Cheap source/decode stamp used to reuse one capture projection.

    Every Signaling endpoint used to rebuild the same population independently.
    The stamp changes when staged rows or the capture decode state changes, so
    cached values never cross a source mutation or a Deep/Light upgrade.
    """
    stamp = capture_stamp(db, pid, cap)
    return (stamp.decoder_version, stamp.decoded_at, stamp.event_count,
            stamp.raw_count, stamp.max_seq)


def population(db,pid,cap, persist=True):
    stamp = _population_stamp(db, pid, cap)
    key = (pid, cap, stamp[0])
    with _POPULATION_CACHE_LOCK:
        cached = _POPULATION_CACHE.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[2]
    # The first page load fans out to several endpoints. Serialize only the
    # cold projection build so those requests share one computed population.
    with _POPULATION_BUILD_LOCK:
        with _POPULATION_CACHE_LOCK:
            cached = _POPULATION_CACHE.get(key)
            if cached is not None and cached[0] == stamp:
                return cached[2]
        value = _build_population(db, pid, cap, persist=persist)
        with _POPULATION_CACHE_LOCK:
            _POPULATION_CACHE[key] = (stamp, monotonic(), value)
        return value


def _build_population(db,pid,cap, persist=True):
    meta=capture(db,pid,cap)
    times,_,_=clock(db,pid,cap)
    rows=query(db,SOURCE_SQL,dict(pid=pid,cap=cap,markers=list(MARKERS)))
    for r in rows:
        r['protocol']=('RRC '+r['technology']) if r['event_code']=='RRCSM' else 'NAS' if r['event_code']=='L3SM' else 'MAC-RACH' if r['event_code']=='RACHI' else 'Événements Nemo'
        r['layer']=LAYER_FOR_PROTOCOL[r['protocol']]
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
    # 0.87.1 BC3 — Source unique nmf_event_pair pour les types qui y figurent
    # (attach, bearer, call, data_session, ho, rrc_connection). Les paires de
    # cette table sont déjà construites avec la discipline capture-local +
    # ordre (capture_id, seq) + outcome strict. Elles REMPLACENT la sortie de
    # `reconstruct` qui s'appariait à tort (ex. attach GAA→GAD au lieu de
    # GAA→GAC) ou coupait sur chaque nouveau PBA. Les types absents de
    # `nmf_event_pair` (rrc_setup, reestablishment) restent produits par
    # `reconstruct`. Témoin 01bfc2fc5350 : attach seq_start=2 passe de
    # duration_ms=801107 (bug) à 0 (pair GAA→GAC same ts).
    _PAIR_TYPES = {'attach','bearer','call','data_session','ho','rrc_connection'}
    pair_rows = query(db,
        """SELECT type, seq_start, seq_end, duration_nemo_ms, outcome, cause,
                  context_id
           FROM nmf_event_pair
           WHERE project_id=:pid AND capture_id=:cap AND type = ANY(:types)
           ORDER BY type, seq_start""",
        dict(pid=pid, cap=cap, types=sorted(_PAIR_TYPES)))
    # Index reconstruct pour hériter technology + boundary_seqs quand match.
    _reco_idx = {(p['type'], p['seq_start']): p for p in procedures}
    # Mapping outcome nmf_event_pair → UI procedure outcome.
    def _norm_outcome(oc):
        if oc in ('completed','ok'): return 'ok'
        return oc or 'incomplete'
    pair_procs = []
    for pr in pair_rows:
        kind = pr['type']
        reco = _reco_idx.get((kind, pr['seq_start']))
        tech = (reco or {}).get('technology') or 'LTE'
        boundary = [pr['seq_start']] + ([pr['seq_end']] if pr['seq_end'] is not None else [])
        # Preserve intermediate boundary_seqs du reconstruct quand disponible
        # (ex. pour le highlighting du setup middle event). Fallback sinon.
        if reco and reco.get('boundary_seqs'):
            seen = set(boundary)
            for s in reco['boundary_seqs']:
                if s not in seen:
                    boundary.append(s); seen.add(s)
        pair_procs.append(dict(
            id=sha256(f"pair:{pid}:{cap}:{kind}:{pr['seq_start']}".encode()).hexdigest()[:24],
            project_id=pid, capture_id=cap, type=kind, technology=tech,
            seq_start=pr['seq_start'], seq_end=pr['seq_end'],
            duration_ms=(float(pr['duration_nemo_ms']) if pr['duration_nemo_ms'] is not None else None),
            outcome=_norm_outcome(pr['outcome']), cause=pr['cause'],
            boundary_seqs=sorted(boundary),
            # 0.89.1 — Procs sourced depuis nmf_event_pair = marqueurs Nemo
            # (RRA/HOA/CAA/DAA/GAA/PBA → stage0 des RULES). source_start/_end
            # exposent le code Nemo du marker d'ouverture/fermeture.
            source='nmf_marker',
            source_start=RULES[kind][0][0] if kind in RULES else None,
            source_end=(RULES[kind][-1][0] if (kind in RULES and pr['seq_end'] is not None) else None),
        ))
    # Remplacement : garde reconstruct pour les types hors _PAIR_TYPES uniquement.
    procedures = [p for p in procedures if p['type'] not in _PAIR_TYPES] + pair_procs
    procedures.sort(key=lambda p: (p['seq_start'], p['type']))
    if procedures and persist:
        db.execute(text('''INSERT INTO signaling_procedure(id,project_id,capture_id,type,technology,seq_start,seq_end,duration_ms,outcome,cause,boundary_seqs)
          VALUES(:id,:project_id,:capture_id,:type,:technology,:seq_start,:seq_end,:duration_ms,:outcome,:cause,:boundary_seqs)
          ON CONFLICT(id) DO UPDATE SET seq_end=excluded.seq_end,duration_ms=excluded.duration_ms,
          outcome=excluded.outcome,cause=excluded.cause,boundary_seqs=excluded.boundary_seqs'''),procedures)
        db.commit()
    for r in rows:
        matches=[p for p in procedures if r['seq'] in p['boundary_seqs'] or
                 (p['type']=='ho' and r['ho_reconfiguration'] and p['seq_end'] is not None and p['seq_start']<=r['seq']<=p['seq_end'])]
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
        points.append(dict(seq=r['seq'],t_rel_s=r['t_rel_s'],protocol=r['protocol'],layer=r['layer'],lat=g['lat'] if g else None,lng=g['lng'] if g else None,
                           gps_seq=g['seq'] if g else None,seq_gap=r['seq']-g['seq'] if g else None))
    return points,indoor


def context(db,pid,cap,seq):
    from app.nmf_decoder.projection import source_sql
    times,_,_=clock(db,pid,cap)
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
    for metric in values.values():
        source_time=times.get(metric['seq'])
        event_time=times.get(seq)
        metric['time_gap_s']=(float(Decimal(str(event_time))-Decimal(str(source_time)))
                              if event_time is not None and source_time is not None else None)
        metric['temporal_relation']=('unavailable' if metric['time_gap_s'] is None else
                                     'same_timestamp' if metric['time_gap_s']==0 else 'previous_timestamp')
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
    elif events and events[0]['event_code']=='L3SM':
        # 0.72.0 — NAS sanitized decode via pycrate. Allowlist safe IE,
        # denylist identité + crypto. P0 CLAUDE.md : jamais imsi/imei/
        # tmsi/guti/mac/rand/autn/res/keys dans la réponse.
        from .nas_decoder import decode as nas_decode
        event=events[0]
        if event['payload_hex']:
            nas=nas_decode(event['payload_hex'],event['direction'],event['system'])
            # pycrate param rows → même format que RRC (path/value/param_key).
            parameters=[dict(path=p['path'],value=p['value'] if p['safe'] else '<redacted>',
                             param_key=p['name'],
                             redacted_reason=p['redacted_reason'] if not p['safe'] else None)
                        for p in nas['parameters']]
            reason=(f"NAS {nas['pdu_class']} — statut {nas['status']}. "
                    f"Identités et secrets de sécurité masqués (CLAUDE.md P0). "
                    f"Payload binaire non exposé.") if nas['status']!='UNSUPPORTED' else \
                   (nas['reason'] or 'NAS : décodage indisponible.')
        else:
            reason='NAS : pas de payload.'
    else:
        # 0.73.1 — Événements d'état BC2 (RACHI, HOA, HOS, HOI, MEI, CREL,
        # RRA, RRC, RRD, PBA, PBC, PBD, CAA, CAC, CAD, DAA, DAC, DAD, GAA,
        # GAC, GAD, LOCK, MARK, SCELLMOD) : pas de PDU ASN.1 par nature.
        # Expose les attributs décodeur depuis nmf_event_deep / light,
        # préfixés par event_code (ex. rachi_pathloss, hoi_ho_duration).
        marker=query(db,"""SELECT r.event_code,r.ts
          FROM stg_event_raw r
          WHERE r.project_id=:pid AND r.capture_id=:cap AND r.seq=:seq
          AND r.event_code=ANY(:markers) LIMIT 1""",
          dict(pid=pid,cap=cap,seq=seq,markers=list(MARKERS)))
        if marker:
            ec=marker[0]['event_code']
            prefix=ec.lower()+'_'
            # Pull non-null attributes from nmf_event_deep (fall back to _light).
            attrs=query(db,f"""SELECT * FROM nmf_event_deep
              WHERE project_id=:pid AND capture_id=:cap AND seq=:seq LIMIT 1""",
              dict(pid=pid,cap=cap,seq=seq))
            if not attrs:
                attrs=query(db,"""SELECT * FROM nmf_event_light
                  WHERE project_id=:pid AND capture_id=:cap AND seq=:seq
                  AND event_code=:ec LIMIT 1""",dict(pid=pid,cap=cap,seq=seq,ec=ec))
            if attrs:
                row=attrs[0]
                parameters=[dict(path=f'{ec}/{k[len(prefix):]}',value=v,
                                 param_key=k[len(prefix):],redacted_reason=None)
                            for k,v in row.items()
                            if k.startswith(prefix) and v not in (None,'',[],{})]
            reason=(f"Événement d'état décodeur BC2 ({ec}) — pas de PDU ASN.1 "
                    f"par nature. {len(parameters)} attribut(s) décodeur exposé(s).")
    tree={}
    for p in parameters:
        node=tree
        for part in p['path'].split('/'):
            node=node.setdefault(part,{})
        node['$value']=p['value']
    return dict(tree=tree,parameters=parameters,text='\n'.join(p['path']+' = '+str(p['value']) for p in parameters),hex=hex_value,hex_reason=reason,
                tree_source='BC1 param_occurrence (sanitized)',tree_route_gap='No per-message BC1 tree endpoint in current OpenAPI')


# ---------------------------------------------------------------------------
# 0.70.0 — Timeline événements. Agrège markers + procedures en events pour
# le ruban front, en appliquant les règles d'appariement explicites de
# app.signaling.links. Aucun ts, aucune invention.
# ---------------------------------------------------------------------------
from .links import EVENT_RULES, EVENT_LANE, PROCEDURE_LANE, LANES, LinkContext


def project_legacy_events(db, pid, cap, rows, procedures, meta, times,
                          lanes=None, failures_only=False):
    """Pure-ish legacy projection over an already loaded capture population.

    Link rules may perform capture-scoped lookups through ``db``.  Loading the
    expensive population is deliberately left to the import materializer.
    """
    rows_by_seq = {r['seq']: r for r in rows}
    seqs = sorted(rows_by_seq)
    ctx = LinkContext(project_id=pid, capture_id=cap, rows_by_seq=rows_by_seq, seqs=seqs, db=db)
    allowed = set(lanes.split(',')) if lanes else set(LANES)
    out = []
    # Mobilité étape 3 — pré-charger GPS points (capture-local) + attrs par
    # seq pour les events avec cause/status/cells (RRRE, RRD, SCELLMOD groups,
    # HOA type). Ordre (capture_id, seq) JAMAIS ts.
    indoor = (meta.get('env') or '').lower() == 'indoor'
    gps_rows = query(db, """SELECT seq, lat, lon AS lng FROM stg_event_raw
        WHERE project_id=:pid AND capture_id=:cap AND event_code='GPS'
          AND lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180
          AND NOT(lat=0 AND lon=0) ORDER BY seq""",
        dict(pid=pid, cap=cap)) if not indoor else []
    gps_seqs = [g['seq'] for g in gps_rows]
    def _attach_gps(seq):
        """Nearest GPS point (prev OR next in seq) with seq_gap. Rule
        (capture_id, seq) ordered — never ts. Returns (lat, lng, gps_seq,
        seq_gap) ; (None,None,None,None) si pas de GPS disponible."""
        if not gps_seqs:
            return None, None, None, None
        idx = bisect_left(gps_seqs, seq)
        prev_g = gps_rows[idx - 1] if idx > 0 else None
        next_g = gps_rows[idx] if idx < len(gps_rows) else None
        best = None
        for g in (prev_g, next_g):
            if g is None:
                continue
            gap = abs(g['seq'] - seq)
            if best is None or gap < best[3]:
                best = (g['lat'], g['lng'], g['seq'], gap)
        return best if best else (None, None, None, None)
    # Attrs enrichis pour certains codes via nmf_event_deep + nmf_event_group
    # (seules les colonnes documentées dans les YAML de décodeur sont lues).
    attrs_by_seq = {}
    enriched_codes = tuple(c for c in ('HOA', 'RRRE', 'RRD', 'SCELLMOD') if c in EVENT_LANE)
    if enriched_codes:
        det_rows = query(db, f"""SELECT seq, event_code, hoa_hoa_type,
                hoa_pci, hoa_ch_number, hoa_att_pci, hoa_att_ch,
                rrre_re_est_cause, rrre_re_est_status,
                rrd_rrc_rel_cause, rrd_rrc_rel_status, scellmod_result
            FROM nmf_event_deep WHERE project_id=:pid AND capture_id=:cap
              AND event_code = ANY(:codes)""",
            dict(pid=pid, cap=cap, codes=list(enriched_codes)))
        for d in det_rows:
            attrs_by_seq[d['seq']] = d
    # SCELLMOD subtype par event (PSCELL 199) : add/remove dans le même event
    # = PSCELL_CHANGE ; add seul = SCG_ADD ; remove seul = SCG_RELEASE.
    scellmod_by_seq = {}
    if 'SCELLMOD' in EVENT_LANE:
        scg_rows = query(db, """SELECT d.seq,
            BOOL_OR(g.group_name='added' AND g.scellmod_cell_type=199) AS a,
            BOOL_OR(g.group_name='removed' AND g.scellmod_cell_type=199) AS r,
            MAX(g.scellmod_added_pci) FILTER
              (WHERE g.group_name='added' AND g.scellmod_cell_type=199) AS added_pci,
            MAX(g.scellmod_added_arfcn) FILTER
              (WHERE g.group_name='added' AND g.scellmod_cell_type=199) AS added_earfcn,
            MAX(g.scellmod_removed_pci) FILTER
              (WHERE g.group_name='removed' AND g.scellmod_cell_type=199) AS removed_pci,
            MAX(g.scellmod_removed_arfcn) FILTER
              (WHERE g.group_name='removed' AND g.scellmod_cell_type=199) AS removed_earfcn
            FROM nmf_event_deep d
            LEFT JOIN nmf_event_group g USING (project_id, capture_id, seq)
            WHERE d.project_id=:pid AND d.capture_id=:cap
              AND d.event_code='SCELLMOD' GROUP BY d.seq""",
            dict(pid=pid, cap=cap))
        for s in scg_rows:
            if s['a'] and s['r']:
                s['subtype'] = 'PSCELL_CHANGE'
            elif s['a']:
                s['subtype'] = 'SCG_ADD'
            elif s['r']:
                s['subtype'] = 'SCG_RELEASE'
            else:
                continue
            scellmod_by_seq[s['seq']] = s
    # HOS carries no PCI/channel columns of its own.  Its target is the
    # hoa_att_* pair on the capture-local HOA boundary certified by
    # nmf_event_pair; never infer it from timestamp proximity.
    hoa_seq_by_hos_seq = {
        p['seq_end']: p['seq_start'] for p in procedures
        if p['type'] == 'ho' and p['seq_end'] is not None
    }
    # 1) State events (markers) → one event each, lane + rule from links.py
    for r in rows:
        code = r['event_code']
        if code not in EVENT_LANE:
            continue
        lane = EVENT_LANE[code]
        if lane not in allowed:
            continue
        rule = EVENT_RULES.get(code)
        link = rule(ctx, r) if rule else dict(pivot_seq=None, linked_seqs=[], link_rule='no_rule', seq_gap=None)
        # Outcome : failures connus (RRF, RRRE rejected, TUF, LUF, PBF,
        # SCELLMOD result ∈ {2,10..15}) marqués 'fail' explicitement pour
        # le filtre success/échec côté front. Les autres = None (neutre).
        ok = None
        ev_type = code  # type exposé ; SCELLMOD remplacé par sous-type plus bas
        ev_attrs = {}
        ev_cause = None
        det_seq = hoa_seq_by_hos_seq.get(r['seq']) if code == 'HOS' else r['seq']
        det = attrs_by_seq.get(det_seq)
        sub, transition_attrs = radio_transition_attrs(
            code, det, scellmod_by_seq.get(r['seq']))
        ev_attrs.update(transition_attrs)
        if code == 'HOS' and det:
            ok = 'ok'
        if code == 'RRRE' and det:
            if det.get('rrre_re_est_cause') is not None:
                ev_attrs['re_est_cause'] = int(det['rrre_re_est_cause'])
                ev_cause = str(int(det['rrre_re_est_cause']))
            if det.get('rrre_re_est_status') is not None:
                ev_attrs['re_est_status'] = int(det['rrre_re_est_status'])
                if int(det['rrre_re_est_status']) == 3:
                    ok = 'fail'
        if code == 'RRD' and det:
            if det.get('rrd_rrc_rel_cause') is not None:
                ev_attrs['rrc_rel_cause'] = int(det['rrd_rrc_rel_cause'])
                ev_cause = str(int(det['rrd_rrc_rel_cause']))
        if code in ('RRF', 'TUF', 'LUF', 'PBF'):
            ok = 'fail'
        if code == 'SCELLMOD':
            if sub:
                ev_type = sub
            if det and det.get('scellmod_result') is not None:
                res = int(det['scellmod_result'])
                ev_attrs['scellmod_result'] = res
                if res == 2 or (10 <= res <= 15):
                    ok = 'fail'
                    ev_cause = str(res)
        # GPS nearest seq (prev or next, lowest |seq_gap|) — Mobilité 2d point 2.
        lat, lng, gps_seq, gps_gap = _attach_gps(r['seq'])
        ev_attrs['lat'] = lat
        ev_attrs['lng'] = lng
        ev_attrs['gps_seq'] = gps_seq
        ev_attrs['gps_seq_gap'] = gps_gap
        ev_attrs.setdefault('pci', r.get('pci'))
        ev_attrs['ecgi'] = r.get('ecgi')
        ev = dict(
            id=f"{code.lower()}:{r['seq']}",
            lane=lane,
            type=ev_type,
            kind='fail' if ok == 'fail' else 'mark',
            seq=r['seq'],
            seq_end=None,
            t_rel_s=r['t_rel_s'],
            t_rel_end_s=None,
            duration_ms=None,
            outcome=ok,
            cause=ev_cause,
            label=ev_type,
            attrs=ev_attrs,
            pivot_seq=link['pivot_seq'],
            linked_seqs=link['linked_seqs'],
            link_rule=link['link_rule'],
            seq_gap=link['seq_gap'],
        )
        if failures_only and ok != 'fail':
            continue
        out.append(ev)
    # 2) Procedures (reconstructed by procedures.reconstruct) → bars with duration.
    for p in procedures:
        lane = PROCEDURE_LANE.get(p['type'])
        if not lane or lane not in allowed:
            continue
        if failures_only and p['outcome'] != 'fail':
            continue
        # Pivot/linked already materialized as boundary_seqs by reconstruct.
        boundaries = p['boundary_seqs']
        pivot = boundaries[0] if boundaries else None
        gap = max((abs(s - (pivot or 0)) for s in boundaries), default=None)
        out.append(dict(
            id=f"proc:{p['id']}",
            lane=lane,
            type=p['type'],
            kind='bar',
            seq=p['seq_start'],
            seq_end=p['seq_end'],
            t_rel_s=_times_for_seq(rows_by_seq, p['seq_start']),
            t_rel_end_s=_times_for_seq(rows_by_seq, p['seq_end']) if p['seq_end'] else None,
            duration_ms=p['duration_ms'],
            outcome=p['outcome'],
            cause=p['cause'],
            label=p['type'],
            attrs={'technology': p['technology']},
            pivot_seq=pivot,
            linked_seqs=boundaries,
            link_rule='procedure_boundary',
            seq_gap=gap,
        ))
    out.sort(key=lambda e: (e['seq'], e['type']))
    return out, meta


def events(db, pid, cap, lanes=None, failures_only=False):
    rows, procedures, meta, times = population(db, pid, cap, persist=False)
    return project_legacy_events(
        db, pid, cap, rows, procedures, meta, times,
        lanes=lanes, failures_only=failures_only,
    )


def _times_for_seq(rows_by_seq, seq):
    if seq is None:
        return None
    row = rows_by_seq.get(seq)
    return row['t_rel_s'] if row else None
