"""Task reconstruction and privacy, with conspicuously synthetic test input."""
import base64,zlib
import pytest
from app.services.task_privacy import command_xml,redact_command,has_private_value
from app.services.task_run import reconstruct
from app.routes.tasks import axis,percentile,where
from fastapi import HTTPException

def payload(xml):return base64.b64encode(zlib.compress(xml.encode())).decode()

def event(seq,code,fields=None,cap='TEST-capture'):
 return dict(capture_id=cap,seq=seq,event_code=code,raw_fields=fields or {})

def start(seq=1,cap='TEST-capture'):
 return event(seq,'CMDREQ',dict(service_action='StartHTTPTransfer',payload_b64=payload('<TEST><Direction All="1"/><Address All="https://TEST.invalid/path"/></TEST>')),cap)

def test_privacy_redaction_before_storage_is_idempotent():
 f={'event_code':'CMDREQ','service_action':'VoiceCallStart','payload_b64':payload('<TEST><PhoneNumber All="TEST-PRIVATE-NUMBER"/><IMSI>TEST-PRIVATE-ID</IMSI><CallDuration All="10"/></TEST>')}
 safe=redact_command(f);root=command_xml(safe['payload_b64'])
 assert not has_private_value(root)
 assert root.find('PhoneNumber').attrib['All']=='***'
 assert root.find('CallDuration').attrib['All']=='10'
 assert redact_command(safe)==safe
 assert safe!=f


def test_malformed_payload_fails_closed_and_never_raises_payload():
 assert redact_command({'payload_b64':'TEST-invalid','service_action':'VoiceCallStart'})['payload_b64']=='***'


def test_canonical_capture_boundary_and_incomplete_tasks():
 rows=[start(),event(2,'DAA',{'ts':'10:00:00'}),event(3,'DRATE',{'ts':'10:00:01','c6':'0','c8':'0'}),event(4,'DCOMP',{'ts':'10:00:02','c10':'0'}),start(cap='TEST-second'),event(2,'DRATE',{'ts':'09:00:00','c6':'123','c8':'10'},cap='TEST-second')]
 tasks=reconstruct(rows,'TEST-project')
 assert len(tasks)==2
 assert tasks[0]['status']=='ok' and tasks[0]['_samples'][0]['bps']==0
 assert tasks[0]['_samples'][0]['t_rel_s']==1
 assert tasks[1]['status']=='incomplete' and tasks[1]['seq_daa'] is None
 assert tasks[1]['_samples'][0]['t_rel_s'] is None
 assert tasks[0]['capture_id']!=tasks[1]['capture_id']
 assert reconstruct(rows,'TEST-project')[0]['id']==tasks[0]['id']


def test_nonmonotonic_time_not_interpolated():
 rows=[start(),event(2,'DAA',{'ts':'10:00:00'}),event(3,'DRATE',{'ts':'10:00:01','c6':'1'}),event(4,'DRATE',{'ts':'10:00:01','c6':'2'}),event(5,'DCOMP',{'ts':'10:00:02','c10':'1'})]
 t=reconstruct(rows,'TEST-project')[0]
 assert t['status']=='incomplete' and 'invalid_task_time' in t['reason']
 assert [s['t_rel_s'] for s in t['_samples']]==[1,1]


def test_missing_drate_allows_proven_dcomp_fallback():
 t=reconstruct([start(),event(2,'DAA',{'ts':'10:00:00'}),event(3,'DCOMP',{'ts':'10:00:02','c10':'125000'})],'TEST-project')[0]
 assert t['status']=='ok'
 assert t['bytes_dcomp']==125000 and t['duration_s']==2


def test_axis_and_project_scope():
 with pytest.raises(HTTPException) as e:axis('TEST-sql-injection',['task_time'])
 assert e.value.status_code==422
 condition,params=where('TEST-server-project',{'project_id':'TEST-other','operator':['TEST-operator']})
 assert params['pid']=='TEST-server-project' and 'TEST-other' not in str(params)
 assert percentile([0,100],.5)==50


def test_result_sql_is_admin_only():
 from app.routes.tasks import result
 from app.schemas.settings import Actor
 with pytest.raises(HTTPException) as denied:
  result('TEST-result',actor=Actor(login='TEST-reader',role='viewer'),db=None)
 assert denied.value.status_code==403


def test_integral_not_cumulative_counter_and_partial_gap():
 rows=[start(),event(2,'DAA',{'ts':'10:00:00'}),event(3,'DRATE',{'ts':'10:00:01','c6':'800','c8':'10'}),event(4,'DRATE',{'ts':'10:00:03','c6':'400','c8':'20'}),event(5,'DCOMP',{'ts':'10:00:04','c10':'200'})]
 assert reconstruct(rows,'TEST-project')[0]['status']=='ok'
 rows[-1]['raw_fields']['c10']='400'
 t=reconstruct(rows,'TEST-project')[0]
 assert t['status']=='partial'
 assert t['reason']=='DRATE_integral_DCOMP_gap_gt_5pct'


def test_axes_route_precedes_dynamic_kpi_route():
 from app.main import app
 from starlette.routing import Match
 scope={'type':'http','method':'GET','path':'/projects/TEST-project/kpi/axes'}
 route=next(r for r in app.router.routes if r.matches(scope)[0]==Match.FULL)
 assert route.endpoint.__name__=='axes'
