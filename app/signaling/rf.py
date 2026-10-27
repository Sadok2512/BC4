"""RF timeline v1: evidence projection, not another Nemo/ASN.1 decoder.

Order and joins are capture + sequence. All times come from metrics.clock.
Unclosed intervals stay markers. Proximity links never establish outcomes.
Only allowlisted typed columns are selected; identity/raw tokens are not read.
"""
from decimal import Decimal
from . import service as svc

RULE_VERSION = '1.0.0'
UNAVAILABLE = {
    'nsa': 'SCG configuration and completion association unavailable; SCELLMOD is not proof of NSA activity.',
    'sa': 'NR RRC alone does not distinguish standalone access from EN-DC.',
    'vonr': 'No documented VoNR call discriminator in the activated schemas.',
    'nr_radio': 'NR SSB occurrences lack verified physical-unit conversions and serving-MO attribution.',
    'ho_failure': 'No proven causal association between handover attempts and radio failures.',
}
# 0.88.0 BC3 — Fallback nmf_event_light pour captures decode_level='light'.
# Avant 0.88.0 : rf.events ne lisait que nmf_event_deep. Pour les 66/85
# captures live en decode_level='light' (78%), `deep` était vide → aucun
# RRC_STATE / UE_STATE émis → UI « Unknown » partout.
# Fix : UNION ALL deep PRIORITY puis light (uniquement pour les seq NON
# présents dans deep). Les champs HOA/CAD/RRD spécifiques (hoa_ch_number,
# cad_call_type, …) restent NULL en light → les events dépendants (HOA
# full dump, CAD VoLTE discriminator) restent "UNKNOWN" explicite (jamais
# inventé). Ordre (capture_id, seq) préservé par ORDER BY seq.
DEEP_SQL = '''
WITH deep AS (
  SELECT seq, event_code, system, context_id, decode_status, reasons,
    hoa_ch_number, hoa_pci, hoa_band, hoa_att_ch, hoa_att_pci, hoa_att_band,
    cad_call_type, cad_cs_disc_status, cad_volte_cause,
    rrd_rrc_rel_status, rrd_rrc_rel_cause
  FROM nmf_event_deep
  WHERE project_id=:pid AND capture_id=:cap AND event_code=ANY(:markers)
),
light_fallback AS (
  SELECT l.seq, l.event_code, l.system, l.context_id,
    'light_fallback'::text AS decode_status, NULL::text[] AS reasons,
    NULL::int AS hoa_ch_number, NULL::int AS hoa_pci, NULL::int AS hoa_band,
    NULL::int AS hoa_att_ch, NULL::int AS hoa_att_pci, NULL::int AS hoa_att_band,
    NULL::int AS cad_call_type, NULL::int AS cad_cs_disc_status,
    NULL::int AS cad_volte_cause,
    NULL::int AS rrd_rrc_rel_status, NULL::int AS rrd_rrc_rel_cause
  FROM nmf_event_light l
  WHERE l.project_id=:pid AND l.capture_id=:cap AND l.event_code=ANY(:markers)
    AND NOT EXISTS (SELECT 1 FROM deep d WHERE d.seq=l.seq)
)
SELECT * FROM deep
UNION ALL
SELECT * FROM light_fallback
ORDER BY seq'''
PAIR_SQL = '''SELECT type,context_id,seq_start,seq_end,seq_hoi,outcome,cause,
 ho_duration_nemo_ms,ho_duration_hoi_ms FROM nmf_event_pair
 WHERE project_id=:pid AND capture_id=:cap ORDER BY seq_start,type'''
TASK_SQL = '''SELECT id,task_type,tech,seq_daa,seq_dcomp,status,reason FROM task_run
 WHERE project_id=:pid AND capture_id=:cap AND task_type IN ('HTTP_DL','HTTP_UL') ORDER BY seq_start'''


