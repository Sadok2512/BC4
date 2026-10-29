from types import SimpleNamespace

from app.dict import materialized


class _Result:
    def __init__(self, *, scalar=None, rows=None, one=None):
        self._scalar = scalar
        self._rows = rows or []
        self._one = one

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self._rows)

    def one(self):
        return self._one


class _BuildDb:
    def __init__(self):
        self.sql = []
        self.commits = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.sql.append((sql, params or {}))
        if sql.startswith("SELECT 1 FROM projects"):
            return _Result(scalar=1)
        if "source_occurrences" in sql and "FROM param_occurrence" in sql:
            return _Result(one={"source_occurrences": 60970,
                                "eligible_occurrences": 60000,
                                "total_occurrences": 171766,
                                "distinct_param_keys": 456,
                                "available_messages": ["A", "B"]})
        if sql.startswith("SELECT count(*)"):
            return _Result(scalar=321)
        return _Result()

    def commit(self):
        self.commits += 1


def test_materialization_builds_then_activates(monkeypatch):
    monkeypatch.setattr(materialized, "uuid4",
                        lambda: SimpleNamespace(hex="generation-1"))
    monkeypatch.setattr("app.dict.cell_ref_group.build_group_by_options",
                        lambda *_: [])
    db = _BuildDb()
    report = materialized.materialize_network_catalog(db, "project-1")
    statements = [sql for sql, _ in db.sql]
    build = next(i for i, sql in enumerate(statements)
                 if sql.startswith("INSERT INTO dict_network_catalog_entry"))
    activate = next(i for i, sql in enumerate(statements)
                    if sql.startswith("INSERT INTO dict_network_catalog_state"))
    assert build < activate
    assert "LEFT JOIN stg_event e" in statements[build]
    assert "e.project_id=p.project_id" in statements[build]
    assert "regexp_replace(p.path" in statements[build]
    assert report == {"project_id": "project-1", "generation": "generation-1",
                      "source_occurrences": 60970,
                      "eligible_occurrences": 60000, "summary_rows": 321,
                      "total_occurrences": 171766, "distinct_param_keys": 456,
                      "available_messages": ["A", "B"],
                      "catalog_rows": 321, "group_by_options": []}
    assert db.commits == 7


def test_reader_is_project_and_generation_scoped():
    class Db:
        def __init__(self): self.calls = []
        def execute(self, statement, params):
            sql = str(statement); self.calls.append((sql, params))
            if "FROM dict_network_catalog_state" in sql:
                return _Result(scalar="g-active")
            return _Result(rows=[])
    db = Db()
    assert materialized.network_catalog_rows(db, "p", "RRC") == []
    sql, params = db.calls[-1]
    assert "e.project_id=:pid" in sql
    assert "e.generation=:generation" in sql
    assert "e.message=:message" in sql
    assert params == {"pid": "p", "generation": "g-active", "message": "RRC"}
