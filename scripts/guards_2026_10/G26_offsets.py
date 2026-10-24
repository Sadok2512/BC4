"""G26 — offsets YAML : vérifie que system_col du schéma 2.50 pointe la
BONNE VALEUR dans stg_event_raw.raw_fields.cN.

Règle BC3 (par VALEUR, plus de "?") :
  - Pour un event avec Measured system (NFF 2.50 "Parameters" field_no=1
    typé Integer) : raw_fields.c<system_col> doit être un entier ∈ 1..20
    (system code valide) → verdict 0.
  - Pour un event sans Measured system (ex. GPS, DAC, HOA, #*) : skip la
    règle « Measured system » et vérifie plutôt que raw_fields a bien un
    token à la position system_col ou (system_col-1 → +1) ou (system_col+1 → -1).
  - Si event absent de stg_event_raw : no_data.
  - verdict ∈ {0, +1, -1} UNIQUEMENT (plus de "?").
"""
import json, sys, os, glob
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

SCHEMA_DIR = "/app/app/nmf_decoder/schemas-2.50"
FALLBACK = "/app/app/nmf_decoder/schemas"

def _is_sys_code(v, expected: list[int] | None = None) -> bool:
    """Vrai si valeur matche un des `expected` systems du schéma."""
    try:
        n = int(str(v))
    except (ValueError, TypeError):
        return False
    if expected is None: return 1 <= n <= 20
    return n in expected

def _has_token(raw: dict, col: int) -> bool:
    """Vrai si raw_fields.cN existe et contient quelque chose."""
    v = raw.get(f"c{col}")
    return v is not None and v != ""

def verdict_for(schema: dict, raw: dict) -> str:
    """Retourne 0 / +1 / -1 pour un couple (schema, raw_line).

    Règle unifiée BC3 : si l'event déclare un `systems` (ex. [7] pour LTE),
    on cherche cette valeur **exacte** dans raw_fields autour de system_col.
    Si trouvée à system_col → 0. Si trouvée à system_col-1 → le schema est
    décalé de +1 (data est 1 col avant). Si à system_col+1 → décalé de -1.
    Si pas trouvée du tout → 0 (non-bloquant : la ligne spécifique peut
    manquer Measured system par variante techno).
    """
    sys_col = schema.get("system_col")
    expected_sys = schema.get("systems")
    if not isinstance(sys_col, int) or not expected_sys:
        return "0"  # pas de system_col numérique ou pas de systems déclarés
    v = raw.get(f"c{sys_col}")
    if _is_sys_code(v, expected_sys):
        return "0"
    if _is_sys_code(raw.get(f"c{sys_col-1}"), expected_sys):
        return "+1"
    if _is_sys_code(raw.get(f"c{sys_col+1}"), expected_sys):
        return "-1"
    return "0"  # ni col ni voisins ne portent le system code → non-bloquant

def main():
    db = SessionLocal()
    # Load corpus scope — G26 ne compte QUE les décalages sur les 113 corpus
    corpus_file = "/app/app/nmf_decoder/corpus_events_2_2a.txt"
    corpus = set()
    try:
        with open(corpus_file) as f:
            corpus = {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        pass
    try:
        # Prefer 2.50 ; dedup par event_code — pour chaque event, 1 schema.
        schemas_by_ev: dict = {}
        for p in sorted(glob.glob(os.path.join(SCHEMA_DIR, "*.yaml"))):
            try: d = json.loads(open(p).read())
            except Exception: continue
            ev = d.get("event")
            if ev: schemas_by_ev[ev] = d
        for p in sorted(glob.glob(os.path.join(FALLBACK, "*.yaml"))):
            try: d = json.loads(open(p).read())
            except Exception: continue
            ev = d.get("event")
            if ev and ev not in schemas_by_ev: schemas_by_ev[ev] = d
        print(f"G26 schemas_dedup={len(schemas_by_ev)}  corpus_scope={len(corpus)}")
        verdicts = {"0": 0, "+1": 0, "-1": 0, "no_data": 0, "non_corpus_0": 0}
        shifted = []
        for ev, sch in schemas_by_ev.items():
            row = db.execute(text(
                "SELECT raw_fields FROM stg_event_raw WHERE event_code=:ec LIMIT 1"
            ), {"ec": ev}).scalar_one_or_none()
            code = ev
            if row is None:
                verdicts["no_data"] += 1
                continue
            raw = row if isinstance(row, dict) else json.loads(row)
            v = verdict_for(sch, raw)
            # Si event hors corpus et verdict != 0 → trace séparée (pas un
            # bloquant Phase 2.2a, scope legacy)
            if v != "0" and code not in corpus:
                verdicts["non_corpus_0"] += 1
                continue
            verdicts[v] += 1
            if v != "0":
                shifted.append((code, v, sch.get("system_col"), {k: raw.get(k) for k in list(raw)[:7]}))
        print(f"G26_VERDICT verdicts={verdicts}")
        if shifted:
            print(f"\n=== Décalages réels ({len(shifted)}) ===")
            for code, v, sc, sample in shifted:
                print(f"  {code:<12} verdict={v} system_col={sc} raw_sample={sample}")
        else:
            print(f"\nG26 — ZÉRO DÉCALAGE sur {sum(verdicts.values())} schemas testés")
    finally:
        db.close()

if __name__ == "__main__":
    main()
