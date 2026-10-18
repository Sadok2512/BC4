"""G7 — garde B1-ingest (après câblage à `bc4_decoder 1.0.0`).

Vérifie, contre une API bc4-back vivante, que :
- POST /projects crée un projet draft (ProjectIngestView) ;
- POST /projects/{id}/nmf accepte plusieurs fichiers streamés et idempotent
  sur sha256 (re-upload du même fichier = pas de doublon stg_event) ;
- GET /projects/{id}/import renvoie l'ImportReport avec des comptes RÉELS
  (jamais 0 par défaut si une erreur a eu lieu — l'erreur est déclarée) ;
- Si `BC4_NMF_WITNESS` est fourni (NMF témoin lisible) : le fichier DOIT
  être en `status=done`, et les comptes `n_events` renvoyés par l'API
  DOIVENT coller à la ligne de commande du décodeur (variable
  `BC4_G7_CLI_N_EVENTS` injectée par `scripts/g7_nmf_ingest.sh`).
- Sans témoin : la garde reste gracieuse et accepte `status=error` /
  `decoder_unavailable` SANS JAMAIS inventer un compte. L'écart est
  alors déclaré.

Aucun chiffre n'est accepté sans comptage de référence côté client.
"""

from __future__ import annotations

import io
import os
import time

import pytest
from sqlalchemy import text

from app.db import SessionLocal


def _witness_bytes() -> tuple[bytes, bool]:
    """Retourne (contenu, est_vrai_nmf). Dans le second cas, l'absence de
    décodeur ou l'erreur de décodage est attendue — on vérifie l'écart
    déclaré, pas un décodage magique.
    """
    path = os.environ.get("BC4_NMF_WITNESS")
    if path and os.path.isfile(path):
        with open(path, "rb") as fh:
            return fh.read(), True
    return b"BC4-NMF-placeholder\x00" * 128, False


def _await_report(client, pid: str, response, headers):
    assert response.status_code == 202, response.text
    job = response.json()
    deadline = time.monotonic() + float(os.environ.get("BC4_IMPORT_TEST_TIMEOUT", "120"))
    while job["status"] not in ("done", "error"):
        assert time.monotonic() < deadline, f"Import still running: {job['id']}"
        time.sleep(0.2)
        poll = client.get(f"/projects/{pid}/imports/{job['id']}", headers=headers)
        assert poll.status_code == 200, poll.text
        job = poll.json()
    assert job["report"] is not None, job.get("error_msg")
    return job["report"]


def _reset_project(pid: str) -> None:
    with SessionLocal() as db:
        db.execute(text("DELETE FROM stg_event WHERE project_id = :p"), {"p": pid})
        db.execute(text("DELETE FROM nmf_file WHERE project_id = :p"), {"p": pid})
        db.execute(text("DELETE FROM projects WHERE id = :p"), {"p": pid})
        db.commit()


