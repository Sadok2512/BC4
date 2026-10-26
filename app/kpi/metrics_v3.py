"""Closed metrics v3 projections. Capture/seq order, server-side cells and event attributes."""
from collections import defaultdict, Counter
from dataclasses import asdict
import csv
import json
import io
import math
import time
from threading import Lock
from fastapi import HTTPException
from sqlalchemy import text
from app.nmf_decoder import DECODER_VERSION
from app.nmf_decoder.schema import schemas, fields, column
from app.nmf_decoder.projection import ALIASES, metric_counts
from app.kpi.english import english_text
from app.kpi.metrics import metric_catalog
from app.kpi.population import context_sql, predicate, validate_operators
from app.kpi.service import date_from_start_at_py


def _pair_previous_or_same(xr, yr):
    """Yields `(y, previous)` for each `y` of `yr` (sorted by seq), where
    `previous` is the last element of `xr` (sorted by seq) with
    `xr.seq <= y.seq`, or `None` if no such element exists.

    0.75.0 — extraction du pattern inline historiquement en place pour les
    pairings G14 (scatter RSRP↔DRATE). Réutilisé pour le join GPS (seq →
    lat/lon le plus récent). Jamais interpolé.
    """
    j = 0
    previous = None
    for y in yr:
        while j < len(xr) and xr[j]['seq'] <= y['seq']:
            previous = xr[j]
            j += 1
        yield y, previous

CATEGORIES = {
 'radio_serving':'Radio serving', 'neighbours':'Neighbours', 'carrier_aggregation':'Carrier Aggregation',
 'throughput_layers':'Throughput by layer', 'link_quality':'Link quality', 'allocation_mcs':'Allocation & MCS',
 'csi':'CSI', 'mimo_port':'MIMO by port', 'ul_power':'UL power', 'voice':'Voice',
 'services':'Services', 'position':'Position', 'signalling_states':'Events',
 'session':'Capture context', 'terminal_cell':'Capture context', 'undocumented':'Undocumented'}
FIELD_LABELS={'plaid_mcs0':'MCS CW0 (DL)','plaid_mcs1':'MCS CW1 (DL)','plaiu_mcs0':'MCS CW0 (UL)',
 # 0.74.7 — labels manquants côté YAML, override explicite ici (plus simple
 # qu'un sweep des schemas/*.yaml). Les codes sont ceux de source_column.
 'ci_snr_port':'RS SNR/Antenna port','ci_port':'Antenna port or channel',
 'aqdl_mos':'Audio quality MOS DL',
 'app_dl_bitrate':'App DL bitrate','app_ul_bitrate':'App UL bitrate',
 'app_dl_bytes':'App DL bytes','app_ul_bytes':'App UL bytes',
 'ppp_dl_bitrate':'PPP DL bitrate','ppp_ul_bitrate':'PPP UL bitrate'}
def _humanize_label(raw: str) -> str:
    """Fallback: si YAML label ressemble à un code brut (contient `.` ou `_`
    et pas d'espace), produire une forme Title Case lisible. Ex. 'ci.snr_port'
    → 'Ci snr port'. Ne modifie pas les vrais labels (contenant déjà espaces)."""
    if not raw or ' ' in raw:
        return raw
    if '.' in raw or '_' in raw:
        return raw.replace('.', ' ').replace('_', ' ').strip().capitalize()
    return raw
EVENT_GROUPS={
 'RRC':{'RRA','RRC','RRD'}, 'Mobility':{'HOA','HOS','HOI','CREL'},
 'Attach':{'GAA','GAC','GAD'}, 'Bearers':{'PBA','PBC','PBD','RABA','RABC','RABD'},
 'Calls':{'CAA','CAC','CAD'}, 'VoLTE / SIP':{'SIPREGA','SIPREGC','SIPREGD'},
 'Data sessions':{'DAA','DAC','DAD','DREQ','DCOMP','DSUMMARY'},
 'Radio access':{'RACHI'}, 'Cell / CA':{'MEI','SEI','SCELLMOD'},
 'Forcing / markers':{'LOCK','ROAM','MARK'}}
