"""Opération unique — backfill snapshot d'import pour le job legacy Test_5.

Le job `c67112ccda3d4e39aae5bc1ffb171904` a été créé avant la migration
`0061_import_job_parsing_snapshot` : ses 6 colonnes de snapshot sont NULL.
La garde `parsing_snapshot()` du worker refuse donc tout retry (ValueError
`import_job_parsing_snapshot_missing`).

Ce script applique la MÊME logique que `app.services.import_jobs.enqueue()`
(lignes 76-82) : les 4 defaults projet + les 2 constantes code (contrat
d'agrégation + DECODER_VERSION live). Aucune valeur tapée à la main.

Discipline :
- opération UNIQUE sur ce job (vérifié par CLI argument explicit) ;
- refuse si les 6 fields ne sont pas tous NULL (idempotence stricte) ;
- SELECT avant + SELECT après imprimés ;
- vérification `nmf_capture.decoder_version` des 22 captures déjà
  terminées : elles doivent rester à '1.7.1' (snapshot per-capture
  posé à l'ingest original, inchangé par ce backfill).

Lancement : `docker exec bc4-api-1 python /tmp/backfill_test5_legacy_snapshot.py`
"""
from __future__ import annotations

import sys

from sqlalchemy import text

from app.db import SessionLocal
from app.models import NmfImportJob, Project
from app.nmf_decoder import DECODER_VERSION


EXPECTED_JOB_ID = "c67112ccda3d4e39aae5bc1ffb171904"
EXPECTED_PROJECT_ID = "d8d14aefa51f"


def main() -> int:
    with SessionLocal() as db:
        job = db.get(NmfImportJob, EXPECTED_JOB_ID)
        if job is None:
            print(f"FAIL: job {EXPECTED_JOB_ID} introuvable", file=sys.stderr)
            return 2
        if job.project_id != EXPECTED_PROJECT_ID:
            print(f"FAIL: job project mismatch (expected {EXPECTED_PROJECT_ID}, got {job.project_id})",
                  file=sys.stderr)
            return 2

        snapshot_cols = (
            "decode_level",
            "binning_mode",
            "temporal_resolution",
            "spatial_bin_m",
            "aggregation_contract_version",
            "decoder_version",
        )

        before = {c: getattr(job, c) for c in snapshot_cols}
        print("BEFORE job snapshot:")
        for c, v in before.items():
            print(f"  {c} = {v!r}")

        non_null = [c for c, v in before.items() if v is not None]
        if non_null:
            print(f"REFUSE: job snapshot déjà rempli sur {non_null} — opération non idempotente", file=sys.stderr)
            return 3

        project = db.get(Project, job.project_id)
        if project is None:
            print(f"FAIL: project {job.project_id} introuvable", file=sys.stderr)
            return 2

        # Même logique que app.services.import_jobs.enqueue (lignes 76-82) :
        # 4 defaults projet + 2 constantes code.
        job.decode_level = project.parse_decode_level
        job.binning_mode = project.parse_binning_mode
        job.temporal_resolution = project.parse_temporal_resolution
        job.spatial_bin_m = project.parse_spatial_bin_m
        job.aggregation_contract_version = "query-binning-v1"
        job.decoder_version = DECODER_VERSION

        db.commit()
        db.refresh(job)

        after = {c: getattr(job, c) for c in snapshot_cols}
        print("\nAFTER job snapshot:")
        for c, v in after.items():
            print(f"  {c} = {v!r}")

        # Captures déjà terminées : leur decoder_version doit rester à '1.7.1'
        # (snapshot per-capture figé par 0061 au moment de l'ingest original).
        rows = db.execute(text("""
            SELECT decoder_version, COUNT(*) AS n
            FROM nmf_capture
            WHERE project_id = :pid
            GROUP BY decoder_version
            ORDER BY decoder_version
        """), {"pid": job.project_id}).all()
        print("\nnmf_capture.decoder_version pour project (inchangé par ce backfill) :")
        for decoder_version, n in rows:
            print(f"  {decoder_version} → {n} captures")

    print("\nOK — backfill snapshot legacy Test_5 appliqué, worker peut reprendre")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
