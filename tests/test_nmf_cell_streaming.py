import pytest

from app.nmf_decoder import store


class FakeCopy:
    def __init__(self, fail_at=None):
        self.rows = []
        self.fail_at = fail_at

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def write_row(self, row):
        if self.fail_at is not None and len(self.rows) == self.fail_at:
            raise RuntimeError("duplicate key")
        self.rows.append(row)


class FakeCursor:
    def __init__(self, copy):
        self._copy = copy

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def copy(self, _statement):
        return self._copy


class FakeConnection:
    def __init__(self, copy):
        self.connection = type("SAConnection", (), {
            "dbapi_connection": type("Dbapi", (), {
                "cursor": lambda _self: FakeCursor(copy),
            })(),
        })()


class FakeSession:
    def __init__(self, fail_at=None):
        self.copy = FakeCopy(fail_at)
        self.commits = 0
        self.rollbacks = 0
        self.statements = []

    def execute(self, statement, params):
        self.statements.append((str(statement), params))

    def connection(self):
        return FakeConnection(self.copy)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def cells(count):
    for index in range(count):
        yield {
            "second": index,
            "event_code": "CELLMEAS",
            "metric_code": "cell_rsrp",
            "cell_index": index,
            "seq_first": index,
            "seq_last": index,
            "value": -90.0,
            "weight": 1.0,
            "reason": None,
        }


def test_cell_projection_consumes_generator_once_and_commits_once():
    db = FakeSession()
    source = cells(10_001)
    assert iter(source) is source
    store.replace_cell_rows(db, "project", "capture", source)
    assert len(db.copy.rows) == 10_001
    assert db.commits == 1
    assert db.rollbacks == 0


def test_cell_projection_rolls_back_atomic_replacement_on_copy_failure():
    db = FakeSession(fail_at=3)
    with pytest.raises(RuntimeError, match="duplicate key"):
        store.replace_cell_rows(db, "project", "capture", cells(10))
    assert db.commits == 0
    assert db.rollbacks == 1
