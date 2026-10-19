"""Exact-path catalogue and project-scoped aggregate selectors for dict v2.2."""
from __future__ import annotations
import base64
import hashlib
import json
from collections import defaultdict
from fastapi import HTTPException
from sqlalchemy import text
from app.dict.category_mapping import excluded_field, resolve_mapping

NORMALIZED = "regexp_replace(p.path, '\\[[0-9]+\\]', '[*]', 'g')"
ELIGIBLE = """p.param_key IS NOT NULL AND NOT COALESCE(p.is_identifier,false)
AND regexp_replace(p.path,'^.*/','') !~ '^(spare[0-9]*|dummy|reserved)$'
AND p.path NOT IN ('systemFrameNumber','mib/systemFrameNumber')"""


def selector_key(selector):
    raw=json.dumps(selector,sort_keys=True,separators=(',',':')).encode()
    return 'dict22:'+base64.urlsafe_b64encode(raw).decode().rstrip('=')


def selector_predicate(key):
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
    # Classification is the very same longest normalized segment prefix as the tree.
    norm=NORMALIZED.replace('p.path','param_occurrence.path')
    clause=f"""system=:sel_tech AND origin='network_config' AND display_name=:sel_name
      AND unit_converted IS NOT DISTINCT FROM :sel_unit
      AND {ELIGIBLE.replace('p.', 'param_occurrence.')}
      AND EXISTS (SELECT 1 FROM (SELECT category_id,subcategory_id FROM dict_category_map m
        WHERE m.technology IN (param_occurrence.system,'BOTH')
        AND ({norm}=m.path_prefix OR starts_with({norm},m.path_prefix||'/'))
        AND COALESCE(param_occurrence.discriminators,'{{}}'::jsonb) @> m.discriminator
        ORDER BY array_length(string_to_array(m.path_prefix,'/'),1) DESC,
          (SELECT count(*) FROM jsonb_object_keys(m.discriminator)) DESC,
          (m.technology=param_occurrence.system) DESC LIMIT 1) chosen
        WHERE chosen.category_id=:sel_category AND chosen.subcategory_id IS NOT DISTINCT FROM :sel_subcategory)"""
    params={'sel_'+k:v for k,v in s.items() if k not in ('message','discriminators')}
    if s['category']=='autres':
        # Unreviewed paths remain visible and their population remains queryable.
        clause=clause[:clause.index('AND EXISTS')] + f"""AND NOT EXISTS (SELECT 1 FROM dict_category_map m WHERE m.technology IN (param_occurrence.system,'BOTH') AND ({norm}=m.path_prefix OR starts_with({norm},m.path_prefix||'/')) AND COALESCE(param_occurrence.discriminators,'{{}}'::jsonb) @> m.discriminator)"""
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
    sql=f"""SELECT p.system,p.origin,p.message,{NORMALIZED} path,p.param_key,p.display_name,
     p.unit_converted,p.choice_of,p.discriminators,count(*) n,array_agg(DISTINCT e.capture_id) captures
     FROM param_occurrence p LEFT JOIN stg_event e ON e.id=p.stg_event_id
     WHERE p.project_id=:pid AND p.origin='network_config' AND {ELIGIBLE}
     AND (CAST(:message AS text) IS NULL OR p.message=:message)
     GROUP BY 1,2,3,4,5,6,7,8,9 ORDER BY 1,3,4,5,9::text"""
    # positional jsonb ordering is supported; avoid an ordinal cast interpreted as a constant.
    sql=sql.replace('9::text','p.discriminators::text')
    rows=[dict(r) for r in db.execute(text(sql),{'pid':pid,'message':message}).mappings()]
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
