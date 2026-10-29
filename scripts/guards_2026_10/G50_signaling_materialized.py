#!/usr/bin/env python3
"""G50 — source projections and import-time materialization are identical."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from app.db import SessionLocal
from app.models import Project
from app.routes.signaling import SignalingEvent, window_events
from app.services import populate_chain
from app.signaling import materialized as mat
from app.signaling import rf
from app.signaling import service as svc

PROJECT_ID = "bc1-kpi-lean"
CAPTURE_ID = "a4b0c321c52e"


def fingerprint(rows):
    payload = json.dumps(jsonable_encoder(rows), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode()).hexdigest()


def source_points(db, rows, meta):
    evidence, _ = rf.events(db, PROJECT_ID, CAPTURE_ID)
    point_rows = []
    for event in evidence:
        attrs = event.get("attrs") or {}
        if attrs.get("rule_id") != "raw_protocol":
            continue
        protocol = attrs.get("protocol")
        if protocol == "Nemo":
            protocol = "Événements Nemo"
        if protocol not in svc.LAYER_FOR_PROTOCOL:
            continue
        point_rows.append(dict(seq=event["seq"], t_rel_s=event["t_rel_s"],
          protocol=protocol, layer=svc.LAYER_FOR_PROTOCOL[protocol]))
    return svc.gps_points(db, PROJECT_ID, CAPTURE_ID, point_rows, meta)[0]


def event_window(rows, start, end):
    return window_events(rows, start, end, None, None)[0]


def api_events(rows):
    return [SignalingEvent(**row).model_dump() for row in rows]


def point_window(rows, start, end):
    return [row for row in rows if
            (start is None or row["t_rel_s"] is not None and row["t_rel_s"] >= start) and
            (end is None or row["t_rel_s"] is not None and row["t_rel_s"] <= end)]


def main():
    with SessionLocal() as db:
        project = db.get(Project, PROJECT_ID)
        if project is None:
            print("G50 VERDICT=FAIL reason=project_missing")
            return 1

        # Complete the historical A-E finalization without materializing yet,
        # so the old request-time computation remains the comparison oracle.
        if project.last_populate_at is None:
            real_materialize = mat.materialize_project
            mat.materialize_project = lambda *_args, **_kwargs: {"guard": "deferred"}
            try:
                populate_chain._run_populate_chain(db, project)
            finally:
                mat.materialize_project = real_materialize
        else:
            print(f"G50 oracle_finalization reused_at={project.last_populate_at.isoformat()}")

        rows, procedures, meta, times = svc.population(
            db, PROJECT_ID, CAPTURE_ID, persist=True,
        )
        legacy, _ = svc.project_legacy_events(
            db, PROJECT_ID, CAPTURE_ID, rows, procedures, meta, times,
        )
        evidence, _ = rf.events(db, PROJECT_ID, CAPTURE_ID)
        legacy = rf.enrich_legacy_connected_events(legacy, evidence, CAPTURE_ID)
        points = source_points(db, rows, meta)

        candidates = [row["t_rel_s"] for row in evidence + points
                      if row["t_rel_s"] is not None]
        end = max(candidates) if candidates else 0.0
        windows = [(0.0, 60.0), (end / 2, end / 2 + 60.0),
                   (max(0.0, end - 60.0), end), (None, None)]

        report = mat.materialize_capture(db, PROJECT_ID, CAPTURE_ID)
        failures = []
        for view, source in (("legacy", legacy), ("rf", evidence)):
            for index, (start, stop) in enumerate(windows, 1):
                expected = api_events(event_window(source, start, stop))
                actual, total, _counts, _rules = mat.read_events(
                    db, PROJECT_ID, CAPTURE_ID, view=view,
                    from_s=start, to_s=stop,
                )
                actual = api_events(actual)
                ok = expected == actual and total == len(expected)
                print(f"G50 events view={view} window={index} rows={len(actual)} "
                      f"source_sha={fingerprint(expected)} materialized_sha={fingerprint(actual)} "
                      f"VERDICT={'PASS' if ok else 'FAIL'}")
                if not ok:
                    failures.append(f"events:{view}:{index}")

        for index, (start, stop) in enumerate(windows, 1):
            expected = point_window(points, start, stop)
            actual, total, _active = mat.read_points(
                db, PROJECT_ID, CAPTURE_ID, from_s=start, to_s=stop,
            )
            ok = expected == actual and total == len(expected)
            print(f"G50 points window={index} rows={len(actual)} "
                  f"source_sha={fingerprint(expected)} materialized_sha={fingerprint(actual)} "
                  f"VERDICT={'PASS' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"points:{index}")

        start, stop = windows[0]
        t0 = perf_counter()
        first_events = mat.read_events(db, PROJECT_ID, CAPTURE_ID, view="rf",
                                       from_s=start, to_s=stop, limit=5000)
        event_s = perf_counter() - t0
        t0 = perf_counter()
        first_points = mat.read_points(db, PROJECT_ID, CAPTURE_ID,
                                       from_s=start, to_s=stop, limit=10000)
        point_s = perf_counter() - t0
        print(f"G50 cold_window events_s={event_s:.6f} rows={len(first_events[0])} "
              f"points_s={point_s:.6f} rows={len(first_points[0])} "
              f"VERDICT={'PASS' if event_s < 1 and point_s < 1 else 'FAIL'}")
        if event_s >= 1 or point_s >= 1:
            failures.append("latency")

        sizes = db.execute(text("""SELECT relname,
          pg_total_relation_size(quote_ident(relname)) AS bytes
          FROM (VALUES ('signaling_materialized_capture'),
                       ('signaling_materialized_event'),
                       ('signaling_materialized_point')) AS tables(relname)
          ORDER BY relname""")).mappings()
        for row in sizes:
            print(f"G50 disk table={row['relname']} bytes={row['bytes']}")
        print("G50 materialize=" + json.dumps(report, sort_keys=True))
        print("G50 VERDICT=" + ("FAIL " + ",".join(failures) if failures else "PASS"))
        return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
