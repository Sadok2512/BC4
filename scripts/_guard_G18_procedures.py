"""Manual deterministic state-machine guards. TEST-only sequences, no reference data."""
from app.signaling.procedures import reconstruct

def rows(names):
    return [dict(seq=i+1,t_rel_s=i/10,message_name=n,technology='LTE') for i,n in enumerate(names)]

def run():
    good=reconstruct('TEST-project','TEST-capture',rows(['RRCConnectionRequest','RRCConnectionSetup','RRCConnectionSetupComplete']))
    assert good[0]['duration_ms']==200 and good[0]['outcome']=='ok'
    missing=reconstruct('TEST-project','TEST-capture',rows(['RRCConnectionRequest','RRCConnectionSetupComplete']))
    assert missing[0]['outcome']=='incomplete' and missing[0]['duration_ms'] is None
    reject=reconstruct('TEST-project','TEST-capture',rows(['RRCConnectionRequest','RRCConnectionReject']))
    assert reject[0]['outcome']=='fail'
    repeated=reconstruct('TEST-project','TEST-capture',rows(['HOA','HOA','HOS']))
    assert [r['outcome'] for r in repeated]==['incomplete','incomplete']
    assert reconstruct('TEST-project','TEST-other',rows(['HOS']))==[]
    unknown=rows(['HOA','HOS']);unknown[1]['t_rel_s']=None
    assert reconstruct('TEST-project','TEST-capture',unknown)[0]['duration_ms'] is None
    assert reconstruct('TEST-project','TEST-capture',list(reversed(rows(['HOA','HOS']))))[0]['outcome']=='ok'
    # BC3 0.65.2: new rrc_connection procedure (RRA -> RRC -> RRD).
    rrc_conn=reconstruct('TEST-project','TEST-capture',rows(['RRA','RRC','RRD']))
    assert rrc_conn[0]['type']=='rrc_connection' and rrc_conn[0]['outcome']=='ok' and rrc_conn[0]['duration_ms']==200
    rrc_conn_mid=reconstruct('TEST-project','TEST-capture',rows(['RRA','RRD']))
    assert rrc_conn_mid[0]['type']=='rrc_connection' and rrc_conn_mid[0]['outcome']=='incomplete'
    print('PASS: complete / missing / rejection / repeated / capture isolation / missing time / canonical sequence / rrc_connection')
if __name__=='__main__':run()
