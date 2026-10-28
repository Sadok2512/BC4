"""Transactional capture replay. Typed columns + arrays, never JSON. One decoder for both levels."""
import time
from dataclasses import asdict
from pathlib import Path
from sqlalchemy import text
from . import DECODER_VERSION
from .schema import fields
from .source import records
from .light import Light
from .cells import cell_rows
from .pairs import Pairs

HEADERS=sorted(k for k,v in fields().items() if v['group'] is None)
GROUPS=sorted(k for k,v in fields().items() if v['group'] is not None)
ALL=sorted(fields())
HEADER_SET=frozenset(HEADERS)
GROUP_SET=frozenset(GROUPS)
DEEP_BASE=['project_id','capture_id','seq','line_no','event_code','system','ts','t_rel_s','format_version','decoder_version','schema_version','decode_status','reasons','tokens','field_codes','unk_string','quoted','context_id','context_ids']
GROUP_BASE=['project_id','capture_id','seq','group_name','set_index']
LIGHT_BASE=['project_id','capture_id','seq','seq_last','event_code','system','second','dimension','t_rel_s','decoder_version','schema_version','format_version','decode_status','reasons','unknown','n_records','n_partial','context_id','context_ids']


LEGACY_NUMERIC_STRING_FIELDS=set('bf_bts_file dl_device_label dn_device_name ei_device_identity ff_file_format_version hv_handler_version hw_hardware_version hw_manufacturer hw_model id_measurement_id mf_map_file product_product_name product_product_version si_subscriber_identity sp_subscriber_phone_number start_date stop_date sw_device_software_version ts_test_script_file caa_phone_number caa_own_phone_number caa_unique_id daa_host_address pac_ip rrcsm_rrc_msg rrcsm_subchannel rrcsm_rrc_data rtpsm_rtp_message rtpsm_rtp_data sipsm_sip_name sipsm_sip_data'.split())

def storage_float_fields(db):
    rows = db.execute(text("""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name IN ('nmf_event_deep', 'nmf_event_group')
          AND data_type IN ('double precision', 'real', 'numeric')
    """)).all()
    return {
        table: frozenset(column for row_table, column in rows if row_table == table)
        for table in ('nmf_event_deep', 'nmf_event_group')
    }

def normalize_for_stored_deep(record, float_fields=None):
    """Match COPY's historical NULL coercion before deriving Light rows.

    Deep used to be written and read back before Light aggregation.  Psycopg's
    COPY adapter discarded textual values for legacy numeric columns, so the
    readback exposed NULL.  Normalizing the in-memory record preserves that
    exact behaviour while avoiding the database round trip.
    """
    for name, value in record.values.items():
        if name in LEGACY_NUMERIC_STRING_FIELDS and isinstance(value, str):
            record.values[name] = None
    for group in record.groups:
        for name, value in group['values'].items():
            if name in LEGACY_NUMERIC_STRING_FIELDS and isinstance(value, str):
                group['values'][name] = None
    float_fields = float_fields or {}
    header_floats = float_fields.get('nmf_event_deep', ())
    group_floats = float_fields.get('nmf_event_group', ())
    # Reproduce the stored Deep projection exactly.  Some format-dependent
    # codes occur once as a header and once as a group field; the global SQL
    # layout assigns each code to only one side.  The historical readback
    # therefore omitted the other occurrence before Light aggregation.
    record.values = {
        name: float(value) if name in header_floats and isinstance(value, int)
        and not isinstance(value, bool) else value
        for name, value in record.values.items()
        if name in HEADER_SET and value is not None
    }
    for group in record.groups:
        group['values'] = {
            name: float(value) if name in group_floats and isinstance(value, int)
            and not isinstance(value, bool) else value
            for name, value in group['values'].items()
            if name in GROUP_SET and value is not None
        }

