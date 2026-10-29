from hashlib import sha256
import json

from app.routes.signaling import window_events


def event(seq,start,end=None,event_id=None):
    return {'id':event_id or f'e{seq}','seq':seq,'t_rel_s':start,'t_rel_end_s':end}


def fingerprint(rows):
    return sha256(json.dumps([(r['id'],r['seq'],r['t_rel_s'],r['t_rel_end_s'])
      for r in rows],separators=(',',':')).encode()).hexdigest()


def test_visible_window_is_capture_seq_ordered_lossless_and_explicitly_limited():
    source=[event(30,30),event(10,0,20),event(20,12),event(40,40)]
    rows,total,truncated,next_seq,complete=window_events(source,10,35,None,2)
    assert [r['seq'] for r in complete]==[10,20,30]
    assert [r['seq'] for r in rows]==[10,20]
    assert total==3 and truncated is True and next_seq==20
    tail,tail_total,tail_truncated,_,_=window_events(source,10,35,next_seq,2)
    assert [r['seq'] for r in tail]==[30]
    assert tail_total==1 and tail_truncated is False
    assert fingerprint(rows+tail)==fingerprint(complete)
