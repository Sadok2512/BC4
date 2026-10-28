"""G38/G39 witness for sparse native Light storage on a disposable DB."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from psycopg.types.json import Jsonb
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db import SessionLocal
from app.config import settings
from app.nmf_decoder.native import NATIVE_COLUMNS, native_row
from app.nmf_decoder.source import records


def fail(label: str, reason: str, code: int = 1) -> None:
    print(f"{label} VERDICT=FAIL reason={reason}")
    raise SystemExit(code)


def main() -> None:
    if os.environ.get("G38_EPHEMERAL_DB") != "YES":
        fail("G38", "G38_EPHEMERAL_DB_must_equal_YES", 2)
    paths = [Path(value) for value in os.environ.get("G38_NMF_PATHS", "").split("::") if value]
    if len(paths) < 3 or any(not path.is_file() for path in paths):
        fail("G38", "three_real_NMF_paths_required", 2)
    project_id = os.environ.get("G38_PROJECT_ID", "")
    if not project_id:
        fail("G38", "G38_PROJECT_ID_required", 2)

    expected: dict[str, tuple[int, str]] = {}
    with SessionLocal() as db:
        database = db.execute(text("SELECT current_database()" )).scalar_one()
        if database == "bc4":
            fail("G38", "live_database_forbidden", 2)
        db.execute(text("DELETE FROM nmf_event_light_native WHERE project_id=:pid"), {"pid": project_id})
        db.commit()
        raw = db.connection().connection.dbapi_connection
        columns = ",".join(NATIVE_COLUMNS)
        with raw.cursor() as cursor, cursor.copy(
            f"COPY nmf_event_light_native ({columns}) FROM STDIN"
        ) as copy:
            for path in paths:
                capture_id = hashlib.sha256(path.name.encode()).hexdigest()[:12]
                digest = hashlib.sha256(); count = 0
                position_state = {}
                for record in records(path, capture_id):
                    if record.excluded:
                        continue
                    count += 1
                    digest.update(f"{capture_id}\x1f{record.seq}\n".encode())
                    row = native_row(project_id, record, position_state)
                    row["values"] = Jsonb(row["values"]) if row["values"] else None
                    row["groups"] = Jsonb(row["groups"]) if row["groups"] else None
                    copy.write_row(tuple(row.get(column) for column in NATIVE_COLUMNS))
                expected[capture_id] = (count, digest.hexdigest())
        # The COPY temporarily carries measured WGS84 lon/lat in x/y.  Convert
        # them in-place with PostGIS before any spatial bin is evaluated.
        db.execute(text("""
            UPDATE nmf_event_light_native
            SET x_2154=ST_X(ST_Transform(ST_SetSRID(ST_Point(x_2154,y_2154),4326),2154)),
                y_2154=ST_Y(ST_Transform(ST_SetSRID(ST_Point(x_2154,y_2154),4326),2154))
            WHERE project_id=:pid AND position_source IN ('exact','previous_fix')
        """), {"pid": project_id})
        db.commit()

        actual = db.execute(text("""
            SELECT capture_id,count(*) AS n,
                   min(seq) AS seq_start,max(seq) AS seq_end
            FROM nmf_event_light_native
            WHERE project_id=:pid GROUP BY capture_id ORDER BY capture_id
        """), {"pid": project_id}).mappings().all()
        mismatches = []
        for row in actual:
            expected_count = expected[row["capture_id"]][0]
            if row["n"] != expected_count:
                mismatches.append({"capture_id": row["capture_id"], "expected": expected_count, "actual": row["n"]})
            digest = hashlib.sha256()
            for seq in db.execute(text("""
                SELECT seq FROM nmf_event_light_native
                WHERE project_id=:pid AND capture_id=:cap ORDER BY project_id,capture_id,seq
            """), {"pid": project_id, "cap": row["capture_id"]}).scalars():
                digest.update(f"{row['capture_id']}\x1f{seq}\n".encode())
            if digest.hexdigest() != expected[row["capture_id"]][1]:
                mismatches.append({"capture_id": row["capture_id"], "seq_order": "different"})
        if len(actual) != len(expected):
            mismatches.append({"captures_expected": len(expected), "captures_actual": len(actual)})
        print("G38 captures=" + json.dumps([dict(row) for row in actual], sort_keys=True))
        if mismatches:
            fail("G38", json.dumps(mismatches, sort_keys=True))
        print("G38 VERDICT=PASS")

        for delta in (0.001, 0.01, 0.1, 1.0):
            stats = db.execute(text("""
                WITH population AS (
                  SELECT capture_id,count(*) n
                  FROM nmf_event_light_native WHERE project_id=:pid GROUP BY capture_id
                ), binned AS (
                  SELECT capture_id,floor(t_rel_s/:delta) bin,count(*) n,
                         min(seq) seq_start,max(seq) seq_end
                  FROM nmf_event_light_native
                  WHERE project_id=:pid AND t_rel_s IS NOT NULL
                  GROUP BY capture_id,floor(t_rel_s/:delta)
                ), outside AS (
                  SELECT capture_id,count(*) n FROM nmf_event_light_native
                  WHERE project_id=:pid AND t_rel_s IS NULL GROUP BY capture_id
                )
                SELECT count(*) FILTER (WHERE coalesce(b.n,0)+coalesce(o.n,0)<>p.n) bad,
                       sum(p.n) population,sum(coalesce(b.n,0)) binned,
                       sum(coalesce(o.n,0)) outside
                FROM population p
                LEFT JOIN (SELECT capture_id,sum(n) n FROM binned GROUP BY capture_id) b USING(capture_id)
                LEFT JOIN outside o USING(capture_id)
            """), {"pid": project_id, "delta": delta}).mappings().one()
            print(f"G39 temporal_delta_s={delta} " + json.dumps(dict(stats), sort_keys=True, default=str))
            if stats["bad"]:
                fail("G39", f"temporal_population_delta_{delta}")

        spatial = db.execute(text("""
            WITH population AS (
              SELECT capture_id,count(*) n FROM nmf_event_light_native
              WHERE project_id=:pid GROUP BY capture_id
            ), binned AS (
              SELECT capture_id,floor(x_2154/50) bx,floor(y_2154/50) by,
                     count(*) n,min(seq) seq_start,max(seq) seq_end
              FROM nmf_event_light_native
              WHERE project_id=:pid AND position_source IN ('exact','previous_fix')
              GROUP BY capture_id,floor(x_2154/50),floor(y_2154/50)
            ), outside AS (
              SELECT capture_id,count(*) n FROM nmf_event_light_native
              WHERE project_id=:pid AND position_source IS NULL GROUP BY capture_id
            )
            SELECT count(*) FILTER (WHERE coalesce(b.n,0)+coalesce(o.n,0)<>p.n) bad,
                   sum(p.n) population,sum(coalesce(b.n,0)) binned,
                   sum(coalesce(o.n,0)) outside,
                   (SELECT count(*) FROM nmf_event_light_native WHERE project_id=:pid AND position_source='exact') n_exact,
                   (SELECT count(*) FROM nmf_event_light_native WHERE project_id=:pid AND position_source='previous_fix') n_inherited,
                   (SELECT count(*) FROM nmf_event_light_native WHERE project_id=:pid AND position_source='previous_fix' AND position_gap_s>:max_gap) gap_violations,
                   (SELECT count(*) FROM nmf_event_light_native n WHERE project_id=:pid AND position_source='previous_fix'
                    AND NOT EXISTS (SELECT 1 FROM nmf_event_light_native f WHERE f.project_id=n.project_id AND f.capture_id=n.capture_id
                      AND f.position_source='exact' AND f.seq<n.seq)) inheritance_without_same_capture_fix
            FROM population p
            LEFT JOIN (SELECT capture_id,sum(n) n FROM binned GROUP BY capture_id) b USING(capture_id)
            LEFT JOIN outside o USING(capture_id)
        """), {"pid": project_id, "max_gap": settings.spatial_fix_max_gap_s}).mappings().one()
        print("G39 spatial_50m=" + json.dumps(dict(spatial), sort_keys=True, default=str))
        if (spatial["bad"] or not spatial["binned"] or spatial["gap_violations"]
                or spatial["inheritance_without_same_capture_fix"]):
            fail("G39", "spatial_population_or_positive_witness")
        gaps = db.execute(text("""SELECT count(*) n,
          percentile_cont(.5) WITHIN GROUP(ORDER BY position_gap_s) p50,
          percentile_cont(.9) WITHIN GROUP(ORDER BY position_gap_s) p90,
          percentile_cont(.95) WITHIN GROUP(ORDER BY position_gap_s) p95,
          percentile_cont(.99) WITHIN GROUP(ORDER BY position_gap_s) p99,
          max(position_gap_s) max_gap
          FROM nmf_event_light_native WHERE project_id=:pid
            AND position_source='previous_fix'"""), {"pid": project_id}).mappings().one()
        print("G39 inherited_gap_distribution_s=" + json.dumps(dict(gaps), sort_keys=True, default=str))
        print("G39 VERDICT=PASS")


if __name__ == "__main__":
    main()