EVENTS=set().union(*EVENT_GROUPS.values())
DERIVED={
 'n_scell_active':('SCells with observed PDSCH traffic','count','carrier_aggregation','PHRATE'),
 'n_cc_active':('CCs with observed PDSCH traffic','count','carrier_aggregation','PHRATE'),
 'scell_throughput_share':('SCell share of observed PHY throughput','%','carrier_aggregation','PHRATE'),
 'neighbor_count':('Type 2 neighbour count','count','neighbours','CELLMEAS'),
 'neighbor_best_rsrp':('Best neighbour RSRP','dBm','neighbours','CELLMEAS'),
 'neighbor_best_rsrq':('Best neighbour RSRQ','dB','neighbours','CELLMEAS'),
 'neighbor_delta_rsrp':('Neighbour RSRP − serving','dB','neighbours','CELLMEAS'),
 'neighbor_delta_rsrq':('Neighbour RSRQ − serving','dB','neighbours','CELLMEAS')}
PAIR_ATTRS={'ho_duration_nemo_ms':('Nemo HO duration','ms'), 'ho_duration_hoi_ms':('HOI duration','ms'),
 'duration_nemo_ms':('Nemo pair duration','ms'), 'outcome':('Pair outcome','')}
_PRIVATE={'caa_phone_number','caa_own_phone_number','sei_lac','sei_tmsi','sei_p_tmsi','sei_m_tmsi'}
_cache={}
_catalog_lock=Lock()


def definitions():
    result={}; fs=fields(); ss=schemas()
    for code,m in metric_catalog(None).items():
        f=fs[m.source_column];s=ss[f['event']]
        scoped=bool(s.get('cell_scoped')) and not f.get('dimension') and not code.endswith('_cell_type') and code!='phrate_ph_ch_type'
        category=f.get('category') or 'session'
        result[code]=dict(code=code,label=english_text(FIELD_LABELS.get(m.source_column,_humanize_label(m.label))),unit=m.unit or '',source_table=m.source_table,
            source_tables=[m.source_table],source_column=m.source_column,tech=m.tech,kind=m.kind,
            event=f['event'],event_code=f['event'],category=category,category_label=CATEGORIES.get(category,category),
            cell_scoped=scoped,cells=[],cell_options=[],attributes=[],proof='documented',proof_ref=f['proof'],
            decoder_version=DECODER_VERSION,n_in_project=0,available=True,reason=english_text(s.get('cell_scope_reason')),
            alias_of=ALIASES.get(code),agg=f.get('agg'),weighted=bool(f.get('weight')),sql=m.sql)
    for event in sorted(EVENTS):
        s=ss.get(event,{});attrs=[]
        for f in s.get('header',[]):
            code=column(f['code'])
            if code in _PRIVATE or f.get('type') not in ('int','float') or not f.get('proof'):continue
            if code in {a['code'] for a in attrs}:continue
            categorical=any(x in code for x in ('cause','status','type','pci','band','system','measured_sys'))
            attrs.append(dict(code=code,label=f.get('label',code),unit=f.get('unit') or '',kind='categorical' if categorical else 'numeric',proof='documented',proof_ref=f['proof']))
        for group in s.get('groups',[]):
            for f in group.get('fields',[]):
                key=column(f['code'])
                if key in _PRIVATE or not f.get('proof') or key in {a['code'] for a in attrs}:continue
                attrs.append(dict(code=key,label=f.get('label',key)+' · sets',unit=f.get('unit') or '',kind='categorical',proof='documented',proof_ref=f['proof'],group=group['name'],repeated=True))
        attrs.append(dict(code='context_id',label='Nemo context',unit='',kind='categorical',proof='documented',proof_ref='NFF 2.19 p5: context count followed by context IDs'))
        if event in {'HOA','HOS','HOI','CAA','CAC','CAD','DAA','DAC','DAD','RRA','RRC','RRD','GAA','GAC','PBA','PBC','PBD'}:
            for key,(label,unit) in PAIR_ATTRS.items():
                if key.startswith('ho_') and event not in {'HOA','HOS','HOI'}:continue
                attrs.append(dict(code=key,label=label,unit=unit,kind='categorical' if key=='outcome' else 'numeric',proof='content',proof_ref='nmf_event_pair; capture-local context state machine; no cross-capture pairing'))
        code='evt_'+event
        result[code]=dict(code=code,label=event,unit='occurrence',source_table='nmf_event_deep',source_tables=['nmf_event_deep','nmf_event_light'],source_column='event_code',tech='BOTH',kind='event',event=event,event_code=event,category='signalling_states',category_label='Events',event_group=next(k for k,v in EVENT_GROUPS.items() if event in v),cell_scoped=False,cells=[],cell_options=[],attributes=attrs,proof='documented' if s and s.get('proof')!='none' else 'none',proof_ref='NFF 2.19; YAML '+event+'; occurrence only when undocumented',decoder_version=DECODER_VERSION,n_in_project=0,available=True,reason=None,alias_of=None,agg='count')
    for code,(label,unit,category,event) in DERIVED.items():
        result[code]=dict(code=code,label=label,unit=unit,source_table='nmf_cell_second',source_tables=['nmf_cell_second'],source_column=code,tech='LTE',kind='numeric',event=event,event_code=event,category=category,category_label=CATEGORIES[category],cell_scoped=False,cells=[],cell_options=[],attributes=[],proof='content',proof_ref='nmf_cell_second; observed cells only, no configured state inferred',decoder_version=DECODER_VERSION,n_in_project=0,available=True,reason=None,alias_of=None,agg='last')
    return result


