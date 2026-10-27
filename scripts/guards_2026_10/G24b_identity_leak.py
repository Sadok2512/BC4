"""G24b — Anti-fuite d'identité sur colonnes virtuelles `cap_*`.

Phase 3b (BC3, 2026-10-27). Les leaves du catalog dont `source_column`
commence par `cap_` sont routés via le resolver CAPTURE Phase 2 et NON par
une colonne SQL de `nmf_event_light` (G24 0.88.1 les ignore via le filtre
`physical_cols`). Mais certaines de ces colonnes exposent une **identité**
de l'acquisition (device_name, log_file_name, measurement_id, unit_id,
session_id, subscriber_identity) qui ne doit JAMAIS être `selectable=true`
dans le catalogue :

  - Un consommateur /metrics/table qui coche la case "metric" pourrait
    récupérer en clair le nom du device ou le fichier source, re-rattacher
    une capture à un utilisateur réel.
  - `cap_identity_subscriber_identity` est le cas le plus sensible (IMSI).

Verdict G24b :
  - FAIL si au moins un leaf `cap_*` identité est `selectable=true`.
  - Message explicite listant project_id + nid pour chaque fuite.
  - exit=1 sur FAIL (0.88.x discipline).

La liste des substrings interdits est volontairement conservatrice :
  identity, subscriber, device_name, log_file_name, measurement_id,
  unit_id, session_id, imei, imsi, phone_number.
project_id est accepté (c'est l'identifiant du projet lui-même, déjà
exposé partout) mais tracé en WARN.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

FORBIDDEN = (
    "identity", "subscriber", "device_name", "log_file_name",
    "measurement_id", "unit_id", "session_id", "imei", "imsi",
    "phone_number",
)
WARN_ONLY = ("project_id",)


def main():
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT c.project_id, m->>'node_id' AS nid, m->>'label' AS lbl,
                   m->>'source_column' AS col, (m->>'selectable')::bool AS sel
            FROM metrics_catalog_cache c, jsonb_array_elements(c.payload->'nodes') m
            WHERE m->>'node_type'='leaf'
              AND m->>'source_column' LIKE 'cap\\_%' ESCAPE '\\'
            ORDER BY c.project_id, nid
        """)).mappings().all()
        fails, warns = [], []
        for r in rows:
            col = r["col"] or ""
            if any(sub in col for sub in FORBIDDEN) and r["sel"]:
                fails.append(r)
            elif any(sub in col for sub in WARN_ONLY) and r["sel"]:
                warns.append(r)
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
        print(f"G24b_VERDICT {verdict} identity_leaks={len(fails)} warns={len(warns)}")
        if verdict == "FAIL":
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
