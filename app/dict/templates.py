"""Exact segment-prefix category mapping and one grouped SQL population per summary."""
import hashlib
import json
from collections import Counter
from sqlalchemy import text
from fastapi import HTTPException
from app.dict.service_v2 import _op_color, _band_color


def configuration(db):
    return [dict(r) for r in db.execute(text('SELECT c.id,c.label,c.position,t.entries,t.revision FROM dict_category c JOIN dict_template t ON t.category_id=c.id ORDER BY c.position,c.id')).mappings()]


def category_maps(db):
    return [dict(r) for r in db.execute(text('SELECT m.*,c.label,c.position FROM dict_category_map m JOIN dict_category c ON c.id=m.category_id ORDER BY length(path_prefix) DESC,c.position')).mappings()]


def classify(technology, path, maps):
    for row in maps:
        if row['technology']==technology and (path==row['path_prefix'] or path.startswith(row['path_prefix']+'/')):
            return row['category_id'],row['label'],row['position']
    return 'autres','Autres',11


def references(entries):
    refs=[]
    for entry in entries:
        for i,ref in enumerate(entry['parameters']):
            refs.append(dict(ref,entry_id=entry['id'],row_id=f"{entry['id']}:{i}"))
    return refs


def aggregate(db,project_id,refs,group_by=None):
    if not refs:return []
    aggregate_refs=[r for r in refs if r['param_key'].startswith('dict22:')]
    if aggregate_refs:
        from app.dict.service_v2 import build_distribution
        result=[]
        for ref in aggregate_refs:
            block=build_distribution(db,project_id,[ref['param_key']],group_by or 'operator')['blocks'][0]
            if not group_by:
                result.append(dict(row_id=ref['row_id'],n=block['n_total']));continue
            for value in block['values']:
                for group in value['groups']:
                    result.append(dict(row_id=ref['row_id'],value=value['value'],unit=block['unit'],operator=group.get('operator'),band=group.get('band'),n=group['n']))
        return result+aggregate(db,project_id,[r for r in refs if r not in aggregate_refs],group_by)
    # Values are grouped once across the entire requested category, not one query per row.
    dims={'operator':('p.operator','NULL::text'),'band':('NULL::text','p.band'),'operator_band':('p.operator','p.band')}
    op,band=dims.get(group_by,('NULL::text','NULL::text'))
    value='COALESCE(p.value_converted,p.value)' if group_by else 'NULL::text'
    sql=f'''WITH refs AS (SELECT * FROM jsonb_to_recordset(CAST(:refs AS jsonb)) AS r(row_id text,entry_id text,param_key text,technology text,discriminators jsonb,path_prefix text))
      SELECT r.row_id,{value} AS value,MIN(p.unit_converted) AS unit,{op} AS operator,{band} AS band,count(*) AS n
      FROM refs r JOIN param_occurrence p ON p.project_id=:pid AND (CASE WHEN r.path_prefix IS NULL THEN p.param_key=r.param_key ELSE regexp_replace(p.path, '\\[[0-9]+\\]', '[*]', 'g')=r.path_prefix OR starts_with(regexp_replace(p.path, '\\[[0-9]+\\]', '[*]', 'g'),r.path_prefix||'/') END) AND p.system=r.technology
        AND COALESCE(p.discriminators,'{{}}'::jsonb) @> r.discriminators
      GROUP BY 1,2,4,5 ORDER BY 1,2,4,5'''
    return [dict(x) for x in db.execute(text(sql),{'pid':project_id,'refs':json.dumps(refs)}).mappings()]


