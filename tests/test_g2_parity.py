"""G2: contract parity.

For each endpoint the UI consumes, replay the exact Zod shape as a Pydantic
model (which is written 1:1 against the Zod schemas, see app/schemas/*).
A mismatch of shape, type, or nullability fails this guard. No hidden
tolerance.
"""

from __future__ import annotations

from app.schemas.assistant import AssistantResponse
from app.schemas.common import OverviewData, Project
from app.schemas.dictionary import DictProject, DictTree, ParamDetail, ParamList, ParamMap
from app.schemas.settings import About, AiConfig, Appearance, KpiCatalogResponse, Organization, UsersResponse
from tests.conftest import PARIS, RENNES


def test_projects_list(client):
    r = client.get("/projects")
    assert r.status_code == 200
    for p in r.json():
        Project.model_validate(p)


def test_project_detail(client):
    r = client.get(f"/projects/{PARIS}")
    assert r.status_code == 200
    Project.model_validate(r.json())


def test_overview_paris(client):
    r = client.get(f"/projects/{PARIS}/overview")
    assert r.status_code == 200
    OverviewData.model_validate(r.json())


def test_overview_rennes(client):
    r = client.get(f"/projects/{RENNES}/overview")
    assert r.status_code == 200
    OverviewData.model_validate(r.json())


def test_dict_project(client):
    r = client.get(f"/projects/{PARIS}/dict")
    assert r.status_code == 200
    DictProject.model_validate(r.json())


def test_dict_tree(client):
    r = client.get(f"/projects/{PARIS}/dict/tree")
    assert r.status_code == 200
    tree = DictTree.model_validate(r.json())
    technos = {b.techno for b in tree.branches}
    # Zod refinement: LTE and NR must always be present.
    assert technos == {"LTE", "NR"}


def test_dict_params(client):
    r = client.get(f"/projects/{PARIS}/dict/params", params={"msg_id": "lte-mr"})
    assert r.status_code == 200
    ParamList.model_validate(r.json())


def test_dict_param_detail(client):
    r = client.get(
        f"/projects/{PARIS}/dict/param",
        params={"param_id": "lte-mr-rsrp", "group_by": "operator"},
    )
    assert r.status_code == 200
    ParamDetail.model_validate(r.json())


def test_dict_param_map(client):
    r = client.get(
        f"/projects/{PARIS}/dict/param/map",
        params={"param_id": "lte-mr-rsrp"},
    )
    assert r.status_code == 200
    ParamMap.model_validate(r.json())


def test_kpi_catalog(client):
    r = client.get("/kpi/catalog")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["catalog"], list) and len(body["catalog"]) > 0
    assert body["kpi"]["name"] and body["kpi"]["byOp"]


def test_appearance(client):
    r = client.get("/settings/appearance")
    assert r.status_code == 200
    Appearance.model_validate(r.json())


def test_organization(client):
    r = client.get("/settings/organization")
    assert r.status_code == 200
    Organization.model_validate(r.json())


def test_about(client):
    r = client.get("/settings/about")
    assert r.status_code == 200
    About.model_validate(r.json())


def test_users(client, admin_headers):
    r = client.get("/settings/users", headers=admin_headers)
    assert r.status_code == 200
    UsersResponse.model_validate(r.json())


def test_kpi_settings(client, admin_headers):
    r = client.get("/settings/kpi", headers=admin_headers)
    assert r.status_code == 200
    KpiCatalogResponse.model_validate(r.json())


def test_ai_config(client, admin_headers):
    r = client.get("/settings/ai", headers=admin_headers)
    assert r.status_code == 200
    AiConfig.model_validate(r.json())


def test_assistant(client):
    r = client.post(
        f"/projects/{PARIS}/assistant",
        json={
            "project_id": PARIS,
            "conversation_id": "conv-test",
            "question": "quel est l'échantillon ?",
            "filters": {},
        },
    )
    assert r.status_code == 200
    AssistantResponse.model_validate(r.json())
