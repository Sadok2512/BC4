from app.scripts.backfill_signaling_materialized import main as backfill_main
from app.signaling import materialized as mat


def test_points_keep_strict_previous_gps_semantics():
    rows = [dict(seq=10, t_rel_s=1.0, protocol="RRC LTE", layer="rrc_lte",
                 technology="LTE", direction="DL", message_name="Paging",
                 procedure_ids=[]),
            dict(seq=11, t_rel_s=2.0, protocol="RRC LTE", layer="rrc_lte",
                 technology="LTE", direction="DL", message_name="Setup",
                 procedure_ids=[])]
    gps = [dict(seq=10, lat=50.0, lng=2.0)]
    points = mat._points(rows, gps, indoor=False)
    assert points[0]["gps_seq"] is None
    assert points[1]["gps_seq"] == 10
    assert points[1]["seq_gap"] == 1


def test_event_window_is_capture_generation_and_seq_scoped():
    params = {"pid": "p", "cap": "c", "generation": "g"}
    where = mat.event_where(params, view="rf", from_s=1, to_s=2,
                            after_seq=3, lanes="radio,mobilite",
                            types="RRF,SCG_ADD")
    assert "e.project_id=:pid" in where
    assert "e.capture_id=:cap" in where
    assert "e.generation=:generation" in where
    assert "e.seq>:after_seq" in where
    assert "COALESCE(e.t_rel_end_s,e.t_rel_s)>=:from_s" in where
    assert "e.t_rel_s<=:to_s" in where
    assert "e.type=ANY(:types)" in where
    assert params["types"] == ["RRF", "SCG_ADD"]
    assert " ts" not in where.lower()


def test_summary_total_is_rf_population_and_hidden_closes_source_gap():
    source = dict(
        event_counts={"messages": 19863, "markers": 3199,
                      "procedures": 415, "tasks": 69},
        tracks=["network"], source_total=23546, without_rf_lane=123,
        seq_start=1, seq_end=2, t_rel_start_s=0.0, t_rel_end_s=1.0,
        indoor=False,
    )
    summary = mat.align_summary(source, [{}] * 23398)
    assert summary["total"] == 23398
    assert summary["hidden"] == {
        "without_rf_lane": 123,
        "procedure_projection_delta": 25,
    }
    assert sum(summary["hidden"].values()) == 23546 - summary["total"]


def test_backfill_refuses_untraced_reason_without_database(capsys):
    assert backfill_main(["p", "--reason", "short"]) == 2
    assert "VERDICT=FAIL reason=reason_too_short" in capsys.readouterr().err


class _TimelineResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return self._rows

    def scalar_one(self):
        return self._scalar


class _TimelineDb:
    def __init__(self):
        self.sql = []

    def execute(self, statement, params):
        sql = str(statement)
        self.sql.append((sql, dict(params)))
        if "GROUP BY 1,2,3" in sql:
            return _TimelineResult([
                {"t_rel_s": 0.0, "protocol": "RRC LTE", "lane": "radio", "n": 3},
                {"t_rel_s": 0.0, "protocol": "Procedures", "lane": "connexion", "n": 1},
                {"t_rel_s": 10.0, "protocol": "NAS", "lane": "radio", "n": 2},
            ])
        if "upper(COALESCE" in sql:
            return _TimelineResult([{"id": "state-1", "seq": 7}])
        if "lower(COALESCE" in sql:
            return _TimelineResult([{
                "id": "task-1", "seq": 11, "seq_end": 22,
                "t_rel_s": 1.0, "t_rel_end_s": 5.0,
                "attrs": {"track": "dl"},
            }])
        return _TimelineResult(scalar=2)


def test_timeline_is_bucketed_from_materialized_capture_without_population(monkeypatch):
    monkeypatch.setattr(mat, "active_capture", lambda *_: {
        "generation": "generation-1", "t_rel_end_s": 20.0,
    })
    monkeypatch.setattr(mat.svc, "population", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("population must not run on timeline request")
    ))
    db = _TimelineDb()

    result = mat.read_timeline(db, "project-1", "capture-1", bucket_s=10)

    assert result["total"] == 8
    assert result["missing_time"] == 2
    assert result["t_rel_end_s"] == 20.0
    assert result["buckets"] == [
        {"t_rel_s": 0.0, "counts": {"RRC LTE": 3, "Procedures": 1},
         "lane_counts": {"radio": 3, "connexion": 1}},
        {"t_rel_s": 10.0, "counts": {"NAS": 2}, "lane_counts": {"radio": 2}},
    ]
    assert result["state_events"] == [{"id": "state-1", "seq": 7}]
    assert result["task_events"] == [{
        "id": "task-1", "seq": 11, "seq_end": 22,
        "t_rel_s": 1.0, "t_rel_end_s": 5.0,
        "attrs": {"track": "dl"},
    }]
    assert all(params["pid"] == "project-1" and params["cap"] == "capture-1"
               for _, params in db.sql)
    assert all("ORDER BY e.project_id,e.capture_id,e.seq" in sql
               for sql, _ in db.sql if "upper(COALESCE" in sql)
    assert all("ORDER BY e.project_id,e.capture_id,e.seq" in sql
               for sql, _ in db.sql if "lower(COALESCE" in sql)
