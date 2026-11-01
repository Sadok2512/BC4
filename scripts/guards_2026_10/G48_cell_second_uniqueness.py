#!/usr/bin/env python3
"""G48: lossless and unique nmf_cell_second projection before COPY."""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.nmf_decoder.cells import (
    CELLMEAS_TYPES_LTE,
    SERVING_CELL_TYPES_LTE,
    CELL_TYPES_NR,
    _cell_index_for,
    cell_rows,
    cell_source_for_index,
)
from app.nmf_decoder.light import Light
from app.nmf_decoder.schema import column, fields, schema_for
from app.nmf_decoder.source import records


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_projection(light: Light, unsupported: Counter):
    for bucket in light.buckets.values():
        if bucket["second"] < 0:
            continue
        system = bucket.get("system")
        event = bucket["event_code"]
        if event == "CELLMEAS":
            by_type = {}
            for group in bucket.get("groupstats", {}).values():
                if group["group_name"] != "cells":
                    continue
                discriminator = group["stats"].get("cell_type")
                raw = discriminator.value() if discriminator else None
                allowed = CELLMEAS_TYPES_LTE if system == 7 else CELL_TYPES_NR
                if raw not in allowed:
                    unsupported[(event, system, raw)] += 1
                    continue
                by_type.setdefault(raw, []).append(group)
            for raw, groups in by_type.items():
                for occurrence, group in enumerate(sorted(groups, key=lambda item: item["identity"])):
                    _cell_index_for(raw, system, occurrence)
                    for metric, stat in group["stats"].items():
                        if metric != "cell_type" and stat.value() is not None:
                            yield (bucket["second"], event, system, raw, occurrence, metric)
            continue
        schema = schema_for(event, system)
        if not schema.get("cell_scoped"):
            continue
        indices = (
            [bucket["cell_type"]]
            if event == "TXPC" and bucket.get("cell_type") is not None
            else [
                bucket["stats"][column(field["code"])].value()
                for field in schema.get("header", [])
                if field["code"].endswith(".cell_type")
                and column(field["code"]) in bucket["stats"]
            ]
        )
        if len(indices) != 1 or indices[0] is None:
            continue
        raw = int(indices[0])
        allowed = SERVING_CELL_TYPES_LTE if system == 7 else CELL_TYPES_NR if system == 9 else ()
        if raw not in allowed:
            unsupported[(event, system, raw)] += 1
            continue
        _cell_index_for(raw, system)
        for metric, stat in bucket["stats"].items():
            definition = fields().get(metric, {})
            if (definition.get("dimension") or metric == "phrate_ph_ch_type"
                    or metric.endswith("_cell_type") or stat.value() is None):
                continue
            yield (bucket["second"], event, system, raw, 0, metric)


def flush_rows(connection, key_rows, actual_rows):
    if key_rows:
        connection.executemany(
            """INSERT INTO cell_key VALUES(?,?,?,?,1)
               ON CONFLICT(second,event,metric,cell_index)
               DO UPDATE SET n=n+1""",
            key_rows,
        )
        key_rows.clear()
    if actual_rows:
        connection.executemany(
            """INSERT INTO actual VALUES(?,?,?,?,?,?,1)
               ON CONFLICT(second,event,system,raw,occurrence,metric)
               DO UPDATE SET n=n+1""",
            actual_rows,
        )
        actual_rows.clear()
    connection.commit()