def project_events(rows, deep, pairs, tasks, times, capture_id=None):
    """Pure, testable evidence projection. Inputs belong to exactly one capture."""
    decoded = {r['seq']: r for r in deep}
    out = []
    source_rows = {r["seq"]:r for r in rows}

    def emit(key, track, label, seq, end=None, refs=None, tech=None, status='UNKNOWN',
             source='stg_event', rule='raw_protocol', evidence='PROVEN', attrs=None, protocol=None,
             context_id=None):
        start_t, end_t = times.get(seq), times.get(end)
        if end is not None and (start_t is None or end_t is None or end_t < start_t):
            end = None; end_t = None; evidence = 'PARTIAL'
        duration = float((Decimal(str(end_t))-Decimal(str(start_t)))*1000) if end_t is not None else None
        time_evidence_status = ('UNAVAILABLE' if end_t is None else
                                'RESOLUTION_LIMITED' if end_t == start_t else 'PROVEN')
        session_id = (f'context:{capture_id}:{context_id}'
                      if capture_id is not None and context_id is not None
                      and rule == 'nemo_context_connected' and evidence == 'PROVEN' else None)
        out.append(dict(id=key, lane={'lte':'connexion','UE_STATE':'connexion','RRC_STATE':'connexion',
            'sa':'connexion','nsa':'endc','mobility':'mobilite',
            'dl':'services','ul':'services','volte':'services','vonr':'services'}.get(track,'radio'),
            type=label, kind='band' if end is not None and end_t != start_t else 'fail' if status=='FAILURE' else 'mark',
            seq=seq,seq_end=end,t_rel_s=start_t,t_rel_end_s=end_t,duration_ms=duration,
            outcome={'SUCCESS':'ok','FAILURE':'fail'}.get(status),cause=(attrs or {}).get('cause'),label=label,
            attrs=dict(track=track,technology=tech or 'UNKNOWN',status=status,source=source,
                source_seqs=refs or [seq],evidence_status=evidence,rule_id=rule,rule_version=RULE_VERSION,
                time_evidence_status=time_evidence_status,
                protocol=protocol,source_message=source_rows.get(seq,{}).get("message_name"),
                **({'capture_id': capture_id} if capture_id is not None else {}),
                **(attrs or {})),pivot_seq=seq,linked_seqs=refs or [seq],
            link_rule=rule,seq_gap=0,context_id=context_id,session_id=session_id))

    for r in rows:
        d = decoded.get(r['seq'], {})
        tech = r['technology'] if r['event_code'] in ('RRCSM','L3SM') else {7:'LTE',8:'LTE',9:'NR'}.get(d.get('system'))
        code = r['event_code']
        protocol = 'RRC '+tech if code=='RRCSM' else 'NAS' if code=='L3SM' else 'MAC-RACH' if code=='RACHI' else 'Nemo'
        track = 'mobility' if code in ('HOA','HOS','HOI','CREL') else 'network'
        # Raw names stay names. Reconfiguration alone is never HO success.
        attrs = {'direction': {'1':'UL','2':'DL'}.get(r.get('direction')), 'pci':r.get('pci')}
        if code=='HOA':
            attrs.update({k:d.get(k) for k in ('hoa_ch_number','hoa_pci','hoa_band','hoa_att_ch','hoa_att_pci','hoa_att_band')})
        if code=='RRD':attrs.update(cause=d.get('rrd_rrc_rel_cause'),release_status=d.get('rrd_rrc_rel_status'))
        # Keep cause a textual contract field; numeric codes stay typed in attrs.
        if attrs.get('cause') is not None:attrs['cause']='RRD cause '+str(attrs['cause'])
        emit(f"raw:{r['seq']}",track,r.get('message_name') or code,r['seq'],tech=tech,
             status='ATTEMPT' if code in ('HOA','RRA','CAA','DAA') else 'UNKNOWN',
             source=r['source'],attrs=attrs,protocol=protocol,context_id=d.get('context_id'))

    for p in pairs:
        start, end = decoded.get(p['seq_start']), decoded.get(p['seq_end'])
        if not start or p['context_id'] is None:continue
        tech = {7:'LTE',8:'LTE',9:'NR'}.get(start['system'])
        bounds = [p['seq_start']] + ([p['seq_end']] if p['seq_end'] is not None else [])
        if p['type']=='ho':
            emit(f"ho:{p['seq_start']}",'mobility','Handover',p['seq_start'],p['seq_end'],bounds,tech,
                 'SUCCESS' if p['outcome']=='ok' and end and end['event_code']=='HOS' else 'UNKNOWN',
                 source='nmf_event_pair',rule='nemo_context_ho',evidence='PROVEN' if end else 'PARTIAL',
                 attrs=dict(cause=p['cause'],ho_duration_nemo_ms=p['ho_duration_nemo_ms'],ho_duration_hoi_ms=p['ho_duration_hoi_ms']),protocol='Procedures',
                 context_id=p['context_id'])
        elif p['type'] in ('rrc_connection','call'):
            middle_code='RRC' if p['type']=='rrc_connection' else 'CAC'
            middles=[d for d in deep if d['event_code']==middle_code and d['context_id']==p['context_id']
                     and d['seq']>p['seq_start'] and (p['seq_end'] is None or d['seq']<p['seq_end'])]
            # Ambiguous indications do not prove a unique interval.
            if len(middles)!=1:continue
            middle=middles[0]
            track='lte' if p['type']=='rrc_connection' and tech=='LTE' else None
            # NFF 2.19 CAD call type 14 = VoLTE. LTE presence alone is insufficient.
            if p['type']=='call' and end and end.get('cad_call_type')==14:track='volte'
            if not track:continue
            refs=[p['seq_start'],middle['seq']] + ([p['seq_end']] if end else [])
            common = dict(
                end=p['seq_end'], refs=refs, tech=tech,
                status='FAILURE' if p['outcome']=='fail' else 'UNKNOWN',
                source='nmf_event_pair + nmf_event_deep', rule='nemo_context_connected',
                evidence='PROVEN' if end else 'PARTIAL', protocol='Procedures',
                context_id=p['context_id'],
            )
            if track == 'lte':
                # One proven connection interval feeds two independent UI tracks.
                # Both retain the exact same source tuple; no Idle interval is inferred.
                emit(f"connected:{p['seq_start']}",'UE_STATE','LTE Connected',middle['seq'],
                     attrs=dict(cause=p['cause'],state='LTE'),**common)
                emit(f"rrc-state:{p['seq_start']}",'RRC_STATE','RRC Connected',middle['seq'],
                     attrs=dict(cause=p['cause'],state='CONNECTED'),**common)
            else:
                emit(f"connected:{p['seq_start']}",track,'VoLTE Connected',middle['seq'],
                     attrs=dict(cause=p['cause']),**common)

    for task in tasks:
        if task['seq_daa'] is None:continue
        emit('task:'+task['id'],'dl' if task['task_type']=='HTTP_DL' else 'ul',task['task_type'],
             task['seq_daa'],task['seq_dcomp'],
             [s for s in (task['seq_daa'],task['seq_dcomp']) if s is not None],task['tech'],
             'SUCCESS' if task['status']=='ok' and task['seq_dcomp'] is not None else 'UNKNOWN',
             source='task_run',rule='task_daa_dcomp',evidence='PROVEN' if task['status']=='ok' else 'PARTIAL',
             attrs=dict(task_id=task['id'],cause=task['reason'],integrity_status=task['status']),protocol='Procedures')
    return sorted(out,key=lambda e:(e['seq'],e['id']))


