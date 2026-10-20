from types import SimpleNamespace
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.dict import signaling_message as service
from app.routes import project_dict_v2 as route
from app.db import get_db
from app.deps import get_current_user, with_statement_timeout_60s


def event(**overrides):
    return dict(id=1, event_code='RRCSM', system='LTE', channel='DCCH', direction='2',
                message='TEST-message', payload_hex='00', **overrides)


def occurrence(path='TEST/config/value', **changes):
    row = dict(path=path, value='0', value_converted=None, unit_converted=None,
               display_name='TEST value', system='LTE', discriminators={},
               is_identifier=False, functional_group=None)
    return row | changes


class Rows(list):
    def mappings(self):
        return self


class DB:
    def __init__(self, events=None, rows=None):
        self.events = [event()] if events is None else events
        self.rows = [occurrence()] if rows is None else rows
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))
        if 'FROM stg_event ' in str(sql):
            return Rows(self.events)
        if 'FROM param_occurrence ' in str(sql):
            return Rows(self.rows)
        return Rows()


@pytest.mark.parametrize('value', [
    {'ue-Identity': {'randomValue': (1, 40)}},
    {'TEST-parent': ('s-TMSI', {'TEST-value': 1})},
    {'TEST-parent': [{'dedicatedInfoNAS': b'TEST'}]},
    {'TEST-parent': {'cellIdentity': (1, 28)}},
    {'traceReference': {'TEST-leaf': 'TEST-PRIVATE'}},
])
def test_content_inspected_before_dictionary_deny(value):
    assert service.inspect_content(value) == 'identity_ie_present'


def test_opaque_and_unknown_fail_closed_but_bit_string_is_not_blanket_denied():
    assert service.inspect_content({'TEST-opaque': b'TEST'}) == 'opaque_ie_identity_not_excluded'
    assert service.inspect_content({'TEST-unknown': object()}) == 'unknown_asn1_value_identity_not_excluded'
    assert service.inspect_content({'TEST-config': (0, 8)}) is None
    assert service.inspect_content({'logicalChannelGroup': 0}) is None


@pytest.mark.parametrize('name', ['RRCConnectionRequest', 'RRCConnectionSetupComplete', 'RRCSetupComplete', 'ULInformationTransfer', 'DLInformationTransfer'])
def test_g18b_even_without_occurrences(name, monkeypatch):
    monkeypatch.setattr(service, 'resolve_pdu', lambda *args: pytest.fail('restricted PDU must not be exposed'))
    e = event() | {'message': name}
    payload, size, reason = service.safe_hex(e, [], 'rrc_lte')
    assert payload is None and size == 1 and reason == 'identity_bearing_message'


def test_safe_hex_requires_content_and_exact_roundtrip(monkeypatch):
    class Pdu:
        def from_uper(self, raw):
            assert raw == b'\x00'
        def get_val(self):
            return {'TEST-config': 0}
        def to_uper(self):
            return b'\x00'
    monkeypatch.setattr(service, 'resolve_pdu', lambda *args: Pdu())
    assert service.safe_hex(event(), [], 'rrc_lte') == ('00', 1, None)
    monkeypatch.setattr(Pdu, 'to_uper', lambda self: b'\x01')
    assert service.safe_hex(event(), [], 'rrc_lte')[2] == 'payload_roundtrip_mismatch'
    monkeypatch.setattr(Pdu, 'get_val', lambda self: {'dedicatedInfoNAS': b'TEST'})
    assert service.safe_hex(event(), [], 'rrc_lte')[0] is None


def test_invalid_nas_and_failed_decode_do_not_echo_content(monkeypatch):
    assert service.safe_hex(event() | {'payload_hex': 'TEST-PRIVATE'}, [], 'rrc_lte') == (None, None, 'invalid_hex_payload')
    assert service.safe_hex(event(), [], 'nas')[2] == 'nas_identity_absence_not_proven'
    def fail(*args):
        raise ValueError('TEST-PRIVATE')
    monkeypatch.setattr(service, 'resolve_pdu', fail)
    result = service.safe_hex(event(), [], 'rrc_lte')
    assert result == (None, 1, 'decode_failed_identity_not_excluded')
    assert 'TEST-PRIVATE' not in str(result)


