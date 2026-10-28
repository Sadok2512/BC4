"""G42: integrity and resource guard for disposable parallel imports."""
from __future__ import annotations

import hashlib
import cProfile
import io
import os
import pstats
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import UploadFile
from sqlalchemy import text

from app.db import SessionLocal
from app.models import NmfImportJob, Project
from app.services.import_jobs import enqueue
from app.services.import_worker import run_job


def fail(reason: str, code: int = 1) -> None:
    print(f"G42 VERDICT=FAIL reason={reason}")
    raise SystemExit(code)


def descendants(pid: int) -> set[int]:
    found: set[int] = set(); frontier = {pid}
    while frontier:
        parent = frontier.pop()
        for stat in Path("/proc").glob("[0-9]*/stat"):
            try:
                values = stat.read_text().split(); child, ppid = int(values[0]), int(values[3])
            except (OSError, ValueError, IndexError):
                continue
            if ppid == parent and child not in found:
                found.add(child); frontier.add(child)
    return found


def monitor(stop: threading.Event, observed: dict[str, float], job_id: str) -> None:
    while not stop.wait(0.2):
        children = descendants(os.getpid())
        observed["parallel_max"] = max(observed["parallel_max"], len(children))
        rss = 0
        for pid in children | {os.getpid()}:
            try:
                line = next(x for x in Path(f"/proc/{pid}/status").read_text().splitlines()
                    if x.startswith("VmRSS:"))
                rss += int(line.split()[1])
            except (OSError, StopIteration):
                pass
        observed["rss_peak_kb"] = max(observed["rss_peak_kb"], rss)
        with SessionLocal() as db:
            files_running = db.execute(text("""
                SELECT count(*) FROM nmf_import_jobs j,
                  LATERAL json_array_elements(j.files) entry
                WHERE j.id=:job_id AND entry->>'status'='decoding'
            """), {"job_id": job_id}).scalar_one()
            observed["files_running_max"] = max(
                observed["files_running_max"], files_running
            )
            row = db.execute(text("""
                SELECT coalesce(extract(epoch FROM now()-state_change),0), query
                FROM pg_stat_activity
                WHERE datname=current_database() AND state='idle in transaction'
                ORDER BY state_change LIMIT 1
            """)).first()
            age = float(row[0]) if row else 0.0
            if age > observed["idle_max_s"]:
                observed["idle_max_s"] = age
                observed["idle_query"] = row[1] if row else ""


def fingerprint(db, project_id: str, table: str, seq: str = "seq") -> tuple[str, int]:
    rows = db.execute(text(
        f"SELECT project_id,capture_id,{seq} AS seq FROM {table} "
        "WHERE project_id=:pid ORDER BY project_id,capture_id,seq"
    ), {"pid": project_id}).all()
    db.rollback()
    digest = hashlib.sha256()
    for row in rows:
        digest.update(("\x1f".join(map(str, row)) + "\n").encode())
    return digest.hexdigest(), len(rows)


