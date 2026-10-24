"""G28 — plages de valeurs pour TOUTES les métriques (n > 0) sur 3 témoins.

Pour chaque métrique Light `code` avec n > 0 sur une capture témoin :
  min / P1 / P50 / P99 / max  (via percentile_cont)
+ verdict vs plages NFF 2.19 / physiques :
    rsrp -140..-44  | rsrq -30..0  | sinr -20..40 | bler 0..100
    cqi  0..15      | mcs  0..31   | ta   0..1282 | tx_pwr -41..33
    débits ≥ 0 (débit upper bound = non testé, warning soft)

Témoins : 44621571bccc, fb5f59006096, 723547b196b3.
"""
import re, sys
sys.path.insert(0, "/app")
from sqlalchemy import text, inspect
from app.db import SessionLocal

CAPTURES = ["44621571bccc", "fb5f59006096", "723547b196b3"]
META = {"project_id","capture_id","seq","seq_last","event_code","system","second",
        "dimension","t_rel_s","decoder_version","schema_version","format_version",
        "decode_status","reasons","unknown","n_records","n_partial"}

# Plages physiques / NFF 2.19 par motif de nom de colonne.
RANGES = [
    (re.compile(r"(^|_)rsrp($|_)"), -140, -44),
    (re.compile(r"(^|_)rsrq($|_)"), -30, 0),
    (re.compile(r"(^|_)(sinr|snr)($|_)"), -20, 40),
    (re.compile(r"(^|_)bler($|_)"), 0, 100),
    (re.compile(r"(^|_)cqi($|_)"), 0, 15),
    (re.compile(r"(^|_)mcs($|_)"), 0, 31),
    (re.compile(r"(^|_)ta($|_)"), 0, 1282),
    (re.compile(r"tx_power|tx_pwr|txpc"), -41, 33),
    (re.compile(r"bitrate|throughput|thrpt|dl_bytes|ul_bytes"), 0, None),  # ≥ 0
]

def match_range(colname):
    for rx, lo, hi in RANGES:
        if rx.search(colname): return (lo, hi)
    return None

def main():
    db = SessionLocal()
    insp = inspect(db.get_bind())
    numeric_cols = [c["name"] for c in insp.get_columns("nmf_event_light")
                    if c["name"] not in META and str(c["type"]).lower().startswith(("double","int","numeric","float","real"))]
    try:
        for cap in CAPTURES:
            print(f"\n=== G28 capture={cap} ===")
            pid = db.execute(text("SELECT project_id FROM nmf_capture WHERE capture_id=:cap LIMIT 1"),
                             {"cap": cap}).scalar_one_or_none()
            if not pid: print("NO_CAPTURE"); continue
            print(f"{'metric':<35} {'n':>7} {'min':>10} {'P1':>10} {'P50':>10} {'P99':>10} {'max':>10} verdict")
            fails = 0
            for col in numeric_cols:
                q = db.execute(text(f"""
                    SELECT COUNT("{col}"), MIN("{col}"), MAX("{col}"),
                      percentile_cont(0.01) WITHIN GROUP (ORDER BY "{col}") p1,
                      percentile_cont(0.50) WITHIN GROUP (ORDER BY "{col}") p50,
                      percentile_cont(0.99) WITHIN GROUP (ORDER BY "{col}") p99
                    FROM nmf_event_light WHERE project_id=:pid AND capture_id=:cap AND "{col}" IS NOT NULL
                """), {"pid": pid, "cap": cap}).first()
                n = int(q[0] or 0)
                if n == 0: continue
                mn, mx, p1, p50, p99 = (float(q[1]), float(q[2]), float(q[3]), float(q[4]), float(q[5]))
                rng = match_range(col)
                verdict = "ok"
                if rng:
                    lo, hi = rng
                    if mn < lo or (hi is not None and mx > hi):
                        verdict = f"OUT[{lo},{hi}]"
                        fails += 1
                print(f"{col:<35} {n:>7} {mn:>10.3f} {p1:>10.3f} {p50:>10.3f} {p99:>10.3f} {mx:>10.3f} {verdict}")
            print(f"G28 cap={cap} metrics_with_data={sum(1 for _ in numeric_cols if True)} fails={fails}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
