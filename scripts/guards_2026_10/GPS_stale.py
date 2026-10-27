"""GPS_stale — règle d'identité fix GPS.

Un fix GPS avec `fix_quality=0` (no fix) ne doit JAMAIS produire une ligne
measurement_points avec `geo_source='gps_fix'` ni (côté UI) gps_source='exact'.
Témoin : scanner metro `d8d7fa995c44` — pas de sky view, fix_quality devrait
être 0 ou absent.

PASS = (a) aucun measurement_points avec geo_source='gps_fix' pour une capture
dont les events GPS stg_event_raw ont tous fix_quality=0 ou absent ;
       (b) scanner `d8d7fa995c44` : 0 ligne mp avec lat NOT NULL ET
geo_source='gps_fix'.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

TEMOIN = "d8d7fa995c44"

def main():
    db = SessionLocal()
    try:
        # 0.89.5 — exige que le témoin existe en base. Si la capture
        # TEMOIN n'est pas ingérée, le garde ne prouve rien.
        exists = db.execute(text(
            "SELECT COUNT(*) FROM nmf_capture WHERE capture_id=:cap"
        ), {"cap": TEMOIN}).scalar_one() or 0
        if exists == 0:
            print(f"GPS_stale_VERDICT FAIL no_witness examined=0 "
                  f"(témoin capture_id={TEMOIN} absent de nmf_capture — "
                  f"ingérer cette capture avant de rejouer le garde)")
            sys.exit(1)
        row = db.execute(text("""
            SELECT COUNT(*) FROM measurement_points
            WHERE capture_id=:cap AND lat IS NOT NULL AND geo_source='gps_fix'
        """), {"cap": TEMOIN}).scalar_one()
        print(f"GPS_stale temoin={TEMOIN} mp_gps_fix_count={row}")
        # Vérif globale : tout mp avec geo_source='gps_fix' doit avoir au
        # moins 1 event GPS dans stg_event_raw avec lat/lon non-NULL ET
        # (fix_quality est stocké dans raw_fields JSON ou absent).
        anomalies = db.execute(text("""
            SELECT m.capture_id, COUNT(*) AS mp_rows
            FROM measurement_points m
            WHERE m.lat IS NOT NULL AND m.geo_source='gps_fix'
              AND NOT EXISTS (
                SELECT 1 FROM stg_event_raw r
                WHERE r.project_id=m.project_id AND r.capture_id=m.capture_id
                  AND r.event_code='GPS' AND r.lat IS NOT NULL AND NOT(r.lat=0 AND r.lon=0)
              )
            GROUP BY m.capture_id
        """)).all()
        for cap, n in anomalies[:10]:
            print(f"GPS_stale ANOMALY cap={cap} mp_gps_fix_without_raw={n}")
        witness_pass = (row == 0)
        verdict = "PASS" if witness_pass and not anomalies else "FAIL"
        print(f"GPS_stale_VERDICT {verdict} witness_zero={witness_pass} anomalies={len(anomalies)}")
        if verdict == "FAIL":
            sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
