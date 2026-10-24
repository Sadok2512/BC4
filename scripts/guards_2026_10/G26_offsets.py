"""G26 — offsets YAML : system_col / first_param_col alignés sur raw_fields.

Pour chaque schema YAML dans app/nmf_decoder/schemas/*.yaml :
  (1) lit system_col et first_param_col (= min des header[].col) ;
  (2) prend UNE ligne stg_event_raw de l'event_code ;
  (3) extrait raw_fields.c<system_col> et raw_fields.c<first_param_col> ;
  (4) verdict offset :
        0  si system_col pointe vers une valeur numérique system ∈ (1..20)
        +1 / -1 sinon (décalage attendu dans le decoder vs YAML).
"""
import json, sys, os, glob
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

SCHEMA_DIR = "/app/app/nmf_decoder/schemas"

def main():
    db = SessionLocal()
    try:
        files = sorted(glob.glob(os.path.join(SCHEMA_DIR, "*.yaml")))
        print(f"G26 schemas={len(files)}")
        verdicts = {"0": 0, "+1": 0, "-1": 0, "?": 0, "no_data": 0}
        for f in files:
            try:
                sch = json.load(open(f))  # ces YAML sont du JSON strict (vérifié CELLMEAS)
            except Exception:
                print(f"  SKIP {os.path.basename(f)} : not JSON-parseable")
                continue
            code = sch.get("event")
            sys_col = sch.get("system_col")
            hdr = sch.get("header", [])
            first_param_col = min((h.get("col") for h in hdr if h.get("col")), default=None)
            if not code or sys_col is None or first_param_col is None:
                verdicts["?"] += 1; continue
            row = db.execute(text(
                "SELECT raw_fields FROM stg_event_raw WHERE event_code=:ec LIMIT 1"
            ), {"ec": code}).scalar_one_or_none()
            if row is None:
                verdicts["no_data"] += 1
                print(f"  {code:<12} sys_col={sys_col} first_param={first_param_col} NO_RAW_DATA")
                continue
            raw = row if isinstance(row, dict) else json.loads(row)
            v_sys = raw.get(f"c{sys_col}")
            v_first = raw.get(f"c{first_param_col}")
            # Verdict : v_sys doit être numérique entier ≤ 20 pour matcher
            # un code système (1..20 selon NFF 2.19).
            try:
                vsi = int(str(v_sys)) if v_sys is not None else None
                if vsi is not None and 0 <= vsi <= 20:
                    v = "0"
                elif raw.get(f"c{sys_col+1}") and str(raw.get(f"c{sys_col+1}")).isdigit():
                    v = "-1"
                elif raw.get(f"c{sys_col-1}") and str(raw.get(f"c{sys_col-1}")).isdigit():
                    v = "+1"
                else: v = "?"
            except Exception: v = "?"
            verdicts[v] += 1
            if v != "0":
                print(f"  {code:<12} sys_col={sys_col} first_param={first_param_col} "
                      f"raw.c{sys_col}={v_sys!r} raw.c{first_param_col}={str(v_first)[:30]!r} verdict={v}")
        print(f"G26_VERDICT verdicts={verdicts}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
