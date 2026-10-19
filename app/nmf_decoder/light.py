"""The same ordered aggregation for streamed decode and replayed Deep records."""
import math
from collections import defaultdict
from .schema import fields,schemas,column

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
    for f in s.get('header',[]):
        if f.get('dimension') or f['code']=='phrate.ph_ch_type':
            idx=f['col']-1
            if idx<len(r.tokens) and r.field_codes[idx]==f['code']:keys.append(f['code']+'='+r.tokens[idx])
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
        b['seq_last']=r.seq;b['n_records']+=1;b['n_partial']+=r.decode_status=='partial';b['reasons'].update(r.reasons)
        b['unknown'].update(c for c in r.field_codes if c.startswith('unk_'))
        def add(code,value,weight=1):
            f=fields().get(code);agg=f.get('agg') if f else None
            if agg and value is not None:b['stats'].setdefault(code,Stat(agg)).add(value,weight)
        for code,value in r.values.items():add(code,value)
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
            yield dict(**{k:v for k,v in b.items() if k not in ('stats','groupstats','reasons','unknown')},reasons=sorted(b['reasons']),
                unknown=sorted(b['unknown']),groups=[dict(group_name=g['group_name'],identity=g['identity'],set_index=g['set_index'],n_records=g['n_records'],values={k:s.value() for k,s in g['stats'].items()}) for _,g in sorted(b['groupstats'].items())],values={k:v.value() for k,v in b['stats'].items()})
