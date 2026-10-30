#!/usr/bin/env python3
"""Print the canonical SHA-256 of a ``/dict/v2/tree`` JSON response.

Fingerprint contract (the exact contract used by the dict-tree cold proof):

* excluded fields: none;
* sorting: object keys are sorted recursively by ``json.dumps(sort_keys=True)``;
  array order is preserved exactly as returned by the API;
* normalization: compact JSON separators, UTF-8 characters kept unescaped, and
  no trailing newline in the bytes passed to SHA-256.

Usage: ``python scripts/fingerprint/dict_tree.py response.json``
The only stdout output is the lowercase SHA-256 hexadecimal digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
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
