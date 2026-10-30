#!/usr/bin/env python3
"""Print the normalized SHA-256 of a ``/metrics/series`` JSON response.

Fingerprint contract (the exact jq ``-cS`` contract used by the proxy proof):

* excluded fields: every recursively nested ``result_id`` and the top-level
  ``csv`` field, because both repeat a request-scoped generated identifier;
* sorting: object keys are sorted recursively; array order is preserved exactly
  as returned by the capture-scoped API (no timestamp-based reordering);
* normalization: compact JSON separators, UTF-8 characters kept unescaped, and
  one trailing newline. The newline reproduces jq's ``-c`` output byte-for-byte.

Usage: ``python scripts/fingerprint/metrics_series.py response.json``
The only stdout output is the lowercase SHA-256 hexadecimal digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _without_result_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_result_ids(item)
            for key, item in value.items()
            if key != "result_id"
        }
    if isinstance(value, list):
        return [_without_result_ids(item) for item in value]
    return value


def fingerprint(payload: dict[str, Any]) -> str:
    normalized = _without_result_ids(payload)
    normalized.pop("csv", None)
    canonical = (
        json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
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
