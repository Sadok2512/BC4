"""Import-time Signaling projection and indexed request-time readers."""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from decimal import Decimal, InvalidOperation
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.signaling import rf
from app.signaling import service as svc

WRITE_BATCH = 1000

EVENT_INSERT = text("""INSERT INTO signaling_materialized_event (
 project_id,capture_id,seq,generation,view,id,seq_end,t_rel_s,t_rel_end_s,
 lane,type,kind,duration_ms,outcome,cause,label,attrs,pivot_seq,linked_seqs,
 link_rule,seq_gap,context_id,session_id,decoder_version)
 VALUES (:project_id,:capture_id,:seq,:generation,:view,:id,:seq_end,:t_rel_s,
 :t_rel_end_s,:lane,:type,:kind,:duration_ms,:outcome,:cause,:label,
 CAST(:attrs AS jsonb),:pivot_seq,:linked_seqs,:link_rule,:seq_gap,:context_id,
 :session_id,:decoder_version)""")

POINT_INSERT = text("""INSERT INTO signaling_materialized_point (
 project_id,capture_id,seq,generation,t_rel_s,lat,lng,protocol,layer,gps_seq,
 seq_gap,technology,direction,message_name,procedure_ids,decoder_version)
 VALUES (:project_id,:capture_id,:seq,:generation,:t_rel_s,:lat,:lng,:protocol,
 :layer,:gps_seq,:seq_gap,:technology,:direction,:message_name,:procedure_ids,
 :decoder_version)""")


def _seconds(value):
    try:
        h, m, s = value.split(":")
        return float(Decimal(h) * 3600 + Decimal(m) * 60 + Decimal(s))
    except (AttributeError, ValueError, InvalidOperation):
        return None


def _batches(rows, size=WRITE_BATCH):
    for offset in range(0, len(rows), size):
        yield rows[offset:offset + size]


def _points(rows, gps, indoor):
    """Exact strict-previous GPS rule used by the former request path."""
    fixes = [] if indoor else gps
    fix_seqs = [fix["seq"] for fix in fixes]
    result = []
    for row in rows:
        index = bisect_left(fix_seqs, row["seq"]) - 1
        fix = fixes[index] if index >= 0 else None
        result.append(dict(
            seq=row["seq"], t_rel_s=row["t_rel_s"], protocol=row["protocol"],
            layer=row["layer"], lat=fix["lat"] if fix else None,
            lng=fix["lng"] if fix else None,
            gps_seq=fix["seq"] if fix else None,
            seq_gap=row["seq"] - fix["seq"] if fix else None,
            technology=row["technology"], direction=row["direction"],
            message_name=row["message_name"],
            procedure_ids=row.get("procedure_ids") or [],
        ))
    return result


def _summary(db, project_id, capture_id, indoor):
    params = dict(pid=project_id, cap=capture_id, markers=list(svc.MARKERS))
    bounds = svc.query(db, """(SELECT seq,ts FROM stg_event_raw
          WHERE project_id=:pid AND capture_id=:cap ORDER BY seq LIMIT 1)
        UNION ALL
        (SELECT seq,ts FROM stg_event_raw
          WHERE project_id=:pid AND capture_id=:cap ORDER BY seq DESC LIMIT 1)""", params)
    if not bounds:
        raise HTTPException(404, "capture_not_found_in_project")
    counts = svc.query(db, """SELECT
      (SELECT count(*) FROM stg_event WHERE project_id=:pid AND capture_id=:cap
       AND event_code IN ('RRCSM','L3SM')) AS messages,
      (SELECT count(*) FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap
       AND event_code=ANY(:markers)) AS markers,
      (SELECT count(*) FROM nmf_event_pair WHERE project_id=:pid AND capture_id=:cap) AS procedures,
      (SELECT count(*) FROM task_run WHERE project_id=:pid AND capture_id=:cap
       AND task_type IN ('HTTP_DL','HTTP_UL')) AS tasks,
      (SELECT count(*) FROM stg_event WHERE project_id=:pid AND capture_id=:cap
       AND event_code IN ('RRCSM','L3SM')
       AND system NOT IN ('LTE','NR')) AS without_rf_lane""", params)[0]
    counts = {key: int(value) for key, value in counts.items()}
    without_rf_lane = counts.pop("without_rf_lane")
    first, last = bounds[0], bounds[-1]
    first_s, last_s = _seconds(first["ts"]), _seconds(last["ts"])
    duration = (last_s - first_s if first_s is not None and last_s is not None
                and last_s >= first_s else None)
    tracks = ["network"]
    if counts["procedures"]:
        tracks.extend(["connexion", "mobilite"])
    if counts["tasks"]:
        tracks.append("services")
    return dict(event_counts=counts, tracks=tracks, source_total=sum(counts.values()),
                without_rf_lane=without_rf_lane,
                seq_start=first["seq"], seq_end=last["seq"],
                t_rel_start_s=0.0, t_rel_end_s=duration, indoor=indoor)


