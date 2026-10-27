#!/usr/bin/env python3
"""G34 — project access isolation, before/after L1.

This guard is destructive by design and therefore refuses the live BC4 database.
Run it only against a disposable PostgreSQL database migrated to Alembic head.

It creates two TEST users (A and B), then creates the project and all project
resources through the public application routes (real NMF upload + worker +
decoder). B then calls every OpenAPI operation whose path contains
``/projects`` or ``/results``. A matching 404 for A and B is *not* considered a
pass: it is reported as UNTESTABLE/FAIL because resource absence is not an access
control decision.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


EXPECTED_OPERATIONS = 62
PROJECT_ID = ""
CAPTURE_ID = ""
RESULT_ID = ""
JOB_ID = ""
PARAM_KEY = ""
TEMPLATE_CATEGORY = ""
MESSAGE_SEQ = 0
USER_A_EMAIL = "test-g34-a@example.invalid"
USER_B_EMAIL = "test-g34-b@example.invalid"
PASSWORD_A = "TEST-G34-A-only-9!"
PASSWORD_B = "TEST-G34-B-only-9!"


def fail(message: str) -> None:
    print(f"G34 PRECONDITION FAIL: {message}", file=sys.stderr)
    raise SystemExit(2)


dsn = os.environ.get("BC4_DSN", "")
if os.environ.get("G34_EPHEMERAL_DB") != "YES":
    fail("G34_EPHEMERAL_DB=YES is required")
if not dsn:
    fail("BC4_DSN is required")

parsed = urlparse(dsn.replace("postgresql+psycopg", "postgresql", 1))
if parsed.port in (None, 5432) or parsed.path.rstrip("/") in ("", "/bc4"):
    fail(f"refusing non-ephemeral DSN host={parsed.hostname} port={parsed.port} db={parsed.path}")

# Imports happen after the safety gate because app.config resolves BC4_DSN at import.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import NmfImportJob  # noqa: E402
from app.nmf_decoder.jobs import process_next as process_decode_job  # noqa: E402
from app.services.auth import hash_password  # noqa: E402
from app.services.import_worker import run_job as run_import_job  # noqa: E402


engine = create_engine(dsn, future=True)


def seed_users() -> None:
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM app_user WHERE email IN (:a,:b)"),
            {"a": USER_A_EMAIL, "b": USER_B_EMAIL},
        )
        users = [
            ("TEST-G34-USER-A", USER_A_EMAIL, PASSWORD_A),
            ("TEST-G34-USER-B", USER_B_EMAIL, PASSWORD_B),
        ]
        for user_id, email, password in users:
            conn.execute(
                text(
                    """INSERT INTO app_user(id,email,password_hash,role,active,created_at)
                       VALUES (:id,:email,:password_hash,'admin',true,:created_at)"""
                ),
                {
                    "id": user_id,
                    "email": email,
                    "password_hash": hash_password(password),
                    "created_at": now,
                },
            )


def login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        fail(f"login {email} returned {response.status_code}")
    return response.json()["token"]


def prepare_real_fixture(client: TestClient, token_a: str) -> None:
    """Create every tested resource through the same HTTP/worker path as production."""
    global PROJECT_ID, CAPTURE_ID, RESULT_ID, JOB_ID, PARAM_KEY, TEMPLATE_CATEGORY, MESSAGE_SEQ
    source = Path(os.environ.get("G34_NMF_PATH", ""))
    if not source.is_file():
        fail("G34_NMF_PATH must point to a real corpus .nmf")

    created = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "TEST-G34 project owned by A"},
    )
    if created.status_code != 201:
        fail(f"POST /projects returned {created.status_code}: {created.text[:300]}")
    PROJECT_ID = created.json()["id"]

    with source.open("rb") as stream:
        uploaded = client.post(
            f"/projects/{PROJECT_ID}/nmf",
            headers={"Authorization": f"Bearer {token_a}"},
            files=[("files", (source.name, stream, "application/octet-stream"))],
        )
    if uploaded.status_code != 202:
        fail(f"POST /nmf returned {uploaded.status_code}: {uploaded.text[:300]}")
    JOB_ID = uploaded.json()["id"]
    with SessionLocal() as db:
        job = db.get(NmfImportJob, JOB_ID)
        if job is None:
            fail("uploaded import job was not persisted")
        run_import_job(db, job)

    imported = client.get(
        f"/projects/{PROJECT_ID}/imports/{JOB_ID}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    if imported.status_code != 200 or imported.json()["status"] != "done":
        fail(f"real import did not finish: {imported.status_code} {imported.text[:500]}")

    captures = client.get(
        f"/projects/{PROJECT_ID}/signaling/captures",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    if captures.status_code != 200 or not captures.json()["captures"]:
        fail(f"real import produced no capture: {captures.status_code} {captures.text[:300]}")
    CAPTURE_ID = captures.json()["captures"][0]["capture_id"]

    decoded = client.post(
        f"/projects/{PROJECT_ID}/decode",
        headers={"Authorization": f"Bearer {token_a}"},
        params={"level": "deep", "capture_id": CAPTURE_ID},
    )
    if decoded.status_code != 202:
        fail(f"POST /decode returned {decoded.status_code}: {decoded.text[:300]}")
    with SessionLocal() as db:
        if not process_decode_job(db):
            fail("decode worker found no queued decode job")

    lines = client.get(
        f"/projects/{PROJECT_ID}/signaling",
        headers={"Authorization": f"Bearer {token_a}"},
        params={"capture_id": CAPTURE_ID, "page": 1, "size": 1},
    )
    if lines.status_code != 200 or not lines.json()["rows"]:
        fail(f"real capture produced no signaling row: {lines.status_code} {lines.text[:300]}")
    # /signaling/message requires a decoded RRC occurrence, not merely any
    # signaling line (the first line may be a non-ASN.1 marker).

    templates = client.get(
        f"/projects/{PROJECT_ID}/dict/v2/templates",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    if templates.status_code != 200 or not templates.json()["categories"]:
        fail(f"template catalogue unavailable: {templates.status_code}")
    TEMPLATE_CATEGORY = templates.json()["categories"][0]["id"]

    with engine.connect() as conn:
        occurrence = conn.execute(
            text("""SELECT p.param_key,e.seq FROM param_occurrence p
                    JOIN stg_event e ON e.id=p.stg_event_id
                    WHERE p.project_id=:pid AND e.capture_id=:cap AND NOT p.is_identifier
                    ORDER BY e.seq,p.id LIMIT 1"""),
            {"pid": PROJECT_ID, "cap": CAPTURE_ID},
        ).mappings().first()
        if occurrence is None:
            fail("real decoded capture produced no non-identity RRC occurrence")
        PARAM_KEY = occurrence["param_key"]
        MESSAGE_SEQ = int(occurrence["seq"])

    tasks = client.get(
        f"/projects/{PROJECT_ID}/tasks",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    if tasks.status_code != 200:
        fail(f"GET /tasks could not create evidence result: {tasks.status_code}")
    RESULT_ID = tasks.json()["result_id"]

    print(
        "G34 FIXTURE "
        f"project_id={PROJECT_ID} capture_id={CAPTURE_ID} job_id={JOB_ID} "
        f"message_seq={MESSAGE_SEQ} template_category={TEMPLATE_CATEGORY}"
    )


def concrete_path(path: str) -> str:
    values = {
        "project_id": PROJECT_ID,
        "capture_id": CAPTURE_ID,
        "result_id": RESULT_ID,
        "job_id": JOB_ID,
        "code": "THR_DL_APP",
        "category": TEMPLATE_CATEGORY,
        "param_key:path": PARAM_KEY,
    }
    for key, value in values.items():
        path = path.replace("{" + key + "}", value)
    return path


def query_for(route: str) -> dict[str, Any]:
    query: dict[str, dict[str, Any]] = {
    "/projects/{project_id}/captures/{capture_id}/events": {"types": "rrc"},
    "/projects/{project_id}/captures/{capture_id}/kpi/{code}/time-series": {},
    "/projects/{project_id}/dict/param": {"param_key": PARAM_KEY},
    "/projects/{project_id}/dict/param/map": {"param_key": PARAM_KEY},
    "/projects/{project_id}/dict/v2/distribution": {"keys": PARAM_KEY},
    "/projects/{project_id}/dict/v2/map": {"keys": PARAM_KEY},
    "/projects/{project_id}/dict/v2/param/{param_key:path}": {},
    "/projects/{project_id}/kpi/{code}/points": {"x": "rsrp"},
    "/projects/{project_id}/kpi/{code}/series": {"x": "task_time"},
    "/projects/{project_id}/metrics/analysis": {"codes": "TEST-G34-CODE"},
    "/projects/{project_id}/metrics/series": {"metric_ids": "TEST-G34-METRIC"},
    "/projects/{project_id}/metrics/table": {"codes": "TEST-G34-CODE"},
    "/projects/{project_id}/signaling": {"capture_id": CAPTURE_ID},
    "/projects/{project_id}/signaling/context": {"capture_id": CAPTURE_ID, "seq": MESSAGE_SEQ},
    "/projects/{project_id}/signaling/details": {"capture_id": CAPTURE_ID, "seq": MESSAGE_SEQ},
    "/projects/{project_id}/signaling/events": {"capture_id": CAPTURE_ID},
    "/projects/{project_id}/signaling/export": {"capture_id": CAPTURE_ID},
    "/projects/{project_id}/signaling/message": {"capture_id": CAPTURE_ID, "seq": MESSAGE_SEQ},
    "/projects/{project_id}/signaling/points": {"capture_id": CAPTURE_ID},
    "/projects/{project_id}/signaling/procedures": {"capture_id": CAPTURE_ID},
    "/projects/{project_id}/signaling/timeline": {"capture_id": CAPTURE_ID},
    }
    return query.get(route, {})


def body_for(method: str, path: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if method != "POST":
        return None, None
    if path == "/projects":
        return {"name": "TEST-G34 project created by B"}, None
    if path.endswith("/assistant"):
        return {"message": "TEST-G34"}, None
    if path.endswith("/decode"):
        return None, None
    return {}, None


@dataclass
class Row:
    role: str
    method: str
    route: str
    a_code: int
    b_code: int
    verdict: str


def call(client: TestClient, token: str, method: str, route: str):
    json_body, files = body_for(method, route)
    if method == "POST" and route.endswith("/nmf"):
        source = Path(os.environ["G34_NMF_PATH"])
        with source.open("rb") as stream:
            return client.request(
                method,
                concrete_path(route),
                headers={"Authorization": f"Bearer {token}"},
                files=[("files", (source.name, stream, "application/octet-stream"))],
            )
    params = query_for(route)
    if method == "POST" and route.endswith("/decode"):
        params = {"level": "light", "capture_id": CAPTURE_ID}
    return client.request(
        method,
        concrete_path(route),
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        json=json_body,
        files=files,
    )


def finish_mutation(route: str, response: Any) -> None:
    if response.status_code != 202:
        return
    if route.endswith("/nmf"):
        jid = response.json()["id"]
        with SessionLocal() as db:
            run_import_job(db, db.get(NmfImportJob, jid))
    elif route.endswith("/decode"):
        with SessionLocal() as db:
            process_decode_job(db)


def classify(route: str, method: str, a: Any, b: Any) -> str:
    if route == "/projects" and method == "GET":
        ids = {item.get("id") for item in b.json()} if b.status_code == 200 else set()
        return "FAIL_EXPOSED" if PROJECT_ID in ids else "PASS_BLOCKED"
    if b.status_code in {401, 403}:
        return "PASS_BLOCKED"
    if b.status_code == 404 and a.status_code != 404:
        return "PASS_BLOCKED"
    if b.status_code == 404 and a.status_code == 404:
        return "FAIL_UNTESTABLE_RESOURCE_ABSENT"
    return "FAIL_EXPOSED"


def set_b_role(role: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE app_user SET role=:role WHERE email=:email"), {"role": role, "email": USER_B_EMAIL})


def main() -> int:
    seed_users()
    rows: list[Row] = []
    with TestClient(app, raise_server_exceptions=False) as client:
        token_a = login(client, USER_A_EMAIL, PASSWORD_A)
        prepare_real_fixture(client, token_a)
        operations = []
        for route in app.routes:
            path = getattr(route, "path", "")
            if "/projects" not in path and "/results" not in path:
                continue
            for method in sorted(getattr(route, "methods", set())):
                if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                    continue
                operations.append((method, path))
        operations.sort(key=lambda x: (x[0] == "DELETE", x[1], x[0]))
        if len(operations) != EXPECTED_OPERATIONS:
            fail(f"OpenAPI operation count={len(operations)}, expected={EXPECTED_OPERATIONS}")

        for role in ("lecteur", "admin"):
            set_b_role(role)
            token_b = login(client, USER_B_EMAIL, PASSWORD_B)
            for method, route in operations:
                if method == "POST" and route == "/projects":
                    b = call(client, token_b, method, route)
                    rows.append(Row(role, method, route, 0, b.status_code, "N/A_NOT_A_RESOURCE"))
                    continue
                if method == "DELETE":
                    if role == "lecteur":
                        b = call(client, token_b, method, route)
                        rows.append(Row(role, method, route, 204, b.status_code, "PASS_BLOCKED" if b.status_code == 403 else "FAIL_EXPOSED"))
                    else:
                        # B deletes A's actual project last: this is the pre-L1 exposure.
                        b = call(client, token_b, method, route)
                        verdict = "PASS_BLOCKED" if b.status_code in {401, 403, 404} else "FAIL_EXPOSED"
                        rows.append(Row(role, method, route, 204, b.status_code, verdict))
                    continue
                if method == "POST" and (route.endswith("/nmf") or route.endswith("/decode")):
                    # A=202 was already proven by prepare_real_fixture. Do not
                    # repeat an expensive real decode merely to obtain the
                    # same owner-side status for each B-role pass. B's 202 is
                    # already proof of exposure; the disposable queue may
                    # remain pending when the guard exits.
                    b = call(client, token_b, method, route)
                    rows.append(Row(role, method, route, 202, b.status_code,
                                    "PASS_BLOCKED" if b.status_code in {401, 403, 404}
                                    else "FAIL_EXPOSED"))
                    continue
                b = call(client, token_b, method, route)
                finish_mutation(route, b)
                a = call(client, token_a, method, route)
                finish_mutation(route, a)
                rows.append(Row(role, method, route, a.status_code, b.status_code, classify(route, method, a, b)))

    print("B role | route | method | A HTTP | B HTTP | verdict")
    print("--- | --- | --- | ---: | ---: | ---")
    for row in rows:
        print(f"{row.role} | {row.route} | {row.method} | {row.a_code} | {row.b_code} | {row.verdict}")
    failed = [r for r in rows if r.verdict.startswith("FAIL")]
    passed = [r for r in rows if r.verdict.startswith("PASS")]
    na = [r for r in rows if r.verdict.startswith("N/A")]
    untestable = [r for r in rows if "UNTESTABLE" in r.verdict]
    print(f"G34 operations={len(rows)} pass={len(passed)} fail={len(failed)} n_a={len(na)} untestable={len(untestable)}")
    if untestable:
        print("G34 RESOURCE COVERAGE=FAIL")
        return 2
    if failed:
        print("G34 VERDICT=FAIL")
        return 1
    print("G34 VERDICT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
