import csv, json, os, sys
from pathlib import Path
sys.path.insert(0,'/app')
from app.nmf_decoder.schema import schemas
from app.nmf_decoder.decoder import decode
sources={
 '44621571bccc':'/var/lib/bc4/nmf-source/4b7bfd50ddb6/718d93e0d9414492.nmf',
 'fb5f59006096':'/var/lib/bc4/nmf-source/4b7bfd50ddb6/2bd990224e784d05.nmf',
}
out=Path('/tmp/metrics_offsets.csv')
rows=[]
for event,s in sorted(schemas().items()):
 if event.startswith('#'): continue
 path=next(iter(sources.values())); raw=''; line_no=0
 with open(path,errors='replace') as f:
  for i,line in enumerate(f,1):
   if line.startswith(event+','):
    raw=line.rstrip();line_no=i;break
 if raw:
  r=decode(raw,format_version='2.59',capture_id='witness',seq=1,line_no=line_no)
  decoded=json.dumps(r.values,ensure_ascii=False,sort_keys=True,separators=(',',':'))
 else: decoded=''; r=None
 sc=s.get('system_col'); sc=json.dumps(sc,sort_keys=True) if isinstance(sc,dict) else str(sc)
 first=s.get('first_param_col')
 rows.append({'event':event,'system_col':sc,'first_param_col':first,'source_line_no':line_no,'raw_line':raw,'decoded_values':decoded,'status': 'witness' if raw else 'no_witness'})
with out.open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
print(out)