def test_exact_occurrences_no_aggregation_identifiers_removed_zero_preserved(monkeypatch):
    db = DB(rows=[occurrence(), occurrence('TEST/config/converted', value='TEST-raw', value_converted='0', unit_converted='ms'), occurrence('TEST/config/missing', value=None), occurrence('TEST/id', value='TEST-PRIVATE', is_identifier=True)])
    result = service.decoded_message(db, 'TEST-PROJECT', 'TEST-CAPTURE', 42)
    assert len(result.tree) == 3
    assert [r.value for r in result.tree] == ['0', '0', None]
    assert result.tree[1].unit == 'ms'
    assert 'TEST-PRIVATE' not in result.model_dump_json()
    assert result.hex is None
    assert result.text == 'TEST\n  config\n    value: 0\n    converted: 0 ms\n    missing: —'
    assert db.calls[0][1] == {'pid': 'TEST-PROJECT', 'cap': 'TEST-CAPTURE', 'seq': 42}
    assert db.calls[1][1] == {'pid': 'TEST-PROJECT', 'event_id': 1}
    assert 'project_id=:pid' in db.calls[0][0] and 'project_id=:pid' in db.calls[1][0]


@pytest.mark.parametrize('events,status', [([],404), ([event(),event()],409), ([event() | {'system':'UMTS'}],422)])
def test_absence_ambiguity_and_unsupported_protocol(events,status):
    with pytest.raises(HTTPException) as error:
        service.decoded_message(DB(events=events), 'TEST-PROJECT', 'TEST-CAPTURE', 1)
    assert error.value.status_code == status


def test_route_auth_validation_and_openapi(monkeypatch):
    app = FastAPI()
    app.include_router(route.router)
    db = DB(events=[event() | {'message':'RRCConnectionRequest'}], rows=[])
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[with_statement_timeout_60s] = lambda: None
    monkeypatch.setattr(route, '_require_project', lambda db, pid: None)
    with TestClient(app) as client:
        url='/projects/TEST-PROJECT/signaling/message'
        assert client.get(url, params={'capture_id':'TEST-CAPTURE','seq':1}).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role='lecteur')
        assert client.get(url, params={'capture_id':'TEST-CAPTURE','seq':-1}).status_code == 422
        assert client.get(url, params={'seq':1}).status_code == 422
        response=client.get(url, params={'capture_id':'TEST-CAPTURE','seq':1})
        assert response.status_code == 200 and response.json()['hex'] is None
        schema=client.get('/openapi.json').json()
        assert schema['paths']['/projects/{project_id}/signaling/message']['get']['responses']['200']['content']['application/json']['schema']['$ref'].endswith('SignalingMessage')


@pytest.mark.parametrize('code,system,protocol', [('RRCSM','NR','rrc_nr'),('L3SM','LTE','nas')])
def test_protocol_uses_source_event_not_message_label(code,system,protocol):
    db=DB(events=[event() | {'event_code':code,'system':system,'message':'TEST-message','payload_hex':None}], rows=[])
    result=service.decoded_message(db,'TEST-PROJECT','TEST-CAPTURE',0)
    assert result.protocol==protocol
    assert result.tree==[] and result.text=='' and result.hex is None
    assert result.tree_reason=='no_admissible_dictionary_occurrences'


def test_identifier_path_defense_even_when_legacy_flag_false():
    db=DB(rows=[occurrence('TEST/cellIdentity',value='TEST-PRIVATE'), occurrence('TEST/config/logicalChannelGroup')])
    result=service.decoded_message(db,'TEST-PROJECT','TEST-CAPTURE',0)
    assert [r.name for r in result.tree]==['logicalChannelGroup']
    assert 'TEST-PRIVATE' not in result.model_dump_json()
