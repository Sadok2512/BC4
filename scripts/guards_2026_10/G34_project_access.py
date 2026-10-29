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

Capture identifiers are shared between projects. Every capture lookup in this
guard therefore uses the canonical key ``(project_id, capture_id, seq)``.
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


EXPECTED_OPERATIONS = 75
PROJECT_ID = ""
CAPTURE_ID = ""
RESULT_ID = ""
SUPERSTREAM_ID = ""
JOB_ID = ""
PARAM_KEY = ""
TEMPLATE_CATEGORY = ""
MESSAGE_SEQ = 0
USER_A_EMAIL = "test-g34-a@example.invalid"
USER_B_EMAIL = "test-g34-b@example.invalid"
USER_B_ID = "TEST-G34-USER-B"
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
        # A failed previous guard run may have left its private fixture. The
        # ephemeral-only guard must be restartable without weakening the live
        # safety gate or deleting any unrelated project.
        conn.execute(
            text("DELETE FROM projects WHERE owner_id IN ('TEST-G34-USER-A','TEST-G34-USER-B')")
        )
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
    global PROJECT_ID, CAPTURE_ID, RESULT_ID, SUPERSTREAM_ID, JOB_ID, PARAM_KEY, TEMPLATE_CATEGORY, MESSAGE_SEQ
    sources = [Path(value) for value in os.environ.get("G34_NMF_PATHS", "").split("::") if value]
    if len(sources) != 2 or any(not source.is_file() for source in sources):
        fail("G34_NMF_PATHS must contain exactly two real corpus .nmf paths separated by ::")

    created = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "TEST-G34 project owned by A", "visibility": "private", "parse_decode_level": "light", "parse_binning_mode": "temporal", "parse_temporal_resolution": "native", "parse_spatial_bin_m": None},
    )
    if created.status_code != 201:
        fail(f"POST /projects returned {created.status_code}: {created.text[:300]}")
    PROJECT_ID = created.json()["id"]

    streams = [source.open("rb") for source in sources]
    try:
        uploaded = client.post(
            f"/projects/{PROJECT_ID}/nmf",
            headers={"Authorization": f"Bearer {token_a}"},
            files=[
                ("files", (source.name, stream, "application/octet-stream"))
                for source, stream in zip(sources, streams)
            ],
        )
    finally:
        for stream in streams:
            stream.close()
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
    if captures.status_code != 200 or len(captures.json()["captures"]) != 2:
        fail(f"real import did not produce exactly two captures: {captures.status_code} {captures.text[:300]}")
    CAPTURE_ID = captures.json()["captures"][0]["capture_id"]

    superstream = client.post(
        f"/projects/{PROJECT_ID}/superstreams",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "TEST-G34 real fixture", "logIds": [source.name for source in sources]},
    )
    if superstream.status_code != 201:
        fail(f"real superstream fixture returned {superstream.status_code}: {superstream.text[:300]}")
    SUPERSTREAM_ID = superstream.json()["id"]

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
                    WHERE p.project_id=:pid AND e.project_id=:pid
                      AND e.capture_id=:cap AND NOT p.is_identifier
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
        "user_id": USER_B_ID,
        "ss_id": SUPERSTREAM_ID,
        "code": "THR_DL_APP",
        "category": TEMPLATE_CATEGORY,
        "param_key:path": PARAM_KEY,
    }
    for key, value in values.items():
        path = path.replace("{" + key + "}", value)
    return path


