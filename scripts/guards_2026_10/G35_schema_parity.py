#!/usr/bin/env python3
"""G35 — compare the live schema with an empty Alembic replay.

The two schema-only dumps are retained as evidence.  The verdict is based on
PostgreSQL catalog definitions for tables, columns, constraints and indexes,
so ownership, ACLs and harmless dump ordering do not hide a structural drift.
Runtime partitions named nmf_group_* or nmf_deep_* are reported separately and
excluded from the parity verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse

import psycopg


DYNAMIC_RE = re.compile(r"^nmf_(?:group|deep)_")


def safe_dsn(dsn: str) -> str:
    parsed = urlparse(dsn.replace("postgresql+psycopg", "postgresql", 1))
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 5432}{parsed.path}"


def fetch_manifest(dsn: str) -> dict[str, Any]:
    out: dict[str, Any] = {"tables": {}, "columns": {}, "constraints": {}, "indexes": {}, "dynamic_partitions": {}}
    with psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql", 1)) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.relname, c.relkind,
                       COALESCE(p.relname, '') AS parent
                FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace
                LEFT JOIN pg_inherits i ON i.inhrelid=c.oid
                LEFT JOIN pg_class p ON p.oid=i.inhparent
                WHERE n.nspname='public' AND c.relkind IN ('r','p')
                ORDER BY c.relname
            """)
            for name, relkind, parent in cur.fetchall():
                item = {"kind": relkind, "parent": parent or None}
                if DYNAMIC_RE.match(name):
                    out["dynamic_partitions"][name] = item
                else:
                    out["tables"][name] = item

            cur.execute("""
                SELECT c.relname, a.attname,
                       pg_catalog.format_type(a.atttypid,a.atttypmod),
                       a.attnotnull,
                       COALESCE(pg_get_expr(d.adbin,d.adrelid),'')
                FROM pg_attribute a
                JOIN pg_class c ON c.oid=a.attrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                WHERE n.nspname='public' AND c.relkind IN ('r','p')
                  AND a.attnum>0 AND NOT a.attisdropped
                ORDER BY c.relname,a.attnum
            """)
            for table, column, typ, notnull, default in cur.fetchall():
                if not DYNAMIC_RE.match(table):
                    out["columns"][f"{table}.{column}"] = {
                        "type": typ, "not_null": bool(notnull), "default": default or None
                    }

            cur.execute("""
                SELECT c.relname, con.conname, con.contype,
                       pg_get_constraintdef(con.oid,true)
                FROM pg_constraint con
                JOIN pg_class c ON c.oid=con.conrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind IN ('r','p')
                ORDER BY c.relname,con.conname
            """)
            for table, name, typ, definition in cur.fetchall():
                if not DYNAMIC_RE.match(table):
                    out["constraints"][f"{table}.{name}"] = {"type": typ, "definition": definition}

            cur.execute("""
                SELECT t.relname, i.relname, pg_get_indexdef(i.oid)
                FROM pg_index x
                JOIN pg_class i ON i.oid=x.indexrelid
                JOIN pg_class t ON t.oid=x.indrelid
                JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE n.nspname='public' AND t.relkind IN ('r','p')
                ORDER BY t.relname,i.relname
            """)
            for table, name, definition in cur.fetchall():
                if not DYNAMIC_RE.match(table):
                    # Index names are part of the schema contract. Tablespace is not.
                    out["indexes"][f"{table}.{name}"] = {"definition": definition}
    return out


def migration_candidates(repo: Path, key: str) -> list[str]:
    tokens = [key, key.split(".", 1)[0]]
    if "." in key:
        tokens.insert(0, key.rsplit(".", 1)[-1])
    matches: list[str] = []
    for path in sorted((repo / "alembic" / "versions").glob("*.py")):
        text = path.read_text(errors="replace")
        if any(token and token in text for token in tokens):
            matches.append(path.name)
    return matches


def compare(live: dict[str, Any], replay: dict[str, Any], repo: Path) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    for section in ("tables", "columns", "constraints", "indexes"):
        keys = sorted(set(live[section]) | set(replay[section]))
        for key in keys:
            lv = live[section].get(key)
            rv = replay[section].get(key)
            if lv == rv:
                continue
            if lv is None:
                change = "missing_live"
            elif rv is None:
                change = "extra_live"
            else:
                change = "changed"
            candidates = migration_candidates(repo, key)
            differences.append({
                "section": section,
                "key": key,
                "change": change,
                "live": lv,
                "replay": rv,
                "responsible": candidates or ["DDL_HORS_ALEMBIC"],
            })
    return differences


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-dsn", required=True)
    parser.add_argument("--replay-dsn", required=True)
    parser.add_argument("--live-dump", type=Path, required=True)
    parser.add_argument("--replay-dump", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()

    for path in (args.live_dump, args.replay_dump):
        if not path.is_file() or path.stat().st_size == 0:
            print(f"G35 PRECONDITION FAIL dump_missing_or_empty={path}")
            return 2
    if safe_dsn(args.live_dsn) == safe_dsn(args.replay_dsn):
        print("G35 PRECONDITION FAIL live_and_replay_dsn_are_identical")
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    live = fetch_manifest(args.live_dsn)
    replay = fetch_manifest(args.replay_dsn)
    differences = compare(live, replay, args.repo)
    report = {
        "live_dsn": safe_dsn(args.live_dsn),
        "replay_dsn": safe_dsn(args.replay_dsn),
        "live_dump": str(args.live_dump),
        "live_dump_sha256": sha256(args.live_dump),
        "replay_dump": str(args.replay_dump),
        "replay_dump_sha256": sha256(args.replay_dump),
        "live_manifest": live,
        "replay_manifest": replay,
        "differences": differences,
    }
    report_path = args.output_dir / "g35-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(f"G35 live={safe_dsn(args.live_dsn)} replay={safe_dsn(args.replay_dsn)}")
    print(f"G35 live_dump_sha256={report['live_dump_sha256']}")
    print(f"G35 replay_dump_sha256={report['replay_dump_sha256']}")
    print(f"G35 dynamic_partitions_live={len(live['dynamic_partitions'])}")
    for key, value in sorted(live["dynamic_partitions"].items()):
        print(f"DYNAMIC_LIVE {key} parent={value['parent']}")
    print(f"G35 dynamic_partitions_replay={len(replay['dynamic_partitions'])}")
    for key, value in sorted(replay["dynamic_partitions"].items()):
        print(f"DYNAMIC_REPLAY {key} parent={value['parent']}")
    print(f"G35 structural_differences={len(differences)}")
    for item in differences:
        print("DIFF " + json.dumps(item, sort_keys=True, ensure_ascii=False))
    print(f"G35 report={report_path}")
    verdict = "PASS" if not differences else "FAIL"
    print(f"G35 VERDICT={verdict}")
    return 0 if not differences else 1


if __name__ == "__main__":
    raise SystemExit(main())