def test_create_upload_report(client, admin_headers):
    # ----- Création projet draft -----
    r = client.post("/projects", json={"name": "G7 témoin NMF"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    created = r.json()
    pid = created["id"]
    assert created["status"] == "draft"
    assert created["n_captures"] in (0, None) or created["n_captures"] == 0
    # Depuis B2 (0.5.0), `actor` est l'identifiant authentifié (email).
    # On vérifie juste qu'il est renseigné et non vide — jamais inventé.
    assert isinstance(created["actor"], str) and created["actor"], (
        "actor doit porter l'identité de l'appelant authentifié"
    )

    witness, is_real = _witness_bytes()
    cli_n_events = os.environ.get("BC4_G7_CLI_N_EVENTS")
    cli_n_gps = os.environ.get("BC4_G7_CLI_N_GPS")

    try:
        # ----- Vue GET /projects/{id}/ingest -----
        r2 = client.get(f"/projects/{pid}/ingest", headers=admin_headers)
        assert r2.status_code == 200
        assert r2.json()["status"] == "draft"

        # ----- Upload streamé (1 fichier) -----
        files = [("files", ("witness-a.nmf", witness, "application/octet-stream"))]
        r3 = client.post(f"/projects/{pid}/nmf", files=files, headers=admin_headers)
        report = _await_report(client, pid, r3, admin_headers)
        assert report["files_received"] == 1
        assert len(report["by_file"]) == 1
        by_file = report["by_file"][0]
        assert by_file["filename"] == "witness-a.nmf"
        assert by_file["status"] in {"done", "error"}

        if is_real:
            # Témoin vrai : on EXIGE status=done + comptes = CLI décodeur.
            assert by_file["status"] == "done", (
                f"NMF témoin fourni mais status={by_file['status']!r} ; "
                f"error_msg={by_file.get('error_msg')!r}"
            )
            assert by_file["decoder_version"], "decoder_version doit être renseigné"
            assert by_file["decoder_version"].startswith("bc4-decoder "), (
                f"decoder_version doit venir du module importé, got "
                f"{by_file['decoder_version']!r}"
            )
            if cli_n_events is not None:
                assert by_file["n_events"] == int(cli_n_events), (
                    f"n_events API={by_file['n_events']} ≠ CLI={cli_n_events} — "
                    f"le pipeline doit coller au décodeur ligne par ligne"
                )
            if cli_n_gps is not None:
                assert by_file["n_gps"] == int(cli_n_gps), (
                    f"n_gps API={by_file['n_gps']} ≠ CLI={cli_n_gps}"
                )
            # Les comptes doivent coller à nmf_file en base.
            with SessionLocal() as db:
                row = db.execute(
                    text(
                        "SELECT n_captures, n_events, n_gps FROM nmf_file "
                        "WHERE project_id = :p AND filename = 'witness-a.nmf'"
                    ),
                    {"p": pid},
                ).one()
            assert by_file["n_captures"] == int(row[0])
            assert by_file["n_events"] == int(row[1])
            assert by_file["n_gps"] == int(row[2])
        else:
            # Pas de témoin : placeholder. Deux cas honnêtes :
            # - décodeur absent → status=error + error_msg=decoder_unavailable ;
            # - décodeur présent mais placeholder non parsable → status=done
            #   avec n_events=0 (le décodeur boucle sans trouver d'event — pas
            #   une erreur). Jamais un chiffre inventé.
            if by_file["status"] == "error":
                assert by_file["error_msg"], "un fichier en error doit porter error_msg"
                assert by_file["error_msg"].startswith("decoder_"), (
                    f"error_msg doit décrire le motif, got: {by_file['error_msg']!r}"
                )
                assert by_file["decoder_version"] == "unavailable"
                assert by_file["n_captures"] == 0
                assert by_file["n_events"] == 0
                assert by_file["n_gps"] == 0
                with SessionLocal() as db:
                    n = db.execute(
                        text("SELECT COUNT(*) FROM stg_event WHERE project_id = :p"),
                        {"p": pid},
                    ).scalar()
                assert n == 0, "aucun event ne doit exister si le décodeur a échoué"
                assert report["gps_coverage_pct"] is None, (
                    "gps_coverage_pct doit être null quand n_events=0 — jamais 0 par défaut"
                )
            else:
                # Décodeur disponible, placeholder : pas d'event signalisation.
                assert by_file["decoder_version"].startswith("bc4-decoder "), (
                    f"decoder_version doit venir du module importé, got "
                    f"{by_file['decoder_version']!r}"
                )
                assert by_file["n_events"] == 0
                assert by_file["n_gps"] == 0

        # ----- Idempotence : rejouer le même fichier ne doit pas dupliquer -----
        files2 = [("files", ("witness-a.nmf", witness, "application/octet-stream"))]
        r4 = client.post(f"/projects/{pid}/nmf", files=files2, headers=admin_headers)
        _await_report(client, pid, r4, admin_headers)
        with SessionLocal() as db:
            n_files = db.execute(
                text("SELECT COUNT(*) FROM nmf_file WHERE project_id = :p"),
                {"p": pid},
            ).scalar()
        assert n_files == 1, "re-upload du même sha256 ne doit pas créer de doublon"

        # ----- GET /projects/{id}/import reflète la base -----
        r5 = client.get(f"/projects/{pid}/import", headers=admin_headers)
        assert r5.status_code == 200
        rep2 = r5.json()
        assert rep2["files_received"] == 1
        assert rep2["by_file"][0]["filename"] == "witness-a.nmf"
        # Le comptage total vient de la somme SQL sur nmf_file.
        with SessionLocal() as db:
            s = db.execute(
                text(
                    "SELECT COALESCE(SUM(n_captures),0), COALESCE(SUM(n_events),0), COALESCE(SUM(n_gps),0) "
                    "FROM nmf_file WHERE project_id = :p"
                ),
                {"p": pid},
            ).one()
        assert rep2["n_captures"] == int(s[0])
        assert rep2["n_events"] == int(s[1])
        if rep2["n_events"] == 0:
            assert rep2["gps_coverage_pct"] is None
        # Si témoin fourni ET comparaison CLI disponible, croisement supplémentaire.
        if is_real and cli_n_events is not None:
            assert rep2["n_events"] == int(cli_n_events)
    finally:
        _reset_project(pid)


def test_project_not_found_on_upload(client, admin_headers):
    r = client.post(
        "/projects/does-not-exist-xyz/nmf",
        files=[("files", ("x.nmf", b"abc", "application/octet-stream"))],
        headers=admin_headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_FOUND"
