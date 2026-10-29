from app.routes import project_dict_v2 as route
from types import SimpleNamespace


class Result:
    def __init__(self, row): self.row=row
    def one(self): return self.row


class DB:
    def __init__(self): self.stamp=(10, 20, 30)
    def execute(self, sql, params):
        assert params == {'pid':'TEST-project'}
        return Result(self.stamp)


def test_catalog_tree_cache_is_project_version_scoped_and_content_invalidated(monkeypatch):
    db=DB(); calls=[]
    monkeypatch.setattr(route, 'current_catalog', lambda *_: SimpleNamespace(version='2.56.2'))
    monkeypatch.setattr(route, 'build_dict_tree', lambda *_: calls.append(1) or {'tree':len(calls)})
    route._TREE_CACHE.clear()
    assert route._catalog_tree(db,'TEST-project') == {'tree':1}
    assert route._catalog_tree(db,'TEST-project') == {'tree':1}
    assert len(calls)==1
    db.stamp=(11, 21, 31)
    assert route._catalog_tree(db,'TEST-project') == {'tree':2}
    assert len(calls)==2


def test_cache_returns_a_copy(monkeypatch):
    db=DB()
    monkeypatch.setattr(route, 'current_catalog', lambda *_: SimpleNamespace(version='2.56.2'))
    monkeypatch.setattr(route, 'build_dict_tree', lambda *_: {'tree':[]})
    route._TREE_CACHE.clear()
    first=route._catalog_tree(db,'TEST-project');first['tree'].append('mutated')
    assert route._catalog_tree(db,'TEST-project') == {'tree':[]}


def test_catalog_release_version_separates_cache_entries(monkeypatch):
    db=DB(); version=['2.56.2']; calls=[]
    monkeypatch.setattr(route, 'current_catalog', lambda *_: SimpleNamespace(version=version[0]))
    monkeypatch.setattr(route, 'build_dict_tree', lambda *_: calls.append(version[0]) or {'version':version[0]})
    route._TREE_CACHE.clear()
    assert route._catalog_tree(db,'TEST-project') == {'version':'2.56.2'}
    version[0]='2.56.3'
    assert route._catalog_tree(db,'TEST-project') == {'version':'2.56.3'}
    assert calls == ['2.56.2','2.56.3']
