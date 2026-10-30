"""Closed metrics v3 projections. Capture/seq order, server-side cells and event attributes."""
from collections import defaultdict, Counter
from dataclasses import asdict
import csv
import json
import io
import math
import time
from functools import lru_cache
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

# Catalog 2.57.0 temporarily hid these documented NFF fields because the
# metrics endpoint only knew continuous curves.  They are event attributes:
# identifiers/enums render as categorical markers, while physical durations,
# powers and counts remain ordinary numeric series.
EVENT_FIELD_CODES=frozenset({
 'cqi_n_params','crel_band','crel_cell_id','crel_new_tac','crel_old_band',
 'crel_old_cell_id','crel_old_system','crel_old_tac','crel_params',
 'dad_application_protocol','dad_data_disc_status','dcomp_application_protocol',
 'dcomp_transf_status','dreq_application_protocol','dreq_transf_dir',
 'gad_detach_cause','gad_detach_status','gad_detach_time','hoa_att_band',
 'hoa_att_ch','hoa_att_pci','hoa_band','hoa_ch_number','hoa_current_system',
 'hoa_hoa_type','hoa_pci','hoi_ho_duration','hoi_ho_u_plane','lock_band',
 'lock_forcings','lock_params','mei_measurement_event','mei_measurement_id',
 'pba_pb_type','pbc_pb_id','rachi_access_delay','rachi_init_tx_power',
 'rachi_pathloss','rachi_preamble_step','rachi_preambles','rachi_pusch_power',
 'rachi_rach_preamble_index','rachi_rach_reason','rachi_rach_result',
 'rachi_rach_type','roam_roaming_status','rra_est_cause','rrd_rrc_rel_cause',
 'rrd_rrc_rel_status','sei_mcc','sei_mme_code','sei_mme_group','sei_mnc',
 'sei_service_status',
})
NUMERIC_EVENT_FIELDS=frozenset({
 'cqi_n_params','crel_params','gad_detach_time','hoi_ho_duration',
 'hoi_ho_u_plane','lock_forcings','rachi_access_delay','rachi_init_tx_power',
 'rachi_pathloss','rachi_preamble_step','rachi_preambles','rachi_pusch_power',
})
MARKER_FIELD_CODES=(EVENT_FIELD_CODES-NUMERIC_EVENT_FIELDS)|frozenset({'cell_ch','cell_pci'})


@lru_cache(maxsize=1)
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
    # Direct leaves use the same decoder schema metadata as evt_EVENT~attr,
    # but expose the catalog's stable field code without an artificial event
    # wrapper.  Repeated LOCK values keep set_index in attributes.
    for code in sorted(EVENT_FIELD_CODES):
        f=fs.get(code)
        if not f:continue
        event=f['event'];schema=ss.get(event,{})
        scoped=(bool(schema.get('cell_scoped')) and not f.get('dimension'))
        kind='numeric' if code in NUMERIC_EVENT_FIELDS else 'categorical'
        result[code]=dict(
            code=code,label=english_text(f.get('label') or _humanize_label(code)),
            unit=f.get('unit') or '',source_table='nmf_event_group' if f.get('group') else 'nmf_event_deep',
            source_tables=['nmf_event_group','nmf_event_light_group'] if f.get('group') else ['nmf_event_deep','nmf_event_light'],
            source_column=code,tech='BOTH',kind=kind,event=event,event_code=event,
            category=f.get('category') or 'signalling_states',
            category_label=CATEGORIES.get(f.get('category') or 'signalling_states','Events'),
            cell_scoped=scoped,cells=[],cell_options=[],attributes=[],proof='documented',
            proof_ref=f.get('proof') or '',decoder_version=DECODER_VERSION,n_in_project=0,
            available=True,reason=None,alias_of=None,agg=f.get('agg') or 'last',
            weighted=bool(f.get('weight')),event_attribute=not scoped,
            repeated_group=f.get('group'),marker_series=code in MARKER_FIELD_CODES,
        )
    for code in MARKER_FIELD_CODES:
        if code in result:result[code]['marker_series']=True
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
    # 2.53.0 — CAPTURE Phase 2 : inject 27 feuilles (hors MASKED filtrées
    # côté metrics_catalog_v4). Codes `cap_{group}_{slug}` dispatchent
    # vers metrics_v3_capture.load_capture() dans Dataset.load().
    from app.kpi.metrics_v3_capture import capture_definitions
    result.update(capture_definitions())
    return result


