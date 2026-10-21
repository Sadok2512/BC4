"""TEST-only inputs exercise privacy, distinct clocks and unequal cell weights."""
from app.nmf_decoder.decoder import decode
from app.nmf_decoder.light import Light
from app.nmf_decoder.cells import cell_rows
from app.nmf_decoder.pairs import Pairs


def record(line,seq=1,t=0):
    r=decode(line,capture_id='TEST-capture',seq=seq,format_version='2.19');r.t_rel_s=t;return r


def test_context_is_not_a_system_and_hoi_has_no_system():
    a=record('HOA,00:00:00.000,1,30,1,903,7,3,3175,90,70007,7,3,227,90,70001')
    assert (a.context_id,a.context_ids,a.system)==(30,[30],7)
    assert a.values['hoa_att_ch']==227 and a.values['hoa_hoa_type']==903
    h=record('HOI,00:00:00.100,1,30,3,53,43,53')
    assert h.system is None and h.context_id==30 and h.values['hoi_ho_duration']==53
    assert 'system_missing' in h.reasons


def test_private_fields_are_never_numeric_or_unknown_values():
    r=record('CAA,00:00:00.000,1,30,7,14,1,"TEST-phone","TEST-own",60000')
    assert r.system==7 and r.context_id==30
    assert not any('TEST-phone' in t or 'TEST-own' in t for t in r.tokens)
    assert r.tokens[7:9]==['','']
    s=record('SEI,00:00:00.000,,7,1,123,208,1,"TEST-TMSI","TEST-PTMSI",2,3,"TEST-MTMSI"')
    assert [s.tokens[i] for i in (5,8,9,12)]==['']*4
    assert (s.values['sei_mcc'],s.values['sei_mnc'])==(208,1)
    from app.nmf_decoder.privacy import redact_raw
    assert redact_raw('CAA',{'c2':'1','c7':'TEST-phone','c8':'TEST-own'})['c7'] is None


def test_distinct_ho_durations_and_contexts():
    p=Pairs()
    p.add(record('HOA,00:00:00.000,1,30,1,903,7,3,3175,90,70007,7,3,227,90,70001',1,0))
    p.add(record('HOS,00:00:00.035,1,30',2,.035))
    p.add(record('HOI,00:00:00.035,1,31,3,90,0,0',3,.035))
    p.add(record('HOI,00:00:00.035,1,30,3,53,43,53',4,.035))
    row=p.rows()[0]
    assert row['ho_duration_nemo_ms']==35 and row['ho_duration_hoi_ms']==53
    assert row['seq_hoi']==4 and row['outcome']=='ok'


def test_rate_sum_and_bler_weighted_by_blocks_not_mean_of_means():
    l=Light()
    for seq,cell,rate,blocks,bler in [(1,0,100,10,10),(2,2,300,30,30)]:
        l.add(record(f'PHRATE,00:00:00.000,,7,2,{rate},0,{blocks},{bler},0,{rate},0,{cell},0,0,0',seq))
    rows={(r['metric_code'],r['cell_index']):r for r in cell_rows(l)}
    assert rows['pdsch_bitrate',-1]['value']==400
    assert rows['pdsch_bler',-1]['value']==25
    assert rows['n_scell_active',-1]['value']==1
    assert rows['scell_throughput_share',-1]['value']==.75


def test_unknown_event_never_guesses_system():
    r=record('TESTUNKNOWN,00:00:00.000,,7,162119527')
    assert r.system is None and 'system_missing' in r.reasons
    assert r.tokens[4]=='162119527'


def test_volte_cause_is_conditional_and_privacy_unknown_layout_fails_closed():
    r=record('CAD,00:00:01.000,1,30,7,14,1,200')
    assert r.values['cad_volte_cause']==200
    r=record('CAD,00:00:01.000,1,30,7,1,1,200')
    assert 'cad_volte_cause' not in r.values
    r=record('CAA,00:00:01.000,2,123,456,7,14,1,"TEST-phone","TEST-own"')
    assert r.system is None and r.context_id is None and r.context_ids==[]
    assert not any(r.tokens[3:])


def test_drate_keeps_independent_context_dimensions():
    light=Light()
    light.add(record('DRATE,00:00:00.000,1,1,4,0,100,0,100',1))
    light.add(record('DRATE,00:00:00.000,1,2,4,0,900,0,900',2))
    rows=list(light.rows())
    assert len(rows)==2 and {r['context_id'] for r in rows}=={1,2}


def test_undecoded_nr_does_not_create_zero_neighbors_or_collide_with_lte():
    light=Light()
    light.add(record('CELLMEAS,00:00:00.000,,7,0,1,9,0,70007,2825,1,-44,-71,-8,100,50',1))
    light.add(record('CELLMEAS,00:00:00.000,,9,0,0,9',2))
    rows=list(cell_rows(light))
    assert len({(r['second'],r['event_code'],r['metric_code'],r['cell_index']) for r in rows})==len(rows)
    assert all(r['seq_first']==1 for r in rows)
    only_nr=Light();only_nr.add(record('CELLMEAS,00:00:00.000,,9,0,0,9'))
    assert list(cell_rows(only_nr))==[]
