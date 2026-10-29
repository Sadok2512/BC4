#!/usr/bin/env python3
"""G47 — suppression exhaustive et isolation d'une capture.

Base PostgreSQL jetable obligatoire. Le garde importe par les routes publiques
les deux petits fichiers witness explicitement fournis dans A, puis le fichier
de la capture cible dans B. Il compare des empreintes de CONTENU, jamais des
timestamps, pour la capture conservée et pour la capture homonyme de B.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse


def fail(message: str, code: int = 1) -> int:
    print(f"G47 VERDICT=FAIL reason={message}", file=sys.stderr)
    return code


dsn = os.environ.get("BC4_DSN", "")
if os.environ.get("G47_EPHEMERAL_DB") != "YES":
    raise SystemExit(fail("G47_EPHEMERAL_DB=YES is required", 2))
if not dsn:
    raise SystemExit(fail("BC4_DSN is required", 2))
parsed = urlparse(dsn.replace("postgresql+psycopg", "postgresql", 1))
db_name = parsed.path.lstrip("/")
if parsed.port in (None, 5432) or not db_name.startswith("bc1_"):
    raise SystemExit(
        fail(
            f"refusing non-disposable DSN host={parsed.hostname} port={parsed.port} db={db_name}",
            2,
        )
    )

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import NmfImportJob  # noqa: E402
from app.services.auth import hash_password  # noqa: E402
from app.services.capture_delete import ALL_CAPTURE_DATA, capture_counts  # noqa: E402
from app.services.import_worker import run_job  # noqa: E402


USER_ID = "TEST-G47-OWNER"
EMAIL = "test-g47-owner@example.invalid"
PASSWORD = "TEST-G47-only-9!"
WITNESS_DIR = Path(os.environ.get("G47_WITNESS_DIR", "/home/devmat/BC4/artifacts/witness-nmf"))
WITNESS_NAMES = (
    "ikea_26Jun10_172354.2.nmf",
    "ikea_26Jun10_172354.6.nmf",
)
engine = create_engine(dsn, future=True)


def seed_user() -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM projects WHERE owner_id=:id"), {"id": USER_ID})
        connection.execute(text("DELETE FROM app_user WHERE email=:email"), {"email": EMAIL})
        connection.execute(
            text("""INSERT INTO app_user(id,email,password_hash,role,active,created_at)
                    VALUES (:id,:email,:password_hash,'admin',true,now())"""),
            {"id": USER_ID, "email": EMAIL, "password_hash": hash_password(PASSWORD)},
        )


def token(client: TestClient) -> str:
    response = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if response.status_code != 200:
        raise RuntimeError(f"login_http_{response.status_code}:{response.text[:300]}")
    return response.json()["token"]


def create_project(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post(
        "/projects",
        headers=headers,
        json={
            "name": name,
            "visibility": "private",
            "parse_decode_level": "light",
            "parse_binning_mode": "temporal",
            "parse_temporal_resolution": "native",
            "parse_spatial_bin_m": None,
        },
    )
    if response.status_code != 201:
        raise RuntimeError(f"create_project_http_{response.status_code}:{response.text[:300]}")
    return response.json()["id"]


def import_files(
    client: TestClient, headers: dict[str, str], project_id: str, files: list[Path]
) -> None:
    streams = [path.open("rb") for path in files]
    try:
        response = client.post(
            f"/projects/{project_id}/nmf",
            headers=headers,
            files=[("files", (path.name, stream, "application/octet-stream")) for path, stream in zip(files, streams)],
        )
    finally:
        for stream in streams:
            stream.close()
    if response.status_code != 202:
        raise RuntimeError(f"upload_http_{response.status_code}:{response.text[:500]}")
    job_id = response.json()["id"]
    with SessionLocal() as db:
        job = db.get(NmfImportJob, job_id)
        if job is None:
            raise RuntimeError("import_job_not_persisted")
        run_job(db, job)
        db.refresh(job)
        if job.status != "done":
            raise RuntimeError(f"import_job_status={job.status}:error={job.error_msg}")


def capture_ids(project_id: str) -> list[str]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text("""SELECT capture_id FROM nmf_capture
                        WHERE project_id=:pid ORDER BY capture_id"""),
                {"pid": project_id},
            ).scalars()
        )


def _rows(connection, table: str, project_id: str, capture_id: str) -> list[dict]:
    params = {"pid": project_id, "cap": capture_id}
    if table == "param_occurrence":
        query = """SELECT to_jsonb(p) AS row FROM param_occurrence p
                   JOIN stg_event e ON e.id=p.stg_event_id
                   WHERE p.project_id=:pid AND e.project_id=:pid AND e.capture_id=:cap"""
    elif table == "task_sample":
        query = """SELECT to_jsonb(s) AS row FROM task_sample s
                   JOIN task_run r ON r.id=s.task_id
                   WHERE r.project_id=:pid AND r.capture_id=:cap"""
    elif table == "nmf_file":
        query = """SELECT to_jsonb(f) AS row FROM nmf_file f
                   JOIN nmf_capture c ON c.nmf_file_id=f.id
                   WHERE c.project_id=:pid AND c.capture_id=:cap"""
    else:
        query = f"SELECT to_jsonb(t) AS row FROM {table} t WHERE project_id=:pid AND capture_id=:cap"
    return [dict(row[0]) for row in connection.execute(text(query), params)]


def fingerprint(project_id: str, capture_id: str, *, include_project: bool = False) -> dict:
    tables = list(ALL_CAPTURE_DATA) + ["task_sample", "nmf_file"]
    content: dict[str, dict[str, object]] = {}
    with engine.connect() as connection:
        for table in tables:
            rows = _rows(connection, table, project_id, capture_id)
            encoded = [json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) for row in rows]
            digest = hashlib.sha256("\n".join(sorted(encoded)).encode()).hexdigest()
            content[table] = {"count": len(rows), "sha256": digest}
        if include_project:
            row = connection.execute(
                text("SELECT to_jsonb(p) FROM projects p WHERE id=:pid"), {"pid": project_id}
            ).scalar_one()
            encoded = json.dumps(dict(row), sort_keys=True, separators=(",", ":"), default=str)
            content["projects"] = {"count": 1, "sha256": hashlib.sha256(encoded.encode()).hexdigest()}
    return content


def main() -> int:
    witnesses = [WITNESS_DIR / name for name in WITNESS_NAMES]
    missing = [str(path) for path in witnesses if not path.is_file()]
    if missing:
        return fail(f"missing_witnesses={missing}", 2)
    print("G47 COMMAND source_files=" + ",".join(str(path) for path in witnesses))

    try:
        seed_user()
        with TestClient(app, raise_server_exceptions=False) as client:
            auth = {"Authorization": f"Bearer {token(client)}"}
            project_a = create_project(client, auth, "TEST-G47 two captures")
            project_b = create_project(client, auth, "TEST-G47 shared capture")
            import_files(client, auth, project_a, witnesses)

            captures_a = capture_ids(project_a)
            if len(captures_a) != 2:
                return fail(f"project_a_capture_count={len(captures_a)} expected=2")

            # Retrouve par le CONTENU DB quel fichier porte chaque capture ;
            # aucune déduction depuis le nom du witness.
            with engine.connect() as connection:
                target = connection.execute(
                    text("""SELECT c.capture_id,f.filename FROM nmf_capture c
                            JOIN nmf_file f ON f.id=c.nmf_file_id
                            WHERE c.project_id=:pid
                            ORDER BY f.size_bytes,c.capture_id LIMIT 1"""),
                    {"pid": project_a},
                ).mappings().one()
            shared_path = next((path for path in witnesses if path.name == target["filename"]), None)
            if shared_path is None:
                return fail(f"source_not_found_for_db_filename={target['filename']}")
            target_capture = str(target["capture_id"])
            import_files(client, auth, project_b, [shared_path])
            captures_b = capture_ids(project_b)
            if captures_b != [target_capture]:
                return fail(f"shared_capture_mismatch a={target_capture} b={captures_b}")

            kept = [capture_id for capture_id in captures_a if capture_id != target_capture]
            before_kept = {capture_id: fingerprint(project_a, capture_id) for capture_id in kept}
            before_shared = fingerprint(project_b, target_capture, include_project=True)

            response = client.delete(
                f"/projects/{project_a}/captures/{target_capture}",
                headers=auth,
                params={"reason": "TEST-G47 exhaustive capture deletion"},
            )
            if response.status_code != 204:
                return fail(f"delete_http_{response.status_code}:{response.text[:500]}")

        with SessionLocal() as db:
            deleted_counts = capture_counts(db, project_a, target_capture)
        residual = {table: count for table, count in deleted_counts.items() if count}
        if residual:
            return fail(f"residual_rows={residual}")
        after_kept = {capture_id: fingerprint(project_a, capture_id) for capture_id in kept}
        after_shared = fingerprint(project_b, target_capture, include_project=True)
        if after_kept != before_kept:
            changed = {
                capture_id: [
                    table
                    for table in before_kept[capture_id]
                    if before_kept[capture_id][table] != after_kept[capture_id][table]
                ]
                for capture_id in kept
                if before_kept[capture_id] != after_kept[capture_id]
            }
            print("G47 KEPT_FINGERPRINT_DELTA " + json.dumps(changed, sort_keys=True))
            return fail("kept_capture_fingerprint_changed")
        if after_shared != before_shared:
            changed = [
                table
                for table in before_shared
                if before_shared[table] != after_shared[table]
            ]
            print("G47 SHARED_FINGERPRINT_DELTA " + json.dumps(changed))
            return fail("other_project_fingerprint_changed")
        if capture_ids(project_a) != kept:
            return fail(f"project_a_remaining={capture_ids(project_a)} expected={kept}")
        if capture_ids(project_b) != [target_capture]:
            return fail("other_project_capture_missing")

        print(
            "G47 COUNTS "
            + json.dumps(
                {
                    "project_a_before": len(captures_a),
                    "project_a_after": len(capture_ids(project_a)),
                    "project_b_after": len(capture_ids(project_b)),
                    "deleted_table_counts": deleted_counts,
                },
                sort_keys=True,
            )
        )
        print("G47 VERDICT=PASS")
        return 0
    except Exception as exc:
        return fail(f"unexpected:{exc!r}")


if __name__ == "__main__":
    raise SystemExit(main())
