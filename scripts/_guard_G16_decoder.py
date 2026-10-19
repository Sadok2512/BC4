"""Manual G16. Run in API container; --phase before before deploying, after after jobs.
No subscriber values are written to reports. SQL uses parameters, never literal identities.
"""
import argparse,csv,json,math,hashlib
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
from sqlalchemy import text
from app.db import SessionLocal
P='134af70a06eb';T='4b7bfd50ddb6';C='41c13c9b4ce0'
p=argparse.ArgumentParser();p.add_argument('--phase',choices=['before','after'],required=True);p.add_argument('--out',required=True);a=p.parse_args()
out=Path(a.out);out.mkdir(parents=True,exist_ok=True);sqls=[]
def query(db,q,params=None,private=False):
    sqls.append(dict(sql=q,params='<identity literals kept in memory only>' if private else params))
    return db.execute(text(q),params or {})
def baseline(db):
    radio=dict(query(db,'SELECT count(rsrp) n,percentile_cont(0.5) WITHIN GROUP(ORDER BY rsrp) p50 FROM measurement_points WHERE project_id=:pid',{'pid':P}).mappings().one())
    samples=dict(query(db,"SELECT count(s.bps) n,percentile_cont(0.5) WITHIN GROUP(ORDER BY s.bps) p50 FROM task_sample s JOIN task_run t ON t.id=s.task_id WHERE t.project_id=:pid AND t.task_type='HTTP_DL'",{'pid':P}).mappings().one())
    from app.kpi.service_v2 import compute_kpi_v2
    kpi=compute_kpi_v2(db,P,'THR_DL_APP')
    return dict(rsrp=radio,app_samples=samples,kpi=kpi)
def save(name,data):
    (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str)+'\n')
