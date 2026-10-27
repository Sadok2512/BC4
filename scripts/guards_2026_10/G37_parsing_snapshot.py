#!/usr/bin/env python3
"""G37 — project parsing changes never rewrite capture/job snapshots."""
import os, sys
from pathlib import Path
from urllib.parse import urlparse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

dsn=os.environ.get("BC4_DSN", "")
parsed=urlparse(dsn.replace("postgresql+psycopg", "postgresql", 1))
ephemeral_host = (parsed.hostname or "").startswith("bc1-")
non_live_port = parsed.port not in (None, 5432)
if os.environ.get("G37_EPHEMERAL_DB") != "YES" or not (ephemeral_host or non_live_port) or parsed.path.rstrip("/") in ("","/bc4"):
    print("G37 VERDICT=FAIL unsafe_or_missing_ephemeral_dsn"); raise SystemExit(2)
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.main import app

engine=create_engine(dsn,future=True)
with engine.connect() as conn:
    fixture=conn.execute(text("""SELECT p.id project_id,c.capture_id FROM projects p JOIN nmf_capture c ON c.project_id=p.id
        WHERE p.owner_id='TEST-G34-USER-A' ORDER BY c.capture_id LIMIT 1""")).mappings().first()
if fixture is None:
    print("G37 VERDICT=FAIL g34_fixture_absent"); raise SystemExit(2)

with TestClient(app,raise_server_exceptions=False) as client:
    auth=client.post('/auth/login',json={'email':'test-g34-a@example.invalid','password':'TEST-G34-A-only-9!'})
    token=auth.json()['token']; headers={'Authorization':f'Bearer {token}'}
    capture_key={"pid":fixture["project_id"],"cap":fixture["capture_id"]}
    with engine.connect() as conn:
        before=conn.execute(text("""SELECT decode_level,binning_mode,temporal_resolution,spatial_bin_m,
            aggregation_contract_version,decoder_version FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap"""),capture_key).mappings().one()
    changed=client.patch(f"/projects/{fixture['project_id']}/parsing",headers=headers,json={
        'parse_decode_level':'deep','parse_binning_mode':'spatial','parse_temporal_resolution':None,'parse_spatial_bin_m':50})
    with engine.connect() as conn:
        after=conn.execute(text("""SELECT decode_level,binning_mode,temporal_resolution,spatial_bin_m,
            aggregation_contract_version,decoder_version FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap"""),capture_key).mappings().one()
    queued=client.post(f"/projects/{fixture['project_id']}/decode",headers=headers,params={'level':'deep','capture_id':fixture['capture_id']})

print(f"G37 project_id={fixture['project_id']} capture_id={fixture['capture_id']}")
print(f"G37 capture_before={dict(before)}")
print(f"G37 project_patch_http={changed.status_code}")
print(f"G37 capture_after={dict(after)}")
if queued.status_code == 202:
    job=queued.json(); print("G37 job_snapshot="+str({k:job[k] for k in ('decode_level','binning_mode','temporal_resolution','spatial_bin_m','aggregation_contract_version','decoder_version')}))
ok=changed.status_code==200 and dict(before)==dict(after) and queued.status_code==202 and queued.json()['binning_mode']=='spatial' and queued.json()['spatial_bin_m']==50
print("G37 VERDICT="+("PASS" if ok else "FAIL")); raise SystemExit(0 if ok else 1)