def list_templates(db,project_id):
    cats=configuration(db);refs=references([e for c in cats for e in c['entries']]);counts=Counter()
    for row in aggregate(db,project_id,refs):counts[row['row_id']]+=row['n']
    # Category population is based on unique catalog occurrences, independent of overlapping templates.
    from app.dict.catalog_v22 import network_catalog
    cat_counts=Counter();cat_keys={}
    for tech,categories in network_catalog(db,project_id).items():
        for category in categories:
            for sub in category['subcategories']:
                for node in sub['parameters']:
                    cid=category['id'];cat_counts[cid]+=node['n']
                    for leaf in node['leaves']:
                        cat_keys.setdefault(cid,set()).update((tech,key) for key in leaf['source_param_keys'])
    for c in cats:
        c['n_parameters']=len(cat_keys.get(c['id'],set()));c['n_in_project']=cat_counts[c['id']]
        c['entries']=[dict(e,n_in_project=sum(counts[f"{e['id']}:{i}"] for i in range(len(e['parameters']))),resolved=bool(e['parameters'])) for e in sorted(c['entries'],key=lambda e:(e['position'],e['id']))]
    return {'project_id':project_id,'categories':cats}


def summarize(db,project_id,category,group_by,keys=None):
    cat=next((x for x in configuration(db) if x['id']==category),None)
    if cat is None:raise HTTPException(404,'Catégorie introuvable')
    if keys:
        from app.dict.catalog_v22 import network_catalog
        nodes=[(tech,node) for tech,categories in network_catalog(db,project_id).items() for c in categories if c['id']==category for sub in c['subcategories'] for node in sub['parameters'] if node['param_key'] in keys]
        if {n['param_key'] for _,n in nodes} != set(keys):raise HTTPException(422,'Clé agrégée absente de cette catégorie/projet')
        cat=dict(cat,entries=[dict(id='aggregate-'+str(i),label=n['display_name'],position=i,technology=tech,discriminators={},parameters=[dict(param_key=n['param_key'],technology=tech,discriminators={})]) for i,(tech,n) in enumerate(nodes)])
    refs=references(cat['entries']);grouped={}
    for row in aggregate(db,project_id,refs,group_by):grouped.setdefault(row['row_id'],[]).append(row)
    output=[]
    for entry in sorted(cat['entries'],key=lambda e:(e['position'],e['id'])):
        for i,ref in enumerate(entry['parameters'] or [None]):
            rows=grouped.get(f"{entry['id']}:{i}",[]);values={};cells={}
            for r in rows:
                key=(r['operator'],r['band']);cell=cells.setdefault(key,{'operator':key[0],'band':key[1],'n':0,'missing_value_n':0,'counts':Counter()})
                cell['n']+=r['n']
                if r['value'] is None:cell['missing_value_n']+=r['n'];continue
                v=str(r['value']);cell['counts'][v]+=r['n']
                g={'n':r['n']}
                if group_by!='band':g.update(operator=r['operator'],operator_color=_op_color(r['operator']))
                if group_by!='operator':g.update(band=r['band'],band_color=_band_color(r['band']))
                values.setdefault(v,{'value':v,'value_display':f"{v} {r['unit']}" if r['unit'] else v,'groups':[]})['groups'].append(g)
            cs=[]
            for cell in cells.values():
                counts=cell.pop('counts');n=max(counts.values(),default=0);dom=sorted(v for v,c in counts.items() if c==n)
                cell.update(dominant_values=dom,dominant_value=dom[0] if len(dom)==1 else None,percentage=100*n/cell['n'] if counts and cell['n'] else None,differs_from_majority=None);cs.append(cell)
            eligible=[c for c in cs if c['dominant_value'] is not None and (group_by=='band' or c['operator'] not in (None,'N/D')) and (group_by=='operator' or c['band'] not in (None,'N/D'))]
            votes=Counter(c['dominant_value'] for c in eligible);majority=next((v for v,n in votes.items() if n>len(eligible)/2),None)
            if majority is not None:
                for c in eligible:c['differs_from_majority']=c['dominant_value']!=majority
            identity=[project_id,category,entry['id'],ref,group_by,cat['revision']]
            output.append(dict(entry_id=entry['id'],label=entry['label'],param_key=ref['param_key'] if ref else None,technology=entry['technology'],discriminators=ref['discriminators'] if ref else entry['discriminators'],n_in_project=sum(r['n'] for r in rows),resolved=ref is not None,reason=entry.get('reason') if ref is None else None,distribution=[values[k] for k in sorted(values)],cells=cs,result_id=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]))
    return dict(project_id=project_id,category_id=category,group_by=group_by,rows=output)
