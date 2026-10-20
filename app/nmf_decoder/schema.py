"""Closed declarative schemas; JSON is used as a strict YAML subset (no executable tags)."""
import json
from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=1)
def schemas():
    return {p.stem:json.loads(p.read_text()) for p in sorted((Path(__file__).parent/'schemas').glob('*.yaml'))}

def column(code):
    return code.replace('.', '_')

@lru_cache(maxsize=1)
def fields():
    result={}
    for s in schemas().values():
        for f in s.get('header', []):
            result.setdefault(column(f['code']),dict(f,event=s['event'],group=None))
        # 1.1.0 — YAMLs sans groupes (événements plats comme les headers #,
        # markers signalisation …) sautent la boucle groups ; les anciens
        # YAMLs 1.0.0 portent groups explicitement.
        for g in s.get('groups', []):
            for f in g['fields']:
                result.setdefault(column(f['code']),dict(f,event=s['event'],group=g['name']))
            for k in ('count_code','params_code'):
                result.setdefault(column(g[k]),dict(code=g[k],label=g[k],type='int',unit='count',agg='last',event=s['event'],group=None,proof=g['proof'],metric=k=='count_code'))
    return result