def catalog(db,pid):
    with _catalog_lock:
        return _catalog(db,pid)

def _catalog(db,pid):
    stamp=tuple(db.execute(text('SELECT capture_id,decoder_version,decoded_at FROM nmf_capture WHERE project_id=:pid ORDER BY capture_id'),{'pid':pid}))
    cached=_cache.get(pid)
    if cached and cached[0]==stamp:return cached[2]
    defs=definitions(); counts,sources=metric_counts(db,pid)
    cells=defaultdict(list)
    for r in db.execute(text('SELECT metric_code,cell_index,count(DISTINCT (capture_id,second)) FILTER (WHERE value IS NOT NULL) n FROM nmf_cell_second WHERE project_id=:pid GROUP BY 1,2'),{'pid':pid}).mappings():cells[r['metric_code']].append(dict(r))
    event_rows=list(db.execute(text("SELECT event_code,sum(n_records) n,count(*) FILTER(WHERE cardinality(unknown)>0) unknown_n FROM nmf_event_light WHERE project_id=:pid GROUP BY event_code"),{'pid':pid}).mappings())
    event_counts={r['event_code']:r['n'] for r in event_rows}
    unknown=[dict(event_code=r['event_code'],n=r['unknown_n']) for r in event_rows if r['unknown_n']]
    out=[]
    for code,m in defs.items():
        m=dict(m);m.pop('sql',None);m.pop('agg',None);m.pop('weighted',None)
        if m['kind']=='event':m['n_in_project']=int(event_counts.get(m['event'],0))
        elif code in DERIVED:m['n_in_project']=sum(x['n'] for x in cells[code] if x['cell_index']==-1)
        else:m['n_in_project']=counts.get(m['source_column'],0);m['source_tables']=sources.get(m['source_column'],m['source_tables'])
        if m['cell_scoped']:
            by={x['cell_index']:x['n'] for x in cells[m['source_column']]}
            m['cells']=sorted(i for i,n in by.items() if i>=0 and n)
            m['cell_options']=[dict(cell='all' if i==-1 else str(i),label='Total CA' if i==-1 else 'PCell' if i==0 else f'SCell{i}',n_in_project=by.get(i,0),available=bool(by.get(i,0)),reason=None if by.get(i,0) else 'No observations or total weighting unproven') for i in [-1,0,1,2,3,4]]
        # Keep the complete contract in the catalogue.  A metric with no
        # observation is still rendered (greyed) with an explicit reason;
        # silently dropping it made cell_absent and absent_in_capture
        # indistinguishable from a missing schema.
        out.append(m)
    for r in unknown:
        out.append(dict(code='unk_'+r['event_code'],label=r['event_code']+' · undocumented fields',unit='',source_table='nmf_event_light',source_tables=['nmf_event_light'],source_column='unknown',tech='BOTH',kind='categorical',event=r['event_code'],event_code=r['event_code'],category='undocumented',category_label='Undocumented',cell_scoped=False,cells=[],cell_options=[],attributes=[],proof='none',proof_ref='',decoder_version=DECODER_VERSION,n_in_project=r['n'],available=False,reason='Unproven field position (NFF 2.19)',alias_of=None))
    # Explicitly visible blocked hypothesis, not an invented SCell measurement.
    for code in ('cell_rsrp','cell_rsrq'):
        if any(m['code']==code for m in out):
            base=next(m for m in out if m['code']==code)
            base['unproven_cells']=[dict(cell=str(i),label=f'Cell type {i}',reason='Secondary serving cell — unproven hypothesis; requires BC1 /dict/v2/scells') for i in range(10,14)]
    nr=any(isinstance(s.get('systems'),list) and 9 in s['systems'] for s in schemas().values())
    notices=[] if nr else [dict(label='NR',reason='No documented NR field positions in active schemas'),dict(label='EN-DC',reason='Unproven LTE/NR association; captures are never combined')]
    for item in out:item['root_notices']=notices
    _cache[pid]=(stamp,time.monotonic(),out)
    return out


