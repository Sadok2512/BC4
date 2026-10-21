"""BC3 Signaling guards G18a/b/d/e against TEST2 (134af70a06eb / 723547b196b3).

Run with: docker exec -w /app bc4-api-1 python -m scripts._guard_G18_signaling_live

Reproducible, no fabricated data. Every number comes from a SQL query or
app.signaling.service output. Reads only, no writes."""
import re
from sqlalchemy import text
from app.db import SessionLocal
from app.signaling import service as svc

PID = '134af70a06eb'
CAP = '723547b196b3'
IDENTITY_PATTERNS = re.compile(r'\b(rnti|guti|tmsi|imsi|imei|msisdn)\b', re.I)
NUMBER_FIELD_HINT = re.compile(r'subscriber.?number|phone|msisdn|mobile.?identity', re.I)
IDENTITY_MESSAGES = {
    'RRCConnectionRequest', 'RRCSetupRequest',
    'RRCConnectionSetupComplete', 'RRCSetupComplete',
    'ULInformationTransfer', 'DLInformationTransfer',
    'ULDCCHMessage', 'DLDCCHMessage',
}


def g18a(db):
    """Population list = direct SQL on RRCSM+L3SM+markers ordered by seq."""
    rows, _, _, _ = svc.population(db, PID, CAP, persist=False)
    reference = db.execute(text("""
        SELECT seq FROM stg_event WHERE project_id=:pid AND capture_id=:cap
          AND event_code IN ('RRCSM','L3SM') AND system IN ('LTE','NR')
        UNION ALL
        SELECT r.seq FROM stg_event_raw r JOIN nmf_capture c USING(project_id,capture_id)
         WHERE r.project_id=:pid AND r.capture_id=:cap
           AND r.event_code=ANY(:markers)
           AND (c.decode_level='deep' AND EXISTS(SELECT 1 FROM nmf_event_deep d
                WHERE d.project_id=r.project_id AND d.capture_id=r.capture_id AND d.seq=r.seq)
             OR c.decode_level='light' AND EXISTS(SELECT 1 FROM nmf_event_light d
                WHERE d.project_id=r.project_id AND d.capture_id=r.capture_id AND d.event_code=r.event_code))
    """), dict(pid=PID, cap=CAP, markers=list(svc.MARKERS))).scalars().all()
    pop_seqs = sorted(r['seq'] for r in rows)
    ref_seqs = sorted(reference)
    assert len(pop_seqs) == len(ref_seqs), f"count diff: pop={len(pop_seqs)} ref={len(ref_seqs)}"
    assert pop_seqs == ref_seqs, "seq set diff"
    return f"G18a PASS — population={len(pop_seqs)} seqs = direct SQL union"


def g18b(db):
    """hex=null on identity-bearing messages; no RNTI/TMSI/IMSI in any response."""
    sample = db.execute(text("""
        SELECT seq, message FROM stg_event WHERE project_id=:pid AND capture_id=:cap
          AND event_code='RRCSM' ORDER BY seq LIMIT 1000
    """), dict(pid=PID, cap=CAP)).mappings().all()
    assert sample, "G18b empty sample"
    identity_checked = 0
    identity_masked = 0
    scanned_identity_hits = []
    for row in sample:
        d = svc.details(db, PID, CAP, row['seq'])
        if row['message'] in IDENTITY_MESSAGES:
            identity_checked += 1
            if d['hex'] is None:
                identity_masked += 1
        # Walk the full response for forbidden tokens anywhere.
        blob = repr(d)
        for m in IDENTITY_PATTERNS.finditer(blob):
            # Match on raw tokens only; parameter paths that contain these as
            # substrings are already filtered by DENY+SENSITIVE in service.py.
            scanned_identity_hits.append((row['seq'], row['message'], m.group(0)))
    assert not scanned_identity_hits, f"identity token leaked: {scanned_identity_hits[:3]}"
    if identity_checked:
        assert identity_masked == identity_checked, (
            f"hex not masked on identity messages: masked={identity_masked}/{identity_checked}")
    return f"G18b PASS — scanned={len(sample)} identity_msgs={identity_checked} hex_masked={identity_masked}"


