"""G24b — Anti-fuite d'identité sur colonnes virtuelles `cap_*`.

Phase 3b (BC3, 2026-10-27). Les leaves du catalog dont `source_column`
commence par `cap_` sont routés via le resolver CAPTURE Phase 2 et NON par
une colonne SQL de `nmf_event_light` (G24 0.88.1 les ignore via le filtre
`physical_cols`). Les colonnes du groupe catalogue `MASKED` (identité
abonné, IMSI, IMEI, téléphone) ne doivent JAMAIS être `selectable=true` :

  - Un consommateur /metrics/table qui coche la case "metric" pourrait
    récupérer en clair le nom du device ou le fichier source, re-rattacher
    une capture à un utilisateur réel.
  - `cap_identity_subscriber_identity` est le cas le plus sensible (IMSI).

Verdict G24b :
  - FAIL si au moins un leaf `cap_*` identité est `selectable=true`.
  - Message explicite listant project_id + nid pour chaque fuite.
  - exit=1 sur FAIL (0.88.x discipline).

Les métadonnées explicitement exposées par le groupe CAPTURE `FILE`
(device_name, log_file_name, measurement_id, unit_id, session_id,
project_id) sont tracées en WARN ; elles ne relèvent pas du groupe `MASKED`.
"""
import argparse, sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from guard_runtime import session_local_or_fail
from scope_args import add_scope_args, resolve_scope

SessionLocal = session_local_or_fail("G24b")

FORBIDDEN = ("identity", "subscriber", "imei", "imsi", "phone_number")
WARN_ONLY = (
    "project_id", "device_name", "log_file_name", "measurement_id",
    "unit_id", "session_id",
)


def main():
    ap = argparse.ArgumentParser()
    add_scope_args(ap)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        try:
            project_id, capture_ids = resolve_scope(db, args)
        except ValueError as exc:
            print(f"G24b VERDICT=FAIL reason=scope_error detail={exc}")
            sys.exit(1)
        print(f"G24b scope: project_id={project_id} captures={capture_ids}")
        rows = db.execute(text("""
            SELECT c.project_id, m->>'node_id' AS nid, m->>'label' AS lbl,
                   m->>'source_column' AS col, (m->>'selectable')::bool AS sel
            FROM metrics_catalog_cache c, jsonb_array_elements(c.payload->'nodes') m
            WHERE m->>'node_type'='leaf'
              AND m->>'source_column' LIKE 'cap\\_%' ESCAPE '\\'
              AND c.project_id=:pid
            ORDER BY c.project_id, nid
        """), {"pid": project_id}).mappings().all()
        fails, warns = [], []
        for r in rows:
            col = r["col"] or ""
            if any(sub in col for sub in FORBIDDEN) and r["sel"]:
                fails.append(r)
            elif any(sub in col for sub in WARN_ONLY) and r["sel"]:
                warns.append(r)
        # 0.89.5 — garde sans témoin = FAIL (jamais PASS silencieux).
        if len(rows) == 0:
            print(f"G24b VERDICT=FAIL reason=no_witness examined=0 "
                  f"(metrics_catalog_cache vide ou aucun leaf cap_* — upload un projet d'abord)")
            sys.exit(1)
        print(f"G24b scan : {len(rows)} leaves cap_* examinés")
        if warns:
            print(f"  WARN ({len(warns)}) — identifiants non critiques exposés :")
            for r in warns[:5]:
                print(f"    {r['project_id']} {r['nid']}  col={r['col']}")
        if fails:
            print(f"  FAIL ({len(fails)}) — identité LEAKS :")
            for r in fails:
                print(f"    {r['project_id']} {r['nid']}  col={r['col']}  label={r['lbl']}")
        verdict = "PASS" if not fails else "FAIL"
        print(f"G24b VERDICT={verdict} identity_leaks={len(fails)} warns={len(warns)}")
        if verdict == "FAIL":
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
