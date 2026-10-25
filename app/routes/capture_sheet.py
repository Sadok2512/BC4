"""Fiche capture — métadonnées, SCRIPT, DAA/DREQ/DCOMP, DEVI, taille .nmf.

Jamais inventé : si une valeur est absente, retourne `null` + `reason` dans
le champ `missing_fields` au lieu de remplir avec une valeur plausible.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.routes.tasks import project

router = APIRouter(tags=['captures'], dependencies=[Depends(get_current_user)])


@router.get('/projects/{project_id}/captures/{capture_id}/sheet')
def capture_sheet(project_id: str, capture_id: str, db: Session = Depends(get_db)):
    """Fiche capture pour l'app Metrics. Pas d'identifiant abonné
    (#EI, #SI, numéros de téléphone, IMSI/IMEI/TMSI/GUTI masqués).
    """
    project(db, project_id)
    cap = db.execute(text("""
        SELECT c.capture_id, c.decode_level, c.decoder_version, c.schema_version,
               c.format_version, c.decoded_at, c.deep_decoded_at, c.n_records,
               c.n_partial, c.elapsed_s, c.kind, c.nmf_file_id,
               f.filename, f.size_bytes, f.sha256, f.uploaded_at
        FROM nmf_capture c JOIN nmf_file f ON f.id = c.nmf_file_id
        WHERE c.project_id = :pid AND c.capture_id = :cap
    """), {'pid': project_id, 'cap': capture_id}).mappings().first()
    if not cap:
        raise HTTPException(404, 'capture_not_found')

    missing = []

    # SCRIPT event : c4=name, c5=version, c10/c13/c16=commands
    script = db.execute(text("""
        SELECT raw_fields FROM stg_event_raw
        WHERE project_id = :pid AND capture_id = :cap AND event_code = 'SCRIPT'
        ORDER BY seq LIMIT 1
    """), {'pid': project_id, 'cap': capture_id}).scalar()
    script_meta = None
    if script:
        rf = script if isinstance(script, dict) else {}
        script_meta = {
            'file': rf.get('c4'),
            'version': rf.get('c5'),
            'cmd_1': rf.get('c10'),
            'cmd_2': rf.get('c13'),
            'cmd_3': rf.get('c16'),
        }
    else:
        missing.append({'field': 'script', 'reason': 'no_SCRIPT_event_in_capture'})

    # DEVI events : batterie + température (jamais individuellement, agrégé)
    devi = db.execute(text("""
        SELECT MIN((raw_fields->>'c3')::float) AS batt_min,
               MAX((raw_fields->>'c3')::float) AS batt_max,
               MIN((raw_fields->>'c8')::float) AS temp_min,
               MAX((raw_fields->>'c8')::float) AS temp_max,
               MIN((raw_fields->>'c11')::float) AS volt_min,
               MAX((raw_fields->>'c11')::float) AS volt_max,
               COUNT(*) AS n
        FROM stg_event_raw
        WHERE project_id = :pid AND capture_id = :cap AND event_code = 'DEVI'
    """), {'pid': project_id, 'cap': capture_id}).mappings().first()
    devi_meta = None
    if devi and devi['n']:
        devi_meta = dict(devi)
    else:
        missing.append({'field': 'devi', 'reason': 'no_DEVI_event_in_capture'})

    # DAA (connexions ouvertes), DREQ (demandes), DCOMP (complétions)
    daa_dreq = db.execute(text("""
        SELECT event_code,
               COUNT(*) AS n,
               MIN(seq)::int AS seq_first,
               MAX(seq)::int AS seq_last
        FROM stg_event_raw
        WHERE project_id = :pid AND capture_id = :cap
          AND event_code IN ('DAA', 'DREQ', 'DCOMP')
        GROUP BY event_code ORDER BY event_code
    """), {'pid': project_id, 'cap': capture_id}).mappings().all()
    traffic = {r['event_code']: dict(r) for r in daa_dreq}
    for ev in ('DAA', 'DREQ', 'DCOMP'):
        if ev not in traffic:
            missing.append({'field': ev.lower(), 'reason': f'no_{ev}_event_in_capture'})

    return {
        'project_id': project_id,
        'capture_id': capture_id,
        'nmf_file': {
            'filename': cap['filename'],
            'size_bytes': cap['size_bytes'],
            'sha256': cap['sha256'],
            'uploaded_at': cap['uploaded_at'].isoformat() if cap['uploaded_at'] else None,
        },
        'decode': {
            'level': cap['decode_level'],
            'decoder_version': cap['decoder_version'],
            'schema_version': cap['schema_version'],
            'format_version': cap['format_version'],
            'decoded_at': cap['decoded_at'].isoformat() if cap['decoded_at'] else None,
            'deep_decoded_at': cap['deep_decoded_at'].isoformat() if cap['deep_decoded_at'] else None,
            'n_records': cap['n_records'],
            'n_partial': cap['n_partial'],
            'elapsed_s': cap['elapsed_s'],
            'kind': cap['kind'],
        },
        'script': script_meta,
        'devi': devi_meta,
        'traffic': traffic,
        # Pas d'identifiant abonné : #EI, #SI, numéros masqués par
        # privacy.redact_tokens (jamais ressortis).
        'identity': {
            'present': False,
            'reason': 'all_subscriber_identifiers_masked_by_privacy_policy',
            'masked_events': ['#EI', '#SI', 'CAA', 'SEI'],
        },
        'missing_fields': missing,
    }


@router.get('/projects/{project_id}/captures/{capture_id}/tasks')
def capture_tasks(project_id: str, capture_id: str, db: Session = Depends(get_db)):
    """Timeline des tâches CMDREQ → CMDCOMP par (capture_id, seq ≤).

    Jamais inventé : si un CMDREQ n'a pas de CMDCOMP, seq_end est null et
    `complete` est false. Hors tâche (entre deux tâches), task_name = null.
    """
    project(db, project_id)
    rows = db.execute(text("""
        SELECT seq, event_code, raw_fields->>'service_action' AS action,
               raw_fields->>'cmd_index' AS cmd_index,
               raw_fields->>'c4' AS c4, ts
        FROM stg_event_raw
        WHERE project_id = :pid AND capture_id = :cap
          AND event_code IN ('CMDREQ', 'CMDCOMP')
        ORDER BY seq
    """), {'pid': project_id, 'cap': capture_id}).mappings().all()
    tasks = []
    open_task = None
    for r in rows:
        if r['event_code'] == 'CMDREQ':
            if open_task is not None:
                # CMDREQ sans CMDCOMP préalable : clôture le précédent comme incomplet.
                tasks.append(open_task)
            open_task = {
                'seq_req': r['seq'], 'seq_comp': None,
                'ts_req': r['ts'] if r['ts'] else None,
                'ts_comp': None,
                'action': r['action'], 'cmd_index': r['cmd_index'],
                'complete': False, 'result': None,
            }
        elif r['event_code'] == 'CMDCOMP' and open_task is not None:
            open_task['seq_comp'] = r['seq']
            open_task['ts_comp'] = r['ts'] if r['ts'] else None
            open_task['result'] = r['c4']  # c4 = cmd result code
            open_task['complete'] = True
            tasks.append(open_task)
            open_task = None
    if open_task is not None:
        tasks.append(open_task)
    return {'project_id': project_id, 'capture_id': capture_id, 'tasks': tasks}