def audit(path: Path) -> bool:
    digest = sha256(path)
    light = Light()
    decoded = 0
    for record in records(path, digest[:12]):
        if not record.excluded:
            light.add(record)
            decoded += 1

    unsupported = Counter()
    expected_by_type = Counter()
    actual_by_type = Counter()
    row_count = 0
    with TemporaryDirectory(prefix="g48-") as directory:
        connection = sqlite3.connect(str(Path(directory) / "projection.sqlite"))
        connection.executescript("""
          PRAGMA journal_mode=OFF;
          PRAGMA synchronous=OFF;
          CREATE TABLE cell_key(
            second INTEGER,event TEXT,metric TEXT,cell_index INTEGER,n INTEGER,
            PRIMARY KEY(second,event,metric,cell_index)) WITHOUT ROWID;
          CREATE TABLE actual(
            second INTEGER,event TEXT,system INTEGER,raw INTEGER,
            occurrence INTEGER,metric TEXT,n INTEGER,
            PRIMARY KEY(second,event,system,raw,occurrence,metric)) WITHOUT ROWID;
          CREATE TABLE expected(
            second INTEGER,event TEXT,system INTEGER,raw INTEGER,
            occurrence INTEGER,metric TEXT,n INTEGER,
            PRIMARY KEY(second,event,system,raw,occurrence,metric)) WITHOUT ROWID;
        """)
        key_rows = []
        actual_rows = []
        for row in cell_rows(light):
            row_count += 1
            key_rows.append((row["second"], row["event_code"],
                             row["metric_code"], row["cell_index"]))
            if row["cell_index"] >= 0:
                source = cell_source_for_index(row["cell_index"])
                if source is not None:
                    system, raw, occurrence = source
                    actual_rows.append((row["second"], row["event_code"], system,
                                        raw, occurrence, row["metric_code"]))
                    actual_by_type[(row["event_code"], system, raw)] += 1
            if len(key_rows) >= 5000:
                flush_rows(connection, key_rows, actual_rows)
        flush_rows(connection, key_rows, actual_rows)

        expected_rows = []
        for key in expected_projection(light, unsupported):
            expected_rows.append(key)
            expected_by_type[(key[1], key[2], key[3])] += 1
            if len(expected_rows) >= 5000:
                connection.executemany(
                    """INSERT INTO expected VALUES(?,?,?,?,?,?,1)
                       ON CONFLICT(second,event,system,raw,occurrence,metric)
                       DO UPDATE SET n=n+1""", expected_rows)
                expected_rows.clear()
        if expected_rows:
            connection.executemany(
                """INSERT INTO expected VALUES(?,?,?,?,?,?,1)
                   ON CONFLICT(second,event,system,raw,occurrence,metric)
                   DO UPDATE SET n=n+1""", expected_rows)
        connection.commit()
        unique_keys = connection.execute("SELECT count(*) FROM cell_key").fetchone()[0]
        duplicate_count = connection.execute(
            "SELECT count(*) FROM cell_key WHERE n>1").fetchone()[0]
        duplicates = connection.execute(
            "SELECT second,event,metric,cell_index,n FROM cell_key WHERE n>1 ORDER BY second,event,metric,cell_index LIMIT 20"
        ).fetchall()
        difference_sql = """SELECT e.second,e.event,e.system,e.raw,e.occurrence,e.metric,e.n-coalesce(a.n,0)
               FROM expected e LEFT JOIN actual a USING(second,event,system,raw,occurrence,metric)
               WHERE e.n<>coalesce(a.n,0)"""
        missing_count = connection.execute(
            f"SELECT count(*) FROM ({difference_sql})").fetchone()[0]
        missing = connection.execute(
            difference_sql + " ORDER BY 1,2,3,4,5,6 LIMIT 20"
        ).fetchall()
        extra_sql = """SELECT a.second,a.event,a.system,a.raw,a.occurrence,a.metric,a.n-coalesce(e.n,0)
               FROM actual a LEFT JOIN expected e USING(second,event,system,raw,occurrence,metric)
               WHERE a.n<>coalesce(e.n,0)"""
        extra_count = connection.execute(
            f"SELECT count(*) FROM ({extra_sql})").fetchone()[0]
        extra = connection.execute(
            extra_sql + " ORDER BY 1,2,3,4,5,6 LIMIT 20"
        ).fetchall()
        connection.close()

    print(f"G48 file={path.name} sha256={digest} decoded_records={decoded}")
    print(f"G48 cell_rows={row_count} unique_keys={unique_keys} duplicate_keys={duplicate_count}")
    for (event, system, raw), count in sorted(expected_by_type.items()):
        print(
            f"G48 event={event} system={system} raw_cell_type={raw} "
            f"expected={count} actual={actual_by_type[(event, system, raw)]}"
        )
    if duplicates:
        for *key, count in duplicates[:20]:
            print(f"DUPLICATE key={tuple(key)} count={count}")
    if missing:
        for *key, count in missing[:20]:
            print(f"MISSING source={tuple(key)} count={count}")
    if extra:
        for *key, count in extra[:20]:
            print(f"EXTRA source={tuple(key)} count={count}")
    if unsupported:
        for key, count in sorted(unsupported.items(), key=lambda item: str(item[0])):
            print(f"UNSUPPORTED system_raw={key} groups={count}")
    passed = (duplicate_count == 0 and missing_count == 0 and extra_count == 0
              and not unsupported
              and bool(expected_by_type))
    print(f"G48 file={path.name} VERDICT: {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nmf", required=True, action="append", type=Path)
    args = parser.parse_args()
    missing = [path for path in args.nmf if not path.is_file()]
    if missing:
        for path in missing:
            print(f"G48 witness_missing={path}")
        print("VERDICT: FAIL")
        return 2
    results = [audit(path) for path in args.nmf]
    passed = all(results)
    print(f"G48 files={len(args.nmf)} VERDICT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