def enrich_legacy_connected_events(legacy_events, evidence_events, capture_id):
    """Attach proven RF context evidence to matching legacy procedures.

    The legacy timeline remains the default API view.  Its reconstructed
    ``rrc_connection`` procedures and the RF evidence view describe the same
    procedure with different ids, so the exact ordered source sequence tuple
    is the stable join key.  Partial/open evidence is deliberately ignored.
    """
    proven = {}
    for evidence in evidence_events:
        attrs = evidence.get('attrs') or {}
        source_seqs = attrs.get('source_seqs') or []
        if (attrs.get('rule_id') == 'nemo_context_connected'
                and attrs.get('track') == 'UE_STATE'
                and attrs.get('evidence_status') == 'PROVEN'
                and evidence.get('context_id') is not None
                and evidence.get('session_id') is not None):
            proven[tuple(source_seqs)] = evidence

    for event in legacy_events:
        if event.get('type') != 'rrc_connection':
            continue
        evidence = proven.get(tuple(event.get('linked_seqs') or []))
        if evidence is None:
            continue
        proof_attrs = evidence['attrs']
        event['context_id'] = evidence['context_id']
        event['session_id'] = evidence['session_id']
        event['kind'] = evidence['kind']
        event['link_rule'] = proof_attrs['rule_id']
        event['attrs'] = {
            **(event.get('attrs') or {}),
            'capture_id': capture_id,
            'technology': proof_attrs['technology'],
            'track': 'UE_STATE',
            'rule_id': proof_attrs['rule_id'],
            'rule_version': proof_attrs['rule_version'],
            'evidence_status': proof_attrs['evidence_status'],
            'source_seqs': proof_attrs['source_seqs'],
            'time_evidence_status': proof_attrs['time_evidence_status'],
        }
    return legacy_events


def events(db,pid,cap,protocols=None,technology=None,direction=None,q=None):
    meta=svc.capture(db,pid,cap)
    times,_,_=svc.clock(db,pid,cap)
    params=dict(pid=pid,cap=cap,markers=list(svc.MARKERS))
    rows=svc.query(db,svc.SOURCE_SQL,params)
    deep=svc.query(db,DEEP_SQL,params)
    pairs=svc.query(db,PAIR_SQL,params)
    tasks=svc.query(db,TASK_SQL,params)
    out=project_events(rows,deep,pairs,tasks,times,capture_id=cap)
    if protocols is not None:
        selected=protocols.split(',')
        out=[e for e in out if e['attrs']['protocol'] in selected]
    if technology:out=[e for e in out if e['attrs']['technology']==technology]
    if direction:out=[e for e in out if e['attrs'].get('direction')==direction]
    if q:out=[e for e in out if q.casefold() in e['label'].casefold()]
    return out,meta