def align_summary(summary, rf_events):
    """Make the headline count describe exactly the visible RF population."""
    rf_total = len(rf_events)
    gap = summary.pop("source_total") - rf_total
    without_rf_lane = min(summary.pop("without_rf_lane"), max(gap, 0))
    procedure_delta = max(gap - without_rf_lane, 0)
    hidden = {}
    if without_rf_lane:
        hidden["without_rf_lane"] = without_rf_lane
    if procedure_delta:
        hidden["procedure_projection_delta"] = procedure_delta
    return dict(**summary, total=rf_total, hidden=hidden)


def materialize_capture(db, project_id, capture_id, *, batch_size=WRITE_BATCH):
    state = db.execute(text("""SELECT c.decoder_version,n.env
      FROM nmf_capture c JOIN nmf_file n ON n.id=c.nmf_file_id
      WHERE c.project_id=:pid AND c.capture_id=:cap"""),
      dict(pid=project_id, cap=capture_id)).mappings().one_or_none()
    if state is None:
        raise LookupError(f"capture_not_found:{project_id}:{capture_id}")
    decoder_version = state["decoder_version"]
    indoor = (state["env"] or "").lower() == "indoor"

    rows, procedures, meta, times = svc.population(
        db, project_id, capture_id, persist=True,
    )
    params = dict(pid=project_id, cap=capture_id, markers=list(svc.MARKERS))
    rf_rows = svc.query(db, svc.SOURCE_SQL, params)
    deep = svc.query(db, rf.DEEP_SQL, params)
    pairs = svc.query(db, rf.PAIR_SQL, params)
    tasks = svc.query(db, rf.TASK_SQL, params)
    gps = ([] if indoor else svc.query(db, """SELECT seq,lat,lon AS lng
      FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap
      AND event_code='GPS' AND lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180
      AND NOT(lat=0 AND lon=0) ORDER BY seq""", params))
    summary = _summary(db, project_id, capture_id, indoor)
    # Release the read snapshot before CPU projection and sliced writes.
    db.commit()

    evidence = rf.project_events(rf_rows, deep, pairs, tasks, times,
                                 capture_id=capture_id)
    summary = align_summary(summary, evidence)
    legacy, _ = svc.project_legacy_events(
        db, project_id, capture_id, rows, procedures, meta, times,
    )
    legacy = rf.enrich_legacy_connected_events(legacy, evidence, capture_id)
    points = _points(rows, gps, indoor)
    generation = uuid4().hex

    # A failed prior generation is never active and can be reclaimed first.
    for table in ("signaling_materialized_event", "signaling_materialized_point"):
        db.execute(text(f"""DELETE FROM {table} x
          WHERE x.project_id=:pid AND x.capture_id=:cap
          AND NOT EXISTS (SELECT 1 FROM signaling_materialized_capture c
            WHERE c.project_id=x.project_id AND c.capture_id=x.capture_id
              AND c.generation=x.generation)"""), params)
        db.commit()

    event_values = []
    for view, events in (("legacy", legacy), ("rf", evidence)):
        for event in events:
            event_values.append(dict(
                project_id=project_id, capture_id=capture_id,
                generation=generation, view=view,
                decoder_version=decoder_version,
                id=event["id"], seq=event["seq"], seq_end=event.get("seq_end"),
                t_rel_s=event.get("t_rel_s"),
                t_rel_end_s=event.get("t_rel_end_s"), lane=event["lane"],
                type=event["type"], kind=event["kind"],
                duration_ms=event.get("duration_ms"), outcome=event.get("outcome"),
                cause=event.get("cause"), label=event["label"],
                attrs=json.dumps(event.get("attrs") or {}, sort_keys=True,
                                 separators=(",", ":"), default=str),
                pivot_seq=event.get("pivot_seq"),
                linked_seqs=event.get("linked_seqs") or [],
                link_rule=event["link_rule"], seq_gap=event.get("seq_gap"),
                context_id=event.get("context_id"),
                session_id=event.get("session_id"),
            ))
    for batch in _batches(event_values, batch_size):
        db.execute(EVENT_INSERT, batch)
        db.commit()

    point_values = [dict(project_id=project_id, capture_id=capture_id,
                         generation=generation, decoder_version=decoder_version,
                         **point) for point in points]
    for batch in _batches(point_values, batch_size):
        db.execute(POINT_INSERT, batch)
        db.commit()

    db.execute(text("""INSERT INTO signaling_materialized_capture (
      project_id,capture_id,generation,decoder_version,event_counts,tracks,hidden,total,
      seq_start,seq_end,t_rel_start_s,t_rel_end_s,indoor,built_at)
      VALUES (:pid,:cap,:generation,:decoder_version,CAST(:event_counts AS jsonb),
      CAST(:tracks AS jsonb),CAST(:hidden AS jsonb),:total,:seq_start,:seq_end,:t_rel_start_s,
      :t_rel_end_s,:indoor,now())
      ON CONFLICT (project_id,capture_id) DO UPDATE SET
      generation=excluded.generation,decoder_version=excluded.decoder_version,
      event_counts=excluded.event_counts,tracks=excluded.tracks,hidden=excluded.hidden,
      total=excluded.total,
      seq_start=excluded.seq_start,seq_end=excluded.seq_end,
      t_rel_start_s=excluded.t_rel_start_s,t_rel_end_s=excluded.t_rel_end_s,
      indoor=excluded.indoor,built_at=excluded.built_at"""),
      dict(pid=project_id, cap=capture_id, generation=generation,
           decoder_version=decoder_version,
           event_counts=json.dumps(summary["event_counts"], sort_keys=True),
           tracks=json.dumps(summary["tracks"]), hidden=json.dumps(summary["hidden"], sort_keys=True),
           **{key: value for key, value in summary.items()
           if key not in ("event_counts", "tracks", "hidden")}))
    db.commit()

    # Activation above is atomic; old rows can now be removed independently.
    for table in ("signaling_materialized_event", "signaling_materialized_point"):
        db.execute(text(f"""DELETE FROM {table}
          WHERE project_id=:pid AND capture_id=:cap AND generation<>:generation"""),
          dict(pid=project_id, cap=capture_id, generation=generation))
        db.commit()
    return dict(capture_id=capture_id, decoder_version=decoder_version,
                generation=generation, legacy_events=len(legacy),
                rf_events=len(evidence), points=len(points), batch_size=batch_size)


