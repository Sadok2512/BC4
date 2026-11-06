from app.routes import metrics


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self._rows)

    def all(self):
        return list(self._rows)


class _Db:
    def __init__(self):
        self.sql = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.sql.append((sql, dict(params or {})))
        if sql == metrics.EVENT_SQL:
            return _Rows([
                {"seq": 10, "message": "RRCConnectionSetup", "mobility": False},
                {"seq": 20, "message": "RRCConnectionRelease", "mobility": False},
            ])
        if "WITH context_sequences AS" in sql:
            return _Rows([(20,)])
        if sql == metrics.LOCK_SQL:
            return _Rows([])
        raise AssertionError(f"unexpected SQL: {sql}")


def test_events_filters_only_candidate_sequences(monkeypatch):
    db = _Db()
    monkeypatch.setattr(metrics, "project", lambda *_: None)
    monkeypatch.setattr(metrics, "validate_operators", lambda *_: None)
    monkeypatch.setattr(
        metrics,
        "clock_subset",
        lambda _db, _pid, _cap, seqs: ({seq: float(seq) for seq in seqs}, 1, "00:00:00"),
    )
    monkeypatch.setattr(metrics, "evidence", lambda *_args, **_kwargs: "proof")

    response = metrics.events(
        "project",
        "capture",
        types="rrc",
        f={"rat": ["LTE", "NR"]},
        db=db,
    )

    assert [marker["seq"] for marker in response["markers"]] == [20]
    filter_sql, filter_params = next(
        (sql, params) for sql, params in db.sql if "WITH context_sequences AS" in sql
    )
    assert "context_sql" not in filter_sql
    assert "measurement_points" in filter_sql
    assert "context_sequences" in filter_sql
    assert filter_params["context_seqs"] == [10, 20]


def test_compact_catalog_omits_only_null_node_metadata():
    payload = {
        "metrics": [{"reason": None}],
        "nodes": [{"node_id": "leaf", "reason": None, "n": 0, "label": "RSRP"}],
    }

    compact = metrics._compact_catalog_response(payload)

    assert compact["nodes"] == [{"node_id": "leaf", "n": 0, "label": "RSRP"}]
    assert compact["metrics"] == [{"reason": None}]