# Static decoder/catalog definitions are immutable at runtime.  Build them
# once while workers start instead of charging the first analytics request.
definitions()


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
    # 2.55.0 (BC4) — Codex67 point 1 : la whitelist cell `{all,0,1,2,3,4}`
    # a été étendue à l'enum NFF 2.50 complet. Les valeurs admises sont :
    #   - 'all'  → Total CA
    #   - 'null' → cell_type non renseigné (dispatch cellule inconnu)
    #   - tout entier non négatif ≤ 10000 (SCell 1-31, SCG SCell 100-131,
    #     SCG PSCell 199, NR neighbours 1000-1002 ; max large pour
    #     absorber de futures valeurs spec sans redéploiement). Le libellé
    #     spec de la valeur vient de `nodes_out[].label` côté catalog ;
    #     ici on produit un libellé minimal « cell N » / « cell NULL »
    #     seulement en fallback (les clients canoniques utilisent la
    #     feuille du catalogue qui porte déjà le libellé de l'enum).
    from app.kpi.metrics_catalog_v4 import (
        cell_type_display,
        parse_cell_type_selector,
    )
    semantic_cell = parse_cell_type_selector(cell) if isinstance(cell, str) else None
    if cell != 'all' and cell != 'null' and semantic_cell is None:
        try:
            _cell_int = int(cell)
            if _cell_int < 0 or _cell_int > 10000:
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(422, dict(
                reason='unknown_cell',
                allowed=['all', 'null', '<entier ≥ 0, ≤ 10000 — enum NFF 2.50>']
            ))
    if cell!='all' and not m['cell_scoped']:raise HTTPException(422,'metric_not_cell_scoped')
    if attr:
        a=next((a for a in m['attributes'] if a['code']==attr),None)
        if not a:raise HTTPException(422,dict(reason='unknown_event_attribute',allowed=[a['code'] for a in m['attributes']]))
        m.update(label=m['event']+' · '+a['label'],unit=a['unit'],kind=a['kind'],attr=attr)
    else:m['attr']=None
    m['cell']=cell;m['selection']=code+('~'+attr if attr else '')+('@'+cell if m['cell_scoped'] else '')
    if m['cell_scoped']:
        if cell == 'all':
            cell_label = 'Total CA'
        elif cell == 'null':
            cell_label = 'cell_type NULL'
        else:
            if semantic_cell is not None:
                system, raw_cell_type = semantic_cell
                display = cell_type_display(m['event'], system, raw_cell_type)
                m['cell_type_filter'] = {
                    'system': system,
                    'raw_cell_type': raw_cell_type,
                }
            else:
                from app.nmf_decoder.cells import cell_source_for_index
                internal_index = int(cell)
                source = cell_source_for_index(internal_index)
                system, raw_cell_type, occurrence = (
                    source if source is not None else (7, internal_index, 0)
                )
                display = cell_type_display(m['event'], system, raw_cell_type)
                m['legacy_internal_index'] = internal_index
                m['legacy_occurrence'] = occurrence
            cell_label = display['label'] + (f" · {display['system']}" if display['system'] else '')
            m['cell_display'] = display
        m['label'] += ' · ' + cell_label
    return m


