"""Audit reproductible du contrat KPI Analytics d'une release catalogue."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.kpi.catalog_release.registry import catalog_file_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    payload = json.loads(catalog_file_path(args.version).read_text(encoding="utf-8"))
    leaves = [node for node in payload["nodes"] if node.get("node_type") == "leaf"]
    decisions = payload.get("analytics_series_decisions", [])
    policy = payload.get("analytics_classification_policy", {})
    counts = Counter(node.get("analytics_tab") for node in leaves)
    classifications = Counter(node.get("analytics_classification") for node in leaves)
    unique_decisions = {(row.get("code"), row.get("event")) for row in decisions}
    report = {
        "command": f"python3 scripts/catalog/audit_analytics_release.py --version {args.version}",
        "catalog_version": payload.get("catalog_version"),
        "leaf_count": len(leaves),
        "tab_counts": dict(sorted(counts.items(), key=lambda item: str(item[0]))),
        "classification_counts": dict(sorted(classifications.items(), key=lambda item: str(item[0]))),
        "missing_analytics_tab": [node["node_id"] for node in leaves if not node.get("analytics_tab")],
        "residual_ambiguous": policy.get("residual_ambiguous_node_ids", []),
        "series_decisions_count": len(decisions),
        "series_decisions_unique": len(unique_decisions),
        "series_decisions": decisions,
    }
    report["verdict"] = (
        "PASS"
        if not report["missing_analytics_tab"]
        and len(decisions) == len(unique_decisions)
        else "FAIL"
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
