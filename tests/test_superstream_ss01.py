"""SS-01 integration coverage.

These tests require an Alembic-migrated disposable PostgreSQL database. They
never create, decode, update or delete NMF events; only minimal capture
metadata and Superstream grouping rows are used.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.deps import get_current_user
from app.main import app


OWNER = SimpleNamespace(id="ss01-owner", active=True, role="ingenieur")
VIEWER = SimpleNamespace(id="ss01-viewer", active=True, role="lecteur")
P1 = "ss01-project-a"
P2 = "ss01-project-b"
C1 = "aaaaaaaaaaaa"
C2 = "bbbbbbbbbbbb"
C3 = "cccccccccccc"


def _seed() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.execute(text("DELETE FROM app_user WHERE id IN (:owner, :viewer)"), {"owner": OWNER.id, "viewer": VIEWER.id})
        for user, email, role in (
            (OWNER.id, "ss01-owner@example.test", "ingenieur"),
            (VIEWER.id, "ss01-viewer@example.test", "lecteur"),
        ):
            db.execute(text("""
                INSERT INTO app_user(id,email,password_hash,role,active,created_at,must_change_password)
                VALUES (:id,:email,'test-only',:role,true,:now,false)
            """), {"id": user, "email": email, "role": role, "now": now})
        for project_id in (P1, P2):
            db.execute(text("""
                INSERT INTO projects(
                  id,name,geography,center_lng,center_lat,operators,technologies,
                  services,bands,departements,period_start,period_end,captures,
                  imported_at,status,owner_id,visibility
                ) VALUES (
                  :id,:id,'test',0,0,CAST('[]' AS json),CAST('[]' AS json),
                  CAST('[]' AS json),CAST('[]' AS json),CAST('[]' AS json),
                  '2026-01-01','2026-01-01',0,'2026-01-01','ready',:owner,'public'
                )
            """), {"id": project_id, "owner": OWNER.id})
        fixtures = (
            (P1, "ss01-file-a", C1, "a" * 64),
            (P1, "ss01-file-b", C2, "b" * 64),
            (P2, "ss01-file-c", C3, "c" * 64),
        )
        for project_id, file_id, capture_id, sha in fixtures:
            db.execute(text("""
                INSERT INTO nmf_file(
                  id,project_id,filename,size_bytes,sha256,uploaded_at,status,
                  n_captures,n_events,n_gps
                ) VALUES (:fid,:pid,:name,1,:sha,:now,'done',1,0,0)
            """), {
                "fid": file_id,
                "pid": project_id,
                "name": f"{file_id}.nmf",
                "sha": sha,
                "now": now,
            })
            db.execute(text("""
                INSERT INTO nmf_capture(
                  project_id,capture_id,nmf_file_id,decode_level,decoder_version,
                  schema_version,format_version,n_records,n_partial,elapsed_s
                ) VALUES (:pid,:cap,:fid,'deep','test','test','test',7,0,0)
            """), {"pid": project_id, "cap": capture_id, "fid": file_id})
        db.commit()


@pytest.fixture(scope="module", autouse=True)
def ss01_database():
    _seed()
    yield
    with SessionLocal() as db:
        db.execute(text("DELETE FROM projects WHERE id IN (:p1,:p2)"), {"p1": P1, "p2": P2})
        db.execute(text("DELETE FROM app_user WHERE id IN (:owner,:viewer)"), {"owner": OWNER.id, "viewer": VIEWER.id})
        db.commit()


@pytest.fixture()
def api():
    app.dependency_overrides[get_current_user] = lambda: OWNER
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_crud_revision_order_permissions_and_data_preservation(api: TestClient):
    legacy = api.post(f"/projects/{P1}/superstreams", json={"name": "legacy", "logIds": ["ss01-file-a.nmf"]})
    assert legacy.status_code == 422

    created = api.post(
        f"/projects/{P1}/superstreams",
        json={"name": "ordered", "captureIds": [C2, C1]},
    )
    assert created.status_code == 201, created.text
    stream = created.json()
    stream_id = stream["id"]
    assert created.headers["etag"] == '"1"'
    assert stream["revision"] == 1
    assert stream["captureIds"] == [C2, C1]
    assert stream["positions"] == [0, 1]

    duplicate_name = api.post(
        f"/projects/{P1}/superstreams",
        json={"name": "ordered", "captureIds": [C1]},
    )
    assert duplicate_name.status_code == 409

    no_precondition = api.patch(
        f"/projects/{P1}/superstreams/{stream_id}", json={"name": "renamed"}
    )
    assert no_precondition.status_code == 428

    renamed = api.patch(
        f"/projects/{P1}/superstreams/{stream_id}",
        headers={"If-Match": '"1"'},
        json={"name": "renamed"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.headers["etag"] == '"2"'
    assert renamed.json()["captureIds"] == [C2, C1]

    stale = api.patch(
        f"/projects/{P1}/superstreams/{stream_id}",
        headers={"If-Match": '"1"'},
        json={"name": "stale-write"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "REVISION_CONFLICT"

    duplicate_member = api.put(
        f"/projects/{P1}/superstreams/{stream_id}/members",
        headers={"If-Match": '"2"'},
        json={"captureIds": [C1, C1]},
    )
    assert duplicate_member.status_code == 422

    cross_project = api.put(
        f"/projects/{P1}/superstreams/{stream_id}/members",
        headers={"If-Match": '"2"'},
        json={"captureIds": [C3]},
    )
    assert cross_project.status_code == 422
    unchanged = api.get(f"/projects/{P1}/superstreams/{stream_id}")
    assert unchanged.json()["revision"] == 2
    assert unchanged.json()["captureIds"] == [C2, C1]

    reordered = api.put(
        f"/projects/{P1}/superstreams/{stream_id}/members",
        headers={"If-Match": '"2"'},
        json={"captureIds": [C1, C2]},
    )
    assert reordered.status_code == 200, reordered.text
    assert reordered.json()["revision"] == 3
    assert reordered.json()["captureIds"] == [C1, C2]
    assert reordered.json()["positions"] == [0, 1]

    other = api.post(
        f"/projects/{P1}/superstreams",
        json={"name": "taken", "captureIds": [C1]},
    )
    assert other.status_code == 201
    name_conflict = api.patch(
        f"/projects/{P1}/superstreams/{stream_id}",
        headers={"If-Match": '"3"'},
        json={"name": "taken"},
    )
    assert name_conflict.status_code == 409
    rolled_back = api.get(f"/projects/{P1}/superstreams/{stream_id}").json()
    assert rolled_back["revision"] == 3
    assert rolled_back["name"] == "renamed"
    assert api.delete(
        f"/projects/{P1}/superstreams/{other.json()['id']}",
        headers={"If-Match": '"1"'},
    ).status_code == 204

    app.dependency_overrides[get_current_user] = lambda: VIEWER
    readable = api.get(f"/projects/{P1}/superstreams/{stream_id}")
    assert readable.status_code == 200
    forbidden = api.patch(
        f"/projects/{P1}/superstreams/{stream_id}",
        headers={"If-Match": '"3"'},
        json={"name": "viewer-write"},
    )
    assert forbidden.status_code == 404
    app.dependency_overrides[get_current_user] = lambda: OWNER

    with SessionLocal() as db:
        before = db.execute(text("""
            SELECT
              (SELECT count(*) FROM nmf_capture WHERE project_id=:pid),
              (SELECT count(*) FROM nmf_file WHERE project_id=:pid)
        """), {"pid": P1}).one()

    deleted = api.delete(
        f"/projects/{P1}/superstreams/{stream_id}", headers={"If-Match": '"3"'}
    )
    assert deleted.status_code == 204
    with SessionLocal() as db:
        after = db.execute(text("""
            SELECT
              (SELECT count(*) FROM nmf_capture WHERE project_id=:pid),
              (SELECT count(*) FROM nmf_file WHERE project_id=:pid),
              (SELECT count(*) FROM superstream_member WHERE superstream_id=:sid)
        """), {"pid": P1, "sid": stream_id}).one()
    assert tuple(before) == tuple(after[:2])
    assert after[2] == 0


def test_database_rejects_cross_project_member_atomically():
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.execute(text("""
            INSERT INTO superstream(id,project_id,name,created_by,created_at,updated_at,revision)
            VALUES ('ss01-db-guard',:pid,'db-guard',:owner,:now,:now,1)
        """), {"pid": P1, "owner": OWNER.id, "now": now})
        db.commit()
        with pytest.raises(IntegrityError):
            db.execute(text("""
                INSERT INTO superstream_member(superstream_id,project_id,capture_id,position)
                VALUES ('ss01-db-guard',:wrong_pid,:capture_id,0)
            """), {"wrong_pid": P2, "capture_id": C3})
            db.commit()
        db.rollback()
        assert db.execute(text(
            "SELECT count(*) FROM superstream_member WHERE superstream_id='ss01-db-guard'"
        )).scalar_one() == 0
