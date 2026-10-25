"""G28 — plages de valeurs sur TOUT le corpus 1.6.0.

Pour chaque colonne métrique de nmf_event_light où COUNT > 0 : min / P1 /
P50 / P99 / max. Verdict : hors range physique = FAIL explicite.

Ranges BC3 :
  RSRP -140..-44  | RSRQ -30..0   | SINR/SNR -20..40 | BLER 0..100
  CQI 0..15       | MCS 0..31     | TA 0..1282       | TX_PWR -41..33
  débits ≥ 0      | PDSCH ≤ théorique (soft warning)
"""
import re, sys
sys.path.insert(0, "/app")
from sqlalchemy import text, inspect
from app.db import SessionLocal

META = {"project_id","capture_id","seq","seq_last","event_code","system","second",
        "dimension","t_rel_s","decoder_version","schema_version","format_version",
        "decode_status","reasons","unknown","n_records","n_partial","context_id","context_ids"}
# Matches EXACTS sur les métriques physiques BC3 (plus de "regex large").
EXACT_RANGES = {
    # RSRP/RSRQ/SNR sur CELLMEAS, CI, SCELL
    "cell_rsrp": (-140, -44), "cellmeas_rsrp": (-140, -44), "ci_rsrp": (-140, -44),
    "cell_rsrq": (-30, 0),    "cellmeas_rsrq": (-30, 0),    "ci_rsrq": (-30, 0),
    "cell_rssi": (-130, -20), "cellmeas_rssi": (-130, -20),
    "ci_snr": (-20, 40), "ci_rs_snr": (-20, 40), "ci_snr_port": (-20, 40),
    # CQI 0..15 (nominal CQI, PAS les débits/pct/durée)
    "cqi_wb_cqi_0": (0, 15), "cqi_wb_cqi_1": (0, 15),
    "cqi_sb_cqi_0": (0, 15), "cqi_sb_cqi_1": (0, 15),
    # MCS 0..31
    "plaid_mcs": (0, 31), "plaiu_mcs": (0, 31),
    # BLER 0..100
    "plaid_bler": (0, 100), "plaiu_bler": (0, 100),
    "macrate_mac_dl_bler": (0, 100), "macrateu_mac_ul_bler": (0, 100),
    # TA : LTE 0..1282, NR 0..3846 (NFF 2.50 §TAD NR). Max union = 3846.
    "tad_ta": (0, 3846),
    # TX power -41..33 (strict, NOT txpc_f_i/g_i/power_headroom/tpc_count)
    "txpc_pusch_tx_power": (-41, 33), "txpc_pucch_tx_power": (-41, 33),
    "txpc_tx_power": (-41, 33),
}
# Soft lower-bound check : débits ≥ 0
SOFT_NONNEG = ("mac_dl_bitrate", "mac_ul_bitrate", "pdcp_dl_bitrate",
               "pdcp_ul_bitrate", "rlc_dl_bitrate", "rlc_ul_bitrate",
               "ppprate", "drate", "app_dl_bitrate", "app_ul_bitrate")
def match_range(col):
    if col in EXACT_RANGES: return EXACT_RANGES[col]
    for pat in SOFT_NONNEG:
        if pat in col: return (0, None)
    return None

def main():
    db = SessionLocal()
    insp = inspect(db.get_bind())
    numeric = [c["name"] for c in insp.get_columns("nmf_event_light")
               if c["name"] not in META and
                  str(c["type"]).lower().startswith(("double","int","numeric","float","real"))]
    try:
        fails = []
        headers = f'{"metric":<35} {"n":>10} {"min":>10} {"P1":>10} {"P50":>10} {"P99":>10} {"max":>10}  verdict'
        print(headers)
        for col in numeric:
            q = db.execute(text(f"""
                SELECT COUNT("{col}"), MIN("{col}"), MAX("{col}"),
                  percentile_cont(0.01) WITHIN GROUP (ORDER BY "{col}") AS p1,
                  percentile_cont(0.50) WITHIN GROUP (ORDER BY "{col}") AS p50,
                  percentile_cont(0.99) WITHIN GROUP (ORDER BY "{col}") AS p99
                FROM nmf_event_light WHERE "{col}" IS NOT NULL
            """)).first()
            n = int(q[0] or 0)
            if n == 0: continue
            mn, mx, p1, p50, p99 = (float(q[1]), float(q[2]), float(q[3]), float(q[4]), float(q[5]))
            rng = match_range(col)
            verdict = "ok"
            if rng:
                lo, hi = rng
                if mn < lo or (hi is not None and mx > hi):
                    verdict = f"OUT[{lo},{hi}]"
                    fails.append((col, mn, mx, lo, hi))
            print(f"{col:<35} {n:>10} {mn:>10.3f} {p1:>10.3f} {p50:>10.3f} {p99:>10.3f} {mx:>10.3f}  {verdict}")
        from app.nmf_decoder import DECODER_VERSION
        print(f"\nG28_VERDICT {'PASS' if not fails else 'FAIL'} corpus={DECODER_VERSION} metrics_with_data={len([c for c in numeric])} out_of_range={len(fails)}")
        for col, mn, mx, lo, hi in fails:
            print(f"  OUT {col}: min={mn} max={mx} range=[{lo},{hi}]")
    finally:
        db.close()

if __name__ == "__main__":
    main()