def parse_selection(token,defs,cell='all',attr=None):
    code,sep,own_cell=token.partition('@');code,sep_attr,own_attr=code.partition('~')
    cell=own_cell if sep else cell;attr=own_attr if sep_attr else attr
    if code not in defs:raise HTTPException(422,dict(reason='unknown_metric',code=code,allowed=sorted(defs)))
    m=dict(defs[code]);m['base_code']=code
    if cell not in {'all','0','1','2','3','4'}:raise HTTPException(422,dict(reason='unknown_cell',allowed=['all','0','1','2','3','4']))
    if cell!='all' and not m['cell_scoped']:raise HTTPException(422,'metric_not_cell_scoped')
    if attr:
        a=next((a for a in m['attributes'] if a['code']==attr),None)
        if not a:raise HTTPException(422,dict(reason='unknown_event_attribute',allowed=[a['code'] for a in m['attributes']]))
        m.update(label=m['event']+' · '+a['label'],unit=a['unit'],kind=a['kind'],attr=attr)
    else:m['attr']=None
    m['cell']=cell;m['selection']=code+('~'+attr if attr else '')+('@'+cell if m['cell_scoped'] else '')
    if m['cell_scoped']:m['label']+=' · '+('Total CA' if cell=='all' else 'PCell' if cell=='0' else 'SCell'+cell)
    return m


def percentile(values,p):
    a=sorted(values)
    if not a:return None
    pos=(len(a)-1)*p;lo=math.floor(pos);hi=math.ceil(pos)
    return a[lo]+(a[hi]-a[lo])*(pos-lo)


def aggregate_values(rows,agg):
    values=[r['value'] for r in rows if r['value'] is not None]
    if not values:return None
    if agg=='last':return values[-1]
    if agg=='dominant':
        c=Counter(values);return min(c,key=lambda x:(-c[x],str(x)))
    if agg=='sum':return sum(values)
    if agg=='count':return len(values)
    if agg=='min':return min(values)
    if agg=='max':return max(values)
    return sum(values)/len(values)


