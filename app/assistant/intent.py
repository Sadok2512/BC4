"""Parser d'intention structuré (0.28.0 — Assistant V3).

Transforme une question utilisateur en `IntentPlan` **typé** que le
système exécute déterministement. Le LLM N'ÉCRIT PLUS LES RÉPONSES —
il ne fait QUE le parsing en JSON schema contraint.

Trois résolutions critiques :

1. **Opération** : `list` | `distribution` | `compare` | `map` |
   `trend` | `describe`. Heuristique française + anglaise + fallback
   LLM structuré.
2. **Métrique canonique** : résolue via `metrics.resolve_user_term`
   contre `CATALOG`. Si un terme matche > 1 métrique → `AMBIGUOUS`
   (demande de clarification côté UI, pas de choix implicite).
3. **Comparabilité** : si `operation="compare"` et le `comparison_dim`
   manque, on applique un défaut **EXPLICITE** (`operator`). Jamais
   de fusion silencieuse.

Si la métrique de l'intent est **INDISPONIBLE** (ex. `throughputDL`
tant que `measurement_points.dl` est NULL partout) → `OUTCOME =
UNAVAILABLE` dès l'étage 2 (`feasibility.py`). Zéro substitution
automatique.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.assistant.metrics import CATALOG, CanonicalMetric, resolve_user_term


IntentOperation = Literal[
    "list", "distribution", "compare", "map", "trend", "describe", "conversation", "unknown"
]


@dataclass
class IntentPlan:
    operation: IntentOperation
    metric_key: str | None                 # clé canonique CATALOG
    dimensions: list[str] = field(default_factory=list)
    comparison_dim: str | None = None
    filters: list[dict] = field(default_factory=list)
    raw_question: str = ""
    # Clarification / écart
    ambiguous_terms: list[str] = field(default_factory=list)  # termes qui matchent > 1 métrique
    ambiguous_candidates: list[str] = field(default_factory=list)  # candidats pour chaque terme
    needs_clarification: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Patterns heuristiques (français + anglais, par le contenu)
# ---------------------------------------------------------------------------

_OP_PATTERNS: list[tuple[IntentOperation, re.Pattern]] = [
    ("conversation", re.compile(r"\b(hello|bonjour|salut|coucou|hey|hi|comment ça marche|qui es[- ]tu|que peux[- ]tu faire|présente[- ]toi|merci|au revoir)\b", re.IGNORECASE)),
    ("map", re.compile(r"\b(carte|map|géo|géolocal|affiche la carte|montre la carte)\b", re.IGNORECASE)),
    ("compare", re.compile(r"\b(compare|comparer|vs|versus|entre .+ et )\b", re.IGNORECASE)),
    ("distribution", re.compile(r"\b(distribution|histogramme|répartition|histogram|histo)\b", re.IGNORECASE)),
    ("trend", re.compile(r"\b(évolution|tendance|dans le temps|trend|time series|série temporelle)\b", re.IGNORECASE)),
    # 0.31.0 — "stats <X>" / "count <X>" / "nombre de <X>" ⇒ list
    ("list", re.compile(r"\b(liste|lister|list|énumère|quels?|quelles?|top \d*|donne[- ]moi les|affiche les|stats|statistiques|count|nombre de|combien)\b", re.IGNORECASE)),
    ("describe", re.compile(r"\b(décris|describe|résume|résumé|synthèse|overview|vue d'ensemble)\b", re.IGNORECASE)),
]


_OPERATOR_LITERALS = ("Orange", "SFR", "Bouygues", "Free")
_BAND_PATTERN = re.compile(r"\b(B\d{1,2}|n\d{1,3})\b")


def _detect_operation(q: str) -> IntentOperation:
    for op, rx in _OP_PATTERNS:
        if rx.search(q):
            return op
    # Question longue (> 3 mots) sans mot-clé reconnu → tentons "list" par défaut.
    return "list" if len(q.split()) >= 3 else "conversation"


def _detect_operator_filters(q: str) -> list[dict]:
    out: list[dict] = []
    for op in _OPERATOR_LITERALS:
        if re.search(rf"\b{op}\b", q, re.IGNORECASE):
            out.append({"dim": "operator", "op": "eq", "value": op})
    # Compare « Orange et SFR » / « Orange vs SFR »
    if len(out) >= 2 and any(k in q.lower() for k in ("vs", " et ", " ou ", "versus")):
        values = [f["value"] for f in out]
        return [{"dim": "operator", "op": "in", "values": values}]
    return out


def _detect_band_filters(q: str) -> list[dict]:
    bands = []
    for m in _BAND_PATTERN.finditer(q):
        bands.append(m.group(1))
    bands = list(dict.fromkeys(bands))  # dédup conservant ordre
    if not bands:
        return []
    if len(bands) == 1:
        return [{"dim": "band", "op": "eq", "value": bands[0]}]
    return [{"dim": "band", "op": "in", "values": bands}]


# ---------------------------------------------------------------------------
# Résolution métrique
# ---------------------------------------------------------------------------


# Mots-clés métier larges qui N'ONT PAS de métrique canonique directe
# mais qui sont fréquents en interro utilisateur. On les signale comme
# AMBIGUOUS pour forcer la clarification plutôt que de deviner.
_BROAD_PARAM_TERMS = {
    "RLC": "rlc",
    "PDCP": "pdcp",
    "MAC": "mac",
    "MOBILITÉ": "mobilit",
    "MOBILITE": "mobilit",
    "TIMER": "timer",
    "POWER": "power",
    "PUISSANCE": "puissance",
    "PARAMÈTRES": "paramètres",
    "PARAMETRES": "paramètres",
}


def _detect_metric(q: str) -> tuple[str | None, list[str], list[str]]:
    """Retourne `(metric_key | None, ambiguous_terms, candidates)`.

    - Essaie une résolution lexicale directe via `resolve_user_term`.
    - Si > 1 match → ambigu.
    - Si aucun match mais `BROAD_PARAM_TERMS` matche → ambigu
      (le user parle d'une famille large, pas d'une métrique
      canonique précise ; on exigera une clarification côté UI).
    - Si aucun match ni famille → `None` (l'intent décidera : opération
      sans métrique = `list`/`describe`, pas de métrique à vérifier).
    """
    # 1) Résolution directe sur chaque sous-séquence (mots individuels + bigrams)
    words = re.findall(r"[A-Za-zàâéèêëïîôöùûüç0-9\-]+", q)
    tried: set[str] = set()
    all_hits: list[str] = []
    for n in (3, 2, 1):  # trigrams d'abord (plus spécifiques)
        for i in range(len(words) - n + 1):
            sub = " ".join(words[i : i + n])
            if sub.lower() in tried:
                continue
            tried.add(sub.lower())
            hits = resolve_user_term(sub)
            for h in hits:
                if h not in all_hits:
                    all_hits.append(h)
    if len(all_hits) == 1:
        return all_hits[0], [], []
    if len(all_hits) > 1:
        return None, [", ".join(all_hits)], all_hits

    # 2) Mots-clés larges (RLC, mobilité, etc.) — famille, pas métrique
    for term, needle in _BROAD_PARAM_TERMS.items():
        if re.search(rf"\b{re.escape(needle)}", q, re.IGNORECASE):
            # On marque l'ambiguïté : il n'y a pas DE métrique canonique
            # dédiée (le catalogue n'a pas tout). L'étage 2 ira chercher
            # les paths candidats dans la DB pour clarification.
            return None, [term.lower()], []

    return None, [], []


# ---------------------------------------------------------------------------
# Parser public
# ---------------------------------------------------------------------------


def parse_intent(question: str) -> IntentPlan:
    """Analyse déterministe (heuristique) d'une question → IntentPlan.

    0.28.0 : implémentation **100 % Python** — aucun appel LLM dans ce
    chemin (le LLM pouvait halluciner l'intent). Si l'heuristique est
    indécise, on tombe en `operation="list"` sans métrique → l'étage
    exécution renverra `n=0` déclaré pour la dimension `operator`.
    """
    q = (question or "").strip()
    plan = IntentPlan(operation="unknown", metric_key=None, raw_question=q)
    if not q:
        plan.operation = "conversation"
        return plan

    op = _detect_operation(q)
    plan.operation = op

    metric_key, ambiguous_terms, ambiguous_cands = _detect_metric(q)
    plan.metric_key = metric_key
    plan.ambiguous_terms = ambiguous_terms
    plan.ambiguous_candidates = ambiguous_cands

    # 0.31.0 — Un énoncé d'analyse ne tombe JAMAIS sur conversation :
    # si un metric canonique est détecté mais que l'opération a été
    # fallback-ée en conversation (ex. 2-mots « rrc setup », « stats rsrp »),
    # on force l'opération par défaut sur `list` (ou `describe`).
    if op == "conversation" and metric_key is not None:
        plan.operation = "list"
        op = "list"

    if op == "conversation":
        # Pas de métrique, pas de filtres — c'est un smalltalk.
        return plan

    # Filtres opérateur/bande (par le CONTENU : regex sur les 4 MNO FR
    # + motifs de bande standard).
    plan.filters = _detect_operator_filters(q) + _detect_band_filters(q)

    # Dimensions par défaut selon opération.
    if op == "list":
        # Que listons-nous ?
        if metric_key == "operator_count":
            plan.dimensions = ["operator"]
        elif metric_key == "band_count":
            plan.dimensions = ["band"]
        elif metric_key == "rrc_message_count":
            plan.dimensions = ["message"]
        else:
            plan.dimensions = ["operator"] if metric_key is None else [CATALOG[metric_key].source_dataset == "rrc_dict" and "operator" or "operator"]
    elif op == "distribution":
        plan.dimensions = ["value_raw", "value_converted"]
    elif op == "compare":
        # comparison_dim : si l'utilisateur n'a pas précisé, défaut EXPLICITE = operator.
        plan.comparison_dim = "operator"
        plan.dimensions = ["operator"]
        # 0.37.0 — Un paramètre RRC (`nature=config` ou `measurement`) se
        # compare par SES VALEURS. Jamais par un count d'occurrences, sauf
        # demande explicite (« combien … » → traité en amont par le LLM
        # côté intent_llm, pas ici).
        if metric_key is not None:
            m = CATALOG.get(metric_key)
            if m is not None and m.nature in ("config", "measurement"):
                plan.dimensions = ["operator", "value_raw", "value_converted"]
    elif op == "map":
        plan.dimensions = []  # map_metric a sa propre grille interne
        if metric_key is None:
            # Par défaut carte RSRP serving si la question dit juste « carte »
            plan.metric_key = "rsrpServing"
    elif op == "describe":
        plan.dimensions = []

    # Clarification requise si ambigu
    if ambiguous_terms:
        plan.needs_clarification = True
        if ambiguous_cands:
            plan.reason = (
                f"Terme ambigu : plusieurs métriques canoniques matchent "
                f"({', '.join(ambiguous_cands)}). Précise laquelle."
            )
        else:
            plan.reason = (
                f"Terme large non résolu en métrique canonique ("
                f"{', '.join(ambiguous_terms)}). "
                f"Précise un paramètre RRC exact (ex. a3-Offset, …) ou group_by param."
            )

    return plan
