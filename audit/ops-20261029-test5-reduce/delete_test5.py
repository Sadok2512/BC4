"""Suppression du projet Test_5 (d8d14aefa51f) via l'ORM.

Appelle la même logique que la route applicative DELETE /projects/{pid}
(`bc4-back/app/routes/projects.py:259 delete_project`) : advisory check
`active_job`, `db.delete(project)`, cascade FK DB.

Trace exhaustive :
- comptages par table (sélection sur `project_id = 'd8d14aefa51f'`)
  avant / après le `db.delete`, pour chaque table ayant une colonne
  `capture_id` ou `project_id` ;
- partitions `nmf_deep_<cap>` / `nmf_group_<cap>` du projet (listées
  avant, droppées après car le service standard ne les détruit pas) ;
- fichiers du volume source `/var/lib/bc4/nmf-source/d8d14aefa51f/`
  (listés avant, supprimés après — hors scope service pur).

Pas de SQL d'écriture manuel : uniquement SELECT pour les comptages,
`db.delete()` pour la cascade, et deux DROP TABLE idempotents + un
`shutil.rmtree` pour la cleanup. Pas de UPDATE / INSERT.

Usage dans bc4-api-1 :
  docker exec -e OPS_CONFIRM=yes bc4-api-1 \
    python /app/audit/ops-20261029-test5-reduce/delete_test5.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402
from app.services.import_jobs import active_job  # noqa: E402


PID = "d8d14aefa51f"
SOURCE_DIR = Path(f"/var/lib/bc4/nmf-source/{PID}")

TABLES = [
    "projects",
    "nmf_file",
    "nmf_capture",
    "nmf_cell_second",
    "nmf_event_light",
    "nmf_event_light_ext",
    "nmf_event_light_group",
    "nmf_event_light_native",
    "nmf_event_deep",
    "nmf_event_group",
    "nmf_event_pair",
    "stg_event",
    "stg_event_raw",
    "stg_measurement_raw",
    "measurement_points",
    "metric_sample",
    "nmf_metric_value",
    "range_violations",
    "rrc_observations",
    "signaling_procedure",
    "task_run",
    "superstream_member",
    "superstream",
    "param_occurrence",
    "nmf_import_jobs",
]


def counts(db, project_id: str) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for table in TABLES:
        if table == "projects":
            query = text("SELECT count(*) FROM projects WHERE id=:pid")
        else:
            query = text(f"SELECT count(*) FROM {table} WHERE project_id=:pid")
        try:
            result[table] = db.execute(query, {"pid": project_id}).scalar_one()
        except Exception as exc:
            result[table] = None  # pragma: no cover - log and continue
            print(f"COUNT_WARN {table}: {type(exc).__name__}: {exc}", file=sys.stderr)
            db.rollback()
    return result


def partitions(db, project_id: str) -> list[str]:
    rows = db.execute(
        text(
            """
            SELECT c.capture_id
            FROM nmf_capture c
            WHERE c.project_id = :pid
            ORDER BY c.capture_id
            """
        ),
        {"pid": project_id},
    ).all()
    return [row[0] for row in rows]


def source_files() -> list[tuple[str, int]]:
    if not SOURCE_DIR.is_dir():
        return []
    return sorted(
        (entry.name, entry.stat().st_size)
        for entry in SOURCE_DIR.iterdir()
    )


def main() -> int:
    if os.environ.get("OPS_CONFIRM") != "yes":
        print("REFUSE: set OPS_CONFIRM=yes to run", file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    with SessionLocal() as db:
        project = db.get(Project, PID)
        if not project:
            print(f"REFUSE: project {PID} not found", file=sys.stderr)
            return 3
        if active_job(db, PID):
            print(f"REFUSE: active import job for {PID}", file=sys.stderr)
            return 4

        print(f"== BEFORE project={PID} name={project.name!r} ==")
        before_counts = counts(db, PID)
        for tbl, n in before_counts.items():
            print(f"  {tbl:30s} = {n}")

        before_captures = partitions(db, PID)
        print(f"\n== partitions (24 captures expected) ==")
        for cap in before_captures:
            print(f"  nmf_deep_{cap}  nmf_group_{cap}")

        before_files = source_files()
        total_bytes = sum(size for _, size in before_files)
        print(f"\n== source files in {SOURCE_DIR} ({total_bytes:,} bytes) ==")
        for name, size in before_files:
            print(f"  {name}  {size:>12,} B")

        # ----- SERVICE CALL (ORM, mirrors app/routes/projects.py:259) -----
        print("\n== calling service: db.delete(project) ... ==", flush=True)
        db.delete(project)
        db.commit()
        print("   service OK, cascade FK applied")

        # ----- AFTER service -----
        print(f"\n== AFTER service (counts should be 0 for pid={PID}) ==")
        after_counts = counts(db, PID)
        anomalies = []
        for tbl, n in after_counts.items():
            print(f"  {tbl:30s} = {n}")
            if n is not None and n != 0:
                anomalies.append((tbl, n))

        # ----- Cleanup partitions (service does not drop them) -----
        print(f"\n== cleanup partitions ({len(before_captures)} captures) ==")
        for cap in before_captures:
            db.execute(text(f'DROP TABLE IF EXISTS "nmf_deep_{cap}"'))
            db.execute(text(f'DROP TABLE IF EXISTS "nmf_group_{cap}"'))
        db.commit()
        print("   DROP TABLE IF EXISTS done for 2 x 24 partitions")

        # ----- Cleanup source dir (service does not rm) -----
        if SOURCE_DIR.is_dir():
            print(f"\n== rmtree {SOURCE_DIR} ==")
            shutil.rmtree(SOURCE_DIR)
            print("   rmtree OK")

    duration = time.perf_counter() - t0

    print(f"\n== SUMMARY ==")
    print(f"  elapsed_s           = {duration:.2f}")
    print(f"  rows_before_total   = {sum(v or 0 for v in before_counts.values()):,}")
    print(f"  rows_after_total    = {sum(v or 0 for v in after_counts.values()):,}")
    print(f"  partitions_dropped  = {2 * len(before_captures)}")
    print(f"  source_bytes_freed  = {total_bytes:,}")
    print(f"  anomalies           = {anomalies if anomalies else 'none'}")

    report = {
        "project_id": PID,
        "project_name": "Test_5",
        "before_counts": before_counts,
        "after_counts": after_counts,
        "captures": before_captures,
        "source_files_before": [{"name": n, "size": s} for n, s in before_files],
        "elapsed_s": duration,
        "anomalies": anomalies,
    }
    out = Path("/app/audit/ops-20261029-test5-reduce/delete_test5.report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"\n   report → {out}")

    return 0 if not anomalies else 1


if __name__ == "__main__":
    sys.exit(main())
