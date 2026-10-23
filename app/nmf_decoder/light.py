"""The same ordered aggregation for streamed decode and replayed Deep records."""
import math
from collections import defaultdict
from .schema import fields,schemas,column
from .decoder import effective_col

def txpc_cell_type(r):
    """Return the content-proven LTE TXPC cell discriminator.

    NMF 2.59 appends it as the last token.  NMF 2.62 adds one more
    undocumented value after it.  System 9 records are deliberately left
    unbound until the P4 NR proof is closed.
    """
    if r.event_code!='TXPC' or r.system!=7 or not r.tokens:return None
    index=-2 if r.format_version=='2.62' else -1
    try:value=float(r.tokens[index])
    except (ValueError,TypeError,IndexError):return None
    return int(value) if value.is_integer() and 0<=value<=4 else None

class Stat:
    def __init__(self,agg):self.agg=agg;self.total=0.;self.weight=0.;self.n=0;self.last=None;self.lo=None;self.hi=None;self.freq={}
    def add(self,value,weight=1.):
        if value is None or weight is None or weight<0:return
        self.n+=1;self.last=value;self.total+=value*weight;self.weight+=weight
        self.lo=value if self.lo is None else min(self.lo,value);self.hi=value if self.hi is None else max(self.hi,value)
        if self.agg=='dominant':self.freq[value]=self.freq.get(value,0)+weight
    def value(self):
        if not self.n or (self.agg in ("mean","dominant") and self.weight==0):return None
        return {'sum':lambda:self.total,'mean':lambda:self.total/self.weight if self.weight else None,
            'min':lambda:self.lo,'max':lambda:self.hi,'last':lambda:self.last,'count':lambda:self.n,
            'dominant':lambda:min(self.freq,key=lambda v:(-self.freq[v],v))}[self.agg]()

def dimensions(r):
    s=schemas().get(r.event_code,{})
    keys=[]
    if s.get('context_dimension'):keys.append('context_ids='+','.join(map(str,r.context_ids or [])))
    if s.get('parameter_dimension_col'):
        idx=s['parameter_dimension_col']-1
        if idx<len(r.tokens):keys.append('parameter_type='+r.tokens[idx])
    for f in s.get('header',[]):
        if f.get('dimension') or f['code']=='phrate.ph_ch_type':
            try: context_count=int(r.tokens[2]) if len(r.tokens)>2 and r.tokens[2] != '' else 0
            except (ValueError,TypeError): context_count=None
            idx=effective_col(s,f,context_count)-1
            if idx<len(r.tokens) and r.field_codes[idx]==f['code']:keys.append(f['code']+'='+r.tokens[idx])
    cell_type=txpc_cell_type(r)
    if cell_type is not None:keys.append('txpc.cell_type='+str(cell_type))
    return '|'.join(keys)

class Light:
    def __init__(self):self.buckets={}
    def add(self,r):
        # Untimed lines are retained as individual partial buckets; never dropped.
        second=math.floor(r.t_rel_s) if r.t_rel_s is not None else -r.seq-1
        key=(r.event_code,r.system,second,dimensions(r))
        b=self.buckets.get(key)
        if b is None:
            b=self.buckets[key]=dict(event_code=r.event_code,system=r.system,second=second,dimension=key[3],seq=r.seq,seq_last=r.seq,
                t_rel_s=r.t_rel_s,n_records=0,n_partial=0,reasons=set(),unknown=set(),stats={},groupstats={},format_version=r.format_version)
        if r.event_code=='TXPC':b['cell_type']=txpc_cell_type(r)
        b['seq_last']=r.seq;b['n_records']+=1;b['n_partial']+=r.decode_status=='partial';b['reasons'].update(r.reasons)
        b['context_id']=r.context_id;b['context_ids']=r.context_ids or []
        if r.event_code=='CELLMEAS':b.pop('neighbors',None)
        if r.event_code=='CELLMEAS' and r.values.get('cellmeas_n_cells') is not None:
            cells=[g['values'] for g in r.groups if g['group_name']=='cells']
            neighbors=[c for c in cells if c.get('cell_type')==2]
            serving=[c for c in cells if c.get('cell_type')==0]
            b['neighbors']={'neighbor_count':len(neighbors)}
            for metric in ('rsrp','rsrq'):
                values=[c['cell_'+metric] for c in neighbors if c.get('cell_'+metric) is not None]
                best=max(values) if values else None
                own=serving[0].get('cell_'+metric) if len(serving)==1 else None
                b['neighbors']['neighbor_best_'+metric]=best
                b['neighbors']['neighbor_delta_'+metric]=best-own if best is not None and own is not None else None
        b['unknown'].update(c for c in r.field_codes if c.startswith('unk_'))
        def add(code,value,weight=1):
            f=fields().get(code);agg=f.get('agg') if f else None
            if agg and value is not None:b['stats'].setdefault(code,Stat(agg)).add(value,weight)
        for code,value in r.values.items():
            weight_code=fields().get(code,{}).get('weight_code')
            add(code,value,r.values.get(column(weight_code)) if weight_code else 1)
        if schemas().get(r.event_code,{}).get('groups_last'):
            b['groupstats']={}
            for code in list(b['stats']):
                if fields().get(code,{}).get('group') is not None:del b['stats'][code]
        for g in r.groups:
            definition=next(x for x in schemas()[r.event_code]['groups'] if x['name']==g['group_name'])
            identity=str(g['set_index'])+'|'+ '|'.join(f'{k}={v}' for k,v in sorted(g['values'].items()) if v is not None and k.endswith(('_pci','_ch','_port','_band')))
            target=b['groupstats'].setdefault((g['group_name'],identity),dict(group_name=g['group_name'],identity=identity,set_index=g['set_index'],n_records=0,stats={}))
            target['n_records']+=1
            for field in definition['fields']:
                code=column(field['code']);value=g['values'].get(code);agg=field.get('agg')
                weight=g['values'].get(column(field['code'].split('.')[0]+'.'+field['weight'])) if field.get('weight') else 1
                if agg and value is not None:target['stats'].setdefault(code,Stat(agg)).add(value,weight)
            if definition.get('aggregate_selection')=='first' and g['set_index']!=0:continue
            for f in definition['fields']:
                weight=g['values'].get(column(f['code'].split('.')[0]+'.'+f['weight'])) if f.get('weight') else 1
                add(column(f['code']),g['values'].get(column(f['code'])),weight)
    def rows(self):
        for key in sorted(self.buckets,key=lambda k:(k[2],k[0],str(k[1]),k[3])):
            b=self.buckets[key]
            yield dict(**{k:v for k,v in b.items() if k not in ('stats','groupstats','reasons','unknown','neighbors')},reasons=sorted(b['reasons']),
                unknown=sorted(b['unknown']),groups=[dict(group_name=g['group_name'],identity=g['identity'],set_index=g['set_index'],n_records=g['n_records'],values={k:s.value() for k,s in g['stats'].items()}) for _,g in sorted(b['groupstats'].items())],values={k:v.value() for k,v in b['stats'].items()})
