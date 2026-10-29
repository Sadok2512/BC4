#!/usr/bin/env python3
"""Build the disposable parcours fixture used by the KPI lean-table guard."""
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text

from app.db import SessionLocal
from app.ingest.nmf import ingest_upload
from app.models import AppUser, Project
from app.services.auth import hash_password
from app.services.import_worker import resolve_decoder

PROJECT_ID = "bc1-kpi-lean"
SOURCE = Path("/home/devmat/BC4/artifacts/witness-nmf/parcours_26Jun10_155941.8.nmf")


def main() -> int:
    with SessionLocal() as db:
        user = AppUser(
            id="bc1-kpi-user", email="bc1-kpi@example.invalid",
            password_hash=hash_password("bc1-kpi-test-password"),
            role="admin", active=True, created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        project = Project(
            id=PROJECT_ID, owner_id=user.id, visibility="private",
            parse_decode_level="deep", parse_binning_mode="temporal",
            parse_temporal_resolution="native", parse_spatial_bin_m=None,
            name="bc1 KPI lean disposable", geography="disposable",
            center_lng=0, center_lat=0, operators=[], technologies=[],
            services=[], bands=[], departements=[], period_start="",
            period_end="", captures=0, imported_at="", status="draft",
            created_at=datetime.now(timezone.utc), status_ingest="importing",
        )
        db.add(project)
        db.commit()
        with SOURCE.open("rb") as stream:
            nmf = ingest_upload(
                db, project, stream, SOURCE.name, resolve_decoder(), populate=False,
                parsing_snapshot={
                    "decode_level": "deep", "binning_mode": "temporal",
                    "temporal_resolution": "native", "spatial_bin_m": None,
                    "aggregation_contract_version": "query-binning-v1",
                    "decoder_version": "1.8.2",
                },
            )
        capture = db.execute(text(
            "SELECT capture_id FROM nmf_capture WHERE project_id=:pid ORDER BY capture_id"
        ), {"pid": PROJECT_ID}).scalar_one()
        print(f"G49 project_id={PROJECT_ID} capture_id={capture} file_status={nmf.status}")
        print("G49 VERDICT: PASS" if nmf.status == "done" else "G49 VERDICT: FAIL")
        return 0 if nmf.status == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
