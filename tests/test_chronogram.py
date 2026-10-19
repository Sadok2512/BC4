import pytest
from fastapi import HTTPException
from app.routes.metrics import sample, clock

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
class DB:
    def __init__(self,rows):self.rows=rows
    def execute(self,sql,params):
        assert params=={'pid':'TEST-project','cap':'TEST-capture'}
        return Rows(self.rows)

def test_capture_clock_does_not_smooth_or_sort_timestamps():
    db=DB([{'seq':1,'ts':'10:00:00.000'},{'seq':2,'ts':'10:00:00.000'},{'seq':3,'ts':'10:00:00.123'}])
    assert clock(db,'TEST-project','TEST-capture')==({1:0,2:0,3:.123},1,'10:00:00.000')
    db.rows.append({'seq':4,'ts':'09:59:59.999'})
    with pytest.raises(HTTPException) as exc:clock(db,'TEST-project','TEST-capture')
    assert exc.value.detail['reason']=='capture_timestamp_regression'