def main() -> None:
    if os.environ.get("G42_EPHEMERAL_DB") != "YES":
        fail("G42_EPHEMERAL_DB_must_equal_YES", 2)
    paths = [Path(value) for value in os.environ.get("G42_NMF_PATHS", "").split("::") if value]
    if not paths or any(not path.is_file() for path in paths):
        fail("G42_NMF_PATHS_missing_or_invalid", 2)
    level = os.environ.get("G42_LEVEL", "light")
    if level not in ("light", "deep"):
        fail("G42_LEVEL_invalid", 2)

    with SessionLocal() as db:
        database = db.execute(text("SELECT current_database()" )).scalar_one()
        if database == "bc4": fail("live_database_forbidden", 2)
        owner = db.execute(text(
            "SELECT id FROM app_user ORDER BY created_at,id LIMIT 1"
        )).scalar_one()
        project_id = "g42-" + uuid.uuid4().hex[:12]
        db.add(Project(id=project_id, owner_id=owner, visibility="private",
            name="TEST-G42 parallel import", geography="", center_lng=0,
            center_lat=0, operators=[], technologies=[], services=[], bands=[],
            departements=[], period_start="", period_end="", captures=0,
            imported_at="", status="processing", status_ingest="importing",
            parse_decode_level=level, parse_binning_mode="temporal",
            parse_temporal_resolution="native", parse_spatial_bin_m=None))
        db.commit()
        uploads = [UploadFile(filename=path.name, file=path.open("rb")) for path in paths]
        job = enqueue(db, project_id, uploads)
        job_id = job.id
        corrupt_index = os.environ.get("G42_CORRUPT_INDEX")
        if corrupt_index is not None:
            index = int(corrupt_index)
            queued_path = Path(job.files[index]["path"])
            with queued_path.open("r+b") as stream:
                stream.seek(max(0, queued_path.stat().st_size // 2))
                original = stream.read(1)
                if not original:
                    fail("G42_corrupt_target_empty", 2)
                stream.seek(-1, os.SEEK_CUR)
                stream.write(bytes((original[0] ^ 0xFF,)))
            print(f"G42 corrupted_queue_index={index} file={job.files[index]['filename']}")

    observed = {"parallel_max": 0.0, "files_running_max": 0.0, "rss_peak_kb": 0.0,
        "idle_max_s": 0.0, "idle_query": ""}
    monitor_stop = threading.Event()
    thread = threading.Thread(
        target=monitor, args=(monitor_stop, observed, job_id), daemon=True
    )
    thread.start(); started = time.perf_counter()
    profiler = cProfile.Profile() if os.environ.get("G42_PROFILE") == "YES" else None
    try:
        with SessionLocal() as db:
            if profiler:
                profiler.enable()
            run_job(db, db.get(NmfImportJob, job_id))
            if profiler:
                profiler.disable()
    finally:
        elapsed = time.perf_counter() - started
        monitor_stop.set(); thread.join()

    if profiler:
        stream = io.StringIO()
        raw_stats = pstats.Stats(profiler)
        display_stats = pstats.Stats(
            profiler, stream=stream
        ).strip_dirs().sort_stats("cumulative")
        display_stats.print_stats(20)
        database_tottime = sum(
            values[2] for func, values in raw_stats.stats.items()
            if any(term in " ".join(map(str, func)).lower()
                   for term in ("psycopg", "sqlalchemy", "select.poll", "cursor"))
        )
        total = raw_stats.total_tt
        database_pct = 100.0 * database_tottime / total if total else 0.0
        print(f"PROFILE PARENT total_s={total:.3f} postgresql_exclusive_s={database_tottime:.3f} "
              f"postgresql_pct={database_pct:.2f} python_other_pct={100.0-database_pct:.2f}")
        from app.services.import_worker import _profile_stages
        stages = _profile_stages(raw_stats)
        print("PROFILE PARENT STAGES " + " ".join(
            f"{name}={seconds:.3f}s({100.0 * seconds / total if total else 0.0:.2f}%)"
            for name, seconds in stages.items()
        ))
        print("PROFILE PARENT TOP20\n" + stream.getvalue())

    with SessionLocal() as db:
        job = db.get(NmfImportJob, job_id)
        statuses = [entry["status"] for entry in job.files]
        nmf_files, distinct_sha = db.execute(text(
            "SELECT count(*),count(DISTINCT sha256) FROM nmf_file WHERE project_id=:pid"
        ), {"pid": project_id}).one()
        fingerprints = {
            "stg_event_raw": fingerprint(db, project_id, "stg_event_raw"),
            "nmf_event_light": fingerprint(db, project_id, "nmf_event_light"),
            "nmf_event_deep": fingerprint(db, project_id, "nmf_event_deep"),
            "nmf_cell_second": fingerprint(db, project_id, "nmf_cell_second", "seq_first"),
        }
        duplicate_files = db.execute(text("""
            SELECT count(*) FROM (
              SELECT sha256 FROM nmf_file WHERE project_id=:pid
              GROUP BY sha256 HAVING count(*)>1
            ) duplicate
        """), {"pid": project_id}).scalar_one()

    print(f"G42 database={database} project_id={project_id} job_id={job_id}")
    print(f"G42 elapsed_s={elapsed:.3f} files_running_max={int(observed['files_running_max'])} "
          f"child_processes_max={int(observed['parallel_max'])} "
          f"rss_peak_kb={int(observed['rss_peak_kb'])} idle_in_transaction_max_s={observed['idle_max_s']:.3f}")
    print(f"G42 idle_query={observed['idle_query']}")
    print(f"G42 statuses={statuses} nmf_files={nmf_files} distinct_sha={distinct_sha} "
          f"duplicate_files={duplicate_files}")
    for table, values in fingerprints.items():
        print(f"G42 table={table} sha256={values[0]} rows={values[1]}")

    expected_errors = int(os.environ.get("G42_EXPECT_ERRORS", "0"))
    idle_limit = float(os.environ.get("G42_IDLE_MAX_S", "1.0"))
    ok = (statuses.count("error") == expected_errors and
          all(status in ("done", "error") for status in statuses) and
          nmf_files == distinct_sha and duplicate_files == 0 and
          observed["idle_max_s"] <= idle_limit)
    print(f"G42 VERDICT={'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
