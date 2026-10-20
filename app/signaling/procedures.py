"""Explicit ordered state machines. No timestamp matching, no subscriber keys.

One active procedure per type and technology within a capture. A repeated
start closes the previous attempt as incomplete (ambiguity is never success).
Durations use the proven capture-local clock only; absent bounds stay NULL.
"""
from hashlib import sha256

RULES = {
    'rrc_setup': (('RRCConnectionRequest', 'RRCSetupRequest'), ('RRCConnectionSetup', 'RRCSetup'), ('RRCConnectionSetupComplete', 'RRCSetupComplete')),
    'rrc_connection': (('RRA',), ('RRC',), ('RRD',)),
    'ho': (('HOA',), ('HOS',)),
    'call': (('CAA',), ('CAC',), ('CAD',)),
    'data_session': (('DAA',), ('DAC',), ('DAD',)),
    'attach': (('GAA',), ('GAC',), ('GAD',)),
    'bearer': (('PBA',), ('PBC',), ('PBD',)),
    'reestablishment': (('RRCConnectionReestablishmentRequest', 'RRCReestablishmentRequest'), ('RRCConnectionReestablishment', 'RRCReestablishment'), ('RRCConnectionReestablishmentComplete', 'RRCReestablishmentComplete')),
}
REJECTS = {'RRCConnectionReject': 'rrc_setup', 'RRCReject': 'rrc_setup', 'RRCConnectionReestablishmentReject': 'reestablishment'}


def reconstruct(project_id, capture_id, rows):
    active = {}
    result = []

    def finish(key, end, outcome, cause):
        attempt = active.pop(key)
        start = attempt['start']
        duration = None
        if end is not None and start['t_rel_s'] is not None and end['t_rel_s'] is not None:
            delta = (end['t_rel_s'] - start['t_rel_s']) * 1000
            if delta >= 0:
                duration = round(delta, 3)
            else:
                outcome, cause = 'incomplete', 'capture_clock_regression'
        if attempt.get('ambiguous') and outcome=='ok':
            outcome,cause,duration='incomplete','ambiguous_overlapping_attempts',None
        result.append(dict(id=sha256(f"{project_id}:{capture_id}:{key}:{start['seq']}".encode()).hexdigest()[:24],
                           project_id=project_id, capture_id=capture_id, type=key[0],
                           technology=key[1], seq_start=start['seq'], seq_end=end['seq'] if end else None,
                           duration_ms=duration, outcome=outcome, cause=cause,
                           boundary_seqs=attempt['seqs']))

    for row in sorted(rows, key=lambda r: r['seq']):
        name = row['message_name']
        technology = row.get('technology')
        if name in REJECTS:
            key = (REJECTS[name], technology)
            if key in active:
                active[key]['seqs'].append(row['seq'])
                finish(key, row, 'fail', name)
            continue
        for kind, stages in RULES.items():
            key = (kind, technology)
            if name in stages[0]:
                ambiguous=key in active
                if key in active:
                    finish(key, None, 'incomplete', 'repeated_start_before_completion')
                active[key] = {'start': row, 'stage': 1, 'seqs': [row['seq']], 'ambiguous': ambiguous}
            elif key in active and name in stages[active[key]['stage']]:
                active[key]['seqs'].append(row['seq'])
                active[key]['stage'] += 1
                if active[key]['stage'] == len(stages):
                    finish(key, row, 'ok', None)
    for key in list(active):
        finish(key, None, 'incomplete', 'missing_terminal_event')
    return sorted(result, key=lambda p: (p['seq_start'], p['type']))
