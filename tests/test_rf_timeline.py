"""Synthetic TEST-only evidence checks; not reference data."""
from app.signaling.rf import enrich_legacy_connected_events, project_events


def row(seq, code, **kw):
    return dict(seq=seq,event_code=code,system=7,context_id=1,**kw)


def pair(kind,start,end,**kw):
    return dict(type=kind,context_id=1,seq_start=start,seq_end=end,outcome='ok',cause=None,
                ho_duration_nemo_ms=None,ho_duration_hoi_ms=None,**kw)


def test_connected_starts_at_indication_not_attempt_and_never_extends_open_end():
    d=[row(1,'RRA'),row(2,'RRC'),row(3,'RRD')]
    out=project_events([],d,[pair('rrc_connection',1,3)],[],{1:0,2:0.012,3:1.5},capture_id='TEST-capture')
    assert len(out) == 2
    ue=next(e for e in out if e['attrs']['track']=='UE_STATE')
    rrc=next(e for e in out if e['attrs']['track']=='RRC_STATE')
    assert ue['seq']==2 and ue['t_rel_s']==0.012 and ue['seq_end']==3
    assert ue['duration_ms']==1488
    assert ue['context_id']==1
    assert ue['session_id']=='context:TEST-capture:1'
    assert ue['attrs']['time_evidence_status']=='PROVEN'
    assert ue['attrs']['capture_id']=='TEST-capture' and ue['attrs']['state']=='LTE'
    assert rrc['attrs']['capture_id']=='TEST-capture' and rrc['attrs']['state']=='CONNECTED'
    open_events=project_events([],d[:2],[pair('rrc_connection',1,None)],[],{1:0,2:0.012})
    assert all(e['seq_end'] is None and e['duration_ms'] is None and e['kind']=='mark'
               for e in open_events)


def test_equal_source_timestamps_are_not_rendered_as_a_fabricated_period():
    d=[row(1,'RRA'),row(2,'RRC'),row(3,'RRD')]
    event=next(e for e in project_events([],d,[pair('rrc_connection',1,3)],[],
               {1:0.001,2:0.001,3:0.001},capture_id='TEST-capture')
               if e['attrs']['track']=='UE_STATE')
    assert event['seq_end']==3 and event['t_rel_end_s']==0.001
    assert event['kind']=='mark'
    assert event['attrs']['time_evidence_status']=='RESOLUTION_LIMITED'


def test_overlapping_contexts_cannot_supply_connection_indication():
    d=[row(1,'RRA'),{**row(2,'RRC'),'context_id':2},row(3,'RRD')]
    assert project_events([],d,[pair('rrc_connection',1,3)],[],{1:0,2:1,3:2})==[]


def test_unknown_call_type_is_not_volte_and_nr_is_not_sa():
    d=[row(1,'CAA'),row(2,'CAC'),row(3,'CAD',cad_call_type=None)]
    assert project_events([],d,[pair('call',1,3)],[],{1:0,2:1,3:2})==[]
    d[-1]['cad_call_type']=14
    assert project_events([],d,[pair('call',1,3)],[],{1:0,2:1,3:2})[0]['attrs']['track']=='volte'
    d=[{**row(s,c),'system':9} for s,c in [(1,'RRA'),(2,'RRC'),(3,'RRD')]]
    assert project_events([],d,[pair('rrc_connection',1,3)],[],{1:0,2:1,3:2})==[]


def test_absent_time_remains_null_and_partial_task_is_not_success():
    task=dict(id='TEST-task',task_type='HTTP_DL',tech='LTE',seq_daa=10,seq_dcomp=20,status='partial',reason='TEST-gap')
    e=project_events([],[],[],[task],{20:2})[0]
    assert e['t_rel_s'] is None and e['t_rel_end_s'] is None
    assert e['outcome'] is None and e['attrs']['status']=='UNKNOWN'
    assert e['attrs']['source_seqs']==[10,20]


def test_ho_success_requires_hos_and_source_order_is_seq():
    d=[row(1,'HOA'),row(3,'HOS')]
    e=project_events([],d,[pair('ho',1,3)],[],{1:0,3:0.1})[0]
    assert e['attrs']['status']=='SUCCESS'
    d[-1]['event_code']='RRD'
    assert project_events([],d,[pair('ho',1,3)],[],{1:0,3:0.1})[0]['attrs']['status']=='UNKNOWN'


def test_proven_context_evidence_enriches_matching_legacy_connection_only():
    evidence = project_events(
        [], [{**row(234, 'RRA'), 'context_id': 54},
             {**row(243, 'RRC'), 'context_id': 54},
             {**row(1608, 'RRD'), 'context_id': 54}],
        [{**pair('rrc_connection', 234, 1608), 'context_id': 54}], [],
        {234: 1.4, 243: 1.4, 1608: 24.182}, capture_id='TEST-capture',
    )
    legacy = [{
        'id': 'proc:TEST-procedure', 'type': 'rrc_connection', 'kind': 'bar',
        'linked_seqs': [234, 243, 1608], 'attrs': {'technology': None},
        'context_id': None, 'session_id': None, 'link_rule': 'procedure_boundary',
    }, {
        'id': 'proc:TEST-unmatched', 'type': 'rrc_connection', 'kind': 'bar',
        'linked_seqs': [1, 2, 3], 'attrs': {'technology': None},
        'context_id': None, 'session_id': None, 'link_rule': 'procedure_boundary',
    }]

    enriched = enrich_legacy_connected_events(legacy, evidence, 'TEST-capture')

    assert enriched[0]['context_id'] == 54
    assert enriched[0]['session_id'] == 'context:TEST-capture:54'
    assert enriched[0]['kind'] == 'band'
    assert enriched[0]['link_rule'] == 'nemo_context_connected'
    assert enriched[0]['attrs'] == {
        'technology': 'LTE', 'capture_id': 'TEST-capture', 'track': 'UE_STATE',
        'rule_id': 'nemo_context_connected', 'rule_version': '1.0.0',
        'evidence_status': 'PROVEN', 'source_seqs': [234, 243, 1608],
        'time_evidence_status': 'PROVEN',
    }
    assert enriched[1]['context_id'] is None
    assert enriched[1]['session_id'] is None
