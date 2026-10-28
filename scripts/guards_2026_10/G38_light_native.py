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
from app.nmf_decoder.source import records


REASON_BITS = {
    reason: 1 << index for index, reason in enumerate((
        "context_layout_unsupported", "csv_malformed", "event_undocumented",
        "fields_truncated", "format_extensions_unproven", "format_unknown",
        "format_unsupported", "identity_header_redacted",
        "parameter_type_undocumented", "system_missing",
        "system_undocumented", "time_missing", "time_regression",
        "unknown_fields",
    ))
}


def fail(label: str, reason: str, code: int = 1) -> None:
    print(f"{label} VERDICT=FAIL reason={reason}")
    raise SystemExit(code)


def clean_values(values: dict) -> dict | None:
    result = {key: value for key, value in values.items() if value is not None}
    return result or None


def clean_groups(groups: list[dict]) -> list[dict] | None:
    result = []
    for group in groups:
        values = clean_values(group["values"])
        if values:
            result.append([group["group_name"], group["set_index"], values])
    return result or None


def measured_position(record) -> tuple[float | None, float | None, str | None]:
    lon = record.values.get("gps_lon", record.values.get("posi_lon"))
    lat = record.values.get("gps_lat", record.values.get("posi_lat"))
    # GPS is deliberately inactive in the metric schema, but NFF 2.19 proves
    # its physical longitude/latitude columns.  Position provenance is a
    # storage concern, not a metric activation decision, so retain those two
    # documented tokens without treating any neighbouring record as measured.
    if (lon is None or lat is None) and record.event_code == "GPS" and len(record.tokens) >= 5:
        try:
            lon, lat = float(record.tokens[3]), float(record.tokens[4])
        except (TypeError, ValueError):
            lon = lat = None
    if (lon is None or lat is None) and record.event_code == "POSI" and len(record.tokens) >= 8:
        try:
            lon, lat = float(record.tokens[6]), float(record.tokens[7])
        except (TypeError, ValueError):
            lon = lat = None
    if lon is None or lat is None:
        return None, None, None
    lon, lat = float(lon), float(lat)
    if not (-180 <= lon <= 180 and -90 <= lat <= 90) or (lon == 0 and lat == 0):
        return None, None, None
    return lon, lat, "measured"


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
        columns = (
            "project_id,capture_id,seq,event_code,system,t_rel_s,partial,reason_mask,"
            "reason_extra,unknown_cols,context_id,context_ids,values,groups,"
            "x_2154,y_2154,position_source"
        )
        with raw.cursor() as cursor, cursor.copy(
            f"COPY nmf_event_light_native ({columns}) FROM STDIN"
        ) as copy:
            for path in paths:
                capture_id = hashlib.sha256(path.name.encode()).hexdigest()[:12]
                digest = hashlib.sha256(); count = 0
                for record in records(path, capture_id):
                    if record.excluded:
                        continue
                    count += 1
                    digest.update(f"{capture_id}\x1f{record.seq}\n".encode())
                    lon, lat, source = measured_position(record)
                    unknown = [
                        int(code.rsplit("_", 1)[1]) for code in record.field_codes
                        if code.startswith("unk_") and code.rsplit("_", 1)[1].isdigit()
                    ] or None
                    reason_mask = sum(REASON_BITS.get(reason, 0) for reason in record.reasons)
                    reason_extra = [reason for reason in record.reasons if reason not in REASON_BITS] or None
                    values = clean_values(record.values)
                    groups = clean_groups(record.groups)
                    copy.write_row((
                        project_id, capture_id, record.seq, record.event_code,
                        record.system, record.t_rel_s,
                        record.decode_status == "partial", reason_mask, reason_extra,
                        unknown, record.context_id, record.context_ids or None,
                        Jsonb(values) if values else None,
                        Jsonb(groups) if groups else None,
                        lon, lat, source,
                    ))
                expected[capture_id] = (count, digest.hexdigest())
        # The COPY temporarily carries measured WGS84 lon/lat in x/y.  Convert
        # them in-place with PostGIS before any spatial bin is evaluated.
        db.execute(text("""
            UPDATE nmf_event_light_native
            SET x_2154=ST_X(ST_Transform(ST_SetSRID(ST_Point(x_2154,y_2154),4326),2154)),
                y_2154=ST_Y(ST_Transform(ST_SetSRID(ST_Point(x_2154,y_2154),4326),2154))
            WHERE project_id=:pid AND position_source='measured'
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
              WHERE project_id=:pid AND position_source='measured'
              GROUP BY capture_id,floor(x_2154/50),floor(y_2154/50)
            ), outside AS (
              SELECT capture_id,count(*) n FROM nmf_event_light_native
              WHERE project_id=:pid AND position_source IS NULL GROUP BY capture_id
            )
            SELECT count(*) FILTER (WHERE coalesce(b.n,0)+coalesce(o.n,0)<>p.n) bad,
                   sum(p.n) population,sum(coalesce(b.n,0)) binned,
                   sum(coalesce(o.n,0)) outside
            FROM population p
            LEFT JOIN (SELECT capture_id,sum(n) n FROM binned GROUP BY capture_id) b USING(capture_id)
            LEFT JOIN outside o USING(capture_id)
        """), {"pid": project_id}).mappings().one()
        print("G39 spatial_50m=" + json.dumps(dict(spatial), sort_keys=True, default=str))
        if spatial["bad"] or not spatial["binned"]:
            fail("G39", "spatial_population_or_positive_witness")
        print("G39 VERDICT=PASS")


if __name__ == "__main__":
    main()
