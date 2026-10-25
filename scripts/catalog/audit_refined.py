"""Audit refiné : séparer les events 'simple' (1.5.1 header-only, pas de
groups) des events 'complex' (groups). Pour les simples, les colonnes
2.50 nouvelles sont peu nombreuses. Pour les complex (CELLMEAS, CQI, etc.),
l'ajout de colonnes flat écraserait le schema group — à écarter de la
migration et laisser en 1.5.1."""
import sys, json
sys.path.insert(0, "/app")
from pathlib import Path
from sqlalchemy import text
from app.db import SessionLocal

CORPUS = sorted({line.strip() for line in open("/tmp/corpus_events.txt") if line.strip()})

db = SessionLocal()
cur_cols = {r[0] for r in db.execute(text(
    "SELECT column_name FROM information_schema.columns WHERE table_name='nmf_event_light'"
)).all()}
db.close()
print(f"nmf_event_light existing cols: {len(cur_cols)}")

OLD = Path("/app/app/nmf_decoder/schemas")
NEW = Path("/app/app/nmf_decoder/schemas-2.50")

simple_events = []  # events with 0 groups in 1.5.1 (safe to migrate)
complex_events = []  # events with groups → leave in 1.5.1
missing_cols_simple = []
new_fields_complex = {}

for ev in CORPUS:
    safe = ev.replace("#", "_hash_")
    new_p = NEW / f"{safe}.yaml"
    old_p = OLD / f"{ev}.yaml"
    if not new_p.exists():
        print(f"  SKIP {ev}: no 2.50 YAML")
        continue
    new_d = json.loads(new_p.read_text())
    old_d = json.loads(old_p.read_text()) if old_p.exists() else {}
    has_groups = bool(old_d.get("groups"))
    new_codes = [h["code"].replace(".", "_") for h in new_d.get("header", [])]
    if has_groups:
        complex_events.append(ev)
        # New fields vs old header+group codes
        old_hdr = {h["code"].replace(".", "_") for h in old_d.get("header", [])}
        old_grp = {f["code"].replace(".", "_") for g in old_d.get("groups", []) for f in g.get("fields", [])}
        truly_new = [c for c in new_codes if c not in old_hdr and c not in old_grp and c not in cur_cols]
        if truly_new:
            new_fields_complex[ev] = truly_new
    else:
        simple_events.append(ev)
        for c in new_codes:
            if c not in cur_cols:
                missing_cols_simple.append((c, ev))

print(f"\nSIMPLE events (no groups 1.5.1) : {len(simple_events)}")
print(f"COMPLEX events (groups 1.5.1)  : {len(complex_events)}")
print(f"\nMissing cols for SIMPLE events to migrate : {len(missing_cols_simple)}")
for c, ev in missing_cols_simple[:30]:
    print(f"  + {c:40s} ev={ev}")

print(f"\nCOMPLEX events (keep 1.5.1 header+group split, don't flat-migrate)")
for ev, nf in list(new_fields_complex.items())[:10]:
    print(f"  {ev}: {len(nf)} truly-new fields : {nf[:5]}")
