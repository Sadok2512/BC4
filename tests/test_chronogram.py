import pytest
from fastapi import HTTPException
from app.routes.metrics import sample, clock
from app.signaling.capture_cache import clear_capture

def points(values):return [dict(seq=i*3,t_rel_s=i/10,value=v) for i,v in enumerate(values)]

def test_minmax_preserves_spikes_deterministic_bounded():
    raw=points([0,1,90,-50,2,3,4,99,-99,2,1,0])
    out,meta=sample(raw,4,'numeric')
    assert [p['value'] for p in out]==[90,-50,99,-99]
    assert len(out)<=4 and out==sorted(out,key=lambda r:r['seq'])
    assert sample(raw,4,'numeric')==(out,meta)
    assert meta['factor']==3

def test_categories_preserve_actual_changes_and_fail_if_too_many():
    raw=points(['a','a','b','b','a'])
    out,_=sample(raw,3,'categorical')
    assert [p['seq'] for p in out]==[0,6,12]
    with pytest.raises(HTTPException) as exc:sample(raw,2,'categorical')
    assert exc.value.status_code==422

class Rows:
    def __init__(self,rows):self.rows=rows
    def mappings(self):return self
    def all(self):return self.rows
    def one_or_none(self):return self.rows[0] if self.rows else None
class DB:
    def __init__(self,rows):self.rows=rows;self.decoded_at=None
    def execute(self,sql,params):
        assert params=={'pid':'TEST-project','cap':'TEST-capture'}
        if 'FROM nmf_capture c' in str(sql):
            return Rows([{'decoder_version':'TEST-1.0.0','decoded_at':self.decoded_at,
              'event_count':len(self.rows),'raw_count':len(self.rows),
              'max_seq':max((r['seq'] for r in self.rows),default=-1)}])
        return Rows(self.rows)

def test_capture_clock_does_not_smooth_or_sort_timestamps():
    clear_capture('TEST-project','TEST-capture')
    db=DB([{'seq':1,'ts':'10:00:00.000'},{'seq':2,'ts':'10:00:00.000'},{'seq':3,'ts':'10:00:00.123'}])
    assert clock(db,'TEST-project','TEST-capture')==({1:0,2:0,3:.123},1,'10:00:00.000')
    db.rows.append({'seq':4,'ts':'09:59:59.999'})
    with pytest.raises(HTTPException) as exc:clock(db,'TEST-project','TEST-capture')
    assert exc.value.detail['reason']=='capture_timestamp_regression'

def test_same_decoder_version_reparse_stamp_invalidates_clock():
    clear_capture('TEST-project','TEST-capture')
    db=DB([{'seq':1,'ts':'10:00:00.000'},{'seq':2,'ts':'10:00:00.123'}])
    assert clock(db,'TEST-project','TEST-capture')[0][2]==.123
    db.rows[1]['ts']='10:00:00.456'
    db.decoded_at='TEST-reparse-at'
    assert clock(db,'TEST-project','TEST-capture')[0][2]==.456