def copy_rows(db,table,columns,rows):
    if not rows:return
    legacy_positions = [
        index for index, name in enumerate(columns)
        if name in LEGACY_NUMERIC_STRING_FIELDS
    ]
    connection=db.connection().connection.dbapi_connection
    with connection.cursor() as cursor:
        with cursor.copy('COPY '+table+' ('+','.join(columns)+') FROM STDIN') as copy:
            for row in rows:
                # map(dict.get, ...) performs the hundreds of sparse column
                # lookups in C.  Only legacy columns require a Python-side
                # type check; all other values are passed through unchanged.
                vals=list(map(row.get,columns))
                for index in legacy_positions:
                    if isinstance(vals[index],str):vals[index]=None
                copy.write_row(tuple(vals))
    # A completed COPY batch is a resumability checkpoint.  Callers delete
    # the capture before replay, so an interrupted sequence is rebuilt without
    # duplicates while no transaction spans the next CPU-heavy batch build.
    db.commit()

def write_light(db,pid,cap,light):
    db.execute(text('DELETE FROM nmf_event_light WHERE project_id=:pid AND capture_id=:cap'),{'pid':pid,'cap':cap})
    db.execute(text('DELETE FROM nmf_event_light_group WHERE project_id=:pid AND capture_id=:cap'),{'pid':pid,'cap':cap})
    db.commit()
    rows=[];groups=[]
    for r in light.rows():
        for g in r.pop('groups'):
            groups.append(dict(project_id=pid,capture_id=cap,seq=r['seq'],group_name=g['group_name'],identity=g['identity'],set_index=g['set_index'],n_records=g['n_records'],**g['values']))
        if len(groups)>=10000:
            copy_rows(db,'nmf_event_light_group',GROUP_BASE+['identity','n_records']+GROUPS,groups);groups=[]
        values=r.pop('values');r.update(values,project_id=pid,capture_id=cap,decoder_version=DECODER_VERSION,schema_version=DECODER_VERSION,
            decode_status='partial' if r['n_partial'] else 'ok')
        rows.append(r)
        if len(rows)>=1000:copy_rows(db,'nmf_event_light',LIGHT_BASE+ALL,rows);rows=[]
    copy_rows(db,'nmf_event_light',LIGHT_BASE+ALL,rows)
    copy_rows(db,'nmf_event_light_group',GROUP_BASE+['identity','n_records']+GROUPS,groups)
    cell_values=[dict(project_id=pid,capture_id=cap,decoder_version=DECODER_VERSION,**r) for r in cell_rows(light)]
    # Build the CPU-heavy projection before opening its replacement
    # transaction.  DELETE + COPY remain atomic and no transaction sits idle.
    db.execute(text('DELETE FROM nmf_cell_second WHERE project_id=:pid AND capture_id=:cap'),{'pid':pid,'cap':cap})
    if cell_values:copy_rows(db,'nmf_cell_second',list(cell_values[0]),cell_values)
    else:db.commit()