def percentile(values,p):
    # 0.99.2 (hotfix) : certains metrics marqués kind='numeric' dans
    # `definitions()` renvoient parfois des valeurs textuelles (ex. enum
    # categorical mal typé — cap_script_*, maci_cell_type, maci_cell_state,
    # plaisum_total_prb_usage). Avant le fix : `a[hi]-a[lo]` sur str → TypeError
    # → 500 sur /metrics/table en groupe KPI (histogrammes). Fix défensif :
    # ne garder que les valeurs numériques pour calculer le percentile ; le
    # typage upstream (metrics_catalog) sera à corriger par BC1 dans un lot
    # suivant.
    a=sorted(v for v in values if isinstance(v,(int,float)) and not isinstance(v,bool))
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
    def __init__(self,db,pid,cap,f,lo=None,hi=None,lean_table=False,
                 lean_series=False):
        from app.routes.metrics import clock
        self.db=db;self.pid=pid;self.cap=cap;self.f=f;self.lo=lo;self.hi=hi;self.sqls=[]
        self.params={'pid':pid,'cap':cap,'ctx_cap':cap}
        condition,params=predicate(f);self.params.update(params)
        if condition != 'TRUE':validate_operators(db,pid,f)
        self.lean_table=bool(lean_table and condition=='TRUE')
        self.lean_series=bool(lean_series and condition=='TRUE')
        if self.lean_table or self.lean_series:
            meta=self.query("""
                WITH origin AS (
                  SELECT seq,ts FROM (
                    (SELECT seq,ts FROM stg_event_raw
                     WHERE project_id=:pid AND capture_id=:cap ORDER BY seq LIMIT 1)
                    UNION ALL
                    (SELECT seq,ts FROM stg_event
                     WHERE project_id=:pid AND capture_id=:cap ORDER BY seq LIMIT 1)
                  ) candidates ORDER BY seq LIMIT 1
                )
                SELECT o.seq AS origin_seq,o.ts AS origin_ts,
                       (SELECT t_rel_s FROM nmf_event_light
                        WHERE project_id=:pid AND capture_id=:cap
                        ORDER BY seq DESC LIMIT 1) AS duration_s,
                       c.decoder_version,c.schema_version,c.decode_level,
                       f.start_at,f.utc_offset_min
                FROM nmf_capture c
                JOIN nmf_file f ON f.id=c.nmf_file_id
                CROSS JOIN origin o
                WHERE c.project_id=:pid AND c.capture_id=:cap
            """).first()
            if not meta:raise HTTPException(404,'capture_not_found_in_project')
            self.times={};self.origin_seq=meta['origin_seq'];self.origin_ts=meta['origin_ts']
            self.duration_s=float(meta['duration_s'] or 0)
            self.state={k:meta[k] for k in ('decoder_version','schema_version','decode_level')}
            self.file_meta={k:meta[k] for k in ('start_at','utc_offset_min')}
        else:
            self.times,self.origin_seq,self.origin_ts=clock(db,pid,cap)
            self.duration_s=max(self.times.values())
            self.state=self.query('SELECT decoder_version,schema_version,decode_level FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap').first()
            if not self.state:raise HTTPException(409,'capture_requires_decode')
            # 0.75.0 — meta temporelle du fichier source joint via nmf_capture.
            # Lecture read-only ; jamais inventé (NULL si absent).
            self.file_meta=self.query('SELECT f.start_at AS start_at, f.utc_offset_min AS utc_offset_min FROM nmf_capture c JOIN nmf_file f ON f.id=c.nmf_file_id WHERE c.project_id=:pid AND c.capture_id=:cap').first() or {'start_at':None,'utc_offset_min':None}
        self.context={} if (self.lean_table or self.lean_series) else {r['seq']:dict(r) for r in self.query(context_sql())}
        self.allowed=None if condition=='TRUE' else {r['seq'] for r in self.query('SELECT seq FROM ('+context_sql()+') c WHERE '+condition)}
        self.pairs=[] if (self.lean_table or self.lean_series) else list(self.query('SELECT * FROM nmf_event_pair WHERE project_id=:pid AND capture_id=:cap ORDER BY seq_start'))

    def query(self,sql,extra=None):
        params={**self.params,**(extra or {})};self.sqls.append(dict(sql=sql,params=params))
        return self.db.execute(text(sql),params).mappings()

    def admissible(self,seq):
        return (self.lo is None or seq>=self.lo) and (self.hi is None or seq<=self.hi) and (self.allowed is None or seq in self.allowed)

    def _ensure_times(self, seqs):
        """Load only requested capture timestamps for the lean series path.

        ``nmf_event_light.t_rel_s`` is produced in canonical seq order at
        import.  It avoids rebuilding the complete staging clock for every
        graph request.  Deep-only fallback remains bounded to the requested
        seq values and never joins captures by timestamp.
        """
        missing=sorted({int(seq) for seq in seqs if seq not in self.times})
        if not missing:return
        rows=self.query("""
            SELECT seq,MIN(t_rel_s) AS t_rel_s
            FROM nmf_event_light
            WHERE project_id=:pid AND capture_id=:cap AND seq=ANY(:wanted_seqs)
            GROUP BY seq ORDER BY seq
        """,{'wanted_seqs':missing})
        for row in rows:
            if row['t_rel_s'] is not None:self.times[row['seq']]=float(row['t_rel_s'])
        remaining=[seq for seq in missing if seq not in self.times]
        if remaining:
            from app.routes.metrics import clock_subset
            subset,_,_=clock_subset(self.db,self.pid,self.cap,remaining)
            self.times.update(subset)

    def _load_semantic_cell(self, m, *, page=None, page_size=None,
                            cell_pci=None, cell_arfcn=None):
        """Load one enum leaf as physical cells, with SQL pagination.

        Storage occurrences are joined back to the exact CELLMEAS repeated
        group by `(project_id, capture_id, seq, raw type, occurrence)`. Rows
        are then reduced to `(seq, system, ARFCN, PCI)`; duplicate samples of
        the same physical cell retain their count and use their documented
        weights for the displayed mean.
        """
        from app.nmf_decoder.cells import cell_index_bounds
        spec = m['cell_type_filter']
        if m.get('marker_series') and m['source_column'] in {'cell_ch','cell_pci'}:
            metric=m['source_column']
            filters=''
            params={'system':spec['system'],'raw':spec['raw_cell_type'],
                    'cell_pci':cell_pci,'cell_arfcn':cell_arfcn}
            if cell_pci is not None:filters+=' AND g.cell_pci=:cell_pci'
            if cell_arfcn is not None:filters+=' AND g.cell_ch=:cell_arfcn'
            sql=f"""
                SELECT g.seq,g.seq AS seq_last,FLOOR(MIN(l.t_rel_s))::int AS second,
                       MIN(l.t_rel_s) AS exact_t_rel_s,g.cell_pci,
                       g.cell_ch AS cell_arfcn,g.{metric} AS value,
                       1::int AS observation_count,
                       COUNT(*) OVER()::int AS total_rows
                FROM nmf_event_light_group g
                JOIN nmf_event_light l
                  ON l.project_id=g.project_id AND l.capture_id=g.capture_id
                 AND l.seq=g.seq AND l.event_code='CELLMEAS'
                WHERE g.project_id=:pid AND g.capture_id=:cap
                  AND g.group_name='cells' AND g.cell_type=:raw
                  AND l.system=:system AND g.{metric} IS NOT NULL {filters}
                GROUP BY g.project_id,g.capture_id,g.seq,g.cell_pci,g.cell_ch,g.{metric}
                ORDER BY g.project_id,g.capture_id,g.seq,g.cell_ch NULLS LAST,
                         g.cell_pci NULLS LAST
            """
            if page is not None and page_size is not None:
                sql+=' LIMIT :limit OFFSET :offset'
                params.update(limit=page_size,offset=(page-1)*page_size)
            result=[dict(r) for r in self.query(sql,params)]
            total=int(result[0].pop('total_rows')) if result else 0
            for row in result[1:]:row.pop('total_rows',None)
            return result,total
        bounds = cell_index_bounds(spec['system'], spec['raw_cell_type'])
        if bounds is None:
            return [], 0
        first_index, last_index = bounds
        params = {
            'metric': m['source_column'], 'event': m['event'],
            'system': spec['system'], 'raw': spec['raw_cell_type'],
            'first_index': first_index, 'last_index': last_index,
            'cell_pci': cell_pci, 'cell_arfcn': cell_arfcn,
        }
        identity_filters = ""
        if cell_pci is not None:
            identity_filters += " AND r.cell_pci=:cell_pci"
        if cell_arfcn is not None:
            identity_filters += " AND r.cell_ch=:cell_arfcn"
        grouped = f"""
            WITH ranked AS (
              SELECT g.seq,g.cell_pci,g.cell_ch,
                     row_number() OVER (
                       PARTITION BY g.project_id,g.capture_id,g.seq,g.cell_type
                       ORDER BY g.identity
                     )-1 AS occurrence
              FROM nmf_event_light_group g
              WHERE g.project_id=:pid AND g.capture_id=:cap
                AND g.group_name='cells' AND g.cell_type=:raw
            ), physical AS (
              SELECT s.seq_first AS seq,MAX(s.seq_last) AS seq_last,s.second,
                     NULL::double precision AS exact_t_rel_s,
                     r.cell_pci,r.cell_ch AS cell_arfcn,
                     CASE WHEN SUM(s.weight) FILTER (WHERE s.weight>0)>0
                       THEN SUM(s.value*s.weight) FILTER (WHERE s.weight>0)
                            / SUM(s.weight) FILTER (WHERE s.weight>0)
                       ELSE AVG(s.value) END AS value,
                     COUNT(*)::int AS observation_count,
                     MIN(s.cell_index)::int AS storage_order
              FROM nmf_cell_second s
              LEFT JOIN ranked r
                ON r.seq=s.seq_first
               AND r.occurrence=s.cell_index-:first_index
              WHERE s.project_id=:pid AND s.capture_id=:cap
                AND s.event_code=:event AND s.metric_code=:metric
                AND s.cell_index BETWEEN :first_index AND :last_index
                {identity_filters}
              GROUP BY s.seq_first,s.second,r.cell_pci,r.cell_ch,
                       CASE WHEN r.cell_pci IS NULL OR r.cell_ch IS NULL
                            THEN s.cell_index ELSE NULL END
            )
        """
        sql = grouped + """
            SELECT seq,seq_last,second,exact_t_rel_s,cell_pci,cell_arfcn,value,
                   observation_count,COUNT(*) OVER()::int AS total_rows
            FROM physical
            ORDER BY seq,cell_arfcn NULLS LAST,cell_pci NULLS LAST,storage_order
        """
        if page is not None and page_size is not None:
            sql += " LIMIT :limit OFFSET :offset"
            params.update(limit=page_size, offset=(page-1)*page_size)
        result = [dict(r) for r in self.query(sql, params)]
        if result:
            total = int(result[0].pop('total_rows'))
            for row in result[1:]:row.pop('total_rows',None)
        else:
            # Only an out-of-range page needs the extra count query.
            count_row = self.query(grouped + "SELECT COUNT(*) AS n FROM physical", params).first()
            total = int(count_row['n'] if count_row else 0)
        return result, total

    def load(self,m,*,page=None,page_size=None,cell_pci=None,cell_arfcn=None):
        code=m['source_column'];cell=m['cell'];attr=m['attr'];event=m['event'];rows=[]
        # 2.53.0 — CAPTURE dispatcher (prefix `cap_`). Résolveurs :
        # CONST (nmf_file/nmf_capture) · SERIES_DEVI (stg_event_raw c{col})
        # · SERIES_TASK (CMDREQ/CMDCOMP window) · MASKED (jamais appelé).
        if m['base_code'].startswith('cap_'):
            from app.kpi.metrics_v3_capture import load_capture
            raw_rows = load_capture(self, m)
            if self.lean_series:
                self._ensure_times(r['seq'] for r in raw_rows)
            out=[]
            for r in raw_rows:
                seq=r['seq']
                if not self.admissible(seq):continue
                t=self.times.get(seq)
                r.update(t_rel_s=t,second=math.floor(t) if t is not None else None)
                ctx=self.context.get(seq,{})
                r.update(operator=ctx.get('operator'),band=ctx.get('band'),cell=cell)
                if r['value'] is not None and m['kind']=='categorical':r['value']=str(r['value'])
                out.append(r)
            return out
        if m.get('cell_type_filter') and event == 'CELLMEAS':
            rows, total = self._load_semantic_cell(
                m, page=page, page_size=page_size,
                cell_pci=cell_pci, cell_arfcn=cell_arfcn,
            )
            m['_total_rows'] = total
            display=m['cell_display']
            for r in rows:
                r['cell_label']=display['label']
                r['cell_system']=display['system']
                if r.get('exact_t_rel_s') is not None:
                    self.times[r['seq']]=float(r['exact_t_rel_s'])
            scale=1e-6 if fields().get(code,{}).get('unit')=='bit/s' else 100 if code=='scell_throughput_share' else 1
            for r in rows:
                if r['value'] is not None:r['value']*=scale
        elif m['base_code']=='cqi_n_params' and m.get('cell_type_filter'):
            spec=m['cell_type_filter']
            table='nmf_event_deep' if self.state['decode_level']=='deep' else 'nmf_event_light'
            rows=[dict(r) for r in self.query(f"""
                SELECT seq,{code} AS value,
                       {'seq_last' if table.endswith('light') else 'seq AS seq_last'}
                FROM {table}
                WHERE project_id=:pid AND capture_id=:cap AND event_code='CQI'
                  AND system=:system AND cqi_cell_type=:raw AND {code} IS NOT NULL
                ORDER BY project_id,capture_id,seq
            """,{'system':spec['system'],'raw':spec['raw_cell_type']})]
            display=m.get('cell_display')
            for row in rows:
                if display:
                    row['cell_label']=display['label'];row['cell_system']=display['system']
        elif m['cell_scoped'] or m['base_code'] in DERIVED:
            # 0.99.2 (hotfix 2026-10-29 22:00Z, régression 0.97.3 catalog 2.56.2) :
            # cette branche gère TOUT metric cell_scoped qui n'est pas CELLMEAS
            # (dci_ul_grants, txpc, pdcp, …). Avant le hotfix, elle faisait
            # `int(cell)` → ValueError sur les codes `@lte-type-N` / `@nr-type-N`
            # introduits par le catalog 2.56.2. Fix : si `cell_type_filter` est
            # posé par `parse_selection` (semantic enum), traduire en plage
            # `[lo, hi]` dans `nmf_cell_second.cell_index` via la projection
            # injective `cells.cell_index_bounds` (couvre toutes les
            # occurrences stockées pour un même (system, raw_cell_type)).
            cell_type_filter = m.get('cell_type_filter')
            if cell_type_filter is not None:
                from app.nmf_decoder.cells import cell_index_bounds
                bounds = cell_index_bounds(cell_type_filter['system'],
                                           cell_type_filter['raw_cell_type'])
                if bounds is None:
                    raise HTTPException(422, dict(
                        reason='cell_type_not_supported_in_enum',
                        system=cell_type_filter['system'],
                        raw_cell_type=cell_type_filter['raw_cell_type']))
                lo, hi = bounds
                sql = ('SELECT seq_first seq, seq_last, value, reason, second '
                       'FROM nmf_cell_second WHERE project_id=:pid AND capture_id=:cap '
                       'AND metric_code=:metric AND cell_index BETWEEN :lo AND :hi '
                       'ORDER BY seq_first')
                rows = [dict(r) for r in self.query(sql, {'metric': code,
                                                          'lo': lo, 'hi': hi})]
            else:
                sql = ('SELECT seq_first seq,seq_last,value,reason,second '
                       'FROM nmf_cell_second WHERE project_id=:pid AND capture_id=:cap '
                       'AND metric_code=:metric AND cell_index=:cell ORDER BY seq_first')
                internal_cell = m.get('legacy_internal_index',
                                      -1 if cell == 'all' else int(cell))
                rows = [dict(r) for r in self.query(sql, {'metric': code,
                                                          'cell': internal_cell})]
            # CELLMEAS radio identity is carried by the exact repeated group.
            # Resolve it by (project, capture, seq, raw cell_type, occurrence),
            # never by timestamp. Native-light captures simply have no typed
            # group row and therefore expose null PCI/ARFCN.
            display=m.get('cell_display')
            if event=='CELLMEAS' and display:
                identities={r['seq']:dict(r) for r in self.query("""
                    WITH ranked AS (
                      SELECT g.seq,g.cell_pci,g.cell_ch,g.cell_type,l.system,
                             row_number() OVER (
                               PARTITION BY g.seq,g.cell_type
                               ORDER BY g.identity
                             )-1 AS occurrence
                      FROM nmf_event_light_group g
                      JOIN nmf_event_light l
                        ON l.project_id=g.project_id AND l.capture_id=g.capture_id
                       AND l.seq=g.seq AND l.event_code=:event
                      WHERE g.project_id=:pid AND g.capture_id=:cap
                        AND g.group_name='cells'
                        AND g.cell_type=:raw AND l.system=:system
                    )
                    SELECT seq,cell_pci,cell_ch FROM ranked
                    WHERE system=:system AND cell_type=:raw
                      AND occurrence=:occurrence
                """,{'event':event,'system':7 if display['system']=='LTE' else 9,
                       'raw':display['raw_cell_type'],
                       'occurrence':m.get('legacy_occurrence',0)})}
                for r in rows:
                    identity=identities.get(r['seq'],{})
                    r['cell_pci']=identity.get('cell_pci')
                    r['cell_arfcn']=identity.get('cell_ch')
            scale=1e-6 if fields().get(code,{}).get('unit')=='bit/s' else 100 if code=='scell_throughput_share' else 1
            for r in rows:
                if r['value'] is not None:r['value']*=scale
        elif m.get('event_attribute'):
            table=('nmf_event_group' if self.state['decode_level']=='deep' else 'nmf_event_light_group') if m.get('repeated_group') else ('nmf_event_deep' if self.state['decode_level']=='deep' else 'nmf_event_light')
            if m.get('repeated_group'):
                sql=(f'SELECT seq,{code} AS value,set_index FROM {table} '
                     'WHERE project_id=:pid AND capture_id=:cap '
                     'AND group_name=:group_name AND '+code+' IS NOT NULL '
                     'ORDER BY project_id,capture_id,seq,set_index')
                source=self.query(sql,{'group_name':m['repeated_group']})
            else:
                tail=',seq_last' if table.endswith('light') else ',seq AS seq_last'
                sql=(f'SELECT seq,{code} AS value{tail} FROM {table} '
                     'WHERE project_id=:pid AND capture_id=:cap AND event_code=:event '
                     'AND '+code+' IS NOT NULL ORDER BY project_id,capture_id,seq')
                source=self.query(sql,{'event':event})
            for raw in source:
                value=raw['value']
                attrs={'value_label':str(value)}
                if raw.get('set_index') is not None:attrs['set_index']=raw['set_index']
                rows.append(dict(seq=raw['seq'],seq_last=raw.get('seq_last',raw['seq']),
                                 value=value,attributes=attrs,count=1))
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
        if self.lean_series:
            self._ensure_times(r['seq'] for r in rows)
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

    def response(self,selections,limit=5000,group_by='operator',x=None,include_map=False,
                 page=1,page_size=1000,table_only=False,cell_pci=None,cell_arfcn=None,
                 series_only=False):
        from app.routes.metrics import sample
        from app.routes.tasks import evidence
        defs=definitions() if x else None
        sql_paginated = (
            table_only and len(selections)==1
            and bool(selections[0].get('cell_type_filter'))
            and selections[0].get('event')=='CELLMEAS'
        )
        loaded=[(
            m,
            self.load(
                m,
                page=page if sql_paginated else None,
                page_size=page_size if sql_paginated else None,
                cell_pci=cell_pci,
                cell_arfcn=cell_arfcn,
            ),
        ) for m in selections]
        series_table_keys=None
        if series_only:
            candidate_keys=set()
            for metric,metric_rows in loaded:
                physical=bool(metric.get('cell_type_filter')) and metric.get('event')=='CELLMEAS'
                for item in metric_rows:
                    if item['second'] is None:continue
                    candidate_keys.add(
                        (item['seq'],item.get('cell_arfcn'),item.get('cell_pci'))
                        if physical else (item['second'],None,None)
                    )
            def _series_key(k):
                return (k[0],
                        (k[1] is None,0 if k[1] is None else k[1]),
                        (k[2] is None,0 if k[2] is None else k[2]))
            series_table_keys=set(sorted(candidate_keys,key=_series_key)[:page_size])
        table={};series=[];hist=[];map_points=[];gaps=[]
        for m,rows in loaded:
            points=[];buckets=defaultdict(list)
            if any(r['t_rel_s'] is None for r in rows):gaps.append(m['selection']+': Missing timestamp; observations excluded from temporal views')
            for r in rows:
                if r['second'] is not None:buckets[r['second']].append(r)
                if not table_only and r['value'] is not None and r['t_rel_s'] is not None:
                    tip=f"{m['label']} : {r['value']} {m['unit']} · seq {r['seq']}"+(' · '+str(r.get('attributes')) if r.get('attributes') else '')
                    value_label=str(r.get('attributes',{}).get('value_label',r['value']))
                    cell_label=r.get('cell_label')
                    if cell_label and r.get('cell_system'):cell_label+=f" · {r['cell_system']}"
                    if cell_label and r.get('cell_pci') is not None:cell_label+=f" · PCI {r['cell_pci']:g}"
                    if cell_label and r.get('cell_arfcn') is not None:cell_label+=f" · ARFCN {r['cell_arfcn']:g}"
                    points.append(dict(seq=r['seq'],t_rel_s=r['t_rel_s'],value=r['value'],label=value_label,cell=cell_label,tooltip=tip,attributes=r.get('attributes',{})))
                if r.get('reason'):gaps.append(r['reason'])
            if not table_only:
                sample_kind='categorical_marker' if m.get('marker_series') and m['kind']=='categorical' else m['kind']
                out,sampling=sample(points,limit,sample_kind) if m['kind']!='event' else (points,dict(method='all_occurrences',factor=1,seq_bucket_width=None))
                if m['kind']=='event' and len(points)>limit:raise HTTPException(422,dict(reason='event_occurrences_exceed_max_points',required=len(points)))
                series.append(dict(code=m['selection'],label=m['label'] or m['selection'],unit=m['unit'] or '',kind=m['kind'],cell=m['cell'],source_table='nmf_cell_second' if m['cell_scoped'] else m['source_table'],source_column=m['source_column'],n_total=len(points),n_returned=len(out),sampling=sampling,states=list(dict.fromkeys(str(p['value']) for p in points)) if m['kind']=='categorical' else [],segments=[],points=out))
            for second,rs in buckets.items():
                # 0.99.2 (hotfix) : clé de bucket homogène en 3-tuple pour que
                # `sorted(table)` fonctionne même quand plusieurs metrics
                # mélangent le path "physical" (une ligne par (seq, arfcn, pci))
                # et le path "legacy" (une ligne par second). Avant le hotfix,
                # les clés `int(second)` et `tuple` cohabitaient dans le même
                # dict → TypeError sur `sorted` ligne ordered=…
                physical = bool(m.get('cell_type_filter')) and m.get('event') == 'CELLMEAS'
                per_event = bool(m.get('event_attribute'))
                groups = defaultdict(list)
                if physical:
                    for item in rs:
                        groups[(item['seq'], item.get('cell_arfcn'), item.get('cell_pci'))].append(item)
                elif per_event:
                    for item in rs:groups[(item['seq'],None,None)].append(item)
                else:
                    groups[(second, None, None)] = rs
                for physical_key, physical_rows in groups.items():
                    rs = physical_rows
                    table_key = physical_key
                    if series_table_keys is not None and table_key not in series_table_keys:
                        continue
                    row=table.setdefault(table_key,dict(second=second,t_rel_s=self.times.get(rs[0]['seq'],float(second)),seq_first=rs[0]['seq'],seq_last=rs[-1]['seq'],values={},counts={}))
                    row['seq_first']=min(row['seq_first'],rs[0]['seq']);row['seq_last']=max(row['seq_last'],rs[-1]['seq'])
                    value=1 if m['kind']=='event' else aggregate_values(rs,'last' if m.get('attr') or m['cell_scoped'] else m.get('agg','last'))
                    if m.get('weighted') and not m['cell_scoped'] and len([r for r in rs if r['value'] is not None])>1:
                        # Projection preserves weighted per-seq values but does not expose their denominators.
                        # Never average those means again to manufacture a second-level statistic.
                        value=None;gaps.append(m['selection']+': missing inter-sample weights; per-second aggregate unavailable, per-seq series preserved')
                    row['values'][m['selection']]=value;row['counts'][m['selection']]=sum(r.get('observation_count',r.get('count',1)) for r in rs)
                    if m.get('cell_display'):
                        row['cell_label']=m['cell_display']['label']
                        row['cell_system']=m['cell_display']['system']
                        row['cell_pci']=next((r.get('cell_pci') for r in reversed(rs) if r.get('cell_pci') is not None),None)
                        row['cell_arfcn']=next((r.get('cell_arfcn') for r in reversed(rs) if r.get('cell_arfcn') is not None),None)
            if not table_only and not series_only:
                groups=defaultdict(list)
                for r in rows:
                    if r['value'] is None:continue
                    groups[(r.get('operator') if 'operator' in group_by else None,r.get('band') if 'band' in group_by else None)].append(r)
                for (op,band),rs in groups.items():
                    vals=[r['value'] for r in rs];numeric=m['kind']=='numeric'
                    hist.append(dict(code=m['selection'],label=m['label'],operator=op,band=band,cell=m['cell'],n=sum(r.get('count',1) for r in rs),p10=percentile(vals,.1) if numeric else None,p50=percentile(vals,.5) if numeric else None,p90=percentile(vals,.9) if numeric else None,distribution=[dict(value=v,n=n) for v,n in Counter(vals).items()] if not numeric else []))
        durations=self.connected_seconds(group_by) if not table_only and not series_only and any(m['kind']=='event' for m in selections) else {}
        connected=sum(durations.values()) if durations else None
        for h in hist:
            duration=durations.get((h['operator'],h['band']))
            h['per_connected_hour']=h['n']*3600/duration if duration and next(m for m in selections if m['selection']==h['code'])['kind']=='event' else None
        scatter=[]
        if x and not table_only and not series_only:
            xm=parse_selection(x,defs);xr=self.load(xm)
            for m,yr in loaded:
                if m['cell']!=xm['cell'] or m['cell_scoped']!=xm['cell_scoped']:
                    gaps.append('scatter_cell_scope_mismatch');continue
                for y, previous in _pair_previous_or_same(xr, yr):
                    if previous and previous['value'] is not None and y['value'] is not None:
                        scatter.append(dict(code=m['selection'],seq=y['seq'],x_seq=previous['seq'],seq_gap=y['seq']-previous['seq'],cell=m['cell'],x=previous['value'],value=y['value']))
        # 0.75.0 — GPS seq→(lat,lon). Lu une fois, utilisé pour map_points
        # ET pour enrichir chaque row de la table (previous-or-same seq).
        # N1 — filter event_code='GPS' AJOUTÉ : avant N1, tout event avec
        # lat/lon non-NULL (y compris positions héritées propagées par Nemo)
        # était traité comme fix exact → les points de la carte étaient
        # majoritairement des positions ré-utilisées. Désormais seuls les
        # events GPS vrais peuplent `gps_exact` ; `_pair_previous_or_same`
        # produit explicitement `previous_fix` + `delta_seq`.
        gps_hi=None
        if series_only and table:
            def _early_sort_key(k):
                return (k[0],
                        (k[1] is None, 0 if k[1] is None else k[1]),
                        (k[2] is None, 0 if k[2] is None else k[2]))
            csv_keys=sorted(table,key=_early_sort_key)[:page_size]
            gps_hi=max(table[k]['seq_first'] for k in csv_keys)
        gps_fixes=[]
        if self.lean_series and table:
            gps_sql="""
                SELECT r.seq,r.lat,r.lon,MIN(l.t_rel_s) AS t_rel_s
                FROM stg_event_raw r
                LEFT JOIN nmf_event_light l
                  ON l.project_id=r.project_id AND l.capture_id=r.capture_id
                 AND l.seq=r.seq AND l.event_code='GPS'
                WHERE r.project_id=:pid AND r.capture_id=:cap
                  AND r.event_code='GPS' AND r.lat IS NOT NULL AND r.lon IS NOT NULL
                  AND NOT(r.lat=0 AND r.lon=0) AND r.seq<=:gps_hi
                GROUP BY r.seq,r.lat,r.lon ORDER BY r.seq
            """
            for raw_fix in self.query(gps_sql,{'gps_hi':gps_hi}):
                fix=dict(raw_fix)
                t_rel_s=fix.pop('t_rel_s')
                if t_rel_s is not None:self.times[fix['seq']]=float(t_rel_s)
                gps_fixes.append(fix)
        elif not self.lean_series:
            gps_fixes=[dict(r) for r in self.query("""
                SELECT seq,lat,lon FROM stg_event_raw
                WHERE project_id=:pid AND capture_id=:cap AND event_code='GPS'
                  AND lat IS NOT NULL AND lon IS NOT NULL AND NOT(lat=0 AND lon=0)
                ORDER BY seq
            """)]
        if self.lean_series:
            self._ensure_times(f['seq'] for f in gps_fixes)
        gps_exact={f['seq']:(f['lat'],f['lon']) for f in gps_fixes}
        if include_map and not series_only:
            # Serving-cell proof for map links. CHI #6 is the documented LTE
            # Cell ID. Its state is carried forward only inside this capture
            # in canonical seq order, then joined by exact ECI to cell_ref.
            # An absent reference match stays absent: never pick a nearby site.
            chi_rows=[dict(r) for r in self.query("""
                SELECT seq, raw_fields->>'c9' AS eci
                FROM stg_event_raw
                WHERE project_id=:pid AND capture_id=:cap
                  AND event_code='CHI' AND system='LTE'
                  AND raw_fields->>'c9' ~ '^[0-9]+$'
                ORDER BY seq
            """)]
            cell_ids=sorted({r['eci'] for r in chi_rows})
            cell_refs={}
            if cell_ids:
                cell_refs={r['eci']:dict(r) for r in self.query("""
                    SELECT eci,id AS cell_ref_id,site_id,site_name,
                           ST_Y(geom) AS lat,ST_X(geom) AS lng
                    FROM cell_ref
                    WHERE eci=ANY(:serving_ecgis) AND geom IS NOT NULL
                """,{'serving_ecgis':cell_ids})}
            # N1 — map_points.position_source ∈ {'exact','previous_fix'} + delta_seq.
            # Avant N1 : seuls les rows exactement sur un GPS fix étaient
            # tracés ; les autres n'étaient PAS ajoutés sur la carte. En plus
            # `gps_exact` incluait les lat/lon héritées (bug fix ligne 369).
            # Désormais : chaque row avec une valeur est tracé ; position_source
            # distingue le fix exact du fix précédent (delta_seq = r.seq - prev.seq).
            rows_for_map: list[tuple] = []
            for m,rows in loaded:
                for r,chi in _pair_previous_or_same(chi_rows,rows):
                    if r['value'] is None:
                        continue
                    rows_for_map.append((m, r, chi))
            # Un seul previous-or-same seq join GPS pour toute la boucle.
            keyed=[{'seq':r['seq'],'_tuple':(m,r,chi)} for (m,r,chi) in rows_for_map]
            keyed.sort(key=lambda e: e['seq'])
            for y, prev in _pair_previous_or_same(gps_fixes, keyed):
                if prev is None:
                    continue
                m,r,chi = y['_tuple']
                lat,lng = prev['lat'], prev['lon']
                position_source = 'exact' if prev['seq']==r['seq'] else 'previous_fix'
                delta_seq = r['seq'] - prev['seq']
                ref=cell_refs.get(chi['eci']) if chi else None
                tooltip = (f"{m['label']} · seq {r['seq']} · {r['value']} {m['unit']}"
                           + (f" · position héritée du fix seq {prev['seq']} (Δseq {delta_seq})"
                              if position_source=='previous_fix' else ''))
                map_points.append(dict(
                    seq=r['seq'],lat=lat,lng=lng,code=m['selection'],
                    value=r['value'],t_rel_s=r['t_rel_s'],
                    position_source=position_source, delta_seq=delta_seq,
                    position_fix_seq=prev['seq'],
                    tooltip=tooltip,
                    serving_cell_id=chi['eci'] if ref else None,
                    serving_cell_seq=chi['seq'] if ref else None,
                    serving_cell_ref_id=ref['cell_ref_id'] if ref else None,
                    serving_site_id=ref['site_id'] if ref else None,
                    serving_site_name=ref['site_name'] if ref else None,
                    serving_cell_lat=ref['lat'] if ref else None,
                    serving_cell_lng=ref['lng'] if ref else None,
                    serving_cell_source='chi_previous_seq_cell_ref_exact' if ref else None,
                ))
        pair_rows=[] if series_only else [dict(p) for p in self.pairs if self.admissible(p['seq_start']) and (p['seq_end'] is None or self.admissible(p['seq_end']))]
        pair_rates=[]
        for kind in sorted({p['type'] for p in pair_rows}):
            ps=[p for p in pair_rows if p['type']==kind];known=[p for p in ps if p['outcome'] in ('ok','fail')]
            pair_rates.append(dict(type=kind,attempts=len(ps),completed=sum(p['seq_end'] is not None for p in ps),success=sum(p['outcome']=='ok' for p in ps),known_outcomes=len(known),success_pct=100*sum(p['outcome']=='ok' for p in known)/len(known) if known else None))
        rid=evidence(self.db,self.pid,';\n'.join(q['sql'] for q in self.sqls),{'queries':self.sqls,'capture_id':self.cap,'selections':[m['selection'] for m in selections],'filters':self.f},dict(rows=len(table),series=len(series)))
        # 0.99.2 (hotfix) : clés `table` toujours en 3-tuple (seq_or_second,
        # cell_arfcn|None, cell_pci|None). None trié EN PREMIER via la clé de
        # tri explicite (Python 3 ne compare pas None à int directement).
        def _table_sort_key(k):
            return (k[0],
                    (k[1] is None, 0 if k[1] is None else k[1]),
                    (k[2] is None, 0 if k[2] is None else k[2]))
        ordered=[table[k] for k in sorted(table, key=_table_sort_key)]
        total_rows=(int(selections[0].get('_total_rows', len(ordered))) if sql_paginated else len(ordered))
        total_pages=max(1,math.ceil(total_rows/page_size))
        if page>total_pages:raise HTTPException(422,dict(reason='page_out_of_range',total_pages=total_pages))
        page_rows=ordered if sql_paginated else ordered[(page-1)*page_size:page*page_size]
        rows_to_enrich=page_rows if series_only else ordered
        from decimal import Decimal
        # 0.75.0 — time_local (= ancien time_label), time_utc (local - offset)
        # et join GPS previous-or-same seq (sur seq_first).
        h,minute,sec=self.origin_ts.split(':');origin=Decimal(h)*3600+Decimal(minute)*60+Decimal(sec)
        nmf_start_at=self.file_meta['start_at']
        capture_date=date_from_start_at_py(nmf_start_at)
        utc_offset_min=self.file_meta['utc_offset_min']
        # t_rel_s de chaque row (sur capture_id, seq_first) : identique à self.times[seq_first]
        for row in rows_to_enrich:
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
        task_rows=[] if series_only else list(self.db.execute(text(
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
        for row in rows_to_enrich:
            tn, ti = _task_at(row['seq_last'])
            row['task_name']=tn; row['task_index']=ti
        # GPS enrichment par ligne — previous-or-same seq, zero fabrication.
        gps_source=self.state['decode_level']
        no_gps_reason='no_gps_in_capture' if not gps_fixes else None
        # yr pour le join = ordered rows avec clé seq=seq_first
        yr=[{'seq':row['seq_first'],'_row':row} for row in rows_to_enrich]
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
        # CSV = exactement la page renvoyée par la table UI.
        output=io.StringIO();writer=csv.writer(output);keys=[m['selection'] for m in selections]
        writer.writerow(['result_id','capture_id','second','seq_first','seq_last','time_local','time_utc','lat','lon','gps_source','gps_age_s','reason',*keys])
        for row in page_rows:writer.writerow([rid,self.cap,row['second'],row['seq_first'],row['seq_last'],row['time_local'],row['time_utc'],row['lat'],row['lon'],row['gps_source'],row['gps_age_s'],row['reason'],*[row['values'].get(k) for k in keys]])
        columns=[]
        for m in selections:
            display=m.get('cell_display') or {}
            columns.append(dict(code=m['selection'],label=m['label'] or m['selection'],unit=m['unit'] or '',kind=m['kind'],cell=m['cell'],
                cell_label=display.get('label'),cell_system=display.get('system'),
                cell_internal_index=None))
        return dict(**dict(self.state),project_id=self.pid,capture_id=self.cap,result_id=rid,origin_seq=self.origin_seq,origin_ts=self.origin_ts,nmf_start_at=nmf_start_at,capture_date=capture_date,utc_offset_min=utc_offset_min,duration_s=self.duration_s,aggregation='cell: schema-weighted capture-second; other numeric: schema aggregate; event: presence + count / last attribute',time_policy='capture-local source clock in seq order; no interpolation',columns=columns,series=series,rows=page_rows,page=page,page_size=page_size,total_rows=total_rows,total_pages=total_pages,histogram=hist,scatter=scatter,map_points=map_points,connected_seconds=connected,connected_reason=None if connected else 'No proven complete eligible RRC → RRD interval',pair_rates=pair_rates,gaps=sorted(set(gaps)),csv=output.getvalue(),pairing='previous-or-same seq, same capture and same cell; no interpolation')
