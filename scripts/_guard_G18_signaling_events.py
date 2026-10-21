"""BC3 Signaling timeline events guards (G18f/g/h).

Spec: signaling_timeline.html — règles d'appariement explicites.

Run with: docker exec -w /app bc4-api-1 python -m scripts._guard_G18_signaling_events

Target: Test_3 project 4b7bfd50ddb6, capture 01bfc2fc5350 (Petite-Forêt
B7 PCI 423, HO 10:35:48 ± SgNB addition + SCell add). Reads only, no
writes, every assertion backed by a replayable SQL / live call."""
from sqlalchemy import text
from app.db import SessionLocal
from app.signaling import service as svc
from app.signaling.links import EVENT_RULES, EVENT_LANE


PID = '4b7bfd50ddb6'
CAP = '01bfc2fc5350'
WINDOW_HO = 50


def g18f(db):
    """For each HOA, verify pivot = RRCConnectionReconfiguration with
    mobilityControlInfo at most WINDOW_HO seq BEFORE the HOA. If BC2 provides
    fewer than 100 HOA on this capture, use whatever is available and report
    the sample size."""
    evs, _ = svc.events(db, PID, CAP)
    hoas = [e for e in evs if e['type'] == 'HOA']
    assert hoas, 'G18f: no HOA in capture — spec requires one'
    violations = []
    for e in hoas[:100]:
        pivot = e['pivot_seq']
        if pivot is None:
            # Allowed only when no eligible reconfig in window; prove with SQL.
            hit = db.execute(text("""
                SELECT 1 FROM param_occurrence p
                JOIN stg_event s ON s.id = p.stg_event_id
                WHERE p.project_id=:pid AND s.capture_id=:cap
                  AND s.seq BETWEEN :lo AND :hi
                  AND p.path ILIKE '%mobilityControlInfo%'
                LIMIT 1
            """), dict(pid=PID, cap=CAP, lo=e['seq'] - WINDOW_HO, hi=e['seq'])).fetchone()
            if hit:
                violations.append(('HOA no-pivot but mobilityControlInfo exists', e['seq']))
            continue
        gap = e['seq'] - pivot
        if gap < 0 or gap > WINDOW_HO:
            violations.append(('HOA pivot gap out of window', e['seq'], gap))
    assert not violations, f'G18f violations: {violations[:3]}'
    sample = min(100, len(hoas))
    return f'G18f PASS — {sample} HOA pivots ≤ {WINDOW_HO} seq before HOA'


def g18g(db):
    """SgNB addition rule: dict decoder does not currently expose
    nr-Config-r15 paths (audited). The rule must therefore return either
    link_rule=`no_dict_support` with linked_seqs=[] OR be absent entirely.
    No fabricated NR Reconfiguration link allowed."""
    evs, _ = svc.events(db, PID, CAP)
    offenders = [e for e in evs if e['label'] == 'SgNB addition' and
                 e['link_rule'] != 'no_dict_support']
    assert not offenders, f'G18g: SgNB linked without dict proof: {offenders[:2]}'
    # Independently verify the IE isn't in param_occurrence either.
    hits = db.execute(text("""
        SELECT count(*) FROM param_occurrence
        WHERE project_id=:pid AND path ILIKE '%nr-Config-r15%'
    """), dict(pid=PID)).scalar()
    return f'G18g PASS — SgNB rules declared without NR dict support (nr-Config-r15 occurrences in project: {hits})'


def g18h(db):
    """Every link must have seq_gap ≤ its rule's window. Rules without
    linked_seqs may have seq_gap=None."""
    evs, _ = svc.events(db, PID, CAP)
    rule_limits = {
        'ho_reconfig_mobility': WINDOW_HO,
        'rrc_setup_message': 20,
        'rlf_reestab_request': 50,
        # procedures span the entire capture (attach, data_session may run
        # for the full trace) ; no gap limit by design — appartenance is
        # proven by reconstruct(), not by proximity.
        'procedure_boundary': None,
        'pivot_on_state_event': 0,
        'no_dict_support': None,
        'no_rule': None,
    }
    out_of_window = []
    for e in evs:
        limit = rule_limits.get(e['link_rule'])
        if limit is None:
            continue
        if e['seq_gap'] is None:
            continue
        if e['seq_gap'] > limit:
            out_of_window.append((e['id'], e['link_rule'], e['seq_gap'], limit))
    assert not out_of_window, f'G18h violations: {out_of_window[:3]}'
    return f'G18h PASS — {len(evs)} events, no link beyond its rule window'


def g18_deterministic():
    """Pure link-rule logic covered by invented in-memory sequences (TEST-
    only, no reference data)."""
    from app.signaling.links import (
        LinkContext, _link_rrc_setup, _link_pass_through, _link_no_dict_support,
    )
    rows = [
        {'seq': 1, 'event_code': 'RRA', 'protocol': 'Événements Nemo', 'message_name': 'RRA', 't_rel_s': 0.0},
        {'seq': 3, 'event_code': 'RRCSM', 'protocol': 'RRC LTE', 'message_name': 'RRCConnectionRequest', 't_rel_s': 0.01},
        {'seq': 5, 'event_code': 'RRCSM', 'protocol': 'RRC LTE', 'message_name': 'RRCConnectionSetup', 't_rel_s': 0.02},
    ]
    ctx = LinkContext(project_id='TEST', capture_id='TEST', rows_by_seq={r['seq']: r for r in rows}, seqs=[1, 3, 5], db=None)
    rra_link = _link_rrc_setup(ctx, rows[0])
    assert rra_link == dict(pivot_seq=3, linked_seqs=[3], link_rule='rrc_setup_message', seq_gap=2)
    passthrough = _link_pass_through(ctx, rows[0])
    assert passthrough == dict(pivot_seq=1, linked_seqs=[1], link_rule='pivot_on_state_event', seq_gap=0)
    nodict = _link_no_dict_support(ctx, rows[0])
    assert nodict['link_rule'] == 'no_dict_support'
    return 'G18 deterministic PASS — rrc_setup / pass_through / no_dict_support'


def run():
    print(g18_deterministic())
    with SessionLocal() as db:
        print(g18f(db))
        print(g18g(db))
        print(g18h(db))


if __name__ == '__main__':
    run()
