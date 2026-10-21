"""TEST-only inputs exercise privacy, distinct clocks and unequal cell weights."""
from app.nmf_decoder.decoder import decode
from app.nmf_decoder.light import Light, dimensions
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


def test_legacy_null_context_ids_replay_as_empty_dimension():
    decoded=record('DRATE,00:00:00.000,1,1,4,0,100,0,100',1)
    decoded.context_ids=None
    assert dimensions(decoded)=='context_ids='


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
    serving={(r['metric_code'],r['cell_index']):r['value'] for r in rows}
    assert serving['cell_rsrp',0]==-71
    assert serving['cell_rsrq',0]==-8
    assert len({(r['second'],r['event_code'],r['metric_code'],r['cell_index']) for r in rows})==len(rows)
    assert all(r['seq_first']==1 for r in rows)
    only_nr=Light();only_nr.add(record('CELLMEAS,00:00:00.000,,9,0,0,9'))
    assert list(cell_rows(only_nr))==[]


def test_txpc_content_proven_cell_discriminator_depends_on_format():
    light=Light()
    rows=[
        ('TXPC,00:00:00.000,,7,3.6,-16.0,20.4,,,0,2,0,2,,,0', '2.59', 1),
        ('TXPC,00:00:00.000,,7,4.0,,,,,0,2,0,2,,,1,', '2.62', 2),
    ]
    for line,version,seq in rows:
        decoded=decode(line,capture_id='TEST-capture',seq=seq,format_version=version)
        decoded.t_rel_s=0
        light.add(decoded)
    projected={(row['metric_code'],row['cell_index']):row for row in cell_rows(light)}
    assert projected['txpc_pucch_tx_power',0]['value']==-16
    assert projected['txpc_pusch_tx_power',1]['value']==4
    assert all(cell in {-1,0,1} for _,cell in projected)


def test_crel_variable_header_has_declared_system_and_preserves_long_cell_ids():
    r=record('CREL,00:00:00.000,,1,,7,3,49603,162119527,70007,7,3,49603,162119524,70007')
    assert r.system==7 and r.values['crel_old_cell_id']==162119527
    assert r.values['crel_cell_id']==162119524 and 'crel_crs_reason' not in r.values
    r=record('CREL,00:00:00.000,,2,20,1,7,3,49603,162119527,70007,7,3,49603,162119524,70007')
    assert r.system==7 and r.values['crel_crs_time']==20 and r.values['crel_crs_reason']==1
    r=record('CREL,00:00:00.000,,1,,5,3,49603,162119527,70007,7,3,49603,162119524,70007')
    assert r.system is None and not r.values  # An unproved mixed-system layout is not LTE.


def test_lock_variable_groups_and_light_last_snapshot():
    r=record('LOCK,00:00:00.000,,3,3,2,7,106,4,2,70007,106,10,3,423,2850,70007')
    assert r.system is None and len(r.groups)==3
    assert r.groups[0]['values']['lock_system']==7
    assert r.groups[1]['values']['lock_band']==70007
    assert r.groups[2]['values']['lock_pci']==423
    assert r.tokens[7]=='106' and r.field_codes[7].startswith('unk_')
    light=Light();light.add(r)
    light.add(record('LOCK,00:00:00.100,,0',2,.1))
    rows=list(light.rows());assert len(rows)==1 and rows[0]['groups']==[]
    assert rows[0]['values']['lock_forcings']==0 and 'lock_system' not in rows[0]['values']
