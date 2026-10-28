"""Compare canonical imported row content across disposable test projects."""
import hashlib
import os
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db import SessionLocal


TABLES = {
    "stg_event_raw": ("seq", (), ("project_id", "id", "nmf_file_id")),
    "nmf_event_deep": ("seq", (), ("project_id",)),
    "nmf_event_group": (
        "seq", ("group_name", "set_index"), ("project_id",)
    ),
    "nmf_event_light": ("seq", (), ("project_id",)),
    "nmf_event_light_group": (
        "seq", ("group_name", "identity", "set_index"), ("project_id",)
    ),
    "nmf_cell_second": (
        "seq_first", ("second", "event_code", "metric_code", "cell_index", "seq_last"),
        ("project_id",)
    ),
    "nmf_event_pair": (
        "seq_start", ("type", "context_id", "seq_end", "seq_hoi"), ("project_id",)
    ),
}


def fingerprint(db, project_id: str, table: str, seq_column: str,
                tie_columns: tuple[str, ...],
                excluded: tuple[str, ...]) -> tuple[str, int]:
    # JSONB has a deterministic key order.  Explicit schema keys break ties
    # without forcing PostgreSQL to sort each very wide JSON payload.
    order_suffix = "".join(f", {column}" for column in tie_columns)
    statement = text(f"""
        SELECT capture_id, {seq_column} AS seq,
               md5((to_jsonb(t) - CAST(:excluded AS text[]))::text) AS payload_hash
        FROM {table} AS t
        WHERE project_id=:project_id
        ORDER BY project_id, capture_id, {seq_column}{order_suffix}
    """).execution_options(stream_results=True, yield_per=500)
    digest = hashlib.sha256()
    count = 0
    for capture_id, seq, payload_hash in db.execute(statement, {
        "project_id": project_id,
        "excluded": list(excluded),
    }):
        # PostgreSQL reduces the wide canonical JSON row before transfer; the
        # outer SHA-256 binds row order, keys and the complete sequence.
        digest.update(f"{capture_id}\x1f{seq}\x1f{payload_hash}\n".encode())
        count += 1
    db.rollback()
    return digest.hexdigest(), count


def main() -> None:
    if os.environ.get("G42_EPHEMERAL_DB") != "YES":
        print("G42_CONTENT reason=G42_EPHEMERAL_DB_must_equal_YES")
        print("G42_CONTENT VERDICT=FAIL")
        raise SystemExit(2)
    project_ids = [value for value in os.environ.get(
        "G42_FINGERPRINT_PROJECT_IDS", ""
    ).split("::") if value]
    if len(project_ids) < 2:
        print("G42_CONTENT reason=at_least_two_project_ids_required")
        print("G42_CONTENT VERDICT=FAIL")
        raise SystemExit(2)

    results = {}
    with SessionLocal() as db:
        for project_id in project_ids:
            results[project_id] = {}
            for table, (seq_column, tie_columns, excluded) in TABLES.items():
                value = fingerprint(
                    db, project_id, table, seq_column, tie_columns, excluded
                )
                results[project_id][table] = value
                print(f"G42_CONTENT project_id={project_id} table={table} "
                      f"sha256={value[0]} rows={value[1]}")

    reference = results[project_ids[0]]
    mismatches = [
        f"{project_id}:{table}"
        for project_id in project_ids[1:]
        for table in TABLES
        if results[project_id][table] != reference[table]
    ]
    print(f"G42_CONTENT mismatches={mismatches}")
    print(f"G42_CONTENT VERDICT={'PASS' if not mismatches else 'FAIL'}")
    raise SystemExit(0 if not mismatches else 1)


if __name__ == "__main__":
    main()
