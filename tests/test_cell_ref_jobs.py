from io import BytesIO

import pytest
from fastapi import UploadFile
from sqlalchemy import text

from app.db import SessionLocal
from app.services import cell_ref_jobs


HEADER = (
    "id,snapshot_date,rat,vendor,sac_ci_eci,nci,enodebid,pci,band,techno,"
    "earfcn,azimuth,tilt,height,coverage,cell_class,etat_fonctionnement,"
    "nom_upr,nom_dr,plaque_site,id_site,site_name,sector,cell_op_leader,"
    "cat_arcep_code,longitude,latitude\n"
)
ROW = (
    "job-cell,2026-10-01,4G,Ericsson,41000001,,10001,21,LTE800,LTE,6400,"
    "120,2,30,outdoor,macro,OPERATIONAL,UPR-A,DR-IDF,Paris,SITE-01,Paris,"
    "1,Orange,01/ Top15,2.3350,48.8700\n"
)


@pytest.fixture()
def clean_reference_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(cell_ref_jobs, "REFERENCE_DIR", tmp_path)
    with SessionLocal() as db:
        db.execute(text("TRUNCATE TABLE cell_ref"))
        db.execute(text("TRUNCATE TABLE reference_import"))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(text("TRUNCATE TABLE cell_ref"))
        db.execute(text("TRUNCATE TABLE reference_import"))
        db.commit()


def test_queued_upload_is_processed_and_updates_history(clean_reference_tables):
    upload = UploadFile(filename="witness.csv", file=BytesIO((HEADER + ROW).encode()))
    with SessionLocal() as db:
        accepted = cell_ref_jobs.enqueue(db, upload, "admin")
        assert accepted["status"] == "queued"
        assert cell_ref_jobs.get_job(db, accepted["job_id"])["progress_percent"] == 0
        assert cell_ref_jobs.process_next(db) is True
        job = cell_ref_jobs.get_job(db, accepted["job_id"])
        assert job["status"] == "completed"
        assert job["progress_percent"] == 100
        assert job["rows_read"] == 1
        assert job["rows_loaded"] == 1
        assert job["report"]["rows_loaded"] == 1


def test_invalid_csv_becomes_failed_job_with_clear_reason(clean_reference_tables):
    upload = UploadFile(filename="bad.csv", file=BytesIO(b"foo,bar\n1,2\n"))
    with SessionLocal() as db:
        accepted = cell_ref_jobs.enqueue(db, upload, "admin")
        assert cell_ref_jobs.process_next(db) is True
        job = cell_ref_jobs.get_job(db, accepted["job_id"])
        assert job["status"] == "failed"
        assert job["error"]["code"] == "HeaderError"
        assert job["error"]["reason"]
