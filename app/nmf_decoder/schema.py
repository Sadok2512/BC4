"""Closed declarative schemas; JSON is used as a strict YAML subset (no executable tags)."""
import json
from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=1)
def schemas():
    """Phase 2.2a — charge schemas-2.50/ UNIQUEMENT pour les 113 events
    du corpus (scope BC3). Les autres events restent sur schemas/ 1.5.1 ;
    s'ils ne sont pas dans 1.5.1 non plus → absents (decoder tag `unk_`).

    Pour les 12 events COMPLEX du corpus (header+group 1.5.1), on garde
    la 1.5.1 pour préserver nmf_event_light_group.

    1.7.0 — Les YAMLs à suffixe `_NR` sont posés en variants `_variants[9]`
    sous la clé event au lieu de polluer le dict principal, pour que
    schema_for(event, system) retourne le schema NR quand system==9.
    """
    base = Path(__file__).parent
    # Scope 113 corpus events — fichier source généré par
    #   SELECT DISTINCT event_code FROM nmf_event_light ORDER BY event_code
    corpus_file = base / 'corpus_events_2_2a.txt'
    corpus = set()
    if corpus_file.exists():
        corpus = {line.strip() for line in corpus_file.read_text().splitlines() if line.strip()}
    result: dict = {}
    nr_variants: dict = {}
    # Fallback 1.5.1 d'abord — TOUS les events
    for p in sorted((base / 'schemas').glob('*.yaml')):
        doc = json.loads(p.read_text())
        ev = doc.get('event') or p.stem.replace('_hash_', '#')
        if p.stem.endswith('_NR'):
            nr_variants[ev] = doc
        else:
            result[p.stem] = doc
    # 2.50 override UNIQUEMENT pour les corpus events, et seulement s'ils
    # ne sont pas COMPLEX (header+group 1.5.1).
    for p in sorted((base / 'schemas-2.50').glob('*.yaml')):
        try:
            doc = json.loads(p.read_text())
        except Exception:
            continue
        ev = doc.get('event') or p.stem.replace('_hash_', '#')
        if ev not in corpus:
            continue  # scope BC3 : hors corpus = pas d'override 2.50
        if ev in result and result[ev].get('groups'):
            continue  # keep 1.5.1 header+group structure (COMPLEX)
        result[ev] = doc
    for ev, nr in nr_variants.items():
        if ev in result:
            result[ev].setdefault('_variants', {})[9] = nr
        else:
            result[ev] = nr
    # The NFF prefix is event,time,context-count,context-ids.  Expose the
    # schema-declared beginning of the event parameters to consumers so no
    # catalogue or audit has to assume a universal column 5.  Existing
    # absolute ``col`` values remain untouched for backwards compatibility.
    def _first_param_col(schema):
        if not isinstance(schema, dict):return
        system_col = schema.get('system_col')
        if isinstance(system_col, int):
            schema.setdefault('first_param_col', system_col + 1)
        elif isinstance(schema.get('context_count'), int):
            schema.setdefault('first_param_col', 4 + schema['context_count'])
        else:
            schema.setdefault('first_param_col', 4)
    for schema in result.values():
        _first_param_col(schema)
        for variant in (schema.get('_variants') or {}).values():
            _first_param_col(variant)
    return result

def schema_for(event: str, system):
    """1.7.0 — Retourne le YAML correspondant au couple (event, system).

    Si l'event a une variante `_variants[system]` (ex: TXPC_NR.yaml →
    _variants[9]), elle prime quand system matche. Sinon, retourne le
    schema de base (ex: TXPC.yaml pour LTE system=7).
    """
    s = schemas().get(event, {})
    variants = s.get('_variants') if isinstance(s, dict) else None
    if variants and system in variants:
        return variants[system]
    return s


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
    def _collect(s):
        if not isinstance(s, dict):return
        for f in s.get('header', []):
            result.setdefault(column(f['code']),dict(f,event=s['event'],group=None))
        for g in s.get('groups', []):
            for f in g['fields']:
                result.setdefault(column(f['code']),dict(f,event=s['event'],group=g['name']))
            for k in ('count_code','params_code'):
                if k not in g:continue
                result.setdefault(column(g[k]),dict(code=g[k],label=g[k],type='int',unit='count',agg='last',event=s['event'],group=None,proof=g['proof'],metric=k=='count_code'))
    for s in schemas().values():
        _collect(s)
        for variant in (s.get('_variants') or {}).values():
            _collect(variant)
    return result
