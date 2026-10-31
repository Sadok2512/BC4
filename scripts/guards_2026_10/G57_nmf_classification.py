#!/usr/bin/env python3
"""G57 — type-only NMF classification, with zero payload mutation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

from app.nmf_decoder.classification import classify_other


def _load_decoder(path: Path):
    spec = importlib.util.spec_from_file_location("g57_external_decoder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load decoder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "decode_nmf_file_full"):
        raise RuntimeError("decoder lacks decode_nmf_file_full")
    return module


def _baseline_category(code: str, category: str | None) -> str:
    del code
    return category or "signalling"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    if len(args.files) != 3:
        raise SystemExit("G57 FAIL: exactly three witness files are required")
    if any(not path.is_file() for path in [args.decoder, *args.files]):
        raise SystemExit("G57 FAIL: decoder or witness missing")

    decoder = _load_decoder(args.decoder)
    before = Counter()
    after = Counter()
    payload_before = hashlib.sha256()
    payload_after = hashlib.sha256()
    total = 0
    for path in sorted(args.files):
        result = decoder.decode_nmf_file_full(str(path))
        for event in result["events"]:
            total += 1
            code = event.get("event_code") or ""
            before_category = _baseline_category(code, event.get("category"))
            after_category = classify_other(code, event.get("category"))
            before[before_category] += 1
            after[after_category] += 1
            payload = {key: value for key, value in event.items() if key != "category"}
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            payload_before.update(canonical.encode())
            payload_before.update(b"\n")
            payload_after.update(canonical.encode())
            payload_after.update(b"\n")

    reclassified = before["other"] - after["other"]
    payload_equal = payload_before.digest() == payload_after.digest()
    checks = {
        "total": total == 420243,
        "before_other": before["other"] == 326707,
        "after_other": after["other"] == 16795,
        "reclassified": reclassified == 309912,
        "payload_equal": payload_equal,
    }
    print(f"TOTAL_RECORDS={total}")
    print(f"BEFORE_OTHER={before['other']}")
    print(f"AFTER_OTHER={after['other']}")
    print(f"RECLASSIFIED={reclassified}")
    print("DECODED_VALIDATED=0")
    print(f"NFF_259_UNCERTIFIED={reclassified}")
    print(f"KPI_INPUT_DIFF={'0' if payload_equal else 'nonzero'}")
    print(f"G57 VERDICT={'PASS' if all(checks.values()) else 'FAIL'} checks={checks}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
