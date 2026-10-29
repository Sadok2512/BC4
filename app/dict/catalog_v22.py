"""Exact-path catalogue and project-scoped aggregate selectors for dict v2.2."""
from __future__ import annotations
import base64
import hashlib
import json
from collections import defaultdict
from fastapi import HTTPException
from sqlalchemy import text
from app.dict.category_mapping import excluded_field, resolve_mapping
from app.dict.materialized import ELIGIBLE, NORMALIZED, network_catalog_rows



def selector_key(selector):
    raw=json.dumps(selector,sort_keys=True,separators=(',',':')).encode()
    return 'dict22:'+base64.urlsafe_b64encode(raw).decode().rstrip('=')


def selector_predicate(key, db=None, project_id=None):
    """All selector contents are SQL values, never SQL identifiers or expressions."""
    if not key.startswith('dict22:'):
        return 'param_key=:k', {'k':key}
    try:
        raw=key[7:];s=json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
        if set(s)-{'tech','category','subcategory','name','unit','message','discriminators'} or not all(k in s for k in ('tech','category','subcategory','name','unit')):
            raise ValueError()
        if s['tech'] not in ('LTE','NR'): raise ValueError()
    except Exception:
        raise HTTPException(422,'Clé agrégée dict v2.2 invalide')
    # Classify distinct path/discriminator populations once, not every occurrence.
    # SQL then uses a hashed membership test; source values remain untouched.
    if db is None or project_id is None:
        raise ValueError('Aggregate selectors require a server-scoped project')
    candidates=db.execute(text(f"SELECT DISTINCT {NORMALIZED} path,COALESCE(p.discriminators,'{{}}'::jsonb) discriminators FROM param_occurrence p WHERE p.project_id=:pid AND p.system=:tech AND p.display_name=:name AND p.unit_converted IS NOT DISTINCT FROM :unit AND p.origin='network_config' AND {ELIGIBLE}"),dict(pid=project_id,tech=s['tech'],name=s['name'],unit=s['unit'])).mappings()
    maps=list(db.execute(text('SELECT * FROM dict_category_map')).mappings())
    resolved=[]
    for row in candidates:
        match=resolve_mapping(s['tech'],row['path'],row['discriminators'],maps)
        cid=match['category_id'] if match else 'autres';sid=match['subcategory_id'] if match else None
        if (cid,sid)==(s['category'],s['subcategory']):resolved.append(dict(row))
    norm=NORMALIZED.replace('p.path','param_occurrence.path')
    clause=f"""system=:sel_tech AND origin='network_config' AND display_name=:sel_name
      AND unit_converted IS NOT DISTINCT FROM :sel_unit
      AND {ELIGIBLE.replace('p.', 'param_occurrence.')}
      AND ({norm},COALESCE(discriminators,'{{}}'::jsonb)) IN
        (SELECT path,discriminators FROM jsonb_to_recordset(CAST(:sel_paths AS jsonb)) AS r(path text,discriminators jsonb))"""
    params={'sel_tech':s['tech'],'sel_name':s['name'],'sel_unit':s['unit'],'sel_paths':json.dumps(resolved)}
    if 'message' in s:
        clause+=' AND message IS NOT DISTINCT FROM :sel_message';params['sel_message']=s['message']
    if 'discriminators' in s:
        clause+=" AND COALESCE(discriminators,'{}'::jsonb)=CAST(:sel_discriminators AS jsonb)"
        params['sel_discriminators']=json.dumps(s['discriminators'])
    return clause,params


def network_catalog(db,pid,message=None):
    maps=[dict(r) for r in db.execute(text('SELECT * FROM dict_category_map')).mappings()]
    cats={r['id']:dict(r) for r in db.execute(text('SELECT * FROM dict_category')).mappings()}
    subs={r['id']:dict(r) for r in db.execute(text('SELECT * FROM dict_subcategory')).mappings()}
    rows=network_catalog_rows(db,pid,message)
    nodes={};tech_counts=defaultdict(int)
    for r in rows:tech_counts[(r['system'],r['display_name'],r['unit_converted'])]+=r['n']
    for r in rows:
        m=resolve_mapping(r['system'],r['path'],r['discriminators'],maps)
        cid=m['category_id'] if m else 'autres';sid=m['subcategory_id'] if m else None
        identity=(r['system'],cid,sid,r['display_name'],r['unit_converted'])
        s=dict(zip(('tech','category','subcategory','name','unit'),identity))
        node=nodes.setdefault(identity,dict(param_key=selector_key(s),display_name=r['display_name'],unit=r['unit_converted'],category_id=cid,subcategory_id=sid,n=0,n_occurrences=0,n_in_tech=tech_counts[(r['system'],r['display_name'],r['unit_converted'])],captures=set(),leaves={},selector=s))
        disc=r['discriminators'] or {};lid=(r['message'],json.dumps(disc,sort_keys=True))
        leaf=node['leaves'].setdefault(lid,dict(param_key=selector_key(dict(s,message=r['message'],discriminators=disc)),display_name=r['display_name'],unit=r['unit_converted'],message=r['message'],discriminators=disc,discriminator=disc,category_id=cid,subcategory_id=sid,origin='network_config',choice_of=r['choice_of'],n=0,n_occurrences=0,captures=set(),source_param_keys=set(),sample_paths=set(),n_in_tech=node['n_in_tech']))
        leaf['n']+=r['n'];leaf['n_occurrences']+=r['n'];leaf['captures'].update(r['captures']);leaf['source_param_keys'].add(r['param_key']);leaf['sample_paths'].add(r['path'])
        node['n']+=r['n'];node['n_occurrences']+=r['n'];node['captures'].update(r['captures'])
    tree={}
    for (tech,cid,sid,_,_),node in nodes.items():
        node.pop('selector');node['n_captures']=len(node.pop('captures')-{None})
        leaves=list(node.pop('leaves').values())
        for leaf in leaves:
            leaf['n_captures']=len(leaf.pop('captures')-{None});leaf['source_param_keys']=sorted(leaf['source_param_keys']);leaf['sample_paths']=sorted(leaf['sample_paths'])[:3]
        node['leaves']=leaves
        cat=tree.setdefault(tech,{}).setdefault(cid,dict(id=cid,label=cats[cid]['label'],position=cats[cid]['position'],subcategories={}))
        sub=cat['subcategories'].setdefault(sid,dict(id=sid,label=subs[sid]['label'] if sid else 'Non classé',position=subs[sid]['position'] if sid else 99,parameters=[]))
        sub['parameters'].append(node)
    for tech,categories in tree.items():
        for cat in categories.values():cat['subcategories']=sorted(cat['subcategories'].values(),key=lambda s:s['position'])
        tree[tech]=sorted(categories.values(),key=lambda c:c['position'])
    return tree
