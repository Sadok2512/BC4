"""G44 — snapshot de capture immuable sauf re-parse explicite.

Après la reprise d'un job avec N fichiers `done` et M fichiers `error`
par la commande `requeue_import_decoder_172_failures` (ou
`requeue_import_schema_failures`), **seuls les M fichiers sont
redécodés**. Les N captures issues des fichiers `done` doivent
conserver à l'identique :

- les 6 colonnes du snapshot (`decode_level`, `decoder_version`,
  `schema_version`, `binning_mode`, `temporal_resolution`,
  `spatial_bin_m`, `aggregation_contract_version`) ;
- l'empreinte de lignes (`n_records`, `n_partial` dans `nmf_capture` ;
  `COUNT(*)` dans `stg_event_raw`, `nmf_event_deep`, `nmf_event_light`,
  `nmf_event_pair`) ;
- l'horodatage `decoded_at` (sinon preuve d'une réécriture).

Le re-décodage n'est autorisé **que** via `app.scripts.reparse_capture`
avec `force=True` et un `--reason` tracé.

Garde :
- `G44_EPHEMERAL_DB=YES` + DSN non-prod obligatoires (même règle G41) ;
- scénario reproductible sur base jetable, aucun écrit en prod ;
- sortie complète : par capture, les deltas sont imprimés et le verdict
  est explicite.

Scénario :
  1. Projet TEST-G44, 2 vrais NMF uploadés par la route applicative.
  2. Un worker in-process (`run_import_job`) + `populate_chain` complet
     → 2 captures `done`.
  3. Snapshot A : états de chaque capture + comptes par table.
  4. Opération applicative : simule un échec décodeur 1.7.2 sur 1 fichier
     en patchant `job.files[k]` via ORM (status='error', marker exact).
  5. `requeue_import_decoder_172_failures` → ce fichier passe `pending`.
  6. `run_import_job` + `populate_chain` → le fichier est redécodé.
  7. Snapshot B : états de chaque capture + comptes par table.
  8. Comparaison A vs B :
     - 1 capture (fichier remis en file) : son `decoded_at` doit avoir
       avancé → marquée re-décodée (acceptable, c'est le fichier M) ;
     - 1 capture (fichier `done`) : `decoded_at` + snapshot + comptes
       doivent être **strictement identiques** → `PASS`.
     FAIL si une capture `done` a bougé (snapshot ou comptes),
     FAIL si une capture `pending` n'a pas été redécodée.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


# ---- Safety gate ------------------------------------------------------------

def fail_pre(msg: str) -> None:
    print(f"G44 PRECONDITION FAIL: {msg}", file=sys.stderr)
    raise SystemExit(2)


dsn = os.environ.get("BC4_DSN", "")
if os.environ.get("G44_EPHEMERAL_DB") != "YES":
    fail_pre("G44_EPHEMERAL_DB=YES is required")
if not dsn:
    fail_pre("BC4_DSN is required")
parsed = urlparse(dsn.replace("postgresql+psycopg", "postgresql", 1))
if parsed.port in (None, 5432) or parsed.path.rstrip("/") in ("", "/bc4"):
    fail_pre(f"refusing non-ephemeral DSN host={parsed.hostname} port={parsed.port} db={parsed.path}")


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import NmfImportJob  # noqa: E402
from app.services.auth import hash_password  # noqa: E402
from app.services.import_worker import run_job as run_import_job  # noqa: E402


ADMIN_ID = "TEST-G44-ADMIN"
ADMIN_EMAIL = "test-g44-admin@example.invalid"
ADMIN_PASSWORD = "TEST-G44-admin-only-9!"

DECODER_172_MARKER = "unsupported operand type(s) for +=: 'float' and 'str'"

NMF_PATHS = [
    "/home/devmat/BC4/witness-nmf/Mesures Indoor/BCNE 26S24_VD_T_MESURE-BENCH-CENTRE-COMMERCIAL-PETITE-FORET_indoor_26Jun11_111346.7.nmf",
    "/home/devmat/BC4/witness-nmf/Mesures Indoor/BCNE 26S24_VD_T_MESURE-BENCH-CENTRE-COMMERCIAL-PETITE-FORET_indoor_26Jun11_112544.6.nmf",
]

SNAPSHOT_COLS = (
    "decode_level", "decoder_version", "schema_version", "format_version",
    "binning_mode", "temporal_resolution", "spatial_bin_m",
    "aggregation_contract_version",
)
ROW_COUNT_TABLES = ("stg_event_raw", "nmf_event_deep", "nmf_event_light", "nmf_event_pair")


engine = create_engine(dsn, future=True)


def seed_admin() -> None:
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM app_user WHERE email=:e"), {"e": ADMIN_EMAIL})
        conn.execute(text("""
            INSERT INTO app_user(id,email,password_hash,role,active,created_at)
            VALUES (:id,:email,:password_hash,'admin',true,:created_at)
        """), {"id": ADMIN_ID, "email": ADMIN_EMAIL,
               "password_hash": hash_password(ADMIN_PASSWORD),
               "created_at": now})


def login(client: TestClient) -> str:
    r = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        fail_pre(f"login returned {r.status_code}: {r.text[:200]}")
    return r.json()["token"]


def create_project(client: TestClient, token: str) -> str:
    r = client.post("/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "TEST-G44 immutable snapshot",
              "visibility": "private",
              "parse_decode_level": "deep",
              "parse_binning_mode": "temporal",
              "parse_temporal_resolution": "native",
              "parse_spatial_bin_m": None})
    if r.status_code != 201:
        fail_pre(f"POST /projects → {r.status_code}: {r.text[:300]}")
    return r.json()["id"]


def upload_and_run(client: TestClient, token: str, project_id: str,
                   paths: list[str]) -> str:
    files = []
    opened = []
    try:
        for p in paths:
            path = Path(p)
            if not path.is_file():
                fail_pre(f"missing NMF: {p}")
            fh = path.open("rb")
            opened.append(fh)
            files.append(("files", (path.name, fh, "application/octet-stream")))
        r = client.post(f"/projects/{project_id}/nmf",
                        headers={"Authorization": f"Bearer {token}"},
                        files=files)
    finally:
        for fh in opened:
            fh.close()
    if r.status_code != 202:
        fail_pre(f"POST /nmf → {r.status_code}: {r.text[:300]}")
    jid = r.json()["id"]
    with SessionLocal() as db:
        job = db.get(NmfImportJob, jid)
        run_import_job(db, job)
    return jid


def snapshot_captures(project_id: str) -> dict[str, dict]:
    """Snapshot complet par capture_id : 6 cols + n_records + n_partial +
    decoded_at + COUNT par table."""
    out: dict[str, dict] = {}
    with engine.connect() as conn:
        caps = conn.execute(text(f"""
            SELECT capture_id, {', '.join(SNAPSHOT_COLS)},
                   n_records, n_partial, decoded_at, deep_decoded_at
            FROM nmf_capture WHERE project_id = :pid
            ORDER BY capture_id
        """), {"pid": project_id}).mappings().all()
        for cap in caps:
            d = dict(cap)
            counts = {}
            for table in ROW_COUNT_TABLES:
                counts[table] = conn.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE project_id=:pid AND capture_id=:cap"),
                    {"pid": project_id, "cap": cap["capture_id"]}
                ).scalar()
            d["counts"] = counts
            out[cap["capture_id"]] = d
    return out


def mark_file_as_decoder_172_failure(job_id: str, filename: str) -> str:
    """Simule l'échec décodeur 1.7.2 sur un fichier déjà `done` : patch
    `job.files` via ORM pour le repasser status='error' avec le marker
    `requeue_import_decoder_172_failures` reconnaît. Trouve aussi le
    `capture_id` à retirer (sinon la capture reste orpheline)."""
    with SessionLocal() as db:
        job = db.get(NmfImportJob, job_id)
        if job is None:
            fail_pre(f"job {job_id} introuvable")
        patched = []
        touched = None
        for entry in job.files:
            e = dict(entry)
            if e.get("filename") == filename and e.get("status") == "done":
                touched = e.get("filename")
                e.update(status="error", error_msg=DECODER_172_MARKER,
                         n_captures=0, n_events=0, n_gps=0,
                         decoder_version=None)
            patched.append(e)
        if touched is None:
            fail_pre(f"file {filename} not in job.files or not 'done'")
        job.files = patched
        job.status = "error"
        job.error_msg = DECODER_172_MARKER
        db.commit()
    # Supprime la capture et ses lignes (prépare le ré-import, comme si
    # le worker avait abandonné avant l'INSERT nmf_capture).
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT c.capture_id FROM nmf_capture c
            JOIN nmf_file f ON f.id = c.nmf_file_id
            WHERE f.project_id = (SELECT project_id FROM nmf_import_jobs WHERE id=:j)
              AND f.filename = :fn
        """), {"j": job_id, "fn": filename}).first()
        if row is not None:
            cap = row[0]
            for table in ("stg_event_raw", "stg_event", "nmf_event_deep",
                          "nmf_event_group", "nmf_event_light",
                          "nmf_event_light_group", "nmf_event_pair"):
                conn.execute(text(f"""
                    DELETE FROM {table}
                    WHERE project_id=(SELECT project_id FROM nmf_capture WHERE capture_id=:c LIMIT 1)
                      AND capture_id=:c
                """), {"c": cap})
            conn.execute(text("DELETE FROM nmf_capture WHERE capture_id=:c"), {"c": cap})
            conn.execute(text("DELETE FROM nmf_file WHERE filename=:fn"), {"fn": filename})
    return touched