def query_for(route: str) -> dict[str, Any]:
    query: dict[str, dict[str, Any]] = {
    "/projects/{project_id}/captures/{capture_id}": {"reason": "TEST-G34 access isolation"},
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
        return {"name": "TEST-G34 project created by B", "visibility": "private", "parse_decode_level": "light", "parse_binning_mode": "temporal", "parse_temporal_resolution": "native", "parse_spatial_bin_m": None}, None
    if path.endswith("/shares"):
        return {"email": USER_B_EMAIL}, None
    if path.endswith("/parsing"):
        return {"parse_decode_level": "deep", "parse_binning_mode": "spatial", "parse_temporal_resolution": None, "parse_spatial_bin_m": 25}, None
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
        source = Path(os.environ["G34_NMF_PATHS"].split("::")[0])
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


def revoke_b(client: TestClient, token_a: str) -> None:
    response = client.delete(
        f"/projects/{PROJECT_ID}/shares/{USER_B_ID}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    if response.status_code not in {204, 404}:
        fail(f"share cleanup returned {response.status_code}")


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
                    expected = 403 if role == "lecteur" else 201
                    verdict = (
                        "PASS_BLOCKED" if role == "lecteur" and b.status_code == expected
                        else "PASS_OWN_CREATE" if role == "admin" and b.status_code == expected
                        else "FAIL_EXPOSED"
                    )
                    rows.append(Row(role, method, route, expected, b.status_code, verdict))
                    continue
                if method == "DELETE":
                    if route.endswith("/shares/{user_id}"):
                        owner_share = client.post(
                            f"/projects/{PROJECT_ID}/shares",
                            headers={"Authorization": f"Bearer {token_a}"},
                            json={"email": USER_B_EMAIL},
                        )
                        if owner_share.status_code not in {200, 201}:
                            fail(f"share fixture returned {owner_share.status_code}")
                        b = call(client, token_b, method, route)
                        a = call(client, token_a, method, route)
                        rows.append(Row(role, method, route, a.status_code, b.status_code,
                                        "PASS_BLOCKED" if a.status_code == 204 and b.status_code == 404 else "FAIL_EXPOSED"))
                        continue
                    if role == "lecteur":
                        b = call(client, token_b, method, route)
                        rows.append(Row(role, method, route, 204, b.status_code,
                                        "PASS_BLOCKED" if b.status_code in {403, 404}
                                        else "FAIL_EXPOSED"))
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
                if method == "POST" and route.endswith("/shares"):
                    b = call(client, token_b, method, route)
                    a = call(client, token_a, method, route)
                    rows.append(Row(role, method, route, a.status_code, b.status_code,
                                    "PASS_BLOCKED" if a.status_code in {200, 201} and b.status_code == 404 else "FAIL_EXPOSED"))
                    revoke_b(client, token_a)
                    continue
                b = call(client, token_b, method, route)
                finish_mutation(route, b)
                a = call(client, token_a, method, route)
                finish_mutation(route, a)
                rows.append(Row(role, method, route, a.status_code, b.status_code, classify(route, method, a, b)))

            # L2 contract: a named share grants reads only, and revocation is immediate.
            shared = client.post(
                f"/projects/{PROJECT_ID}/shares",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"email": USER_B_EMAIL},
            )
            if shared.status_code not in {200, 201}:
                fail(f"share creation returned {shared.status_code}")
            shared_get = client.get(
                f"/projects/{PROJECT_ID}", headers={"Authorization": f"Bearer {token_b}"}
            )
            shared_write = client.patch(
                f"/projects/{PROJECT_ID}/parsing",
                headers={"Authorization": f"Bearer {token_b}"},
                json={"parse_decode_level": "light", "parse_binning_mode": "temporal", "parse_temporal_resolution": "native", "parse_spatial_bin_m": None},
            )
            rows.append(Row(role, "GET", "/projects/{project_id} [shared]", 200, shared_get.status_code,
                            "PASS_SHARED_READ" if shared_get.status_code == 200 else "FAIL_SHARED_READ"))
            rows.append(Row(role, "PATCH", "/projects/{project_id}/parsing [shared]", 200, shared_write.status_code,
                            "PASS_BLOCKED" if shared_write.status_code == 404 else "FAIL_EXPOSED"))
            revoke_b(client, token_a)
            revoked = client.get(
                f"/projects/{PROJECT_ID}", headers={"Authorization": f"Bearer {token_b}"}
            )
            rows.append(Row(role, "GET", "/projects/{project_id} [revoked]", 200, revoked.status_code,
                            "PASS_REVOKED" if revoked.status_code == 404 else "FAIL_EXPOSED"))

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