def g18d(db):
    """Tree of RRCConnectionReconfiguration = sanitized param_occurrence count."""
    reco = db.execute(text("""
        SELECT seq FROM stg_event WHERE project_id=:pid AND capture_id=:cap
          AND event_code='RRCSM' AND message IN ('RRCConnectionReconfiguration','RRCReconfiguration')
          ORDER BY seq LIMIT 20
    """), dict(pid=PID, cap=CAP)).scalars().all()
    assert reco, "G18d no RRCReconfiguration in TEST2 capture"
    mismatches = []
    for seq in reco:
        d = svc.details(db, PID, CAP, seq)
        ref = db.execute(text("""
            SELECT count(*) FROM param_occurrence p JOIN stg_event s ON s.id=p.stg_event_id
              WHERE p.project_id=:pid AND s.project_id=:pid AND s.capture_id=:cap AND s.seq=:seq
                AND NOT COALESCE(p.is_identifier,false)
                AND p.path !~* '(rnti|guti|tmsi|imsi|imei|msisdn|phone|subscriber|ue\\.identity|randomValue|dedicated.*nas)'
        """), dict(pid=PID, cap=CAP, seq=seq)).scalar()
        got = len(d['parameters'])
        if got != ref:
            mismatches.append((seq, got, ref))
    assert not mismatches, f"tree != param_occurrence sanitized: {mismatches[:3]}"
    return f"G18d PASS — reco_seqs={len(reco)} tree count == sanitized param_occurrence"


def g18e(db):
    """No fabricated GPS; indoor captures => 0 point and is_indoor=true."""
    rows, _, meta, _ = svc.population(db, PID, CAP, persist=False)
    pts, indoor = svc.gps_points(db, PID, CAP, rows, meta)
    if indoor:
        assert all(p['lat'] is None and p['lng'] is None for p in pts), "indoor but points carry GPS"
        return f"G18e PASS — indoor capture, {len(pts)} rows, all lat/lng=NULL, is_indoor=true"
    # Outdoor: every lat/lng is either None (no preceding GPS) or echoed from a real GPS fix seq.
    real = {r['seq']: (r['lat'], r['lng']) for r in db.execute(text("""
        SELECT seq,lat,lon AS lng FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap
          AND event_code='GPS' AND lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180
          AND NOT(lat=0 AND lon=0)
    """), dict(pid=PID, cap=CAP)).mappings()}
    fake = [p for p in pts if p['lat'] is not None and p['gps_seq'] not in real]
    assert not fake, f"non-null GPS without matching source: {fake[:3]}"
    positioned = sum(p['lat'] is not None for p in pts)
    return (f"G18e PASS — outdoor, rows={len(pts)} positioned={positioned} "
            f"gps_fixes={len(real)} no fabricated point")


def g18b_nas(db):
    """0.72.0 — NAS sanitized decode: scan 1000 L3SM messages, assert no
    identity/crypto token (imsi/imei/msisdn/guti/tmsi/supi/suci/pei/mac/
    rand/autn/res/xres/auts/kasme/kamf/kseaf/kausf/naskey) appears in any
    SAFE parameter value. REDACTED values are expected to carry the marker
    "<redacted>" or "<binary · N bytes · redacted>" — those don't count."""
    from app.signaling.nas_decoder import decode
    import re as _re, json as _json
    rows = db.execute(text("""
        SELECT message, direction, payload_hex FROM stg_event
        WHERE event_code='L3SM' AND payload_hex IS NOT NULL
        LIMIT 1000
    """)).mappings().all()
    assert rows, 'G18b_nas: no NAS messages in DB'
    pat = _re.compile(
        r'imsi|imei|msisdn|guti|tmsi|supi|suci|pei|\bmac\b|\brand\b|'
        r'\bautn\b|\bres\b|xres|auts|kasme|kamf|kseaf|kausf|naskey',
        _re.I)
    leaked = []
    stats = {'FULLY_DECODED': 0, 'PARTIALLY_DECODED': 0,
             'REDACTED': 0, 'UNSUPPORTED': 0}
    for r in rows:
        res = decode(r['payload_hex'], r['direction'], 'LTE')
        stats[res['status']] = stats.get(res['status'], 0) + 1
        for p in res['parameters']:
            if p['safe']:
                v = str(p.get('value', ''))
                if pat.search(v):
                    leaked.append((r['message'], p['path'], v[:80]))
    assert not leaked, f'G18b_nas leaks: {leaked[:3]}'
    return (f"G18b_nas PASS — {len(rows)} NAS scanned, 0 identity leak | "
            f"FULLY={stats['FULLY_DECODED']} PARTIAL={stats['PARTIALLY_DECODED']} "
            f"REDACTED={stats['REDACTED']} UNSUPPORTED={stats['UNSUPPORTED']}")


def run():
    with SessionLocal() as db:
        print(g18a(db))
        print(g18b(db))
        print(g18d(db))
        print(g18e(db))
        print(g18b_nas(db))


if __name__ == '__main__':
    run()
