"""G23 (0.24.0 Keystone) — infrastructure extraction mesure/débit.

Phase 1 (mapping champ→métrique prouvé par croisement RRC) ouvert :
aucun NMF témoin dans le repo (/tmp/smoke.nmf = placeholder, stg_event
TEST2 n'a que signalling). Ce test valide uniquement l'**infrastructure
Phase 2** (schémas, routes, décodeur v1.1.0) — pas de valeur métrique
peuplée (toutes NULL par design jusqu'à mapping validé).

Vérifications :
- Décodeur 1.1.0 : constantes MEASUREMENT, THROUGHPUT, _category exposées.
- Table `stg_measurement_raw` existe avec les 11 colonnes attendues.
- Colonnes mesure ajoutées à `measurement_points` (nullable, cf.
  migration 0011) : rsrq, rssi, cqi, mimo_rank, tx_power, thrpt_ul, event_code.
- Endpoint `GET /projects/{id}/measurements/summary` répond 200
  avec le shape attendu même sur un projet vide.
- Endpoint `GET /projects/{id}/measurements/raw` : admin-only (403 pour
  non-admin).
- Aucune identité abonné dans `stg_measurement_raw` (grep sur raw_fields).
"""

from __future__ import annotations

import os
import uuid

import pytest

from sqlalchemy import text

from app.db import SessionLocal


def _hdr(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok(client_noauth) -> str:
    e = os.environ.get("BC4_ADMIN_EMAIL")
    p = os.environ.get("BC4_ADMIN_PASSWORD")
    if not e or not p:
        pytest.skip("BC4_ADMIN_EMAIL/BC4_ADMIN_PASSWORD manquants")
    r = client_noauth.post("/auth/login", json={"email": e, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def ingenieur_tok(client_noauth) -> str:
    e = os.environ.get("BC4_DEMO_EMAIL")
    p = os.environ.get("BC4_DEMO_PASSWORD")
    if not e or not p:
        pytest.skip("BC4_DEMO_EMAIL/BC4_DEMO_PASSWORD manquants")
    r = client_noauth.post("/auth/login", json={"email": e, "password": p})
    assert r.status_code == 200
    return r.json()["token"]


def test_decoder_1_1_0_api_exports():
    """Décodeur canonique : nouvelles constantes + helper exposés."""
    import importlib
    import os as _os
    import sys as _sys

    # Reproduit le chemin candidat du décodeur canonique (bind-mount RO).
    candidates = ["/opt/nmf_decoder", "/home/devmat/BC4/decoder"]
    found = None
    for p in candidates:
        if _os.path.isdir(p):
            if p not in _sys.path:
                _sys.path.insert(0, p)
            found = p
            break
    if not found:
        pytest.skip("Décodeur canonique introuvable sur le host")
    mod = importlib.import_module("bc4_decoder")

    assert "1.1.0" in mod.DECODER_VERSION, mod.DECODER_VERSION
    assert hasattr(mod, "MEASUREMENT")
    assert hasattr(mod, "THROUGHPUT")
    assert "CELLMEAS" in mod.MEASUREMENT
    assert "PHRATE" in mod.THROUGHPUT
    assert mod._category("CELLMEAS") == "measurement"
    assert mod._category("PHRATE") == "throughput"
    assert mod._category("RRCSM") == "signalling"


def test_stg_measurement_raw_schema():
    with SessionLocal() as db:
        cols = db.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'stg_measurement_raw'
                """
            )
        ).all()
    names = {r[0] for r in cols}
    expected = {
        "id", "project_id", "nmf_file_id", "capture_id", "seq", "ts",
        "event_code", "category", "system", "lat", "lon", "raw_fields",
    }
    missing = expected - names
    assert not missing, f"colonnes manquantes: {missing}"


def test_measurement_points_metric_columns():
    with SessionLocal() as db:
        cols = db.execute(
            text(
                """
                SELECT column_name, is_nullable FROM information_schema.columns
                WHERE table_name = 'measurement_points'
                """
            )
        ).all()
    by_name = {r[0]: r[1] for r in cols}
    for c in ("rsrq", "rssi", "cqi", "mimo_rank", "tx_power", "thrpt_ul", "event_code"):
        assert c in by_name, f"colonne {c} manquante"
        assert by_name[c] == "YES", f"colonne {c} doit être NULLABLE (Phase 1 non faite)"


def test_measurements_summary_shape(client_noauth, admin_tok):
    """L'endpoint répond 200 même sur un projet vide."""
    # Pick n'importe quel projet existant.
    r = client_noauth.get("/projects", headers=_hdr(admin_tok))
    assert r.status_code == 200
    projects = r.json()
    if not projects:
        pytest.skip("Aucun projet en DB")
    pid = projects[0]["id"]

    r = client_noauth.get(
        f"/projects/{pid}/measurements/summary", headers=_hdr(admin_tok)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for k in (
        "project_id", "total_points", "by_system", "by_operator", "by_band",
        "by_event_code", "metric_averages", "metric_coverage", "raw_staging",
    ):
        assert k in body, f"clé {k} manquante dans summary"
    # Toutes les moyennes sont NULL quand aucune métrique n'est peuplée.
    # (Si projet seedé B0, `dl` peut être non-NULL.)
    for mkey in ("rsrq", "sinr", "cqi", "tx_power", "thrpt_ul"):
        v = body["metric_averages"][mkey]
        # Avant Phase 1 : TOUJOURS None. Après Phase 1 (future), peut être float.
        assert v is None or isinstance(v, (int, float)), f"{mkey} shape invalide: {v!r}"


def test_measurements_raw_admin_only(client_noauth, admin_tok, ingenieur_tok):
    r = client_noauth.get("/projects", headers=_hdr(admin_tok))
    projects = r.json()
    if not projects:
        pytest.skip("Aucun projet en DB")
    pid = projects[0]["id"]

    # Admin → 200
    r = client_noauth.get(
        f"/projects/{pid}/measurements/raw?event_code=CELLMEAS&limit=5",
        headers=_hdr(admin_tok),
    )
    assert r.status_code == 200, r.text
    # Ingénieur → 403
    r = client_noauth.get(
        f"/projects/{pid}/measurements/raw?event_code=CELLMEAS&limit=5",
        headers=_hdr(ingenieur_tok),
    )
    assert r.status_code == 403


def test_no_identity_in_staging():
    """Grep défensif : aucune identité IMSI/IMEI 15 chiffres dans
    `stg_measurement_raw.raw_fields` (le décodeur masque à la source)."""
    import re
    pat = re.compile(r"(?<!\d)\d{15}(?!\d)")
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT raw_fields::text AS t FROM stg_measurement_raw LIMIT 500"
            )
        ).all()
    leaks = []
    for r in rows:
        if r.t and pat.search(r.t):
            # ID masqué commence par "ID_" + hex — le pattern 15 digits
            # ne matche pas sur ces jetons. Toute occurrence réelle est
            # une fuite.
            leaks.append(r.t[:120])
    assert not leaks, f"identités en clair dans stg_measurement_raw: {leaks[:3]}"
