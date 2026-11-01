"""Workspace template API integration coverage on disposable PostgreSQL."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal
from app.deps import get_current_user
from app.main import app


OWNER = SimpleNamespace(id="template-owner", active=True, role="ingenieur")
OTHER = SimpleNamespace(id="template-other", active=True, role="lecteur")
P1 = "template-project-a"
P2 = "template-project-b"
CAPTURE = "templatecap1"


def configuration() -> dict:
    return {
        "schemaVersion": 1,
        "workspace": {
            "layout": "2",
            "overlay": False,
            "kpiCodes": ["success_rate"],
            "metricCodes": ["cell_rsrp@lte-type-1"],
            "activeKpiCode": "success_rate",
            "chartConfigurations": {
                "success_rate": {
                    "kpiCode": "success_rate",
                    "visualization": "graph",
                    "xMetric": "operator",
                    "yMetric": "success_rate",
                    "groupBy": "operator",
                    "statistic": "value",
                    "curveType": "line_points",
                }
            },
            "metricViews": {"cell_rsrp@lte-type-1": "map"},
            "panelLayout": {
                "order": ["kpi:success_rate", "metric:cell_rsrp@lte-type-1"],
                "span": {"kpi:success_rate": 1},
                "height": {"kpi:success_rate": 420},
                "collapsed": {},
                "titles": {"kpi:success_rate": "Success"},
                "syncTime": True,
            },
            "tableSettings": {
                "perRow": 1,
                "autoFitWidth": True,
                "equalHeights": True,
                "spacing": "normal",
                "height": "auto",
                "customHeight": 480,
                "hScroll": "auto",
                "resizable": False,
                "style": "professional",
                "palette": "white",
                "colors": {
                    "background": "#ffffff",
                    "headerBg": "#f7f9fc",
                    "headerText": "#1e293b",
                    "rowBg": "#ffffff",
                    "altRow": "#f8fafc",
                    "border": "#e2e8f0",
                    "selected": "#dbeafe",
                },
                "fontSize": "medium",
                "rowHeight": "normal",
                "headerHeight": "normal",
                "cellPadding": "medium",
                "borders": "horizontal",
                "zebra": True,
                "stickyHeader": True,
                "stickyFirstColumn": True,
                "wrap": False,
                "cellAlign": "center",
                "numberAlign": "center",
                "radius": "rounded",
                "hidden": [],
                "order": [],
                "showUnits": True,
                "sort": None,
            },
            "metricPane": "charts",
            "mapPreferences": {
                "cell_rsrp@lte-type-1": {
                    "palette": "coverage",
                    "pointSize": 4,
                    "links": {"serving": True, "neighbour": True, "nr_anchor": True},
                }
            },
            "legendSettings": {
                "cell_rsrp@lte-type-1": {"count": 5, "colors": {"0": "#16a34a"}}
            },
        },
    }


def _seed() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.execute(text("DELETE FROM projects WHERE id IN (:p1,:p2)"), {"p1": P1, "p2": P2})
        db.execute(
            text("DELETE FROM app_user WHERE id IN (:owner,:other)"),
            {"owner": OWNER.id, "other": OTHER.id},
        )
        for user_id, email, role in (
            (OWNER.id, "template-owner@example.test", "ingenieur"),
            (OTHER.id, "template-other@example.test", "lecteur"),
        ):
            db.execute(text("""
                INSERT INTO app_user(id,email,password_hash,role,active,created_at,must_change_password)
                VALUES (:id,:email,'test-only',:role,true,:now,false)
            """), {"id": user_id, "email": email, "role": role, "now": now})
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
        db.execute(text("""
            INSERT INTO nmf_file(
              id,project_id,filename,size_bytes,sha256,uploaded_at,status,
              n_captures,n_events,n_gps
            ) VALUES ('template-file',:pid,'template.nmf',1,:sha,:now,'done',1,0,0)
        """), {"pid": P1, "sha": "f" * 64, "now": now})
        db.execute(text("""
            INSERT INTO nmf_capture(
              project_id,capture_id,nmf_file_id,decode_level,decoder_version,
              schema_version,format_version,n_records,n_partial,elapsed_s
            ) VALUES (:pid,:cap,'template-file','deep','test','test','test',7,0,0)
        """), {"pid": P1, "cap": CAPTURE})
        db.commit()


@pytest.fixture(scope="module", autouse=True)
def template_database():
    _seed()
    yield
    with SessionLocal() as db:
        db.execute(text("DELETE FROM projects WHERE id IN (:p1,:p2)"), {"p1": P1, "p2": P2})
        db.execute(
            text("DELETE FROM app_user WHERE id IN (:owner,:other)"),
            {"owner": OWNER.id, "other": OTHER.id},
        )
        db.commit()


@pytest.fixture()
def api():
    app.dependency_overrides[get_current_user] = lambda: OWNER
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_crud_if_match_user_and_project_isolation(api: TestClient):
    body = {
        "name": "RF overview",
        "description": "Reusable radio panels",
        "schemaVersion": 1,
        "configuration": configuration(),
    }
    created = api.post(f"/projects/{P1}/workspace-templates", json=body)
    assert created.status_code == 201, created.text
    template = created.json()
    template_id = template["id"]
    assert created.headers["etag"] == '"1"'
    assert template["ownerId"] == OWNER.id
    assert template["configuration"] == configuration()

    duplicate = api.post(
        f"/projects/{P1}/workspace-templates", json={**body, "name": "rf OVERVIEW"}
    )
    assert duplicate.status_code == 409

    listed = api.get(f"/projects/{P1}/workspace-templates")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [template_id]
    assert api.get(f"/projects/{P2}/workspace-templates/{template_id}").status_code == 404

    app.dependency_overrides[get_current_user] = lambda: OTHER
    assert api.get(f"/projects/{P1}/workspace-templates").json() == []
    assert api.get(f"/projects/{P1}/workspace-templates/{template_id}").status_code == 404
    app.dependency_overrides[get_current_user] = lambda: OWNER

    update_body = {
        "description": "Updated",
        "schemaVersion": 1,
        "configuration": configuration(),
    }
    assert api.put(
        f"/projects/{P1}/workspace-templates/{template_id}", json=update_body
    ).status_code == 428
    updated = api.put(
        f"/projects/{P1}/workspace-templates/{template_id}",
        headers={"If-Match": '"1"'},
        json=update_body,
    )
    assert updated.status_code == 200, updated.text
    assert updated.headers["etag"] == '"2"'
    assert updated.json()["revision"] == 2

    stale = api.put(
        f"/projects/{P1}/workspace-templates/{template_id}",
        headers={"If-Match": '"1"'},
        json=update_body,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"] == 2

    renamed = api.patch(
        f"/projects/{P1}/workspace-templates/{template_id}/name",
        headers={"If-Match": '"2"'},
        json={"name": "Drive RF"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["revision"] == 3
    assert renamed.json()["name"] == "Drive RF"

    with SessionLocal() as db:
        before = db.execute(text("""
            SELECT
              (SELECT count(*) FROM nmf_capture WHERE project_id=:pid),
              (SELECT count(*) FROM nmf_file WHERE project_id=:pid)
        """), {"pid": P1}).one()
    deleted = api.delete(
        f"/projects/{P1}/workspace-templates/{template_id}",
        headers={"If-Match": '"3"'},
    )
    assert deleted.status_code == 204
    with SessionLocal() as db:
        after = db.execute(text("""
            SELECT
              (SELECT count(*) FROM nmf_capture WHERE project_id=:pid),
              (SELECT count(*) FROM nmf_file WHERE project_id=:pid)
        """), {"pid": P1}).one()
    assert tuple(after) == tuple(before)


def test_configuration_rejects_capture_tokens_raw_values_and_unknown_fields(api: TestClient):
    base = {
        "name": "invalid",
        "schemaVersion": 1,
        "configuration": configuration(),
    }
    for forbidden, value in (
        ("captureId", CAPTURE),
        ("jwt", "secret"),
        ("measurements", [1, 2, 3]),
        ("temporaryFilters", {"operator": ["Orange"]}),
    ):
        invalid = configuration()
        invalid["workspace"][forbidden] = value
        response = api.post(
            f"/projects/{P1}/workspace-templates",
            json={**base, "configuration": invalid},
        )
        assert response.status_code == 422, (forbidden, response.text)
