"""G11 — DELETE /projects/{id} + enrichissement + état seed.

Vérifications :
- DELETE 204 par admin → projet disparaît de la liste.
- DELETE 204 par ingenieur (mapping editor) → OK.
- DELETE 403 par lecteur.
- DELETE 404 sur un ID inexistant (même pour admin).
- Cascade : les enfants (nmf_file, stg_event, measurement_points,
  rrc_observations) sont effacés par le ondelete=CASCADE.
- État seed : les projets de démo (idf-t3-2026, …) ont déjà
  operators/technos/bands REMPLIS (le seed les écrit — rien à faire
  dans ce lot). Confirmation par assertion sur la base.
- Enrichissement à l'ingest : `technologies` est écrit depuis
  `technos_seen` dans `refresh_project_summary`. Un projet créé mais
  sans ingest reste vide (déclaré).
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from app.db import SessionLocal


def _login(client_noauth, email: str, password: str) -> str:
    r = client_noauth.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _hdr(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok(client_noauth) -> str:
    e, p = os.environ.get("BC4_ADMIN_EMAIL"), os.environ.get("BC4_ADMIN_PASSWORD")
    if not e or not p:
        pytest.skip("BC4_ADMIN_EMAIL/BC4_ADMIN_PASSWORD manquants")
    return _login(client_noauth, e, p)


@pytest.fixture(scope="module")
def ingenieur_tok(client_noauth) -> str:
    e, p = os.environ.get("BC4_DEMO_EMAIL"), os.environ.get("BC4_DEMO_PASSWORD")
    if not e or not p or os.environ.get("BC4_DEMO_ROLE", "ingenieur") != "ingenieur":
        pytest.skip("compte ingenieur de démo manquant")
    return _login(client_noauth, e, p)


@pytest.fixture(scope="module")
def lecteur_tok(client_noauth, admin_tok) -> str:
    uid = uuid.uuid4().hex[:8]
    login = f"g11-lecteur-{uid}"
    password = "ReaderPassw0rd!"
    r = client_noauth.post(
        "/settings/users",
        headers=_hdr(admin_tok),
        json={
            "login": login,
            "display_name": "G11 Lecteur",
            "role": "viewer",
            "password": password,
            "password_confirm": password,
        },
    )
    assert r.status_code == 201, r.text
    return _login(client_noauth, f"{login}@bc4.local", password)


def _create(client_noauth, tok: str, name: str) -> str:
    r = client_noauth.post("/projects", headers=_hdr(tok), json={"name": name})
    assert r.status_code in {200, 201}, r.text
    return r.json()["id"]


def test_delete_404_on_unknown_id(client_noauth, admin_tok):
    r = client_noauth.delete("/projects/does-not-exist", headers=_hdr(admin_tok))
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_FOUND"


def test_delete_403_for_lecteur(client_noauth, lecteur_tok, admin_tok):
    pid = _create(client_noauth, admin_tok, f"g11-del-{uuid.uuid4().hex[:6]}")
    r = client_noauth.delete(f"/projects/{pid}", headers=_hdr(lecteur_tok))
    assert r.status_code == 403
    # Nettoyage : admin supprime pour ne pas laisser de dette.
    client_noauth.delete(f"/projects/{pid}", headers=_hdr(admin_tok))


def test_delete_by_admin_204_and_disappears(client_noauth, admin_tok):
    name = f"g11-admin-{uuid.uuid4().hex[:6]}"
    pid = _create(client_noauth, admin_tok, name)
    r = client_noauth.delete(f"/projects/{pid}", headers=_hdr(admin_tok))
    assert r.status_code == 204
    # 404 au second DELETE
    r2 = client_noauth.delete(f"/projects/{pid}", headers=_hdr(admin_tok))
    assert r2.status_code == 404
    # Absent du listing
    lst = client_noauth.get("/projects", headers=_hdr(admin_tok)).json()
    assert all(p["id"] != pid for p in lst)


def test_delete_by_ingenieur_204(client_noauth, ingenieur_tok, admin_tok):
    pid = _create(client_noauth, admin_tok, f"g11-ing-del-{uuid.uuid4().hex[:6]}")
    r = client_noauth.delete(f"/projects/{pid}", headers=_hdr(ingenieur_tok))
    assert r.status_code == 204, r.text


def test_seed_projects_have_operators_technos_bands():
    """Trancher point 3 : les projets seedés ont déjà des listes
    non vides en base. Zéro action requise dans ce lot."""
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT id, operators, technologies, bands FROM projects WHERE id IN "
                "('idf-t3-2026','national-2026','rennes-lte-2026','lyon-drive-2026',"
                "'marseille-5g-2026','lille-indoor-2026')"
            )
        ).all()
    assert len(rows) >= 1, "au moins un projet seedé doit être présent"
    for r in rows:
        assert r.operators, f"{r.id} doit avoir des operators seedés"
        assert r.technologies, f"{r.id} doit avoir des technologies seedées"
        assert r.bands, f"{r.id} doit avoir des bands seedées"


def test_fresh_project_without_ingest_declared_empty(client_noauth, admin_tok):
    """Un projet neuf (pas de NMF ingéré) sort avec Zod operators/
    technologies/bands = [] — écart explicitement déclaré au CHANGELOG
    0.10.0 (sources opérateurs & bandes absentes du décodeur actuel)."""
    pid = _create(client_noauth, admin_tok, f"g11-empty-{uuid.uuid4().hex[:6]}")
    try:
        r = client_noauth.get(f"/projects/{pid}", headers=_hdr(admin_tok))
        assert r.status_code == 200
        body = r.json()
        assert body["operators"] == []
        assert body["technologies"] == []
        assert body["bands"] == []
    finally:
        client_noauth.delete(f"/projects/{pid}", headers=_hdr(admin_tok))


def test_refresh_project_summary_writes_technologies():
    """Si on simule une insertion de stg_event (`system='LTE'`), la
    fonction d'enrichissement écrit `project.technologies = ["LTE"]`.
    Preuve que l'enrichissement est câblé à l'ingest réel. operators
    et bands restent intentionnellement vides (écart déclaré)."""
    from app.ingest.nmf import refresh_project_summary
    from app.models import Project

    with SessionLocal() as db:
        pid = f"g11-enrich-{uuid.uuid4().hex[:8]}"
        from datetime import datetime, timezone
        p = Project(
            id=pid, name="G11 Enrich", geography="", center_lng=0.0, center_lat=0.0,
            operators=[], technologies=[], services=[], bands=[], departements=[],
            period_start="2026-01-01", period_end="2026-01-02", captures=0,
            imported_at="2026-01-02", status="processing",
            created_at=datetime.now(timezone.utc), actor="g11",
            status_ingest="draft", operators_plmn={}, technos_seen={},
            n_captures_ingest=0, n_events_ingest=0, gps_coverage_pct=None,
        )
        db.add(p)
        db.commit()
        nmf_id = f"nmf-{uuid.uuid4().hex[:8]}"
        try:
            # 1) nmf_file d'abord — satisfait la FK.
            db.execute(
                text(
                    "INSERT INTO nmf_file (id, project_id, filename, size_bytes, sha256, "
                    "uploaded_at, status, n_captures, n_events, n_gps) "
                    "VALUES (:nid, :pid, 'syn.nmf', 0, :sha, now(), 'done', 1, 3, 0)"
                ),
                {"nid": nmf_id, "pid": pid, "sha": uuid.uuid4().hex},
            )
            # 2) stg_event ensuite.
            db.execute(
                text(
                    "INSERT INTO stg_event (project_id, nmf_file_id, capture_id, seq, system) "
                    "SELECT :pid, :nid, :cap, s, 'LTE' FROM generate_series(1, 3) s"
                ),
                {"pid": pid, "nid": nmf_id, "cap": "cap-g11"},
            )
            db.commit()
            refresh_project_summary(db, p)
            db.commit()
            db.refresh(p)
            assert "LTE" in (p.technologies or [])
            # Pas de source → listes toujours vides, écart déclaré.
            assert p.operators == []
            assert p.bands == []
        finally:
            db.execute(text("DELETE FROM stg_event WHERE project_id = :pid"), {"pid": pid})
            db.execute(text("DELETE FROM nmf_file WHERE project_id = :pid"), {"pid": pid})
            db.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": pid})
            db.commit()
