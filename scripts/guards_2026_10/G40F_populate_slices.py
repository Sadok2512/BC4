#!/usr/bin/env python3
"""G40F — preuve jetable : commits bornés, reprise et parité monolithique."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def fail(reason: str, code: int = 1) -> None:
    print(f"G40F VERDICT=FAIL reason={reason}")
    raise SystemExit(code)


dsn = os.environ.get("BC4_DSN", "")
parsed = urlparse(dsn.replace("postgresql+psycopg", "postgresql", 1))
ephemeral_host = (parsed.hostname or "").startswith("bc1-")
non_live_port = parsed.port not in (None, 5432)
if (
    os.environ.get("G40_EPHEMERAL_DB") != "YES"
    or not (ephemeral_host or non_live_port)
    or parsed.path.rstrip("/") in ("", "/bc4")
):
    fail("unsafe_or_missing_ephemeral_dsn", 2)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Project  # noqa: E402
import app.measure.populate as mp_module  # noqa: E402
from app.measure.populate import populate_measurement_points  # noqa: E402
from app.services.populate_chain import (  # noqa: E402
    _run_populate_chain,
    run_populate_chain,
)
from app.services.populate_measurements import populate_measurements  # noqa: E402


def fingerprint(pid: str) -> tuple[str, int, int]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT project_id, capture_id, seq
            FROM measurement_points
            WHERE project_id=:pid
            ORDER BY project_id, capture_id, seq
        """), {"pid": pid}).all()
        duplicates = conn.execute(text("""
            SELECT count(*) FROM (
              SELECT project_id,capture_id,seq,count(*)
              FROM measurement_points WHERE project_id=:pid
              GROUP BY project_id,capture_id,seq HAVING count(*)>1
            ) d
        """), {"pid": pid}).scalar_one()
    digest = hashlib.sha256()
    for row in rows:
        digest.update(f"{row[0]}\0{row[1]}\0{row[2]}\n".encode())
    return digest.hexdigest(), len(rows), int(duplicates)


with engine.connect() as conn:
    pid = conn.execute(text("""
        SELECT id FROM projects
        WHERE name='TEST-G40 immutable import snapshot'
        ORDER BY created_at DESC LIMIT 1
    """)).scalar_one_or_none()
    timeout = conn.execute(text("SHOW idle_in_transaction_session_timeout")).scalar_one()
    n_files = conn.execute(
        text("SELECT count(*) FROM nmf_file WHERE project_id=:pid AND status='done'"),
        {"pid": pid},
    ).scalar_one() if pid else 0
if pid is None or n_files < 3:
    fail(f"multi_nmf_project_missing:project={pid}:done_files={n_files}", 2)

monitor_engine = create_engine(dsn, future=True)
stop = threading.Event()
observed = {"max_s": 0.0, "query": "none"}


def monitor() -> None:
    while not stop.wait(0.2):
        with monitor_engine.connect() as conn:
            row = conn.execute(text("""
                SELECT extract(epoch FROM now()-state_change), left(query,160)
                FROM pg_stat_activity
                WHERE datname=current_database() AND state='idle in transaction'
                  AND pid<>pg_backend_pid()
                ORDER BY state_change LIMIT 1
            """)).first()
        if row and float(row[0]) > observed["max_s"]:
            observed["max_s"] = float(row[0])
            observed["query"] = row[1]


thread = threading.Thread(target=monitor, daemon=True)
thread.start()
try:
    with SessionLocal() as db:
        project = db.get(Project, pid)
        report = run_populate_chain(db, project)
finally:
    stop.set()
    thread.join(timeout=2)
    monitor_engine.dispose()

sliced = fingerprint(pid)

# Référence : chaîne complète A..F enfermée volontairement dans une seule
# transaction extérieure ; ses commits internes deviennent des savepoints.
with engine.begin() as connection:
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        project = db.get(Project, pid)
        _run_populate_chain(db, project)
monolithic = fingerprint(pid)

# Référence A+B séparée pour la preuve de reprise injectée ci-dessous.
with SessionLocal() as db:
    populate_measurements(db, pid, purge=True)
    populate_measurement_points(db, pid, purge=False)
ab_reference = fingerprint(pid)

# Injection d'arrêt juste après la première tranche réellement commitée, puis
# reprise sans repurge de B : l'UPSERT déterministe doit converger sans doublon.
with SessionLocal() as db:
    populate_measurements(db, pid, purge=True)
original_chunks = mp_module._iter_raw_event_chunks


def interrupted_chunks(*args, **kwargs):
    chunks = original_chunks(*args, **kwargs)
    yield next(chunks)
    raise RuntimeError("G40F injected interruption after committed slice")


mp_module._iter_raw_event_chunks = interrupted_chunks
try:
    with SessionLocal() as db:
        try:
            populate_measurement_points(db, pid, purge=False)
        except RuntimeError as exc:
            if "injected interruption" not in str(exc):
                raise
        else:
            fail("fault_injection_did_not_fire")
finally:
    mp_module._iter_raw_event_chunks = original_chunks

with SessionLocal() as db:
    populate_measurement_points(db, pid, purge=False)
resumed = fingerprint(pid)

ok = (
    timeout == "5min"
    and sliced == monolithic
    and ab_reference == resumed
    and sliced[2] == monolithic[2] == ab_reference[2] == resumed[2] == 0
    and observed["max_s"] <= 5.0
    and int(report["n_points"]) == sliced[1]
)
print(f"G40F project_id={pid} done_files={n_files}")
print(f"G40F timeout={timeout} idle_in_transaction_max_s={observed['max_s']:.3f}")
print(f"G40F idle_query={observed['query']}")
print(f"G40F sliced_sha256={sliced[0]} rows={sliced[1]} duplicates={sliced[2]}")
print(f"G40F monolithic_sha256={monolithic[0]} rows={monolithic[1]} duplicates={monolithic[2]}")
print(f"G40F ab_reference_sha256={ab_reference[0]} rows={ab_reference[1]} duplicates={ab_reference[2]}")
print(f"G40F resumed_sha256={resumed[0]} rows={resumed[1]} duplicates={resumed[2]}")
print(f"G40F complete_chain_n_points={report['n_points']}")
print(f"G40F VERDICT={'PASS' if ok else 'FAIL'}")
raise SystemExit(0 if ok else 1)
