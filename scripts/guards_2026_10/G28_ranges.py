"""G28 — plages de valeurs physiques dans measurement_points.

RSRP ∈ [-156, -31] dBm (3GPP TS 36.133)
RSRQ ∈ [-34, 2.5] dB
SINR ∈ [-23, 40] dB
CQI  ∈ [0, 15]
Lat  ∈ [-90, 90] ; Lng ∈ [-180, 180] (exclut lat=0 ∧ lng=0 = sentinelle).

PASS si 0 ligne hors range (hors NULL). FAIL si une seule.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

RANGES = {
    "rsrp": (-156, -31),
    "rsrq": (-34, 2.5),
    "sinr": (-23, 40),
    "cqi":  (0, 15),
    "lat":  (-90, 90),
    "lng":  (-180, 180),
}

def main():
    db = SessionLocal()
    violations = []
    try:
        for col, (lo, hi) in RANGES.items():
            where = f"{col} IS NOT NULL AND ({col} < {lo} OR {col} > {hi})"
            if col in ("lat", "lng"):
                where += f" AND NOT (lat=0 AND lng=0)"
            n = db.execute(text(
                f"SELECT COUNT(*) FROM measurement_points WHERE {where}"
            )).scalar_one()
            print(f"G28 {col} range=[{lo}, {hi}] out_of_range={n}")
            if n > 0:
                violations.append((col, n))
        verdict = "PASS" if not violations else "FAIL"
        print(f"G28_VERDICT {verdict} violations={violations}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
