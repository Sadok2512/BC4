#!/usr/bin/env python3
"""G46: no column populated by the 1.7.1 Light contract may be emptied.

The two aggregations consume the same decoded records from the same NMF.  The
baseline implements the 1.7.1 result contract without its obsolete arithmetic
on textual ``last`` values; that arithmetic never changed the returned value.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.nmf_decoder import light as light_module
from app.nmf_decoder.source import records


class Baseline171Stat:
    """Result-equivalent 1.7.1 aggregation, safe for current textual fields."""

    def __init__(self, agg):
        self.agg = agg
        self.total = 0.0
        self.weight = 0.0
        self.n = 0
        self.last = None
        self.lo = None
        self.hi = None
        self.freq = {}

    def add(self, value, weight=1.0):
        if value is None or weight is None or weight < 0:
            return
        self.n += 1
        self.last = value
        if self.agg in {'sum', 'mean', 'min', 'max'}:
            self.total += value * weight
            self.weight += weight
            self.lo = value if self.lo is None else min(self.lo, value)
            self.hi = value if self.hi is None else max(self.hi, value)
        elif self.agg == 'dominant':
            self.weight += weight
            self.freq[value] = self.freq.get(value, 0) + weight

    def value(self):
        if not self.n or (self.agg in {'mean', 'dominant'} and self.weight == 0):
            return None
        return {
            'sum': lambda: self.total,
            'mean': lambda: self.total / self.weight,
            'min': lambda: self.lo,
            'max': lambda: self.hi,
            'last': lambda: self.last,
            'count': lambda: self.n,
            'dominant': lambda: min(self.freq, key=lambda value: (-self.freq[value], value)),
        }[self.agg]()


def aggregate(path: Path, capture_id: str, stat_class) -> Counter:
    original = light_module.Stat
    light_module.Stat = stat_class
    try:
        light = light_module.Light()
        for record in records(path, capture_id):
            if not record.excluded:
                light.add(record)
        counts = Counter()
        for row in light.rows():
            event = row['event_code']
            for column, value in row['values'].items():
                if value is not None:
                    counts[(event, column)] += 1
            for group in row['groups']:
                for column, value in group['values'].items():
                    if value is not None:
                        counts[(event, column)] += 1
        return counts
    finally:
        light_module.Stat = original


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--nmf', required=True, type=Path)
    args = parser.parse_args()
    if not args.nmf.is_file():
        print(f'G46 witness_missing={args.nmf}')
        print('VERDICT: FAIL')
        return 2
    digest = hashlib.sha256(args.nmf.read_bytes()).hexdigest()
    capture_id = digest[:12]
    baseline = aggregate(args.nmf, capture_id, Baseline171Stat)
    current = aggregate(args.nmf, capture_id, light_module.Stat)
    if not baseline:
        print(f'G46 sha256={digest} baseline_non_null=0')
        print('VERDICT: FAIL')
        return 3
    print(f'G46 sha256={digest}')
    print('event\tcolumn\tbaseline_1_7_1\tcurrent\tdelta')
    emptied = []
    for event, column in sorted(baseline):
        old = baseline[(event, column)]
        new = current[(event, column)]
        print(f'{event}\t{column}\t{old}\t{new}\t{new-old}')
        if old and not new:
            emptied.append((event, column, old))
    print(f'G46 populated_columns={len(baseline)} emptied_columns={len(emptied)}')
    if emptied:
        for event, column, count in emptied:
            print(f'EMPTIED event={event} column={column} baseline={count}')
        print('VERDICT: FAIL')
        return 1
    print('VERDICT: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
