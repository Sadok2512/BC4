"""Manual-only guard for the catalogue 2.68.6 simplified tree.

This script is intentionally not wired into CI.  Every live count is printed
under the exact API request whose response produced it.
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from app.db import SessionLocal
from app.kpi.catalog_release.registry import current_catalog
from app.kpi.metrics_catalog_v4 import build_catalog_v4
from app.kpi.simple_tree import load_simple_leaves, load_simple_tree


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="Test_6")
    args = parser.parse_args()

    definitions = load_simple_tree()
    leaf_map = load_simple_leaves()
    family_set = {
        leaf.metric_id.split("@", 1)[0]
        for leaf in leaf_map.values()
    }
    linked = [
        row
        for row in definitions
        if (row.status == "open" and not row.families)
        or (row.families and all(family in family_set for family in row.families))
    ]
    duplicate_names = len(leaf_map) - len({leaf.simple_name for leaf in leaf_map.values()})
    print("QUERY=CSV SELECT tech,theme,kpi,familles_metric_id,statut FROM app/kpi/simple_tree.csv")
    print(f"SIMPLE_KPI_LINKED={len(linked)} EXPECTED={len(definitions)}")
    print(f"SIMPLE_NAME_DUPLICATES={duplicate_names}")
    if len(definitions) != 71 or len(linked) != 71 or duplicate_names:
        print("VERDICT=FAIL stage=static")
        return 1

    with SessionLocal() as db:
        project = db.execute(
            text("SELECT id,name FROM projects WHERE name=:name ORDER BY id LIMIT 1"),
            {"name": args.project},
        ).first()
        if project is None:
            print("VERDICT=FAIL reason=project_not_found")
            return 1
        release = current_catalog(db)
        if release is None or release.version != "2.68.6":
            version = release.version if release else "NONE"
            print(f"VERDICT=FAIL reason=catalog_release version={version}")
            return 1
        captures = db.execute(
            text(
                "SELECT capture_id FROM nmf_capture "
                "WHERE project_id=:pid ORDER BY capture_id"
            ),
            {"pid": project.id},
        ).scalars().all()
        for capture_id in captures:
            request = (
                f"GET /projects/{project.id}/metrics?capture_id={capture_id} "
                "ORDER=(capture_id,seq) NEVER=ts"
            )
            print(f"QUERY={request}")
            payload = build_catalog_v4(
                db, project.id, release, capture_ids=(capture_id,)
            )
            simple_nodes = [node for node in payload["nodes"] if node.get("simple_name")]
            names = [node["simple_name"] for node in simple_nodes]
            response_duplicates = len(names) - len(set(names))
            print(f"CAPTURE={capture_id} SIMPLE_NAME_DUPLICATES={response_duplicates}")
            if response_duplicates:
                print("VERDICT=FAIL stage=live_duplicate")
                return 1
            for row in definitions:
                count = sum(
                    int(node.get("n") or 0)
                    for node in simple_nodes
                    if node.get("technology") == row.tech
                    and node.get("simple_theme") == row.theme
                    and node.get("simple_kpi") == row.kpi
                )
                print(
                    f"CAPTURE={capture_id} TECH={row.tech} KPI={row.kpi} "
                    f"ROWS={count} REQUEST={request}"
                )
    print("VERDICT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
