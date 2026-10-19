"""Measured TEST2 fixtures + explicit TEST-only malformed inputs; no reference inserts."""
import csv,io,json
from pathlib import Path
import pytest
from app.nmf_decoder.decoder import decode,hashed
from app.nmf_decoder.light import Light

W=json.loads((Path(__file__).parent/'fixtures/nmf_decoder_witnesses.json').read_text())
def line(tokens):
    s=io.StringIO();csv.writer(s).writerow(tokens);return s.getvalue()

def test_eight_source_witnesses():
    result={r.event_code:r for r in (decode(line(x['fields']),format_version='2.62',capture_id=W['capture_id'],seq=x['seq']) for x in W['source_lines'])}
    for e,c,v in [('PHRATE','pdsch_bler',.5),('MACRATE','mac_dl_bler',2.7),('CI','ci_rs_snr',34.6),('TXPC','txpc_pusch_tx_power',-11.1),('CQI','cqi_wb_cqi_0',15),('PLAID','plaid_n_prb_indexes',75)]:assert result[e].values[c]==v
    assert result['CELLMEAS'].groups[0]['values']['cell_rsrp']==-71
    mimo=result['MIMOMEAS'].groups[0]['values'];assert (mimo['mimo_rsrp_p'],mimo['mimo_port'])==(-80.4,0)
    assert [g['values']['plaid_prb_index'] for g in result['PLAID'].groups if g['group_name']=='prb_indexes']==list(range(75))
    assert all(r.decode_status=='partial' for r in result.values())

def test_content_privacy_preserves_long_numeric_and_hashes_quoted_numeric():
    r=decode('CHI,00:00:00.000,,7,162119527,"162119527","TEST-private,quoted"',format_version='2.59')
    assert r.tokens[4]=='162119527' and not r.unk_string[4]
    assert r.tokens[5]==hashed('162119527') and r.unk_string[5]
    assert r.tokens[6]==hashed('TEST-private,quoted') and r.unk_string[6]
    assert all('TEST-private' not in x for x in r.tokens)

@pytest.mark.parametrize('event',['#EI','#SI','#DN'])
def test_identity_headers_never_retained(event):
    r=decode(event+',,,"TEST-identity"',format_version='2.19')
    assert r.excluded and not r.tokens

def test_no_system_heuristic_and_range_rejection():
    r=decode('TAD,00:00:00.000,7,,7',system=7,format_version='2.19')
    assert r.system is None and 'system_missing' in r.reasons and not r.values
    r=decode('TAD,00:00:00.000,,7,1283',format_version='2.19')
    assert r.decode_status=='partial' and r.values['tad_ta'] is None and r.tokens[4]=='1283'

def test_truncated_group_and_csv_are_counted():
    r=decode('CELLMEAS,00:00:00.000,,7,0,2,11,0',format_version='2.19')
    assert r.decode_status=='partial' and 'group_truncated:cells' in r.reasons
    r=decode('CHI,00:00:00.000,,7,"TEST-unclosed',format_version='2.19')
    assert r.decode_status=='partial' and r.reasons==['csv_malformed']

def test_light_weighted_distribution_and_missing_time_not_lost():
    a=decode('TAD,00:00:00.000,,7,2',format_version='2.19',seq=1);a.t_rel_s=0
    b=decode('TAD,00:00:00.500,,7,4',format_version='2.19',seq=2);b.t_rel_s=.5
    c=decode('TAD,,,7,5',format_version='2.19',seq=3)
    light=Light()
    for r in (a,b,c):light.add(r)
    rows=list(light.rows());assert sum(r['n_records'] for r in rows)==3
    assert next(r for r in rows if r['second']==0)['values']['tad_ta']==3

def test_application_type_is_not_inferred_from_an_unknown_extension():
    r=decode('AQDL,00:00:00.000,,9,4.2',format_version='2.62')
    assert not r.values and 'parameter_type_undocumented' in r.reasons

def test_light_replay_normalizes_null_group_dimensions():
    import copy
    r=decode('CELLMEAS,00:00:00.000,,7,0,1,9,0,70007,2825,,-44,-71,-8,100,50',format_version='2.19',seq=1)
    r.t_rel_s=0;stored=copy.deepcopy(r)
    stored.values={k:v for k,v in stored.values.items() if v is not None}
    for g in stored.groups:g['values']={k:v for k,v in g['values'].items() if v is not None}
    one=Light();two=Light();one.add(r);two.add(stored)
    assert list(one.rows())==list(two.rows())
