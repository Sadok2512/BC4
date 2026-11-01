#!/usr/bin/env python3
"""Exhaustive disposable-stack certification for Metrics cell leaves.

The report keeps raw records, decoded records, projected rows and API results
separate.  It never treats NULL as zero and never derives a cell role from a
display label.  Run only against an isolated stack.
"""
from __future__ import annotations

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.nmf_decoder.cells import cell_source_for_index
from app.services.auth import create_token


def get_json(url: str, token: str) -> dict:
    request = Request(url, headers={"Authorization": f"Bearer {token}"})
    with urlopen(request, timeout=120) as response:  # noqa: S310 - explicit disposable URL
        return json.load(response)


def endpoint(base: str, project: str, suffix: str, params: dict[str, str]) -> str:
    return f"{base.rstrip('/')}/projects/{project}/metrics/{suffix}?{urlencode(params)}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--capture-id", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Reuse successful rows in --output and rerun only explicit API errors",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        user = db.execute(text("""
          SELECT u.id,u.role FROM projects p
          JOIN app_user u ON u.id=p.owner_id
          WHERE p.id=:pid AND u.active IS TRUE
          UNION ALL
          SELECT u.id,u.role FROM project_share s
          JOIN app_user u ON u.id=s.user_id
          WHERE s.project_id=:pid AND u.active IS TRUE
          LIMIT 1
        """), {"pid": args.project_id}).mappings().first()
        if not user:
            raise SystemExit("VERDICT=FAIL reason=no_active_test_user")
        token, _ = create_token(
            user_id=user["id"], role=user["role"], ttl_min=120,
            secret=settings.jwt_secret,
        )
        raw_counts = {
            (row["capture_id"], row["event_code"]): int(row["n"])
            for row in db.execute(text("""
              SELECT capture_id,event_code,COUNT(*)::bigint AS n
              FROM stg_event_raw
              WHERE project_id=:pid AND capture_id=ANY(:caps)
              GROUP BY capture_id,event_code
            """), {"pid": args.project_id, "caps": args.capture_id}).mappings()
        }
        decoded_counts = {
            (row["capture_id"], row["event_code"], row["system"]): int(row["n"])
            for row in db.execute(text("""
              SELECT capture_id,event_code,system,SUM(n_records)::bigint AS n
              FROM nmf_event_light
              WHERE project_id=:pid AND capture_id=ANY(:caps)
              GROUP BY capture_id,event_code,system
            """), {"pid": args.project_id, "caps": args.capture_id}).mappings()
        }
        projected: dict[tuple[str, str, str, int | None, int], tuple[int, int]] = {}
        for row in db.execute(text("""
          SELECT s.capture_id,s.event_code,s.metric_code,i.system,i.cell_type,
                 COUNT(*)::bigint AS projected,
                 COUNT(*) FILTER (WHERE s.value IS NOT NULL)::bigint AS non_null
          FROM nmf_cell_second s
          JOIN nmf_cell_identity i
            ON i.project_id=s.project_id AND i.capture_id=s.capture_id
           AND i.seq=s.seq_first AND i.event_code=s.event_code
           AND i.cell_index=s.cell_index AND i.decoder_version=s.decoder_version
          WHERE s.project_id=:pid AND s.capture_id=ANY(:caps)
            AND s.event_code='CELLMEAS'
          GROUP BY s.capture_id,s.event_code,s.metric_code,i.system,i.cell_type
        """), {"pid": args.project_id, "caps": args.capture_id}).mappings():
            projected[(row["capture_id"], row["event_code"], row["metric_code"],
                       int(row["system"]), int(row["cell_type"]))] = (
                int(row["projected"]), int(row["non_null"])
            )
        for row in db.execute(text("""
          SELECT capture_id,event_code,metric_code,cell_index,
                 COUNT(*)::bigint AS projected,
                 COUNT(*) FILTER (WHERE value IS NOT NULL)::bigint AS non_null
          FROM nmf_cell_second
          WHERE project_id=:pid AND capture_id=ANY(:caps)
            AND event_code<>'CELLMEAS'
          GROUP BY capture_id,event_code,metric_code,cell_index
        """), {"pid": args.project_id, "caps": args.capture_id}).mappings():
            source = cell_source_for_index(int(row["cell_index"]))
            if source is None:
                continue
            system, raw, _occurrence = source
            key = (row["capture_id"], row["event_code"], row["metric_code"], system, raw)
            old = projected.get(key, (0, 0))
            projected[key] = (
                old[0] + int(row["projected"]), old[1] + int(row["non_null"])
            )

    existing: dict[tuple[str, str], dict] = {}
    if args.retry_errors and args.output.exists():
        with args.output.open(newline="", encoding="utf-8") as handle:
            existing = {
                (row["capture_id"], row["selection"]): row
                for row in csv.DictReader(handle)
                if row.get("selection")
            }

    rows: list[dict] = []
    selectable_jobs: list[tuple[int, str, str]] = []
    for capture_id in args.capture_id:
        catalog_url = (
            f"{args.base_url.rstrip('/')}/projects/{args.project_id}/metrics?"
            f"{urlencode([('capture_id', capture_id)])}"
        )
        catalog = get_json(catalog_url, token)
        kind_by_selection = {
            metric["code"]: metric.get("kind", "numeric")
            for metric in catalog.get("metrics", [])
        }
        for node in catalog["nodes"]:
            if node.get("node_type") != "leaf" or not node.get("cell"):
                continue
            event = node.get("event") or ""
            system = 7 if node.get("cell_system") == "LTE" else 9 if node.get("cell_system") == "NR" else None
            raw = node.get("raw_cell_type")
            source = node.get("source_column") or ""
            project_count, projected_non_null = projected.get(
                (capture_id, event, source, system, raw), (0, 0)
            )
            row = {
                "project_id": args.project_id,
                "capture_id": capture_id,
                "technology": node.get("technology") or "",
                "metric": node.get("metric_label") or "",
                "cell": node.get("cell_label") or "",
                "cell_selector": node.get("cell") or "",
                "raw_cell_type": "" if raw is None else raw,
                "selection": node.get("selection") or "",
                "kind": kind_by_selection.get(node.get("selection") or "", "numeric"),
                "event": event,
                "raw_records": raw_counts.get((capture_id, event), 0),
                "decoded_records": decoded_counts.get((capture_id, event, system), 0),
                "projected_rows": project_count,
                "projected_non_null": projected_non_null,
                "usable_values": int(node.get("n") or 0),
                "graph_values": "",
                "table_values": "",
                "map_values": "",
                "map_applicable": event == "CELLMEAS",
                "status": node.get("availability_status") or "",
                "reason": node.get("reason") or "",
                "api_error": "",
            }
            previous = existing.get((capture_id, row["selection"]))
            if previous:
                for field in ("graph_values", "table_values", "map_values", "api_error"):
                    row[field] = previous.get(field, "")
                for field in ("graph_values", "table_values", "map_values"):
                    if row[field] != "":
                        row[field] = int(row[field])
            rows.append(row)
            if node.get("selectable") and node.get("selection"):
                if not args.retry_errors or not previous or bool(previous.get("api_error")):
                    selectable_jobs.append((len(rows) - 1, capture_id, node["selection"]))

    def certify(job: tuple[int, str, str]) -> tuple[int, dict]:
        index, capture_id, selection = job
        common = {"capture_id": capture_id, "codes": selection}
        max_points = "100000" if rows[index]["kind"] == "categorical" else "2"
        series_url = endpoint(args.base_url, args.project_id, "series", {
            **common, "max_points": max_points,
        })
        try:
            series = get_json(series_url, token)
        except HTTPError as exc:
            body = json.load(exc)
            detail = body.get("detail", {}) if isinstance(body, dict) else {}
            if (
                exc.code != 422
                or not isinstance(detail, dict)
                or detail.get("reason") != "categorical_transitions_exceed_max_points"
            ):
                raise
            # Some historical definitions expose a categorical projection as
            # numeric in the catalogue.  The endpoint is authoritative for
            # sampling semantics; retry losslessly and record n_total.
            series = get_json(endpoint(args.base_url, args.project_id, "series", {
                **common, "max_points": "100000",
            }), token)
        table = get_json(endpoint(args.base_url, args.project_id, "table", {
            **common, "table_only": "true", "page": "1", "page_size": "25",
            "group_by": "none", "include_map": "false",
        }), token)
        values = {
            "graph_values": int(series["series"][0]["n_total"]),
            "table_values": int(table["total_rows"]),
        }
        # The workspace only offers a meaningful geographic representation
        # for radio measurements carrying CELLMEAS identity.  DCI/CQI/TXPC
        # counters are certified through Graph/Table and are explicitly
        # marked non-cartographiable rather than silently skipped.
        if rows[index]["map_applicable"]:
            mapped = get_json(endpoint(args.base_url, args.project_id, "map", common), token)
            values["map_values"] = int(mapped["total_points"])
        return index, values

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(certify, job): job for job in selectable_jobs}
        for future in as_completed(futures):
            index, _, _ = futures[future]
            try:
                _, values = future.result()
                rows[index].update(values)
                rows[index]["api_error"] = ""
            except Exception as exc:  # explicit in TSV; never silently skipped
                rows[index]["api_error"] = f"{type(exc).__name__}: {exc}"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    errors = sum(bool(row["api_error"]) for row in rows)
    graph_mismatches = sum(
        row["graph_values"] != "" and row["graph_values"] != row["usable_values"]
        for row in rows
    )
    table_mismatches = sum(
        row["table_values"] != "" and row["table_values"] != row["usable_values"]
        for row in rows
    )
    mismatches = graph_mismatches + table_mismatches
    print(
        f"ROWS={len(rows)} API_JOBS={len(selectable_jobs)} ERRORS={errors} "
        f"GRAPH_MISMATCHES={graph_mismatches} "
        f"TABLE_MISMATCHES={table_mismatches}"
    )
    print("VERDICT=PASS" if errors == 0 and mismatches == 0 else "VERDICT=FAIL")
    return 0 if errors == 0 and mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