def materialize_project(db, project_id, *, capture_id=None, batch_size=WRITE_BATCH):
    clauses = ["project_id=:pid"]
    params = {"pid": project_id}
    if capture_id is not None:
        clauses.append("capture_id=:cap")
        params["cap"] = capture_id
    captures = [row[0] for row in db.execute(text(
        "SELECT capture_id FROM nmf_capture WHERE " + " AND ".join(clauses) +
        " ORDER BY project_id,capture_id"), params)]
    if capture_id is not None and not captures:
        raise LookupError(f"capture_not_found:{project_id}:{capture_id}")
    reports = [materialize_capture(db, project_id, cap, batch_size=batch_size)
               for cap in captures]
    return dict(project_id=project_id, captures=reports,
                legacy_events=sum(r["legacy_events"] for r in reports),
                rf_events=sum(r["rf_events"] for r in reports),
                points=sum(r["points"] for r in reports))


def active_capture(db, project_id, capture_id):
    row = db.execute(text("""SELECT m.* FROM signaling_materialized_capture m
      JOIN nmf_capture c USING(project_id,capture_id)
      WHERE m.project_id=:pid AND m.capture_id=:cap
        AND m.decoder_version=c.decoder_version"""),
      dict(pid=project_id, cap=capture_id)).mappings().one_or_none()
    if row is None:
        raise HTTPException(409, dict(reason="signaling_materialization_required",
          project_id=project_id, capture_id=capture_id))
    return dict(row)


