#!/usr/bin/env python3
"""G40 — an import job keeps its enqueue-time parsing contract.

The guard uses a disposable PostgreSQL database only. It creates its project
through the application API, enqueues a real NMF through the upload API, then
changes the project defaults before running the real import worker. The capture
snapshot must equal the job snapshot, never the changed project defaults.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def fail(message: str, exit_code: int = 1) -> None:
    print(f"G40 VERDICT=FAIL reason={message}")
    raise SystemExit(exit_code)


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
raw_paths = os.environ.get("G40_NMF_PATHS")
sources = [Path(item) for item in raw_paths.split(os.pathsep)] if raw_paths else [
    Path(os.environ.get("G40_NMF_PATH", ""))
]
if not sources or any(not source.is_file() for source in sources):
    fail("G40_NMF_PATH_missing", 2)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import NmfImportJob  # noqa: E402
from app.services.import_worker import run_job  # noqa: E402

engine = create_engine(dsn, future=True)
with engine.connect() as conn:
    user = conn.execute(text("SELECT email FROM app_user WHERE role='admin' AND active ORDER BY email LIMIT 1")).scalar()
if user is None:
    fail("admin_fixture_absent", 2)
password = os.environ.get("G40_ADMIN_PASSWORD", "")
if not password:
    fail("G40_ADMIN_PASSWORD_missing", 2)

with TestClient(app, raise_server_exceptions=False) as client:
    auth = client.post('/auth/login', json={'email': user, 'password': password})
    if auth.status_code != 200:
        fail(f"login_http_{auth.status_code}", 2)
    headers = {'Authorization': f"Bearer {auth.json()['token']}"}
    created = client.post('/projects', headers=headers, json={
        'name': 'TEST-G40 immutable import snapshot',
        'visibility': 'private',
        'parse_decode_level': 'light',
        'parse_binning_mode': 'temporal',
        'parse_temporal_resolution': '10ms',
        'parse_spatial_bin_m': None,
    })
    if created.status_code != 201:
        fail(f"create_http_{created.status_code}")
    project_id = created.json()['id']
    streams = [source.open('rb') for source in sources]
    try:
        queued = client.post(
            f'/projects/{project_id}/nmf', headers=headers,
            files=[
                ('files', (source.name, stream, 'application/octet-stream'))
                for source, stream in zip(sources, streams)
            ],
        )
    finally:
        for stream in streams:
            stream.close()
    if queued.status_code != 202:
        fail(f"queue_http_{queued.status_code}")
    job_id = queued.json()['id']
    changed = client.patch(f'/projects/{project_id}/parsing', headers=headers, json={
        'parse_decode_level': 'deep',
        'parse_binning_mode': 'spatial',
        'parse_temporal_resolution': None,
        'parse_spatial_bin_m': 50,
    })
    if changed.status_code != 200:
        fail(f"patch_http_{changed.status_code}")

with SessionLocal() as db:
    job = db.get(NmfImportJob, job_id)
    run_job(db, job)

with engine.connect() as conn:
    job = conn.execute(text("""SELECT decode_level,binning_mode,temporal_resolution,spatial_bin_m,
        aggregation_contract_version,decoder_version,status FROM nmf_import_jobs WHERE id=:id"""), {'id': job_id}).mappings().one()
    captures = conn.execute(text("""SELECT decode_level,binning_mode,temporal_resolution,spatial_bin_m,
        aggregation_contract_version,decoder_version FROM nmf_capture
        WHERE project_id=:pid ORDER BY capture_id"""), {'pid': project_id}).mappings().all()
    project = conn.execute(text("""SELECT parse_decode_level,parse_binning_mode,parse_temporal_resolution,
        parse_spatial_bin_m FROM projects WHERE id=:pid"""), {'pid': project_id}).mappings().one()

snapshot = {key: job[key] for key in (
    'decode_level', 'binning_mode', 'temporal_resolution', 'spatial_bin_m',
    'aggregation_contract_version', 'decoder_version',
)}
print(f"G40 project_id={project_id} job_id={job_id}")
print(f"G40 project_current={dict(project)}")
print(f"G40 job_snapshot={snapshot}")
print(f"G40 capture_count={len(captures)}")
print(f"G40 capture_snapshots={[dict(row) for row in captures]}")
ok = (
    job['status'] == 'done'
    and len(captures) > 0
    and all(dict(row) == snapshot for row in captures)
    and project['parse_decode_level'] == 'deep'
    and project['parse_binning_mode'] == 'spatial'
)
print(f"G40 VERDICT={'PASS' if ok else 'FAIL'}")
raise SystemExit(0 if ok else 1)