with SessionLocal() as db:
    if a.phase=='before':
        save('baseline.json',baseline(db));save('baseline-sql.json',sqls);print('baseline saved');raise SystemExit()
    from app.nmf_decoder.source import records,SIGNALLING
    from app.nmf_decoder.store import read_deep,HEADERS,GROUPS
    from app.nmf_decoder.light import Light
    from app.nmf_decoder.schema import fields
    from app.nmf_decoder.decoder import tokenize,hashed
    from app.services.task_privacy import command_xml,local_name,PRIVATE_TAGS
    results={};files=query(db,"SELECT DISTINCT n.id,n.project_id,n.source_path,n.filename,n.sha256,r.capture_id FROM nmf_file n JOIN stg_event_raw r ON r.nmf_file_id=n.id WHERE n.project_id IN (:p,:t)",{'p':P,'t':T}).mappings().all()
    filemap={(r['project_id'],r['capture_id']):r for r in files}
    file=filemap[P,C]
    expected=iter(records(file['source_path'],C,file['sha256']));actual=iter(read_deep(db,P,C));diff=[];count=0;witness={}
    while True:
        x=next(expected,None);y=next(actual,None)
        if x is None and y is None:break
        count+=1
        if x is None or y is None:diff.append({'kind':'missing_record'});break
        same=(x.seq,x.line_no,x.tokens,x.field_codes,x.unk_string,x.decode_status,x.reasons)==(y.seq,y.line_no,y.tokens,y.field_codes,y.unk_string,y.decode_status,y.reasons)
        same=same and {k:v for k,v in x.values.items() if v is not None}==y.values
        ex=sorted([(g['group_name'],g['set_index'],{k:v for k,v in g['values'].items() if v is not None}) for g in x.groups],key=lambda v:(v[0],v[1]))
        ac=[(g['group_name'],g['set_index'],g['values']) for g in y.groups]
        if not same or ex!=ac:diff.append({'seq':x.seq,'line_no':x.line_no})
        if x.seq in (18,70,71,75,144,241,244,250):witness[str(x.seq)]=dict(event=x.event_code,line_no=x.line_no,values=y.values,groups=y.groups)
    checks=[witness['241']['values']['pdsch_bler']==.5,witness['250']['values']['mac_dl_bler']==2.7,
        witness['71']['values']['ci_rs_snr']==34.6,witness['244']['values']['txpc_pusch_tx_power']==-11.1,
        witness['144']['values']['cqi_wb_cqi_0']==15,witness['18']['groups'][0]['values']['cell_rsrp']==-71,
        witness['70']['groups'][0]['values']['mimo_rsrp_p']==-80.4 and witness['70']['groups'][0]['values']['mimo_port']==0,
        witness['75']['values']['plaid_n_prb_indexes']==75]
    save('G16a-diff.json',diff);save('G16a-witnesses.json',dict(filename=file['filename'],capture_id=C,witnesses=witness))
    results['G16a']=dict(pass_=not diff and all(checks),records=count,witnesses=checks)
    caps=query(db,"SELECT capture_id FROM nmf_capture WHERE project_id=:pid AND decode_level='deep' ORDER BY capture_id LIMIT 3",{'pid':T}).scalars().all()
    comparisons=[]
    def rounded(v):
        if isinstance(v,float):return round(v,8)
        if isinstance(v,dict):return {k:rounded(x) for k,x in v.items()}
        if isinstance(v,list):return [rounded(x) for x in v]
        return v
    for cap in caps:
        file=filemap[T,cap];one=Light();two=Light()
        for r in records(file['source_path'],cap,file['sha256']):one.add(r)
        for r in read_deep(db,T,cap):two.add(r)
        comparisons.append(dict(capture_id=cap,equal=rounded(list(one.rows()))==rounded(list(two.rows()))))
    results['G16b']=dict(pass_=len(comparisons)==3 and all(r['equal'] for r in comparisons),captures=comparisons)
    identities=set();coverage=[];formats=Counter()
    for (pid,cap),file in sorted(filemap.items()):
        expected_count=0;source_path=Path(file['source_path'])
        for line in source_path.open(encoding='latin-1'):
            if not line.strip():continue
            try:tokens=next(csv.reader([line]))
            except csv.Error:tokens=[]
            if line.startswith('#'):
                if tokens and tokens[0]=='#EI':identities.update(x for x in tokens[3:] if x)
                if tokens and tokens[0]=='#FF':formats[tokens[3] if len(tokens)>3 else 'unknown']+=1
                continue
            if not tokens or tokens[0] not in SIGNALLING:expected_count+=1
            if tokens and tokens[0]=='CMDREQ' and len(tokens)>5:
                try:
                    root=command_xml(tokens[5])
                    for e in root.iter():
                        if local_name(e.tag) in PRIVATE_TAGS:
                            identities.update(x.strip() for x in [e.text or '',*e.attrib.values()] if x.strip() and x.strip()!='***')
                except Exception:pass  # Non-XML repeat commands have no phone-number field.
        if pid==P:
            row=dict(query(db,"SELECT count(*) n,count(*) FILTER(WHERE decode_status='ok') ok,count(*) FILTER(WHERE decode_status='partial') partial FROM nmf_event_deep WHERE project_id=:pid AND capture_id=:cap",{'pid':pid,'cap':cap}).mappings().one())
            coverage.append(dict(capture_id=cap,source=expected_count,**row))
    results['G16c']=dict(pass_=all(r['source']==r['n']==r['ok']+r['partial'] for r in coverage),captures=coverage)
    invalid=[];conditions={'nmf_event_deep':[],'nmf_event_group':[]}
    for name,f in fields().items():
        table='nmf_event_group' if f['group'] else 'nmf_event_deep';predicates=[];lo,hi=f.get('range',[None,None])
        if lo is not None:predicates.append(f'{name} < {float(lo)}')
        if hi is not None:predicates.append(f'{name} > {float(hi)}')
        if f.get('enum'):predicates.append(f'{name} NOT IN ('+','.join(str(int(v)) for v in f['enum'])+')')
        if predicates:conditions[table].append('count(*) FILTER(WHERE '+' OR '.join(predicates)+') AS '+name)
    for table,expressions in conditions.items():
        row=query(db,'SELECT '+','.join(expressions)+' FROM '+table+' WHERE project_id IN (:p,:t)',{'p':P,'t':T}).mappings().one()
        invalid.extend(dict(field=k,n=v) for k,v in row.items() if v)
    from app.kpi.metrics import metric_catalog
    no_unknown=all(not m.source_column.startswith('unk_') for m in metric_catalog(db).values())
    results['G16d']=dict(pass_=not invalid and no_unknown,invalid=invalid,unknown_metrics=not no_unknown)
    private_counts={}
    # All Deep/Light tables, all stored columns. Literal identities never appear in logs/files.
    for table in ('nmf_event_deep','nmf_event_group','nmf_event_light','nmf_event_light_group'):
        q=f"SELECT count(*) FROM {table} d WHERE EXISTS (SELECT 1 FROM unnest(CAST(:identities AS text[])) identity WHERE strpos(jsonb_strip_nulls(to_jsonb(d))::text,identity)>0)"
        private_counts[table]=query(db,q,{'identities':sorted(identities)},private=True).scalar_one()
    results['G16e']=dict(pass_=not any(private_counts.values()),identities_checked=len(identities),occurrences=private_counts)
    before=json.loads((out/'baseline.json').read_text());after=baseline(db);save('after.json',after)
    # The live KPI result includes provenance/elapsed metadata: compare its actual statistical payload explicitly in report.
    results['G16f']=dict(pass_=before['rsrp']==after['rsrp'] and before['app_samples']==after['app_samples'] and before['kpi']==after['kpi'],before=before,after=after)
    partial=query(db,'SELECT event_code,reason,count(*) n FROM nmf_event_deep CROSS JOIN LATERAL unnest(reasons) reason WHERE project_id=:pid GROUP BY event_code,reason ORDER BY event_code,reason',{'pid':P}).mappings().all()
    unknown=query(db,"SELECT event_code,code,count(*) n FROM nmf_event_deep CROSS JOIN LATERAL unnest(field_codes) code WHERE project_id=:pid AND code LIKE 'unk_%' GROUP BY event_code,code ORDER BY event_code,code",{'pid':P}).mappings().all()
    save('partial-by-reason.json',[dict(r) for r in partial]);save('unknown-by-event.json',[dict(r) for r in unknown]);save('formats.json',formats)
    save('guards.json',dict(at=datetime.now(timezone.utc).isoformat(),project_id=P,proof_project=T,guards=results));save('sql.json',sqls)
    print(json.dumps({k:v['pass_'] for k,v in results.items()}))