def event_where(params, *, lanes=None, failures_only=False, view="legacy",
                protocols=None, technology=None, direction=None, q=None,
                procedure=None, from_s=None, to_s=None, after_seq=None):
    clauses = ["e.project_id=:pid", "e.capture_id=:cap",
               "e.generation=:generation", "e.view=:view"]
    params["view"] = view
    if lanes:
        clauses.append("e.lane=ANY(:lanes)"); params["lanes"] = lanes.split(",")
    if failures_only:
        clauses.append("e.outcome='fail'")
    if view == "rf" and protocols is not None:
        clauses.append("e.attrs->>'protocol'=ANY(:protocols)")
        params["protocols"] = protocols.split(",")
    if view == "rf" and technology:
        clauses.append("e.attrs->>'technology'=:technology"); params["technology"] = technology
    if view == "rf" and direction:
        clauses.append("e.attrs->>'direction'=:direction"); params["direction"] = direction
    if view == "rf" and q:
        clauses.append("e.label ILIKE :q"); params["q"] = f"%{q}%"
    if procedure:
        clauses.append("""(e.id=:procedure OR e.session_id=:procedure
          OR e.attrs->>'procedure_id'=:procedure
          OR COALESCE(e.attrs->'procedure_ids','[]'::jsonb) ? :procedure)""")
        params["procedure"] = procedure
    if from_s is not None:
        clauses.append("COALESCE(e.t_rel_end_s,e.t_rel_s)>=:from_s"); params["from_s"] = from_s
    if to_s is not None:
        clauses.append("e.t_rel_s<=:to_s"); params["to_s"] = to_s
    if after_seq is not None:
        clauses.append("e.seq>:after_seq"); params["after_seq"] = after_seq
    return " AND ".join(clauses)


def read_events(db, project_id, capture_id, **filters):
    active = active_capture(db, project_id, capture_id)
    params = dict(pid=project_id, cap=capture_id,
                  generation=active["generation"])
    limit = filters.pop("limit", None)
    where = event_where(params, **filters)
    counts = [dict(row) for row in db.execute(text(f"""SELECT lane,count(*) AS n
      FROM signaling_materialized_event e WHERE {where}
      GROUP BY lane ORDER BY lane"""), params).mappings()]
    total = sum(int(row["n"]) for row in counts)
    sql = f"""SELECT id,lane,type,kind,seq,seq_end,t_rel_s,t_rel_end_s,
      duration_ms,outcome,cause,label,attrs,pivot_seq,linked_seqs,link_rule,
      seq_gap,context_id,session_id FROM signaling_materialized_event e
      WHERE {where} ORDER BY project_id,capture_id,seq,id"""
    if limit is not None:
        sql += " LIMIT :limit"; params["limit"] = limit
    events = [dict(row) for row in db.execute(text(sql), params).mappings()]
    rules = dict(Counter(event["link_rule"] for event in events))
    return events, total, {row["lane"]: int(row["n"]) for row in counts}, rules