def decode_capture(db,pid,cap,level,*,force=False,parsing_snapshot=None):
    start=time.perf_counter();params={'pid':pid,'cap':cap}
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:k))'),{'k':'populate:'+pid})
    old=db.execute(text('SELECT * FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap'),params).mappings().first()
    parsing = old or parsing_snapshot or db.execute(text('''SELECT parse_binning_mode AS binning_mode,
        parse_temporal_resolution AS temporal_resolution, parse_spatial_bin_m AS spatial_bin_m,
        'query-binning-v1' AS aggregation_contract_version
        FROM projects WHERE id=:pid'''),params).mappings().one()
    # Snapshot de capture immuable (prolongement du contrat 0061 import-snapshot) :
    # une capture déjà présente dans `nmf_capture` est DONE et ne doit JAMAIS
    # être re-décodée implicitement — même quand `DECODER_VERSION` live a
    # évolué. Chaque capture conserve son décodeur d'origine (`old['decoder_version']`)
    # tant qu'un re-parse n'est pas DEMANDÉ explicitement par la commande
    # `app.scripts.reparse_capture` (force=True + trace du snapshot
    # before/after). Historique : avant 2026-10-28, le skip conditionnait sur
    # `old['decoder_version']==DECODER_VERSION`, ce qui déclenchait
    # ensure_light → decode_capture sur TOUTES les captures du projet à
    # chaque upgrade du décodeur (incident Test_5 2026-10-28 : 22 captures
    # repassées 1.7.1→1.7.2 à l'insu de l'opérateur).
    if old and not force:
        db.commit()
        return dict(capture_id=cap, skipped=True, elapsed_s=0,
                    reason='snapshot_immuable',
                    kept_decoder_version=old['decoder_version'])
    file=db.execute(text('''SELECT DISTINCT n.id,n.source_path,n.sha256 FROM nmf_file n JOIN stg_event_raw r ON r.nmf_file_id=n.id
        WHERE n.project_id=:pid AND r.capture_id=:cap UNION SELECT DISTINCT n.id,n.source_path,n.sha256 FROM nmf_file n JOIN stg_event r ON r.nmf_file_id=n.id
        WHERE n.project_id=:pid AND r.capture_id=:cap'''),params).mappings().all()
    if len(file)!=1 or not file[0]['source_path'] or not Path(file[0]['source_path']).is_file():raise ValueError('capture_source_unavailable')
    file=file[0]
    if old and old['decode_level']=='deep':level='deep'  # Never downgrade or erase retained observations.
    float_fields=storage_float_fields(db) if level=='deep' else {}
    # Le parsing NMF est du calcul fichier pur et peut durer plusieurs minutes.
    # Libère la transaction de métadonnées avant d'ouvrir le fichier ; le
    # populate_chain conserve son verrou advisory de session entre les commits.
    db.commit()
    if level=='deep':
        # Partition DDL and parent-table cleanup must be one short serialized
        # transaction.  If separate workers interleave AccessExclusive (DDL)
        # and RowExclusive (DELETE) locks across the two partitioned parents,
        # PostgreSQL can deadlock.  The lock is released by the commit below,
        # before the CPU-heavy decode starts.
        db.execute(text(
            "SELECT pg_advisory_xact_lock(hashtext('nmf_decoder_partition_ddl'))"
        ))
        db.execute(text('SELECT nmf_decoder_partition(:cap)'),{'cap':cap})
        for table in ('nmf_event_group','nmf_event_deep'):
            db.execute(text('DELETE FROM '+table+' WHERE project_id=:pid AND capture_id=:cap'),params)
        db.commit()
    light=Light();pairs=Pairs();deep_rows=[];group_rows=[];n=partial=0;version='unknown'
    for r in records(file['source_path'],cap,file['sha256']):
        if r.excluded:continue
        n+=1;partial+=r.decode_status=='partial';version=r.format_version
        if level=='deep':normalize_for_stored_deep(r,float_fields)
        pairs.add(r)
        light.add(r)
        if level=='deep':
            deep_rows.append(dict(project_id=pid,**{k:getattr(r,k) for k in DEEP_BASE if k!='project_id'},**r.values))
            for g in r.groups:
                group_rows.append(dict(project_id=pid,capture_id=cap,seq=r.seq,group_name=g['group_name'],set_index=g['set_index'],**g['values']))
            if len(deep_rows)>=1000:copy_rows(db,'nmf_event_deep',DEEP_BASE+HEADERS,deep_rows);deep_rows=[]
            if len(group_rows)>=10000:copy_rows(db,'nmf_event_group',GROUP_BASE+GROUPS,group_rows);group_rows=[]
    if level=='deep':
        copy_rows(db,'nmf_event_deep',DEEP_BASE+HEADERS,deep_rows);copy_rows(db,'nmf_event_group',GROUP_BASE+GROUPS,group_rows)
    write_light(db,pid,cap,light)
    pair_values=[dict(project_id=pid,capture_id=cap,decoder_version=DECODER_VERSION,**r) for r in pairs.rows()]
    db.execute(text('DELETE FROM nmf_event_pair WHERE project_id=:pid AND capture_id=:cap'),params)
    if pair_values:copy_rows(db,'nmf_event_pair',list(pair_values[0]),pair_values)
    else:db.commit()
    elapsed=time.perf_counter()-start
    # 0.76.0 — kind detection by content (jamais inventé) :
    # 'scanner' = events SCAN* présents ET aucun event cell-scoped UE (CELLMEAS,CI).
    # 'ue' = CELLMEAS ou CI présent.
    # null = capture non classifiable (très rare : ni SCAN* ni CELLMEAS/CI).
    kind=classify_capture_kind(db,pid,cap)
    db.execute(text('''INSERT INTO nmf_capture(project_id,capture_id,nmf_file_id,decode_level,decoder_version,schema_version,format_version,
        deep_decoded_at,n_records,n_partial,elapsed_s,kind,binning_mode,temporal_resolution,spatial_bin_m,aggregation_contract_version)
        VALUES(:pid,:cap,:fid,:level,:version,:version,:format,
        CASE WHEN :level='deep' THEN now() END,:n,:partial,:elapsed,:kind,:binning_mode,:temporal_resolution,:spatial_bin_m,:aggregation_contract_version)
        ON CONFLICT(project_id,capture_id) DO UPDATE SET decode_level=excluded.decode_level,decoder_version=excluded.decoder_version,
        schema_version=excluded.schema_version,format_version=excluded.format_version,deep_decoded_at=excluded.deep_decoded_at,
        decoded_at=now(),n_records=excluded.n_records,n_partial=excluded.n_partial,elapsed_s=excluded.elapsed_s,kind=excluded.kind'''),
        dict(params,fid=file['id'],level=level,version=DECODER_VERSION,format=version,n=n,partial=partial,elapsed=elapsed,kind=kind,
             binning_mode=parsing['binning_mode'],temporal_resolution=parsing['temporal_resolution'],spatial_bin_m=parsing['spatial_bin_m'],
             aggregation_contract_version=parsing.get('aggregation_contract_version') or 'query-binning-v1'))
    # The capture replacement is the atomic resumability boundary.  Commit it
    # here rather than relying on each caller to do so after arbitrary Python
    # work (ensure_light, import ingestion, or manual decode jobs).
    db.commit()
    return dict(capture_id=cap,level=level,n_records=n,n_partial=partial,elapsed_s=elapsed,kind=kind)


