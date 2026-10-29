#!/usr/bin/env python3
"""G48: lossless and unique nmf_cell_second projection before COPY."""
from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.nmf_decoder.cells import (
    CELLMEAS_TYPES_LTE,
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


def expected_projection(light: Light):
    expected = Counter()
    unsupported = Counter()
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
                            expected[(bucket["second"], event, system, raw, occurrence, metric)] += 1
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
        allowed = range(32) if system == 7 else CELL_TYPES_NR if system == 9 else ()
        if raw not in allowed:
            unsupported[(event, system, raw)] += 1
            continue
        _cell_index_for(raw, system)
        for metric, stat in bucket["stats"].items():
            definition = fields().get(metric, {})
            if (definition.get("dimension") or metric == "phrate_ph_ch_type"
                    or metric.endswith("_cell_type") or stat.value() is None):
                continue
            expected[(bucket["second"], event, system, raw, 0, metric)] += 1
    return expected, unsupported


def audit(path: Path) -> bool:
    digest = sha256(path)
    light = Light()
    decoded = 0
    for record in records(path, digest[:12]):
        if not record.excluded:
            light.add(record)
            decoded += 1

    rows = list(cell_rows(light))
    keys = Counter(
        (row["second"], row["event_code"], row["metric_code"], row["cell_index"])
        for row in rows
    )
    duplicates = {key: count for key, count in keys.items() if count > 1}
    expected, unsupported = expected_projection(light)
    actual = Counter()
    for row in rows:
        if row["cell_index"] < 0:
            continue
        source = cell_source_for_index(row["cell_index"])
        if source is not None:
            system, raw, occurrence = source
            actual[(row["second"], row["event_code"], system, raw,
                    occurrence, row["metric_code"])] += 1

    missing = expected - actual
    extra = actual - expected
    expected_by_type = Counter()
    actual_by_type = Counter()
    for (_second, event, system, raw, _occurrence, _metric), count in expected.items():
        expected_by_type[(event, system, raw)] += count
    for (_second, event, system, raw, _occurrence, _metric), count in actual.items():
        actual_by_type[(event, system, raw)] += count

    print(f"G48 file={path.name} sha256={digest} decoded_records={decoded}")
    print(f"G48 cell_rows={len(rows)} unique_keys={len(keys)} duplicate_keys={len(duplicates)}")
    for (event, system, raw), count in sorted(expected_by_type.items()):
        print(
            f"G48 event={event} system={system} raw_cell_type={raw} "
            f"expected={count} actual={actual_by_type[(event, system, raw)]}"
        )
    if duplicates:
        for key, count in sorted(duplicates.items())[:20]:
            print(f"DUPLICATE key={key} count={count}")
    if missing:
        for key, count in sorted(missing.items())[:20]:
            print(f"MISSING source={key} count={count}")
    if extra:
        for key, count in sorted(extra.items())[:20]:
            print(f"EXTRA source={key} count={count}")
    if unsupported:
        for key, count in sorted(unsupported.items(), key=lambda item: str(item[0])):
            print(f"UNSUPPORTED system_raw={key} groups={count}")
    passed = not duplicates and not missing and not extra and not unsupported and bool(expected)
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
