"""End-to-end Light/Deep/superstream query-bin scenarios on an ephemeral DB."""
from __future__ import annotations

import os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fastapi import UploadFile
from sqlalchemy import null, text

from app.db import SessionLocal
from app.kpi.nmf_bins import query_metric_bins
from app.models import NmfImportJob, Project, Superstream, SuperstreamMember
from app.services.import_jobs import enqueue
from app.services.import_worker import run_job


def fail(reason, code=1):
    print(f"G45 VERDICT=FAIL reason={reason}")
    raise SystemExit(code)


def project(owner, project_id, level, mode, temporal=None, spatial=None):
    return Project(id=project_id,owner_id=owner,visibility="private",name=project_id,
      geography="",center_lng=0,center_lat=0,operators=[],technologies=[],services=[],bands=[],
      departements=[],period_start="",period_end="",captures=0,imported_at="",status="processing",
      status_ingest="importing",parse_decode_level=level,parse_binning_mode=mode,
      parse_temporal_resolution=null() if mode=="spatial" else temporal,
      parse_spatial_bin_m=spatial)


def ingest(db, pid, paths):
    uploads=[UploadFile(filename=path.name,file=path.open("rb")) for path in paths]
    job=enqueue(db,pid,uploads);jid=job.id
    run_job(db,db.get(NmfImportJob,jid))
    refreshed=db.get(NmfImportJob,jid)
    statuses=[entry["status"] for entry in refreshed.files]
    if statuses != ["done"]*len(paths):fail(f"import_{pid}_{statuses}")
    return db.execute(text("SELECT capture_id,n_records FROM nmf_capture WHERE project_id=:pid ORDER BY capture_id"),{"pid":pid}).all()


def main():
    if os.environ.get("G45_EPHEMERAL_DB") != "YES":fail("ephemeral_required",2)
    paths=[Path(value) for value in os.environ.get("G45_NMF_PATHS","").split("::") if value]
    if len(paths)<2 or any(not path.is_file() for path in paths):fail("two_real_paths_required",2)
    with SessionLocal() as db:
        if db.execute(text("SELECT current_database()" )).scalar_one()=="bc4":fail("live_database",2)
        owner=db.execute(text("SELECT id FROM app_user ORDER BY created_at,id LIMIT 1")).scalar_one()
        suffix=uuid.uuid4().hex[:8];light_id="g45-light-"+suffix;deep_id="g45-deep-"+suffix
        db.add(project(owner,light_id,"light","temporal","10ms"))
        db.add(project(owner,deep_id,"deep","spatial",spatial=50));db.commit()
        light_caps=ingest(db,light_id,paths[:1]);deep_caps=ingest(db,deep_id,paths[:2])
        light_cap,light_n=light_caps[0]
        light_resolution,light_bins=query_metric_bins(db,light_id,light_cap,"cqi_sample_duration")
        if light_resolution["temporal"]!="10ms" or sum(row["n_records"] for row in light_bins)!=light_n:
            fail("light_temporal_10ms_population")
        deep_results=[]
        for deep_cap,deep_n in deep_caps:
            resolution,bins=query_metric_bins(db,deep_id,deep_cap,"cqi_sample_duration")
            if resolution["spatial"]!=50 or sum(row["n_records"] for row in bins)!=deep_n:
                fail("deep_spatial_50m_population")
            if any(row["capture_id"]!=deep_cap for row in bins):fail("deep_capture_mix")
            deep_results.append((deep_cap,len(bins),deep_n))
        now=datetime.now(timezone.utc);sid="g45-ss-"+suffix
        db.add(Superstream(id=sid,project_id=deep_id,name="G45",created_by=owner,created_at=now,updated_at=now))
        for position,(capture_id,_) in enumerate(deep_caps):
            db.add(SuperstreamMember(superstream_id=sid,position=position,project_id=deep_id,capture_id=capture_id))
        db.commit()
        members=db.execute(text("SELECT position,capture_id FROM superstream_member WHERE superstream_id=:sid ORDER BY position"),{"sid":sid}).all()
        if [row[0] for row in members] != list(range(len(members))):fail("superstream_order")
        if len({row[1] for row in members}) != len(members):fail("superstream_duplicate_capture")
        print(f"G45 light project={light_id} capture={light_cap} snapshot=temporal/10ms records={light_n} bins={len(light_bins)}")
        print(f"G45 deep project={deep_id} snapshot=spatial/50m captures={deep_results}")
        print(f"G45 superstream={sid} members={members} order=position,capture_id,seq")
        print("G45 VERDICT=PASS")


if __name__=="__main__":
    try: main()
    except SystemExit: raise
    except Exception as exc:
        print(f"G45 VERDICT=FAIL reason=unexpected_{type(exc).__name__}:{exc}")
        raise
