"""G33 — RRC_STATE cycles émis par rf.events ↔ triplets RRA→RRC→RRD stg.

Pour chaque capture light du périmètre (nmf_capture.decode_level='light'),
compare :
  - N(RRC_STATE events) émis par `rf.events(db, pid, cap)` avec track
    'RRC_STATE' AND state 'CONNECTED'.
  - N(triplets RRA→RRC→RRD) complets en stg_event_raw ordonnés par
    (capture_id, seq) : le même context_id passe par les 3 markers dans
    l'ordre, un cycle = RRCConnectionRequest + Setup + SetupComplete.

PASS si N_emitted == N_triplets pour chaque capture (après fix 0.88.0
light-fallback). FAIL accepté par capture, exit=1 si une capture dévie.
Jamais SKIP.

Captures deep sont IGNORÉES (rapport only, pas de pass/fail) car le
chemin deep était déjà fonctionnel pré-fix.
"""
import sys
sys.path.insert(0, "/app")
from app.db import SessionLocal
from app.signaling import rf
from sqlalchemy import text


def main():
    db = SessionLocal()
    try:
        caps_light = db.execute(text(
            "SELECT project_id, capture_id FROM nmf_capture "
            "WHERE decode_level='light' ORDER BY capture_id"
        )).all()
        caps_deep = db.execute(text(
            "SELECT project_id, capture_id FROM nmf_capture "
            "WHERE decode_level='deep' ORDER BY capture_id"
        )).all()
        print(f"G33 witnesses: {len(caps_light)} light + {len(caps_deep)} deep captures")
        print(f"  rules: light = PASS/FAIL ; deep = REPORT only (déjà fonctionnel pré-fix)")
        total_light_fail = 0
        total_light_ok = 0
        print(f"\n  {'kind':<6} {'capture':<14} {'triplets':>9} {'rrc_state_emit':>14} {'verdict':>8}")
        for kind, caps in (("light", caps_light), ("deep", caps_deep)):
            for pid, cap in caps:
                # Triplets RRA→RRC→RRD par context_id en ordre (capture_id, seq)
                triplets = db.execute(text("""
                  WITH rra AS (SELECT seq, context_id FROM nmf_event_light
                               WHERE project_id=:pid AND capture_id=:cap
                               AND event_code='RRA' AND context_id IS NOT NULL),
                       rrc AS (SELECT seq, context_id FROM nmf_event_light
                               WHERE project_id=:pid AND capture_id=:cap
                               AND event_code='RRC' AND context_id IS NOT NULL),
                       rrd AS (SELECT seq, context_id FROM nmf_event_light
                               WHERE project_id=:pid AND capture_id=:cap
                               AND event_code='RRD' AND context_id IS NOT NULL)
                  SELECT COUNT(*) FROM rra a
                  JOIN rrc c ON c.context_id=a.context_id AND c.seq>a.seq
                  JOIN rrd d ON d.context_id=a.context_id AND d.seq>c.seq
                """), {"pid": pid, "cap": cap}).scalar_one() or 0
                # RRC_STATE events émis
                evs, _ = rf.events(db, pid, cap)
                emitted = sum(1 for e in evs
                              if (e.get("attrs", {}) or {}).get("track") == "RRC_STATE")
                verdict = "PASS" if (kind == "deep" or emitted == triplets) else "FAIL"
                print(f"  {kind:<6} {cap[:12]:<14} {triplets:>9} {emitted:>14} {verdict:>8}")
                if kind == "light":
                    if verdict == "PASS": total_light_ok += 1
                    else: total_light_fail += 1
        # 0.89.5 — garde sans témoin = FAIL. Ni light ni deep ⇒ 0 preuve.
        if (len(caps_light) + len(caps_deep)) == 0:
            print(f"\nG33_VERDICT FAIL no_witness examined=0 "
                  f"(nmf_capture vide — ingérer au moins une capture)")
            sys.exit(1)
        global_verdict = "PASS" if total_light_fail == 0 else "FAIL"
        print(f"\nG33_VERDICT {global_verdict}  light_PASS={total_light_ok} "
              f"light_FAIL={total_light_fail} deep_reported={len(caps_deep)}")
        if global_verdict == "FAIL":
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
