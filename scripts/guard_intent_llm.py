"""Manual guard (0.34.0) — extraction d'intention LLM structurée.

Pas de CI. Lance ce script à la main pour vérifier que les 8
formulations de référence sortent le bon triplet `(operation,
metric_key, needs_clarification)` :

- 6 formulations équivalentes RSRP → **toutes** doivent binder
  `metric_key="rsrpServing"` et basculer sur une opération d'analyse
  (`distribution` idéalement, `list` toléré sur l'heuristique pure
  tant que `metric` est bien lié).
- « montre les débits » → `metric_key="throughputDL"` (feasibility
  en aval tranchera AVAILABLE vs UNAVAILABLE selon le projet).
- « quel temps fait-il » → aucune métrique catalogue →
  `needs_clarification=True`. **Jamais** op=list sur operator par
  défaut.

Deux modes selon l'environnement :

- `BC4_DSN` + LLM activé (`settings_llm.enabled=true` + clé) →
  `extract_intent(db, q)` passe par le LLM (structured output).
- `BC4_DSN` absent → fallback sur `parse_intent` directement
  (heuristique Python avec discipline anti-fallback).

Exécution :

    python scripts/guard_intent_llm.py            # heuristique seule
    BC4_DSN=postgresql+psycopg://… python scripts/guard_intent_llm.py

Sortie : tableau par cas (op, metric_key, dims, needs_clarification,
reason), suivi d'un verdict global `PASS` / `FAIL` par la règle « la
métrique est liée OU la clarification est demandée — jamais un fallback
vers une liste d'opérateurs ».
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# Permet d'exécuter depuis bc4-back/ sans installer le package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Mode heuristique seule : stub des variables pour éviter le fail-fast
# de `app.config.Settings` (BC4_DSN / BC4_JWT_SECRET). Ces valeurs ne
# sont PAS lues puisqu'on n'ouvre pas de session DB.
if not os.environ.get("BC4_DSN"):
    os.environ.setdefault("BC4_DSN", "postgresql+psycopg://noop:noop@localhost/noop")
    os.environ.setdefault("BC4_JWT_SECRET", "noop-guard-manual-0.34.0")


# Les 8 formulations de la garde.
# `must_bind_rsrp` : la métrique DOIT être rsrpServing (ou NEEDS_CLARIFICATION
# si le canal LLM est indisponible et l'heuristique ne reconnaît pas
# le synonyme — alors la seule issue acceptable est la clarification).
# `must_bind_metric` : clé métrique attendue (None = pas de métrique).
CASES = [
    {"q": "histogram rsrp", "must_bind_metric": "rsrpServing"},
    {"q": "montre moi la distribution RSRP", "must_bind_metric": "rsrpServing"},
    {"q": "distribution du rsrp", "must_bind_metric": "rsrpServing"},
    {"q": "le rsrp par opérateur", "must_bind_metric": "rsrpServing"},
    {"q": "donne le rsrp en dBm", "must_bind_metric": "rsrpServing"},
    {"q": "affiche la puissance reçue", "must_bind_metric": "rsrpServing"},
    {"q": "montre les débits", "must_bind_metric": "throughputDL"},
    {"q": "quel temps fait-il", "must_bind_metric": None},  # → NEEDS_CLARIFICATION
]


def _run_with_db() -> list[dict]:
    from app.db import SessionLocal
    from app.assistant.intent_llm import extract_intent

    out: list[dict] = []
    with SessionLocal() as db:
        for case in CASES:
            plan = extract_intent(db, case["q"])
            out.append({
                "q": case["q"],
                "expected": case["must_bind_metric"],
                "operation": plan.operation,
                "metric_key": plan.metric_key,
                "dimensions": plan.dimensions,
                "needs_clarification": plan.needs_clarification,
                "reason": plan.reason,
            })
    return out


def _run_heuristic_only() -> list[dict]:
    from app.assistant.intent import parse_intent

    # Même discipline anti-fallback que `extract_intent` applique quand
    # le LLM est down — pour que la garde isolée ait la même sémantique.
    from app.assistant.intent_llm import _apply_antifallback

    out: list[dict] = []
    for case in CASES:
        plan = _apply_antifallback(parse_intent(case["q"]))
        out.append({
            "q": case["q"],
            "expected": case["must_bind_metric"],
            "operation": plan.operation,
            "metric_key": plan.metric_key,
            "dimensions": plan.dimensions,
            "needs_clarification": plan.needs_clarification,
            "reason": plan.reason,
        })
    return out


def _verdict(row: dict) -> str:
    """Vrai verdict de garde :
    - Si le cas attend une métrique précise : soit metric_key == attendu,
      soit needs_clarification=True (fallback honnête).
    - Si le cas attend None (hors catalogue) : needs_clarification=True.
    - JAMAIS acceptable : operation=list + metric_key=None + nc=False
      (c'est l'ancienne fallback-liste-opérateurs que ce lot élimine).
    """
    exp = row["expected"]
    op = row["operation"]
    mk = row["metric_key"]
    nc = row["needs_clarification"]

    if op == "list" and mk is None and not nc:
        return "FAIL (fallback liste opérateurs silencieux)"

    if exp is None:
        return "PASS" if nc else "FAIL (métrique inventée hors catalogue)"

    if mk == exp:
        return "PASS"
    if nc:
        return "PASS (clarification honnête)"
    return f"FAIL (metric={mk!r} ≠ attendu={exp!r})"


def main() -> int:
    # Un vrai DSN (pas le stub posé plus haut) + une table LLM renseignée
    # font passer en mode LLM. Sinon on reste sur l'heuristique seule.
    dsn = os.environ.get("BC4_DSN", "")
    use_db = bool(dsn) and "noop" not in dsn
    mode = "LLM (extract_intent avec DB)" if use_db else "heuristique seule (parse_intent + anti-fallback)"
    print(f"=== Garde manuelle 0.34.0 — intent extraction ===")
    print(f"Mode : {mode}")
    print()

    try:
        rows = _run_with_db() if use_db else _run_heuristic_only()
    except Exception as exc:
        print(f"!! Erreur d'init ({type(exc).__name__}) : {exc}")
        print("   Astuce : exécuter sans BC4_DSN pour la garde heuristique seule.")
        return 2

    all_pass = True
    for row in rows:
        v = _verdict(row)
        if "FAIL" in v:
            all_pass = False
        print(f"[{v}] {row['q']!r}")
        print(f"       op={row['operation']!r} metric={row['metric_key']!r} "
              f"dims={row['dimensions']} nc={row['needs_clarification']}")
        if row["reason"]:
            print(f"       reason={row['reason']!r}")

    print()
    print("Verdict global :", "PASS" if all_pass else "FAIL")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