def diff_capture(before: dict, after: dict) -> list[str]:
    diffs = []
    for k in (*SNAPSHOT_COLS, "n_records", "n_partial", "decoded_at", "deep_decoded_at"):
        if before.get(k) != after.get(k):
            diffs.append(f"{k}: {before.get(k)!r} → {after.get(k)!r}")
    for table in ROW_COUNT_TABLES:
        if before["counts"].get(table) != after["counts"].get(table):
            diffs.append(f"counts.{table}: {before['counts'].get(table)} → {after['counts'].get(table)}")
    return diffs


def main() -> int:
    out_dir = Path(__file__).resolve().parents[2] / "audit" / "g44-reparse-boundary"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[G44] seeding admin ephemeral DB")
    seed_admin()

    with TestClient(app, raise_server_exceptions=False) as client:
        token = login(client)
        print("[G44] creating project + uploading 2 NMFs")
        pid = create_project(client, token)
        jid1 = upload_and_run(client, token, pid, NMF_PATHS)

        print("[G44] snapshot A (après ingestion normale, 2 captures done)")
        before = snapshot_captures(pid)
        print(f"  {len(before)} captures done")
        for cap_id, d in before.items():
            print(f"  cap={cap_id} decoded_at={d['decoded_at']} "
                  f"decoder_version={d['decoder_version']} "
                  f"n_records={d['n_records']} "
                  f"counts={d['counts']}")

        # On patch le FICHIER .6 pour qu'il repasse en 'error'/pending via
        # la commande applicative requeue_import_decoder_172_failures.
        # Le .7 reste done — c'est lui qu'on surveille.
        file_to_requeue = Path(NMF_PATHS[1]).name
        print(f"\n[G44] simulating decoder 1.7.2 failure on {file_to_requeue}")
        mark_file_as_decoder_172_failure(jid1, file_to_requeue)

        # requeue
        print("[G44] running requeue_import_decoder_172_failures")
        from app.scripts.requeue_import_decoder_172_failures import requeue
        n = requeue(jid1)
        print(f"  files requeued: {n}")

        # re-run worker
        print("[G44] run_import_job (should re-decode ONLY requeued file)")
        with SessionLocal() as db:
            job = db.get(NmfImportJob, jid1)
            run_import_job(db, job)

        print("\n[G44] snapshot B (après reprise)")
        after = snapshot_captures(pid)
        print(f"  {len(after)} captures")
        for cap_id, d in after.items():
            print(f"  cap={cap_id} decoded_at={d['decoded_at']} "
                  f"decoder_version={d['decoder_version']} "
                  f"n_records={d['n_records']} "
                  f"counts={d['counts']}")

        # Comparaison : les captures présentes dans BOTH before/after doivent
        # être strictement identiques (ne font pas partie des M fichiers remis).
        # Les captures nouvelles (créées lors du re-import) correspondent au
        # fichier remis en file et ne sont pas dans `before` ou leur capture_id
        # change (nouveau nmf_file_id). On compte :
        #   - fails_frozen   : captures `before` dont la version `after`
        #                      diffère sur un champ immuable → FAIL
        #   - new_captures   : captures présentes dans `after` et pas `before`
        #                      → attendues (M fichiers)
        fails: list[str] = []
        unchanged = 0
        for cap_id, b in before.items():
            if cap_id not in after:
                fails.append(f"capture {cap_id} disparue après reprise (snapshot non immuable)")
                continue
            diffs = diff_capture(b, after[cap_id])
            if diffs:
                fails.append(f"capture {cap_id} modifiée (snapshot non immuable): {diffs}")
            else:
                unchanged += 1
        new_captures = [c for c in after if c not in before]
        print(f"\n[G44] frozen captures: {unchanged} (expected ≥ 1)")
        print(f"[G44] new captures   : {len(new_captures)} (expected = 1)")
        if len(new_captures) != 1:
            fails.append(f"expected exactly 1 new capture after requeue, got {len(new_captures)}")

        verdict = "PASS" if not fails else "FAIL"
        print(f"\nG44_VERDICT {verdict} frozen={unchanged} new={len(new_captures)} fails={len(fails)}")
        if fails:
            print("\n== G44 fails ==")
            for f in fails:
                print(f"  - {f}")

        (out_dir / "snapshot_before.json").write_text(json.dumps(before, indent=2, default=str))
        (out_dir / "snapshot_after.json").write_text(json.dumps(after, indent=2, default=str))
        (out_dir / "verdict.json").write_text(json.dumps({
            "verdict": verdict,
            "fails": fails,
            "frozen_captures": unchanged,
            "new_captures": new_captures,
            "ephemeral_dsn": dsn,
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2))

        return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
