"""SS-03 scope resolution on an Alembic-migrated disposable database."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal
from app.deps import get_current_user
from app.main import app
from app.schemas.analysis_scope import CaptureAnalysisScope, SuperstreamAnalysisScope
from app.services.analysis_scope import resolve_analysis_scope


OWNER = SimpleNamespace(id="ss03-owner", active=True, role="ingenieur")
VIEWER = SimpleNamespace(id="ss03-viewer", active=True, role="lecteur")
P1 = "ss03-project-a"
P2 = "ss03-project-b"
C1 = "111111111111"
C2 = "222222222222"
C3 = "333333333333"
S1 = "ss03-stream-a"
S2 = "ss03-stream-b"


def _seed() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for user_id, email, role in (
            (OWNER.id, "ss03-owner@example.test", "ingenieur"),
            (VIEWER.id, "ss03-viewer@example.test", "lecteur"),
        ):
            db.execute(
                text(
                    "INSERT INTO app_user(id,email,password_hash,role,active,created_at,must_change_password) "
                    "VALUES (:id,:email,'test-only',:role,true,:now,false)"
                ),
                {"id": user_id, "email": email, "role": role, "now": now},
            )
        for project_id in (P1, P2):
            db.execute(
                text("""
                    INSERT INTO projects(
                      id,name,geography,center_lng,center_lat,operators,technologies,
                      services,bands,departements,period_start,period_end,captures,
                      imported_at,status,owner_id,visibility
                    ) VALUES (
                      :id,:id,'test',0,0,'[]'::json,'[]'::json,'[]'::json,
                      '[]'::json,'[]'::json,'2026-01-01','2026-01-01',0,
                      '2026-01-01','ready',:owner,'private'
                    )
                """),
                {"id": project_id, "owner": OWNER.id},
            )
        fixtures = (
            (P1, "ss03-file-a", C1, "1" * 64),
            (P1, "ss03-file-b", C2, "2" * 64),
            (P2, "ss03-file-c", C3, "3" * 64),
        )
        for project_id, file_id, capture_id, sha in fixtures:
            db.execute(
                text("""
                    INSERT INTO nmf_file(
                      id,project_id,filename,size_bytes,sha256,uploaded_at,status,
                      n_captures,n_events,n_gps
                    ) VALUES (:fid,:pid,:fid,1,:sha,:now,'done',1,0,0)
                """),
                {"fid": file_id, "pid": project_id, "sha": sha, "now": now},
            )
            db.execute(
                text("""
                    INSERT INTO nmf_capture(
                      project_id,capture_id,nmf_file_id,decode_level,decoder_version,
                      schema_version,format_version,n_records,n_partial,elapsed_s
                    ) VALUES (:pid,:cap,:fid,'deep','test','test','test',1,0,0)
                """),
                {"pid": project_id, "cap": capture_id, "fid": file_id},
            )
        for stream_id, project_id, name in ((S1, P1, "ordered"), (S2, P2, "foreign")):
            db.execute(
                text("""
                    INSERT INTO superstream(
                      id,project_id,name,created_by,created_at,updated_at,revision
                    ) VALUES (:id,:pid,:name,:owner,:now,:now,4)
                """),
                {
                    "id": stream_id,
                    "pid": project_id,
                    "name": name,
                    "owner": OWNER.id,
                    "now": now,
                },
            )
        for position, capture_id in enumerate((C2, C1)):
            db.execute(
                text("""
                    INSERT INTO superstream_member(
                      superstream_id,project_id,capture_id,position
                    ) VALUES (:sid,:pid,:cap,:position)
                """),
                {"sid": S1, "pid": P1, "cap": capture_id, "position": position},
            )
        db.execute(
            text(
                "INSERT INTO superstream_member(superstream_id,project_id,capture_id,position) "
                "VALUES (:sid,:pid,:cap,0)"
            ),
            {"sid": S2, "pid": P2, "cap": C3},
        )
        db.commit()


@pytest.fixture(scope="module", autouse=True)
def ss03_database():
    _seed()
    yield
    with SessionLocal() as db:
        db.execute(text("DELETE FROM projects WHERE id IN (:p1,:p2)"), {"p1": P1, "p2": P2})
        db.execute(
            text("DELETE FROM app_user WHERE id IN (:owner,:viewer)"),
            {"owner": OWNER.id, "viewer": VIEWER.id},
        )
        db.commit()


@pytest.fixture()
def api():
    app.dependency_overrides[get_current_user] = lambda: OWNER
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_capture_scope_preserves_existing_identity_and_contract(api: TestClient):
    response = api.post(
        f"/projects/{P1}/analysis-scopes/resolve",
        json={"type": "capture", "captureId": C1},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scopeRevision"] is None
    assert body["members"] == [
        {"projectId": P1, "captureId": C1, "memberPosition": 0}
    ]
    assert body["identityFields"] == ["project_id", "capture_id", "seq"]
    assert body["orderFields"] == ["member_position", "seq"]

    with SessionLocal() as db:
        resolved = resolve_analysis_scope(db, P1, CaptureAnalysisScope(type="capture", captureId=C1))
    assert resolved.order_key(C1, 37) == (0, 37)


def test_superstream_boundaries_follow_member_position_then_seq(api: TestClient):
    response = api.post(
        f"/projects/{P1}/analysis-scopes/resolve",
        json={"type": "superstream", "superstreamId": S1},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scopeRevision"] == 4
    assert [(member["captureId"], member["memberPosition"]) for member in body["members"]] == [
        (C2, 0),
        (C1, 1),
    ]

    with SessionLocal() as db:
        resolved = resolve_analysis_scope(
            db,
            P1,
            SuperstreamAnalysisScope(type="superstream", superstreamId=S1),
        )
    events = [(C1, 0), (C2, 999), (C2, 2), (C1, 1)]
    assert sorted(events, key=lambda row: resolved.order_key(*row)) == [
        (C2, 2),
        (C2, 999),
        (C1, 0),
        (C1, 1),
    ]


def test_cross_project_ids_are_indistinguishable_from_unknown(api: TestClient):
    foreign_capture = api.post(
        f"/projects/{P1}/analysis-scopes/resolve",
        json={"type": "capture", "captureId": C3},
    )
    foreign_stream = api.post(
        f"/projects/{P1}/analysis-scopes/resolve",
        json={"type": "superstream", "superstreamId": S2},
    )
    assert foreign_capture.status_code == 404
    assert foreign_stream.status_code == 404
    assert foreign_capture.json() == foreign_stream.json()


def test_private_project_access_is_checked_before_scope_resolution(api: TestClient):
    app.dependency_overrides[get_current_user] = lambda: VIEWER
    response = api.post(
        f"/projects/{P1}/analysis-scopes/resolve",
        json={"type": "capture", "captureId": C1},
    )
    assert response.status_code == 404
    app.dependency_overrides[get_current_user] = lambda: OWNER
