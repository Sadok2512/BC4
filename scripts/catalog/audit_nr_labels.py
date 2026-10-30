"""Audit content-based LTE/NR labels and visual duplicates in a catalog."""
from __future__ import annotations

import argparse
import csv
import io
import json
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile


EVENTS = {"CELLMEAS", "MIMOMEAS"}
SECTION_SYSTEM = {"Parameters for LTE": 7, "Parameters for NR": 9}


def spec_parameters(spec_zip: Path) -> dict[tuple[str, int, str], str]:
    with ZipFile(spec_zip) as archive:
        raw = archive.read("nmf_all_events_fields_2.50.csv")
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    return {
        (row["event"], SECTION_SYSTEM[row["section"]], row["field_no"]): row["name"]
        for row in rows
        if row["event"] in EVENTS and row["section"] in SECTION_SYSTEM
    }


def audit(catalog_path: Path, spec_zip: Path) -> dict:
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    leaves = [
        node
        for node in payload["nodes"]
        if node.get("node_type") == "leaf" and node.get("displayed", True)
    ]
    parameters = spec_parameters(spec_zip)
    shared: dict[tuple[str, str], dict[int, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for leaf in leaves:
        event = leaf.get("event")
        system = leaf.get("field_system")
        field_no = str(leaf.get("field_no") or "")
        parameter = parameters.get((event, system, field_no))
        if parameter:
            shared[(event, parameter)][system].append(leaf)

    shared_rows = []
    for (event, parameter), by_system in sorted(shared.items()):
        if set(by_system) != {7, 9}:
            continue
        shared_rows.append(
            {
                "event": event,
                "parameter": parameter,
                "lte_field_no": sorted({row["field_no"] for row in by_system[7]}),
                "nr_field_no": sorted({row["field_no"] for row in by_system[9]}),
                "lte_leaves": len(by_system[7]),
                "nr_leaves": len(by_system[9]),
                "lte_label": sorted({row["label"].split(" @ ", 1)[0] for row in by_system[7]}),
                "nr_label": sorted({row["label"].split(" @ ", 1)[0] for row in by_system[9]}),
            }
        )

    labels: dict[tuple[str | None, str], list[str]] = defaultdict(list)
    for leaf in leaves:
        labels[(leaf.get("parent_id"), leaf["label"])].append(leaf["node_id"])
    duplicates = [
        {"parent_id": parent, "label": label, "node_ids": node_ids}
        for (parent, label), node_ids in sorted(labels.items())
        if len(node_ids) > 1
    ]
    event_counts = {
        event: {
            str(system): sum(
                leaf.get("event") == event and leaf.get("field_system") == system
                for leaf in leaves
            )
            for system in (7, 9)
        }
        for event in sorted(EVENTS)
    }
    return {
        "catalog_version": payload["catalog_version"],
        "displayed_leaf_count": len(leaves),
        "event_system_leaf_counts": event_counts,
        "shared_parameters_by_content": shared_rows,
        "duplicate_parent_label_groups": duplicates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--spec-zip", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--expect-unique", action="store_true")
    args = parser.parse_args()
    result = audit(args.catalog, args.spec_zip)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    duplicates = result["duplicate_parent_label_groups"]
    if args.expect_unique and duplicates:
        print(f"VERDICT=FAIL duplicate_parent_label_groups={len(duplicates)}")
        return 1
    verdict = "PASS" if not duplicates else "AUDIT"
    print(f"VERDICT={verdict} duplicate_parent_label_groups={len(duplicates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
