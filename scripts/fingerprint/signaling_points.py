#!/usr/bin/env python3
"""Print the logical SHA-256 of a ``/signaling/points`` JSON response.

Fingerprint contract (the exact contract used by signaling-points-lean):

* included point fields, in this order: ``seq``, ``t_rel_s``, ``lat``, ``lng``,
  ``protocol``, ``gps_seq``, ``seq_gap``;
* excluded fields: ``layer`` and every envelope/marker field, including
  ``result_id``; these are not part of the logical map-point comparison;
* sorting: no additional sort is applied. Point order is preserved exactly as
  returned by the capture-scoped API (canonical ``seq`` order);
* normalization: legacy point objects and ``compact-v1`` rows become the same
  seven-value arrays; compact JSON separators, UTF-8 characters unescaped, and
  no trailing newline are used for SHA-256.

Usage: ``python scripts/fingerprint/signaling_points.py response.json``
The only stdout output is the lowercase SHA-256 hexadecimal digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LOGICAL_FIELDS = (
    "seq",
    "t_rel_s",
    "lat",
    "lng",
    "protocol",
    "gps_seq",
    "seq_gap",
)
COMPACT_FIELDS = (
    "seq",
    "t_rel_s",
    "lat",
    "lng",
    "protocol_index",
    "gps_seq",
    "seq_gap",
)


def _logical_rows(payload: dict[str, Any]) -> list[tuple[Any, ...]]:
    points = payload["points"]
    if payload.get("format") != "compact-v1":
        return [tuple(point[field] for field in LOGICAL_FIELDS) for point in points]

    point_fields = tuple(payload.get("point_fields", ()))
    if point_fields != COMPACT_FIELDS:
        raise ValueError(
            f"unsupported compact-v1 point_fields: {point_fields!r}; "
            f"expected {COMPACT_FIELDS!r}"
        )
    protocols = payload["protocols"]
    return [
        (
            row[0],
            row[1],
            row[2],
            row[3],
            protocols[row[4]],
            row[5],
            row[6],
        )
        for row in points
    ]


def fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        _logical_rows(payload),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("response", type=Path, help="JSON response file")
    args = parser.parse_args()
    with args.response.open(encoding="utf-8") as source:
        payload = json.load(source)
    print(fingerprint(payload))


if __name__ == "__main__":
    main()
