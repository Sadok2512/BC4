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
                            after_seq=3, lanes="radio,mobilite")
    assert "e.project_id=:pid" in where
    assert "e.capture_id=:cap" in where
    assert "e.generation=:generation" in where
    assert "e.seq>:after_seq" in where
    assert "COALESCE(e.t_rel_end_s,e.t_rel_s)>=:from_s" in where
    assert "e.t_rel_s<=:to_s" in where
    assert " ts" not in where.lower()


def test_backfill_refuses_untraced_reason_without_database(capsys):
    assert backfill_main(["p", "--reason", "short"]) == 2
    assert "VERDICT=FAIL reason=reason_too_short" in capsys.readouterr().err