class Dataset:
    def __init__(self,db,pid,cap,f,lo=None,hi=None):
        from app.routes.metrics import clock
        validate_operators(db,pid,f)
        self.db=db;self.pid=pid;self.cap=cap;self.f=f;self.lo=lo;self.hi=hi;self.sqls=[]
        self.params={'pid':pid,'cap':cap,'ctx_cap':cap}
        self.times,self.origin_seq,self.origin_ts=clock(db,pid,cap)
        self.state=self.query('SELECT decoder_version,schema_version,decode_level FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap').first()
        if not self.state:raise HTTPException(409,'capture_requires_decode')
        # 0.75.0 — meta temporelle du fichier source joint via nmf_capture.
        # Lecture read-only ; jamais inventé (NULL si absent).
        self.file_meta=self.query('SELECT f.start_at AS start_at, f.utc_offset_min AS utc_offset_min FROM nmf_capture c JOIN nmf_file f ON f.id=c.nmf_file_id WHERE c.project_id=:pid AND c.capture_id=:cap').first() or {'start_at':None,'utc_offset_min':None}
        self.context={r['seq']:dict(r) for r in self.query(context_sql())}
        condition,params=predicate(f);self.params.update(params)
        self.allowed=None if condition=='TRUE' else {r['seq'] for r in self.query('SELECT seq FROM ('+context_sql()+') c WHERE '+condition)}
        self.pairs=list(self.query('SELECT * FROM nmf_event_pair WHERE project_id=:pid AND capture_id=:cap ORDER BY seq_start'))

    def query(self,sql,extra=None):
        params={**self.params,**(extra or {})};self.sqls.append(dict(sql=sql,params=params))
        return self.db.execute(text(sql),params).mappings()

    def admissible(self,seq):
        return (self.lo is None or seq>=self.lo) and (self.hi is None or seq<=self.hi) and (self.allowed is None or seq in self.allowed)

    def load(self,m):
        code=m['source_column'];cell=m['cell'];attr=m['attr'];event=m['event'];rows=[]
        if m['cell_scoped'] or m['base_code'] in DERIVED:
            sql='SELECT seq_first seq,seq_last,value,reason,second FROM nmf_cell_second WHERE project_id=:pid AND capture_id=:cap AND metric_code=:metric AND cell_index=:cell ORDER BY seq_first'
            rows=[dict(r) for r in self.query(sql,{'metric':code,'cell':-1 if cell=='all' else int(cell)})]
            scale=1e-6 if fields().get(code,{}).get('unit')=='bit/s' else 100 if code=='scell_throughput_share' else 1
            for r in rows:
                if r['value'] is not None:r['value']*=scale
        elif m['base_code'].startswith('evt_'):
            attributes=[a['code'] for a in m['attributes'] if a['code'] not in PAIR_ATTRS and a['code']!='context_id' and not a.get('group')]
            group_fields={a['code']:a['group'] for a in m['attributes'] if a.get('group')}
            grouped=defaultdict(dict)
            if group_fields:
                group_table='nmf_event_group' if self.state['decode_level']=='deep' else 'nmf_event_light_group'
                for g in self.query('SELECT seq,group_name,set_index,'+','.join(group_fields)+f' FROM {group_table} WHERE project_id=:pid AND capture_id=:cap AND group_name=ANY(:groups) ORDER BY seq,set_index',{'groups':list(set(group_fields.values()))}):
                    for key,group_name in group_fields.items():
                        if g['group_name']==group_name and g[key] is not None:grouped[g['seq']].setdefault(key,[]).append(dict(set_index=g['set_index'],value=g[key]))
            table='nmf_event_deep' if self.state['decode_level']=='deep' else 'nmf_event_light'
            sql='SELECT seq,context_id'+(' ,n_records,seq_last' if table.endswith('light') else ',1 AS n_records,seq AS seq_last')+(' ,'+','.join(attributes) if attributes else '')+f' FROM {table} WHERE project_id=:pid AND capture_id=:cap AND event_code=:event ORDER BY seq'
            for r in self.query(sql,{'event':event}):
                attrs={k:r[k] for k in attributes if r[k] is not None};attrs['context_id']=r['context_id']
                attrs.update({k:json.dumps(v) for k,v in grouped.get(r['seq'],{}).items()})
                for pair in self.pairs:
                    if r['seq'] in (pair['seq_start'],pair['seq_end'],pair['seq_hoi']):
                        attrs.update({k:pair[k] for k in PAIR_ATTRS if pair[k] is not None});break
                rows.append(dict(seq=r['seq'],seq_last=r['seq_last'],value=attrs.get(attr) if attr else 1,attributes=attrs,count=1 if attr else r['n_records']))
        else:
            sql='SELECT seq,value FROM ('+m['sql']+') v WHERE capture_id=:cap ORDER BY seq'
            rows=[dict(r) for r in self.query(sql)]
        out=[]
        for r in rows:
            seq=r['seq']
            if not self.admissible(seq):continue
            # A pre-aggregated cell bucket may not combine admitted and rejected observations.
            if (self.allowed is not None or self.lo is not None or self.hi is not None) and r.get('seq_last',seq)!=seq:
                if any(not self.admissible(s) for s in self.times if seq<=s<=r['seq_last']):continue
            t=self.times.get(seq)
            r.update(t_rel_s=t,second=math.floor(t) if t is not None else None)
            ctx=self.context.get(seq,{})
            r.update(operator=ctx.get('operator'),band=ctx.get('band'),cell=cell)
            if r['value'] is not None and m['kind']=='categorical':r['value']=str(r['value'])
            out.append(r)
        return out

    def connected_seconds(self,group_by='none'):
        # Only RRC -> RRD boundaries in the same Nemo context, not RRA setup time.
        rows=self.query("SELECT seq,event_code,context_id FROM nmf_event_deep WHERE project_id=:pid AND capture_id=:cap AND event_code IN ('RRC','RRD') ORDER BY seq")
        starts={};intervals=[]
        for r in rows:
            key=r['context_id'];seq=r['seq']
            if key is None:continue
            if r['event_code']=='RRC':starts[key]=seq
            elif key in starts:
                start=starts.pop(key)
                if not all(self.admissible(s) for s in self.times if start<=s<=seq):continue
                a=self.times.get(start);b=self.times.get(seq)
                if a is not None and b is not None and b>=a:
                    op=self.context.get(start,{}).get('operator') if 'operator' in group_by else None
                    band=self.context.get(start,{}).get('band') if 'band' in group_by else None
                    if 'band' in group_by and any(self.context.get(s,{}).get('band')!=band or band is None for s in self.times if start<=s<=seq):continue
                    intervals.append((op,band,a,b))
        grouped=defaultdict(list)
        for op,band,a,b in intervals:grouped[(op,band)].append((a,b))
        result={}
        for key,spans in grouped.items():
            merged=[]
            for a,b in sorted(spans):
                if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
                else:merged.append((a,b))
            result[key]=sum(b-a for a,b in merged)
        return result

    def response(self,selections,limit=5000,group_by='operator',x=None,include_map=False):
        from app.routes.metrics import sample
        from app.routes.tasks import evidence
        defs=definitions();loaded=[(m,self.load(m)) for m in selections]
        table={};series=[];hist=[];map_points=[];gaps=[]
        for m,rows in loaded:
            points=[];buckets=defaultdict(list)
            if any(r['t_rel_s'] is None for r in rows):gaps.append(m['selection']+': Missing timestamp; observations excluded from temporal views')
            for r in rows:
                if r['second'] is not None:buckets[r['second']].append(r)
                if r['value'] is not None and r['t_rel_s'] is not None:
                    tip=f"{m['label']} : {r['value']} {m['unit']} · seq {r['seq']}"+(' · '+str(r.get('attributes')) if r.get('attributes') else '')
                    points.append(dict(seq=r['seq'],t_rel_s=r['t_rel_s'],value=r['value'],tooltip=tip,attributes=r.get('attributes',{})))
                if r.get('reason'):gaps.append(r['reason'])
            out,sampling=sample(points,limit,m['kind']) if m['kind']!='event' else (points,dict(method='all_occurrences',factor=1,seq_bucket_width=None))
            if m['kind']=='event' and len(points)>limit:raise HTTPException(422,dict(reason='event_occurrences_exceed_max_points',required=len(points)))
            series.append(dict(code=m['selection'],label=m['label'],unit=m['unit'],kind=m['kind'],cell=m['cell'],source_table='nmf_cell_second' if m['cell_scoped'] else m['source_table'],source_column=m['source_column'],n_total=len(points),n_returned=len(out),sampling=sampling,states=list(dict.fromkeys(str(p['value']) for p in points)) if m['kind']=='categorical' else [],segments=[],points=out))
            for second,rs in buckets.items():
                row=table.setdefault(second,dict(second=second,t_rel_s=float(second),seq_first=rs[0]['seq'],seq_last=rs[-1]['seq'],values={},counts={}))
                row['seq_first']=min(row['seq_first'],rs[0]['seq']);row['seq_last']=max(row['seq_last'],rs[-1]['seq'])
                value=1 if m['kind']=='event' else aggregate_values(rs,'last' if m.get('attr') or m['cell_scoped'] else m.get('agg','last'))
                if m.get('weighted') and not m['cell_scoped'] and len([r for r in rs if r['value'] is not None])>1:
                    # Projection preserves weighted per-seq values but does not expose their denominators.
                    # Never average those means again to manufacture a second-level statistic.
                    value=None;gaps.append(m['selection']+': missing inter-sample weights; per-second aggregate unavailable, per-seq series preserved')
                row['values'][m['selection']]=value;row['counts'][m['selection']]=sum(r.get('count',1) for r in rs)
            groups=defaultdict(list)
            for r in rows:
                if r['value'] is None:continue
                groups[(r.get('operator') if 'operator' in group_by else None,r.get('band') if 'band' in group_by else None)].append(r)
            for (op,band),rs in groups.items():
                vals=[r['value'] for r in rs];numeric=m['kind']=='numeric'
                hist.append(dict(code=m['selection'],label=m['label'],operator=op,band=band,cell=m['cell'],n=sum(r.get('count',1) for r in rs),p10=percentile(vals,.1) if numeric else None,p50=percentile(vals,.5) if numeric else None,p90=percentile(vals,.9) if numeric else None,distribution=[dict(value=v,n=n) for v,n in Counter(vals).items()] if not numeric else []))
        durations=self.connected_seconds(group_by) if any(m['kind']=='event' for m in selections) else {}
        connected=sum(durations.values()) if durations else None
        for h in hist:
            duration=durations.get((h['operator'],h['band']))
            h['per_connected_hour']=h['n']*3600/duration if duration and next(m for m in selections if m['selection']==h['code'])['kind']=='event' else None
        scatter=[]
        if x:
            xm=parse_selection(x,defs);xr=self.load(xm)
            for m,yr in loaded:
                if m['cell']!=xm['cell'] or m['cell_scoped']!=xm['cell_scoped']:
                    gaps.append('scatter_cell_scope_mismatch');continue
                for y, previous in _pair_previous_or_same(xr, yr):
                    if previous and previous['value'] is not None and y['value'] is not None:
                        scatter.append(dict(code=m['selection'],seq=y['seq'],x_seq=previous['seq'],seq_gap=y['seq']-previous['seq'],cell=m['cell'],x=previous['value'],value=y['value']))
        # 0.75.0 — GPS seq→(lat,lon). Lu une fois, utilisé pour map_points
        # ET pour enrichir chaque row de la table (previous-or-same seq).
        gps_fixes=sorted(({'seq':r['seq'],'lat':r['lat'],'lon':r['lon']} for r in self.query('SELECT seq,lat,lon FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap AND lat IS NOT NULL AND lon IS NOT NULL AND NOT(lat=0 AND lon=0) ORDER BY seq')), key=lambda f: f['seq'])
        gps_exact={f['seq']:(f['lat'],f['lon']) for f in gps_fixes}
        if include_map:
            # Exact recorded GPS only: no previous-position point presented as exact.
            for m,rows in loaded:
                for r in rows:
                    if r['seq'] in gps_exact and r['value'] is not None:
                        lat,lng=gps_exact[r['seq']];map_points.append(dict(seq=r['seq'],lat=lat,lng=lng,code=m['selection'],value=r['value'],t_rel_s=r['t_rel_s'],tooltip=f"{m['label']} · seq {r['seq']} · {r['value']} {m['unit']}"))
        pair_rows=[dict(p) for p in self.pairs if self.admissible(p['seq_start']) and (p['seq_end'] is None or self.admissible(p['seq_end']))]
        pair_rates=[]
        for kind in sorted({p['type'] for p in pair_rows}):
            ps=[p for p in pair_rows if p['type']==kind];known=[p for p in ps if p['outcome'] in ('ok','fail')]
            pair_rates.append(dict(type=kind,attempts=len(ps),completed=sum(p['seq_end'] is not None for p in ps),success=sum(p['outcome']=='ok' for p in ps),known_outcomes=len(known),success_pct=100*sum(p['outcome']=='ok' for p in known)/len(known) if known else None))
        rid=evidence(self.db,self.pid,';\n'.join(q['sql'] for q in self.sqls),{'queries':self.sqls,'capture_id':self.cap,'selections':[m['selection'] for m in selections],'filters':self.f},dict(rows=len(table),series=len(series)))
        ordered=[table[k] for k in sorted(table)]
        from decimal import Decimal
        # 0.75.0 — time_local (= ancien time_label), time_utc (local - offset)
        # et join GPS previous-or-same seq (sur seq_first).
        h,minute,sec=self.origin_ts.split(':');origin=Decimal(h)*3600+Decimal(minute)*60+Decimal(sec)
        nmf_start_at=self.file_meta['start_at']
        capture_date=date_from_start_at_py(nmf_start_at)
        utc_offset_min=self.file_meta['utc_offset_min']
        # t_rel_s de chaque row (sur capture_id, seq_first) : identique à self.times[seq_first]
        for row in ordered:
            actual=origin+Decimal(str(self.times[row['seq_first']]))
            hh=int(actual//3600);mm=int((actual%3600)//60);ss=actual%60
            row['time_label']=f'{hh:02d}:{mm:02d}:{ss:06.3f}'
            row['time_local']=row['time_label']
            if utc_offset_min is None:
                row['time_utc']=None
                row.setdefault('reason',None)
                if row.get('reason') is None:row['reason']='no_utc_offset_header'
            else:
                utc_actual=actual-Decimal(utc_offset_min)*60
                # Garder modulo 86400 (temps du jour) ; jamais inventer de date.
                while utc_actual<0:utc_actual+=86400
                while utc_actual>=86400:utc_actual-=86400
                hh=int(utc_actual//3600);mm=int((utc_actual%3600)//60);ss=utc_actual%60
                row['time_utc']=f'{hh:02d}:{mm:02d}:{ss:06.3f}'
        # 0.82.2 — Enrichissement Task par ligne. CMDREQ → CMDCOMP par
        # (capture_id, seq ≤). task_name = action, task_index = cmd_index
        # (si présent dans CMDREQ), null hors tâche. Jamais inventé.
        import bisect as _bs
        task_rows=list(self.db.execute(text(
            "SELECT seq, event_code, raw_fields->>'service_action' AS action, "
            "raw_fields->>'cmd_index' AS cmd_index FROM stg_event_raw "
            "WHERE project_id=:pid AND capture_id=:cap "
            "AND event_code IN ('CMDREQ','CMDCOMP') ORDER BY seq"
        ), {'pid': self.pid, 'cap': self.cap}).mappings())
        tasks_timeline=[]
        open_t=None
        for tr in task_rows:
            if tr['event_code']=='CMDREQ':
                if open_t is not None: tasks_timeline.append(open_t)
                open_t={'seq_req':tr['seq'],'seq_comp':None,'action':tr['action'],
                        'cmd_index':int(tr['cmd_index']) if tr['cmd_index'] is not None else None}
            elif tr['event_code']=='CMDCOMP' and open_t is not None:
                open_t['seq_comp']=tr['seq'];tasks_timeline.append(open_t);open_t=None
        if open_t is not None: tasks_timeline.append(open_t)
        _req_seqs=[t['seq_req'] for t in tasks_timeline]
        def _task_at(seq_last):
            i=_bs.bisect_right(_req_seqs, seq_last)-1
            if i<0: return (None, None)
            t=tasks_timeline[i]
            end=t['seq_comp'] if t['seq_comp'] is not None else 10**12
            if seq_last < end: return (t['action'], t['cmd_index'])
            return (None, None)
        for row in ordered:
            tn, ti = _task_at(row['seq_last'])
            row['task_name']=tn; row['task_index']=ti
        # GPS enrichment par ligne — previous-or-same seq, zero fabrication.
        gps_source=self.state['decode_level']
        no_gps_reason='no_gps_in_capture' if not gps_fixes else None
        # yr pour le join = ordered rows avec clé seq=seq_first
        yr=[{'seq':row['seq_first'],'_row':row} for row in ordered]
        for y, prev in _pair_previous_or_same(gps_fixes, yr):
            row=y['_row']
            if prev is None:
                row['lat']=None;row['lon']=None;row['gps_source']=None;row['gps_age_s']=None
                if no_gps_reason is not None:
                    row['reason']=no_gps_reason
                elif gps_source=='light':
                    row['reason']='light_decode_no_gps'
                else:
                    row['reason']='no_fix_before_seq'
            else:
                row['lat']=prev['lat'];row['lon']=prev['lon']
                row['gps_source']='exact' if prev['seq']==y['seq'] else 'previous_fix'
                # Age en secondes = différence t_rel_s(seq actuel) - t_rel_s(seq GPS).
                # self.times[seq_first] est en secondes depuis origin. On recalcule
                # self.times[prev.seq] si disponible, sinon age inconnu.
                prev_t=self.times.get(prev['seq'])
                cur_t=self.times[row['seq_first']]
                row['gps_age_s']=float(cur_t-prev_t) if prev_t is not None else None
                row['reason']=None
        # CSV = exactement les colonnes de la table UI (0.75.0).
        output=io.StringIO();writer=csv.writer(output);keys=[m['selection'] for m in selections]
        writer.writerow(['result_id','capture_id','second','seq_first','seq_last','time_local','time_utc','lat','lon','gps_source','gps_age_s','reason',*keys])
        for row in ordered:writer.writerow([rid,self.cap,row['second'],row['seq_first'],row['seq_last'],row['time_local'],row['time_utc'],row['lat'],row['lon'],row['gps_source'],row['gps_age_s'],row['reason'],*[row['values'].get(k) for k in keys]])
        return dict(**dict(self.state),project_id=self.pid,capture_id=self.cap,result_id=rid,origin_seq=self.origin_seq,origin_ts=self.origin_ts,nmf_start_at=nmf_start_at,capture_date=capture_date,utc_offset_min=utc_offset_min,duration_s=max(self.times.values()),aggregation='cell: schema-weighted capture-second; other numeric: schema aggregate; event: presence + count / last attribute',time_policy='capture-local source clock in seq order; no interpolation',columns=[dict(code=m['selection'],label=m['label'],unit=m['unit'],kind=m['kind'],cell=m['cell']) for m in selections],series=series,rows=ordered,histogram=hist,scatter=scatter,map_points=map_points,connected_seconds=connected,connected_reason=None if connected else 'No proven complete eligible RRC → RRD interval',pair_rates=pair_rates,gaps=sorted(set(gaps)),csv=output.getvalue(),pairing='previous-or-same seq, same capture and same cell; no interpolation')