# 0.76.0 — Classification capture par CONTENU (NFF 2.19 events observés), jamais
# devinée depuis le nom du fichier. Les 4 event_codes SCAN sont les marqueurs
# propres au mode Ibflex-Scanner Nemo HANDY ; CELLMEAS/CI sont les 2 events
# cell-scoped systématiques en mode UE.
SCANNER_EVENTS={'SCANCONFIG','STARTSCAN','CELLSCAN','OFDMSCAN'}
UE_CELL_SCOPED_EVENTS={'CELLMEAS','CI'}


def classify_capture_kind(db,pid,cap):
    codes={r[0] for r in db.execute(text(
        'SELECT DISTINCT event_code FROM nmf_event_light WHERE project_id=:pid AND capture_id=:cap'
    ),{'pid':pid,'cap':cap}).all()}
    has_ue=bool(codes & UE_CELL_SCOPED_EVENTS)
    has_scan=bool(codes & SCANNER_EVENTS)
    if has_ue:return 'ue'
    if has_scan:return 'scanner'
    return None

def ensure_light(db,pid):
    caps=db.execute(text('SELECT DISTINCT capture_id FROM stg_event_raw WHERE project_id=:pid ORDER BY capture_id'),{'pid':pid}).scalars().all()
    project_parsing=db.execute(text('''SELECT parse_decode_level AS decode_level,
        parse_binning_mode AS binning_mode, parse_temporal_resolution AS temporal_resolution,
        parse_spatial_bin_m AS spatial_bin_m, 'query-binning-v1' AS aggregation_contract_version
        FROM projects WHERE id=:pid'''),{'pid':pid}).mappings().one()
    results=[]
    for cap in caps:
        # A capture snapshot is immutable.  Population may run after the project
        # defaults changed, so it must never promote an existing Light capture
        # to Deep (or replace any of its binning metadata).
        snapshot=db.execute(text('''SELECT decode_level,binning_mode,temporal_resolution,
            spatial_bin_m,aggregation_contract_version,decoder_version
            FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap'''),
            {'pid':pid,'cap':cap}).mappings().first()
        parsing=snapshot or project_parsing
        results.append(decode_capture(db,pid,cap,parsing['decode_level'],parsing_snapshot=parsing))
    return results
