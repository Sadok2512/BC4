"""Read-only ASN.1 type evidence using the installed decoder definitions. No measurements changed."""
import json,re
from sqlalchemy import text
from app.db import SessionLocal
from app.dict.decode import resolve_pdu, DROP
SQL="""SELECT DISTINCT ON (p.system,p.message,p.path) p.system,p.message,p.path,e.channel,e.direction
FROM param_occurrence p JOIN stg_event e ON e.id=p.stg_event_id
WHERE p.project_id=:pid AND NOT COALESCE(p.is_identifier,false) AND p.param_key IS NOT NULL
ORDER BY p.system,p.message,p.path,p.id"""
def resolve(node,segs,seen=None):
    if not segs:return node
    seen=seen or set()
    marker=(id(node),tuple(segs))
    if marker in seen:return None
    seen=seen|{marker}
    cont=getattr(node,'_cont',None)
    if node.TYPE in ('SEQUENCE OF','SET OF'):
        return resolve(cont,segs[1:] if re.fullmatch(r'\[\d+\]',segs[0]) else segs,seen)
    if hasattr(cont,'keys'):
        if segs[0] in cont:
            found=resolve(cont[segs[0]],segs[1:],seen)
            if found:return found
        for k in DROP:
            if k in cont:
                found=resolve(cont[k],segs,seen)
                if found:return found
    return None
out=[]
with SessionLocal() as db:
    for r in db.execute(text(SQL),{'pid':'134af70a06eb'}).mappings():
        root=resolve_pdu(r['system'],r['channel'],r['direction'],r['message'])
        obj=resolve(root,r['path'].split('/')) if root is not None else None
        out.append(dict(r,asn1_type=obj.TYPE if obj is not None else None,asn1_ref=str(getattr(obj,'_typeref',None)) if obj is not None else None,
                        reason=None if obj is not None else 'No ASN.1 definition resolved from the recorded PDU and flattened path'))
print(json.dumps({'query':SQL,'project_id':'134af70a06eb','paths':out},ensure_ascii=False))