def read_timeline(db, project_id, capture_id, *, bucket_s=10, **filters):
    """Read a compact RF overview without rebuilding the capture population."""
    active = active_capture(db, project_id, capture_id)
    params = dict(pid=project_id, cap=capture_id,
                  generation=active["generation"], bucket_s=float(bucket_s))
    where = event_where(params, view="rf", **filters)
    grouped = list(db.execute(text(f"""
      SELECT floor(e.t_rel_s/:bucket_s)*:bucket_s AS t_rel_s,
             COALESCE(e.attrs->>'protocol','Procedures') AS protocol,
             e.lane,count(*) AS n
      FROM signaling_materialized_event e
      WHERE {where} AND e.t_rel_s IS NOT NULL
      GROUP BY 1,2,3 ORDER BY 1,2,3
    """), params).mappings())
    by_time = {}
    for row in grouped:
        bucket = by_time.setdefault(float(row["t_rel_s"]),
                                    {"counts": {}, "lane_counts": {}})
        bucket["counts"][row["protocol"]] = (
            bucket["counts"].get(row["protocol"], 0) + int(row["n"])
        )
        bucket["lane_counts"][row["lane"]] = (
            bucket["lane_counts"].get(row["lane"], 0) + int(row["n"])
        )
    buckets = [dict(t_rel_s=t, **values) for t, values in sorted(by_time.items())]
    # State bands describe the capture clock itself and must remain available
    # when radio filters narrow only the density/detail layers.
    state_where = event_where(params, view="rf")
    state_events = [dict(row) for row in db.execute(text(f"""
      SELECT id,lane,type,kind,seq,seq_end,t_rel_s,t_rel_end_s,
        duration_ms,outcome,cause,label,attrs,pivot_seq,linked_seqs,link_rule,
        seq_gap,context_id,session_id
      FROM signaling_materialized_event e
      WHERE {state_where}
        AND upper(COALESCE(e.attrs->>'track','')) IN ('RRC_STATE','UE_STATE')
      ORDER BY e.project_id,e.capture_id,e.seq,e.id
    """), params).mappings()]
    # The full-capture UI deliberately does not fetch every RF event. Keep the
    # small, duration-bearing task population in the overview so its bars are
    # still available before zooming into a detail window.
    task_events = [dict(row) for row in db.execute(text(f"""
      SELECT id,lane,type,kind,seq,seq_end,t_rel_s,t_rel_end_s,
        duration_ms,outcome,cause,label,attrs,pivot_seq,linked_seqs,link_rule,
        seq_gap,context_id,session_id
      FROM signaling_materialized_event e
      WHERE {where}
        AND lower(COALESCE(e.attrs->>'track','')) IN ('dl','ul')
        AND e.t_rel_s IS NOT NULL AND e.t_rel_end_s IS NOT NULL
      ORDER BY e.project_id,e.capture_id,e.seq,e.id
    """), params).mappings()]
    missing_time = int(db.execute(text(f"""SELECT count(*)
      FROM signaling_materialized_event e WHERE {where} AND e.t_rel_s IS NULL"""),
      params).scalar_one())
    total = sum(sum(bucket["counts"].values()) for bucket in buckets) + missing_time
    return dict(buckets=buckets,state_events=state_events,task_events=task_events,
                bucket_s=float(bucket_s),
                total=total,missing_time=missing_time,
                t_rel_end_s=active.get("t_rel_end_s"))


def read_points(db, project_id, capture_id, *, protocols=None, direction=None,
                q=None, procedure=None, technology=None, from_s=None, to_s=None,
                limit=None):
    active = active_capture(db, project_id, capture_id)
    params = dict(pid=project_id, cap=capture_id,
                  generation=active["generation"])
    clauses = ["project_id=:pid", "capture_id=:cap", "generation=:generation"]
    if protocols is not None:
        clauses.append("protocol=ANY(:protocols)"); params["protocols"] = protocols.split(",")
    if direction:
        clauses.append("COALESCE(direction,'unknown')=:direction"); params["direction"] = direction
    if q:
        clauses.append("message_name ILIKE :q"); params["q"] = f"%{q}%"
    if procedure:
        clauses.append(":procedure=ANY(procedure_ids)"); params["procedure"] = procedure
    if technology:
        clauses.append("technology=:technology"); params["technology"] = technology
    if from_s is not None:
        clauses.append("t_rel_s>=:from_s"); params["from_s"] = from_s
    if to_s is not None:
        clauses.append("t_rel_s<=:to_s"); params["to_s"] = to_s
    where = " AND ".join(clauses)
    total = int(db.execute(text(f"SELECT count(*) FROM signaling_materialized_point WHERE {where}"), params).scalar() or 0)
    sql = f"""SELECT seq,t_rel_s,lat,lng,protocol,layer,gps_seq,seq_gap
      FROM signaling_materialized_point WHERE {where}
      ORDER BY project_id,capture_id,seq"""
    if limit is not None:
        sql += " LIMIT :limit"; params["limit"] = limit
    points = [dict(row) for row in db.execute(text(sql), params).mappings()]
    return points, total, active
