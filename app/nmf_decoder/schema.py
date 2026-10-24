"""Closed declarative schemas; JSON is used as a strict YAML subset (no executable tags)."""
import json
from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=1)
def schemas():
    """2.2a REVERTED : charge uniquement `schemas/` (1.5.1) pour éviter
    les colonnes `nmf_event_light` manquantes (le refactor 2.50 requiert
    DDL alembic préalable pour les 193 events ADDED). Les YAMLs 2.50
    restent dans `schemas-2.50/` pour la régénération et la génération
    du catalogue, mais le decoder reste 1.5.1 tant que la migration DDL
    n'est pas appliquée. Prochaine session 2.2a bis.
    """
    base = Path(__file__).parent
    result: dict = {}
    for p in sorted((base / 'schemas').glob('*.yaml')):
        result[p.stem] = json.loads(p.read_text())
    # The NFF prefix is event,time,context-count,context-ids.  Expose the
    # schema-declared beginning of the event parameters to consumers so no
    # catalogue or audit has to assume a universal column 5.  Existing
    # absolute ``col`` values remain untouched for backwards compatibility.
    for schema in result.values():
        system_col = schema.get('system_col')
        if isinstance(system_col, int):
            schema.setdefault('first_param_col', system_col + 1)
        elif isinstance(schema.get('context_count'), int):
            schema.setdefault('first_param_col', 4 + schema['context_count'])
        else:
            schema.setdefault('first_param_col', 4)
    return result

def offsets(event: str) -> dict:
    """Return the authoritative positional metadata for an event schema."""
    schema = schemas().get(event, {})
    system_col = schema.get('system_col')
    if isinstance(system_col, dict):
        system_col = None
    return {
        'system_col': system_col,
        'first_param_col': schema.get('first_param_col'),
    }

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
                if k not in g:continue
                result.setdefault(column(g[k]),dict(code=g[k],label=g[k],type='int',unit='count',agg='last',event=s['event'],group=None,proof=g['proof'],metric=k=='count_code'))
    return result
