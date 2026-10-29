"""Cell projections from the SAME Light accumulators; no guessed cell attribution.

Per-cell rate = within-second mean. Total rate = sum of those cell rates.
Quality totals require documented weights; unavailable weights produce NULL + reason.
Activity means a strictly positive observed PDSCH throughput in this second, not
configured-carrier state or an interpolation across missing seconds.
"""
from collections import defaultdict
from .schema import schemas,schema_for,fields,column

# The primary key of nmf_cell_second has no system or source-set column.  A
# cell_index must therefore encode both, otherwise LTE/NR raw 0 collide and
# repeated Listed/Detected neighbours silently collapse.  Keep the new range
# above every 1.8.1 index (0..1002), so mixed historical captures stay
# unambiguous in the catalogue.
CELL_INDEX_BASE=1003
CELL_INDEX_STRIDE=81
# Union of LTE CELLMEAS (0,1,2,10..40) and serving-cell (0..31).
CELL_TYPES_LTE=tuple(range(41))
CELLMEAS_TYPES_LTE=frozenset({0,1,2}|set(range(10,41)))
CELL_TYPES_NR=(*range(32),98,*range(100,132),198,199,1000,1001,1002)
CELL_ENUM=((7,raw) for raw in CELL_TYPES_LTE)
CELL_ENUM=tuple(CELL_ENUM)+tuple((9,raw) for raw in CELL_TYPES_NR)
CELL_ENUM_ORDINAL={key:index for index,key in enumerate(CELL_ENUM)}


def _cell_index_for(cell_type,system,occurrence=0):
    """Injective 1.8.2 projection of (system, raw type, occurrence)."""
    ordinal=CELL_ENUM_ORDINAL.get((system,cell_type))
    if ordinal is None:return None
    if not isinstance(occurrence,int) or not 0<=occurrence<CELL_INDEX_STRIDE:
        raise ValueError('cell_occurrence_out_of_range')
    return CELL_INDEX_BASE+ordinal*CELL_INDEX_STRIDE+occurrence


def cell_source_for_index(cell_index):
    """Inverse of the 1.8.2 projection, or None for legacy indices."""
    encoded=cell_index-CELL_INDEX_BASE
    if encoded<0:return None
    ordinal,occurrence=divmod(encoded,CELL_INDEX_STRIDE)
    if ordinal>=len(CELL_ENUM):return None
    system,raw=CELL_ENUM[ordinal]
    return system,raw,occurrence


def cell_index_bounds(system, cell_type):
    """Inclusive bounds for every storage occurrence of one NFF cell type."""
    first = _cell_index_for(cell_type, system, 0)
    if first is None:
        return None
    return first, first + CELL_INDEX_STRIDE - 1


def cell_rows(light):
    grouped=defaultdict(list)
    for b in light.buckets.values():
        # CELLMEAS carries its discriminator inside every repeated cell set.
        # Its LTE enum is 0=Serving, 1=Listed, 2=Detected, 10..40=SCell;
        # NR uses the complete serving/SCG/neighbour enum declared above.
        if b['event_code']=='CELLMEAS' and b['second']>=0 and b.get('system') in {7,9}:
            by_type=defaultdict(list)
            for group in b.get('groupstats',{}).values():
                if group['group_name']!='cells':continue
                stats=group['stats']
                discriminator=stats.get('cell_type')
                cell_type=discriminator.value() if discriminator else None
                allowed=(CELLMEAS_TYPES_LTE if b.get('system')==7 else CELL_TYPES_NR)
                if cell_type not in allowed:continue
                by_type[cell_type].append(group)
            for cell_type,groups in sorted(by_type.items()):
                # identity includes source set_index and radio identity fields;
                # sorting makes repeated neighbours deterministic.
                for occurrence,group in enumerate(sorted(groups,key=lambda g:g['identity'])):
                    cell=_cell_index_for(cell_type,b.get('system'),occurrence)
                    stats=group['stats']
                    for code,stat in stats.items():
                        if code=='cell_type' or stat.value() is None:continue
                        yield dict(second=b['second'],event_code='CELLMEAS',metric_code=code,
                            cell_index=cell,seq_first=b['seq'],seq_last=b['seq_last'],
                            value=stat.value(),weight=stat.weight,reason=None)
        if b['event_code']=='CELLMEAS' and b['second']>=0 and b.get('system')==7:
            for code,value in b.get('neighbors',{}).items():
                yield dict(second=b['second'],event_code='CELLMEAS',metric_code=code,cell_index=-1,
                           seq_first=b['seq_last'],seq_last=b['seq_last'],value=value,weight=None,
                           reason='missing_neighbor_or_serving_value' if value is None else None)
        schema=schema_for(b['event_code'],b.get('system'))
        if not schema.get('cell_scoped') or b['second']<0:continue
        indices=([b['cell_type']] if b['event_code']=='TXPC' and b.get('cell_type') is not None else
                 [b['stats'][column(f['code'])].value() for f in schema.get('header',[])
                  if f['code'].endswith('.cell_type') and column(f['code']) in b['stats']])
        if len(indices)!=1 or indices[0] is None:continue
        raw=int(indices[0])
        if b.get('system')==7 and raw not in range(32):continue
        cell=_cell_index_for(raw,b.get('system'))
        if cell is None:continue
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
        def is_secondary(index):
            source=cell_source_for_index(index)
            return source is not None and source[1]>0
        secondary=sum(r['value'] for r,_,_ in items if is_secondary(r['cell_index']))
        values={'n_scell_active':sum(is_secondary(i) for i in active),'n_cc_active':len(active),
                'scell_throughput_share':secondary/total if total>0 else None}
        for code,value in values.items():
            yield dict(second=second,event_code='PHRATE',metric_code=code,cell_index=-1,
                       seq_first=min(r['seq_first'] for r,_,_ in items),
                       seq_last=max(r['seq_last'] for r,_,_ in items),value=value,weight=None,
                       reason='zero_total_rate' if value is None else None)
