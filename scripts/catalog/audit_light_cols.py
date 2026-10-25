"""Audit : pour chaque event du corpus (113), liste les colonnes présentes
dans nmf_event_light vs les codes requis par schemas-2.50/*.yaml.
Sortie : liste exacte de colonnes à AJOUTER."""
import sys, json, re
sys.path.insert(0, "/app")
from pathlib import Path
from sqlalchemy import text
from app.db import SessionLocal, engine

CORPUS = sorted({line.strip() for line in open("/tmp/corpus_events.txt") if line.strip()})
print(f"corpus events: {len(CORPUS)}", flush=True)

# Columns actuelles dans nmf_event_light + nmf_event_group (couverture
# complète : les group fields 1.5.1 ne sont pas sur light mais sur group).
db = SessionLocal()
cur_cols = {r[0] for r in db.execute(text(
    "SELECT column_name FROM information_schema.columns WHERE table_name IN ('nmf_event_light','nmf_event_group','nmf_event_deep')"
)).all()}
db.close()
print(f"nmf_event_light+group+deep columns union: {len(cur_cols)}", flush=True)

# Codes requis par schemas-2.50 pour les 113 events corpus
required = {}
schemas_dir = Path("/app/app/nmf_decoder/schemas-2.50")
for ev in CORPUS:
    safe = ev.replace("#", "_hash_")
    p = schemas_dir / f"{safe}.yaml"
    if not p.exists():
        print(f"  NO_YAML_2.50 for {ev}", flush=True)
        continue
    d = json.loads(p.read_text())
    for h in d.get("header", []):
        col_name = h["code"].replace(".", "_")
        required.setdefault(col_name, {"event": ev, "label": h.get("label"), "type": h.get("type")})

missing = {k: v for k, v in required.items() if k not in cur_cols}
present = {k: v for k, v in required.items() if k in cur_cols}
print(f"required_fields_2.50 total: {len(required)}", flush=True)
print(f"  present: {len(present)}", flush=True)
print(f"  MISSING (to add): {len(missing)}", flush=True)
# Save missing list for alembic migration
out = []
for col, info in sorted(missing.items()):
    # Map type to PostgreSQL
    pg_type = {
        "int": "DOUBLE PRECISION",  # NFF ints often negative/large → use double
        "float": "DOUBLE PRECISION",
        "text": "TEXT",
        "bool": "BOOLEAN",
        "hex": "TEXT",
    }.get(info.get("type") or "text", "DOUBLE PRECISION")
    out.append((col, pg_type, info["event"], info.get("label")))
Path("/tmp/missing_cols.json").write_text(json.dumps(out, indent=2))
print(f"written /tmp/missing_cols.json", flush=True)
for c, t, e, l in out[:20]:
    print(f"  + {c:40s} {t:20s} ev={e} label={l!r}")
