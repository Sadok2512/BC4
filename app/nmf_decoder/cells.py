"""Cell projections from the SAME Light accumulators; no guessed cell attribution.

Per-cell rate = within-second mean. Total rate = sum of those cell rates.
Quality totals require documented weights; unavailable weights produce NULL + reason.
Activity means a strictly positive observed PDSCH throughput in this second, not
configured-carrier state or an interpolation across missing seconds.
"""
from collections import defaultdict
from .schema import schemas,fields,column


def cell_rows(light):
    grouped=defaultdict(list)
    for b in light.buckets.values():
        if b['event_code']=='CELLMEAS' and b['second']>=0:
            for code,value in b.get('neighbors',{}).items():
                yield dict(second=b['second'],event_code='CELLMEAS',metric_code=code,cell_index=-1,
                           seq_first=b['seq_last'],seq_last=b['seq_last'],value=value,weight=None,
                           reason='missing_neighbor_or_serving_value' if value is None else None)
        schema=schemas().get(b['event_code'],{})
        if not schema.get('cell_scoped') or b['second']<0:continue
        indices=[b['stats'][column(f['code'])].value() for f in schema['header']
                 if f['code'].endswith('.cell_type') and column(f['code']) in b['stats']]
        if len(indices)!=1 or indices[0] not in range(5):continue
        cell=int(indices[0])
        for code,stat in b['stats'].items():
            f=fields().get(code,{})
            if f.get('dimension') or code=='phrate_ph_ch_type' or code.endswith('_cell_type') or stat.value() is None:continue
            key=(b['second'],b['event_code'],code)
            row=dict(second=b['second'],event_code=b['event_code'],metric_code=code,
                     cell_index=cell,seq_first=b['seq'],seq_last=b['seq_last'],
                     value=stat.value(),weight=stat.weight,reason=None)
            grouped[key].append((row,stat,f))
    rates=defaultdict(list)
    for key,items in sorted(grouped.items()):
        # Different channels cannot silently create duplicate cell rows.
        if len({r['cell_index'] for r,_,_ in items})!=len(items):
            raise ValueError('ambiguous_cell_dimension')
        for r,_,_ in items:yield r
        base=dict(items[0][0],cell_index=-1,
                  seq_first=min(r['seq_first'] for r,_,_ in items),
                  seq_last=max(r['seq_last'] for r,_,_ in items))
        f=items[0][2]
        if f.get('unit')=='bit/s' and 'per_prb' not in key[2]:
            base.update(value=sum(r['value'] for r,_,_ in items),weight=None)
        elif f.get('weight_code') or f.get('weight'):
            weight=sum(s.weight for _,s,_ in items)
            if f.get('agg')=='dominant':
                freq=defaultdict(float)
                for _,s,_ in items:
                    for value,w in s.freq.items():freq[value]+=w
                value=min(freq,key=lambda v:(-freq[v],v)) if weight>0 else None
            else:value=sum(s.total for _,s,_ in items)/weight if weight>0 else None
            base.update(value=value,weight=weight,reason=None if weight>0 else 'weight_unavailable')
        else:
            # No arithmetic mean of cells for CQI/SINR or category labels.
            base.update(value=None,weight=None,reason='cell_total_weight_not_documented')
        yield base
        if key[1:] == ('PHRATE','pdsch_bitrate'):
            rates[key[0]]=items
    for second,items in sorted(rates.items()):
        total=sum(r['value'] for r,_,_ in items)
        active=[r['cell_index'] for r,_,_ in items if r['value']>0]
        secondary=sum(r['value'] for r,_,_ in items if r['cell_index']>0)
        values={'n_scell_active':sum(i>0 for i in active),'n_cc_active':len(active),
                'scell_throughput_share':secondary/total if total>0 else None}
        for code,value in values.items():
            yield dict(second=second,event_code='PHRATE',metric_code=code,cell_index=-1,
                       seq_first=min(r['seq_first'] for r,_,_ in items),
                       seq_last=max(r['seq_last'] for r,_,_ in items),value=value,weight=None,
                       reason='zero_total_rate' if value is None else None)
