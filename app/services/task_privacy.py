"""Remove subscriber identifiers from command XML before persistence.
Never log the payload, parsed private values, or exceptions containing XML.
"""
import base64
import zlib
import xml.etree.ElementTree as ET

PRIVATE_TAGS = {'phonenumber','callednumber','callingnumber','msisdn','imsi','imei','subscriber_id'}
MASK = '***'


def command_xml(payload):
    compressed=base64.b64decode(payload or '',validate=True)
    dec=zlib.decompressobj()
    raw=dec.decompress(compressed,1_000_001)
    if len(raw)>1_000_000 or not dec.eof: raise ValueError('command_payload_size')
    return ET.fromstring(raw)


def local_name(tag):
    return tag.split('}')[-1].lower()


def has_private_value(root):
    for element in root.iter():
        if local_name(element.tag) in PRIVATE_TAGS:
            if any(v.strip() and v.strip()!=MASK for v in [element.text or '',*element.attrib.values()]):
                return True
        if any(local_name(k) in PRIVATE_TAGS and v.strip() not in ('',MASK) for k,v in element.attrib.items()):
            return True
    return False


def redact_command(fields):
    fields=dict(fields)
    for key in fields:
        if local_name(key) in PRIVATE_TAGS and fields[key] is not None:fields[key]=MASK
    if not fields.get('payload_b64'): return fields
    try:
        root=command_xml(fields['payload_b64']);changed=False
        for e in root.iter():
            if local_name(e.tag) in PRIVATE_TAGS:
                if e.text != MASK or any(v!=MASK for v in e.attrib.values()) or len(e):
                    e.text=MASK;e.attrib={k:MASK for k in e.attrib};e[:]=[];changed=True
            for k in e.attrib:
                if local_name(k) in PRIVATE_TAGS and e.attrib[k]!=MASK:e.attrib[k]=MASK;changed=True
        if changed: fields['payload_b64']=base64.b64encode(zlib.compress(ET.tostring(root))).decode()
    except Exception:
        # StartRepeat carries a repeat count, not compressed XML. Only voice
        # commands are required to have inspectable private call content.
        if 'Call' in str(fields.get('service_action')):fields['payload_b64']=MASK
    return fields


PRIVACY_SELECT = """SELECT id,project_id,raw_fields FROM stg_event_raw
WHERE event_code='CMDREQ' AND (raw_fields ? 'payload_b64' OR
raw_fields ?| ARRAY['PhoneNumber','phoneNumber','MSISDN','IMSI','IMEI']) ORDER BY id"""
PRIVACY_UPDATE = "UPDATE stg_event_raw SET raw_fields=CAST(:safe AS jsonb) WHERE id=:id AND project_id=:pid AND event_code='CMDREQ'"


def migrate_existing_commands(db):
    import json
    from sqlalchemy import text
    changed={}
    for row in db.execute(text(PRIVACY_SELECT)).mappings():
        safe=redact_command(row['raw_fields'])
        if safe!=row['raw_fields']:
            db.execute(text(PRIVACY_UPDATE),{'id':row['id'],'pid':row['project_id'],'safe':json.dumps(safe)})
            changed[row['project_id']]=changed.get(row['project_id'],0)+1
    return changed
