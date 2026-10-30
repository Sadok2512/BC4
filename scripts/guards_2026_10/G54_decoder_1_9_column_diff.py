#!/usr/bin/env python3
"""G54: compare decoder 1.8.2 and 1.9.0 column content on one NMF.

The baseline and candidate are imported in separate Python processes. Values
are hashed in canonical source order by ``(seq, group, set_index)``; timestamps
are never used. Existing columns must be byte-identical. Only the six complete
NFF 2.50 LTE PLAIU group columns may be newly populated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


TARGET_COLUMNS = {
    "plaiu_mod1", "plaiu_mcs1", "plaiu_n_rep",
    "plaiu_tbs0", "plaiu_tbs1", "plaiu_scs",
}


def emit(root: Path, nmf: Path) -> int:
    sys.path.insert(0, str(root))
    from app.nmf_decoder import DECODER_VERSION
    from app.nmf_decoder.source import records

    states: dict[str, hashlib._Hash] = defaultdict(hashlib.sha256)
    counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    digest = hashlib.sha256(nmf.read_bytes()).hexdigest()
    for record in records(nmf, digest[:12]):
        if record.excluded:
            continue
        statuses[record.decode_status] += 1
        reasons.update(record.reasons)
        for column, value in record.values.items():
            if value is None:
                continue
            payload = [record.seq, "", -1, value]
            states[column].update(json.dumps(payload, separators=(",", ":")).encode())
            counts[column] += 1
        for group in record.groups:
            for column, value in group["values"].items():
                if value is None:
                    continue
                payload = [record.seq, group["group_name"], group["set_index"], value]
                states[column].update(json.dumps(payload, separators=(",", ":")).encode())
                counts[column] += 1
    print(json.dumps({
        "decoder_version": DECODER_VERSION,
        "columns": {column: {"count": counts[column], "sha256": state.hexdigest()}
                    for column, state in sorted(states.items())},
        "statuses": dict(sorted(statuses.items())),
        "reasons": dict(sorted(reasons.items())),
    }, sort_keys=True))
    return 0


def collect(script: Path, root: Path, nmf: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(script), "--emit", "--root", str(root), "--nmf", str(nmf)],
        text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"decoder subprocess exit={result.returncode}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nmf", required=True, type=Path)
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--candidate-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--root", type=Path)
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args()
    if args.emit:
        return emit(args.root, args.nmf)
    if (not args.nmf.is_file() or args.baseline_root is None
            or not args.baseline_root.is_dir() or not args.candidate_root.is_dir()):
        print("G54 input_missing")
        print("VERDICT: FAIL")
        return 2
    script = Path(__file__).resolve()
    baseline = collect(script, args.baseline_root, args.nmf)
    candidate = collect(script, args.candidate_root, args.nmf)
    old = baseline["columns"]
    new = candidate["columns"]
    changed = sorted(column for column in old.keys() & new.keys() if old[column] != new[column])
    removed = sorted(old.keys() - new.keys())
    added = sorted(new.keys() - old.keys())
    unexpected_added = sorted(set(added) - TARGET_COLUMNS)
    print(
        f"G54 file={args.nmf.name} baseline={baseline['decoder_version']} "
        f"candidate={candidate['decoder_version']}"
    )
    print(f"G54 existing_changed={changed}")
    print(f"G54 removed={removed}")
    print(f"G54 added={added}")
    for column in added:
        print(f"G54 added_column={column} count={new[column]['count']} sha256={new[column]['sha256']}")
    print(f"G54 baseline_statuses={baseline['statuses']} candidate_statuses={candidate['statuses']}")
    passed = (
        baseline["decoder_version"] == "1.8.2"
        and candidate["decoder_version"] == "1.9.0"
        and not changed and not removed and not unexpected_added and bool(added)
    )
    print(f"VERDICT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
