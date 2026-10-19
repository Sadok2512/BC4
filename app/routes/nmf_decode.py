"""Admin jobs run in the existing import worker; status is an explicit OpenAPI contract."""
from datetime import datetime
from typing import Literal
import uuid
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.routes.tasks import project
from app.nmf_decoder import DECODER_VERSION
router=APIRouter(tags=['nmf-decoder'])
class DecodeJob(BaseModel):
    id:str
    project_id:str
    level:Literal['light','deep']
    capture_ids:list[str]
    decoder_version:str
    status:str
    done:int
    total:int
    created_at:datetime
    updated_at:datetime
    elapsed_s:float|None=None
    error:str|None=None
class CaptureDecode(BaseModel):
    capture_id:str
    decode_level:Literal['light','deep']
    decoder_version:str
    schema_version:str
    format_version:str
    deep_decoded_at:datetime|None
    n_records:int
    n_partial:int
    elapsed_s:float
class DecodeStatus(BaseModel):
    project_id:str
    decoder_version:str
    light:int
    deep:int
    undecoded:int
    captures:list[CaptureDecode]
    jobs:list[DecodeJob]
class UnknownField(BaseModel):
    event_code:str
    code:str
    n_buckets:int
    selectable:bool=False
    reason:str='position non prouvée'

@router.post('/projects/{project_id}/decode',response_model=DecodeJob,status_code=202)
def enqueue(project_id:str,level:Literal['light','deep']='deep',capture_id:str|None=None,db:Session=Depends(get_db),user=Depends(get_current_user)):
    if user.role!='admin':raise HTTPException(403,'admin_required')
    project(db,project_id)
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:k))'),{'k':'decode-job:'+project_id})
    caps=db.execute(text('SELECT DISTINCT capture_id FROM stg_event_raw WHERE project_id=:pid UNION SELECT DISTINCT capture_id FROM stg_event WHERE project_id=:pid ORDER BY capture_id'),{'pid':project_id}).scalars().all()
    if capture_id:
        if capture_id not in caps:raise HTTPException(404,'capture_not_found_in_project')
        caps=[capture_id]
    if not caps:raise HTTPException(409,'project_has_no_capture')
    existing=db.execute(text("SELECT * FROM nmf_decode_job WHERE project_id=:pid AND status IN ('queued','running')"),{'pid':project_id}).mappings().first()
    if existing:
        if existing['level']==level and existing['capture_ids']==caps:return existing
        raise HTTPException(409,'decode_job_already_active')
    row=db.execute(text('''INSERT INTO nmf_decode_job(id,project_id,level,capture_ids,decoder_version,status,total)
        VALUES(:id,:pid,:level,:caps,:version,'queued',:total) RETURNING *'''),dict(id=str(uuid.uuid4()),pid=project_id,level=level,caps=caps,version=DECODER_VERSION,total=len(caps))).mappings().one()
    result=dict(row);db.commit();return result

@router.get('/projects/{project_id}/decode/status',response_model=DecodeStatus)
def status(project_id:str,db:Session=Depends(get_db),user=Depends(get_current_user)):
    project(db,project_id)
    caps=db.execute(text('SELECT * FROM nmf_capture WHERE project_id=:pid ORDER BY capture_id'),{'pid':project_id}).mappings().all()
    total=db.execute(text('SELECT count(*) FROM (SELECT capture_id FROM stg_event_raw WHERE project_id=:pid UNION SELECT capture_id FROM stg_event WHERE project_id=:pid) c'),{'pid':project_id}).scalar_one()
    jobs=db.execute(text('SELECT * FROM nmf_decode_job WHERE project_id=:pid ORDER BY created_at DESC LIMIT 20'),{'pid':project_id}).mappings().all()
    return dict(project_id=project_id,decoder_version=DECODER_VERSION,light=sum(c['decode_level']=='light' for c in caps),deep=sum(c['decode_level']=='deep' for c in caps),undecoded=total-len(caps),captures=caps,jobs=jobs)

@router.get('/projects/{project_id}/metrics/unknown',response_model=list[UnknownField])
def unknown(project_id:str,db:Session=Depends(get_db),user=Depends(get_current_user)):
    project(db,project_id)
    return db.execute(text('''SELECT event_code,code,count(*)::bigint n_buckets FROM nmf_event_light
      CROSS JOIN LATERAL unnest(unknown) code WHERE project_id=:pid GROUP BY event_code,code ORDER BY event_code,code'''),{'pid':project_id}).mappings().all()
