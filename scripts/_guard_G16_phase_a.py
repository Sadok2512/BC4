"""Manual read-only source audit. Run with PYTHONPATH pointing at the candidate.

python scripts/_guard_G16_phase_a.py --project 134af70a06eb --out /tmp/phase-a.json
No identity values are printed or persisted by this audit.
"""
import argparse
import json
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from sqlalchemy import text
from app.db import SessionLocal
from app.nmf_decoder.source import records
from app.nmf_decoder.light import Light
from app.nmf_decoder.cells import cell_rows
from app.nmf_decoder.pairs import Pairs
from app.nmf_decoder.privacy import private_indices

p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--out',required=True)
p.add_argument('--capture');args=p.parse_args()
SQL='''SELECT DISTINCT r.capture_id,n.source_path,n.sha256 FROM stg_event_raw r
 JOIN nmf_file n ON n.id=r.nmf_file_id WHERE r.project_id=:pid
 AND (CAST(:cap AS text) IS NULL OR r.capture_id=:cap) ORDER BY r.capture_id'''
report=dict(at=datetime.now(timezone.utc).isoformat(),project=args.project,sql=SQL,captures=[])
with SessionLocal() as db:
    files=db.execute(text(SQL),{'pid':args.project,'cap':args.capture}).mappings().all()
for f in files:
    light=Light();pairs=Pairs();counts=Counter();unknown=Counter();private_failures=0
    for r in records(f['source_path'],f['capture_id'],f['sha256']):
        if r.excluded:continue
        light.add(r);pairs.add(r);counts[r.event_code]+=1
        for code in r.field_codes:
            if code.startswith('unk_'):unknown[code]+=1
        for i in private_indices(r.event_code,len(r.context_ids),len(r.tokens)):
            if r.tokens[i]:private_failures+=1
    rows=list(cell_rows(light));rates=defaultdict(dict)
    for row in rows:
        if row['event_code']=='PHRATE' and row['metric_code']=='pdsch_bitrate':
            rates[row['second']][row['cell_index']]=row['value']
    bad=sum(abs(values[-1]-sum(v for cell,v in values.items() if cell>=0))>1e-7 for values in rates.values())
    ho=[r for r in pairs.rows() if r['type']=='ho'];completed=[r for r in ho if r['seq_end'] is not None]
    with_hoi=sum(r['ho_duration_hoi_ms'] is not None and r['ho_duration_nemo_ms'] is not None for r in completed)
    report['captures'].append(dict(capture_id=f['capture_id'],events=counts,unknown=unknown,
        cell_rows=len(rows),phy_seconds=len(rates),G16h_bad=bad,privacy_position_failures=private_failures,
        ho_total=len(ho),ho_completed=len(completed),ho_both_durations=with_hoi,ho_pairs=ho))
    Path(args.out).write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(f['capture_id'],'source audit complete',flush=True)
