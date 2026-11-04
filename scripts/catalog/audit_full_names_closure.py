"""Reproducible content audit for the 2.68.3 full-name closure.

The static catalog branch determines Technology.  Counts come from the
project-scoped runtime cache and are joined by the immutable baked
``display_code``; presentation labels never decide identity.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "app" / "kpi" / "catalog_release"
BASELINE_PATH = ROOT / "audit" / "catalog_2.68.2_foreign_values.json"
PROJECT_ID = "43e81a34a073"
FOREIGN_BLOCK_RE = re.compile(
    r"\(bloc (?:GSM|UMTS|cdma|WiMAX|TETRA|EVDO|GAN|iDEN|TD-SCDMA)"
)


def artifact_rows(version: str) -> list[dict]:
    payload = json.loads(
        (CATALOG_DIR / f"catalog_{version}.json").read_text(encoding="utf-8")
    )
    nodes = payload["nodes"]
    by_id = {node["node_id"]: node for node in nodes if node.get("node_id")}

    def technology(node: dict) -> str | None:
        visited: set[str] = set()
        while node:
            node_id = node.get("node_id")
            if node_id in visited:
                return None
            if node_id:
                visited.add(node_id)
            value = node.get("tech") or node.get("technology")
            if value:
                return str(value)
            node = by_id.get(node.get("parent_id"))
        return None

    return [
        node
        for node in nodes
        if node.get("node_type") == "leaf"
        and technology(node) in {"LTE", "NR"}
        and FOREIGN_BLOCK_RE.search(str(node.get("label") or ""))
    ]


def export_rows(dsn: str) -> tuple[str, dict[str, dict]]:
    engine = create_engine(dsn)
    query = text(
        "SELECT scope_key,payload FROM metrics_catalog_cache "
        "WHERE project_id=:project_id AND scope_key LIKE 'captures:%' "
        "ORDER BY scope_key"
    )
    with engine.connect() as connection:
        payloads = list(connection.execute(query, {"project_id": PROJECT_ID}))
    versions = {
        str((payload.get("catalog_release") or {}).get("version") or "UNKNOWN")
        for _, payload in payloads
    }
    if len(versions) != 1:
        raise RuntimeError(f"cache versions incohérentes : {sorted(versions)}")
    merged: dict[str, dict] = {}
    for scope_key, payload in payloads:
        capture_id = scope_key.removeprefix("captures:")
        for node in payload.get("nodes", []):
            display_code = node.get("display_code")
            if node.get("node_type") != "leaf" or not display_code:
                continue
            entry = merged.setdefault(display_code, {**node, "n_per_capture": {}})
            entry["n_per_capture"][capture_id] = int(node.get("n") or 0)
    return versions.pop(), merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()

    active_version, cache = export_rows(args.dsn)
    foreign = [
        node
        for node in cache.values()
        if node.get("technology") in {"LTE", "NR"}
        and FOREIGN_BLOCK_RE.search(str(node.get("label") or ""))
    ]
    print(
        f"QUERY foreign_block static technology=LTE|NR regex={FOREIGN_BLOCK_RE.pattern!r}"
    )
    print(
        f"CATALOG {active_version} foreign={len(foreign)} "
        f"with_values={sum(any(n > 0 for n in row['n_per_capture'].values()) for row in foreign)}"
    )

    if args.write_baseline:
        valued = []
        for runtime in foreign:
            display_code = runtime["display_code"]
            counts = runtime["n_per_capture"]
            if any(n > 0 for n in counts.values()):
                valued.append({
                    "display_code": display_code,
                    "metric_id": runtime.get("metric_id"),
                    "label": runtime.get("label"),
                    "n_per_capture": counts,
                })
        BASELINE_PATH.write_text(
            json.dumps(valued, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"ACTIVE {active_version} valued={len(valued)} baseline={BASELINE_PATH}")
        for row in valued:
            print(f"{row['metric_id']}\t{row['label']}\t{row['n_per_capture']}")
        return 0

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    print(f"ACTIVE {active_version} valued_before={len(baseline)}")
    failures = 0
    for row in baseline:
        runtime = cache.get(row["display_code"]) or {}
        after_counts = runtime.get("n_per_capture") or {}
        if after_counts != row["n_per_capture"]:
            failures += 1
        print(
            f"{row['metric_id']}\t{row['label']}\t"
            f"{row['n_per_capture']}->{after_counts}\t"
            f"{runtime.get('label') or 'MISSING'}"
        )
    print(f"VALUE_PARITY failures={failures}")
    return 1 if failures or foreign else 0


if __name__ == "__main__":
    raise SystemExit(main())
