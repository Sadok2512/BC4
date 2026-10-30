#!/usr/bin/env python3
"""Audit the catalog-2.57.0 deferred metric leaves by database content."""
import argparse
import csv
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from app.kpi.metrics_v3 import definitions, parse_selection
from app.nmf_decoder.schema import fields


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--decisions", required=True, type=Path)
    args = parser.parse_args()
    decisions = json.loads(args.decisions.read_text())["series_decisions"]
    codes = [row["code"] for row in decisions]
    if len(codes) != 61 or len(set(codes)) != 61:
        print(f"VERDICT=FAIL expected 61 unique codes, got {len(codes)}", file=sys.stderr)
        return 1

    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(("code", "event", "storage_type", "value_kind", "n_nonnull", "n_distinct"))
    defs = definitions()
    engine = create_engine(args.dsn)
    with engine.connect() as db:
        for token in codes:
            metric = parse_selection(token, defs)
            code = metric["source_column"]
            params = {"pid": args.project_id, "cap": args.capture_id}
            if metric.get("cell_type_filter") and metric["event"] == "CELLMEAS":
                spec = metric["cell_type_filter"]
                params.update(system=spec["system"], raw=spec["raw_cell_type"])
                sql = f"""
                    SELECT pg_typeof(MIN(g.{code}))::text AS storage_type,
                           COUNT(g.{code})::bigint AS n_nonnull,
                           COUNT(DISTINCT g.{code})::bigint AS n_distinct
                    FROM nmf_event_light_group g
                    JOIN nmf_event_light l
                      ON l.project_id=g.project_id AND l.capture_id=g.capture_id
                     AND l.seq=g.seq AND l.event_code='CELLMEAS'
                    WHERE g.project_id=:pid AND g.capture_id=:cap
                      AND g.group_name='cells' AND g.cell_type=:raw
                      AND l.system=:system AND g.{code} IS NOT NULL
                """
            elif metric["base_code"] == "cqi_n_params" and metric.get("cell_type_filter"):
                spec = metric["cell_type_filter"]
                params.update(system=spec["system"], raw=spec["raw_cell_type"])
                sql = f"""
                    SELECT pg_typeof(MIN({code}))::text AS storage_type,
                           COUNT({code})::bigint AS n_nonnull,
                           COUNT(DISTINCT {code})::bigint AS n_distinct
                    FROM nmf_event_deep
                    WHERE project_id=:pid AND capture_id=:cap AND event_code='CQI'
                      AND system=:system AND cqi_cell_type=:raw AND {code} IS NOT NULL
                """
            else:
                field = fields()[code]
                table = "nmf_event_group" if field.get("group") else "nmf_event_deep"
                group_filter = " AND group_name=:group_name" if field.get("group") else " AND event_code=:event"
                params.update(group_name=field.get("group"), event=field["event"])
                sql = f"""
                    SELECT pg_typeof(MIN({code}))::text AS storage_type,
                           COUNT({code})::bigint AS n_nonnull,
                           COUNT(DISTINCT {code})::bigint AS n_distinct
                    FROM {table}
                    WHERE project_id=:pid AND capture_id=:cap {group_filter}
                      AND {code} IS NOT NULL
                """
            row = db.execute(text(sql), params).mappings().one()
            value_kind = "number" if metric["kind"] == "numeric" else "enum_or_identifier"
            writer.writerow((token, metric["event"], row["storage_type"] or "no_value", value_kind,
                             row["n_nonnull"], row["n_distinct"]))
    print("VERDICT=PASS 61/61 audited", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
