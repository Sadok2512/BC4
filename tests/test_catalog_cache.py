from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from app.kpi.catalog_cache import CatalogCache


def test_expiry_isolation_eviction_and_immutable_results():
    now=[0];c=CatalogCache(ttl=30,capacity=2,clock=lambda:now[0]);calls=[]
    def load():
        calls.append(1);return {'status':['PENDING']}
    k=('TEST-project',())
    c.get(k,load)['status'][0]='AVAILABLE'
    assert c.get(k,load)=={'status':['PENDING']}
    assert len(calls)==1
    c.get(('TEST-other',()),load)
    c.get(('TEST-project',('HTTP',)),load)
    assert len(c.ready)==2
    c.get(k,load);assert len(calls)==4
    now[0]=31;c.get(k,load);assert len(calls)==5


def test_failure_is_retried():
    c=CatalogCache()
    with pytest.raises(ValueError):c.get('test',lambda: (_ for _ in ()).throw(ValueError('fail')))
    assert c.get('test',lambda: 'ok')=='ok'


def test_concurrent_requests_share_one_load():
    c=CatalogCache();entered=Event();release=Event();calls=[]
    def load():
        calls.append(1);entered.set();assert release.wait(5);return {'status':'PENDING'}
    with ThreadPoolExecutor(4) as pool:
        first=pool.submit(c.get,'test',load);assert entered.wait(5)
        others=[pool.submit(c.get,'test',load) for _ in range(3)]
        release.set()
        assert all(f.result()=={'status':'PENDING'} for f in [first,*others])
    assert len(calls)==1
