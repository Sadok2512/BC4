"""Classification d'intention pour `/assistant` (0.23.1).

Un simple « hello » ne doit NI appeler les requêtes DB (contexte factuel
enrichi) NI afficher le panneau Agrégats/Sources. Deux modes :

- **CONVERSATION** : salutation, « qui es-tu », « comment tu marches »,
  smalltalk, remerciement. Aucun tool call, aucune Evidence, aucun
  BlockSummary. L'Assistant se présente.
- **ANALYSE** : demande d'un chiffre, d'un paramètre, d'une liste, d'une
  carte, d'une comparaison. Pipeline complet (contexte factuel +
  OBSERVED + Evidence).

Deux étages de classification :
1. **Heuristique regex** (rapide, zéro appel réseau). Couvre > 90% des
   cas typiques : salutations, mots-clés d'analyse.
2. **Fallback LLM** (`call_llm_classify`) uniquement quand l'heuristique
   est ambigüe (`unknown`). Max 5 tokens, timeout 5s.

Si l'heuristique ET le LLM sont indécis / indisponibles, on retombe sur
**ANALYSE** par défaut — ça préserve le comportement 0.17.x–0.23.0 et
évite qu'une classification cassée fasse disparaître des agrégats
légitimes.
"""

from __future__ import annotations

import re
from typing import Literal

from sqlalchemy.orm import Session


Intent = Literal["conversation", "analyse"]


# Patterns conversationnels : salutations, questions sur l'identité /
# capacités de l'assistant, remerciements, au-revoir. L'ordre importe
# peu — on vérifie seulement une correspondance quelconque.
_CONVERSATION_RE = re.compile(
    r"\b("
    r"hello|hi+|hey|coucou|salut|bonjour|bonsoir|yo|wesh|"
    r"au\s+revoir|bye|a\s*\+|ciao|a\s+plus|"
    r"merci|thanks|thx|"
    # « qui es-tu / qui est-tu / t'es qui / qui êtes-vous »
    r"qui\s+(?:es|est)[-\s]?tu|t['e]s\s+qui|qui\s+êtes[-\s]?vous|"
    # « que peux-tu faire / que sais-tu faire / qu'est-ce que tu sais faire »
    r"que\s+peux[-\s]?tu\s+faire|que\s+sais[-\s]?tu\s+faire|"
    r"qu['e]est[-\s]?ce\s+que\s+tu\s+(?:peux|sais)|"
    # « comment tu marches / comment ça marche / comment fonctionnes-tu »
    r"comment\s+tu\s+marches?|comment\s+(?:ça|cela)\s+marche|"
    r"comment\s+fonctionnes?[-\s]?tu|comment\s+est[-\s]?ce\s+que\s+tu\s+fonctionnes?|"
    # « c'est quoi BC4 / cet outil »
    r"c['e]est\s+quoi\s+(?:bc4|cet\s+(?:outil|assistant))|"
    # « présente-toi »
    r"présente[-\s]?toi|peux[-\s]?tu\s+te\s+présenter"
    r")\b",
    re.IGNORECASE,
)

# Patterns d'analyse : vocabulaire métier (opérateurs, bandes, RRC,
# KPIs), verbes de requête (combien, quel, liste, montre, affiche,
# compare), agrégats (top, max, moyenne, distribution).
_ANALYSIS_RE = re.compile(
    r"\b("
    r"combien|quel(?:s|le|les)?|liste|montre|donne|affiche|cite|énumère|"
    # vocabulaire métier
    r"opérateurs?|op[eé]rateurs?|rrc|messages?|paramètres?|param[eè]tres?|"
    r"bandes?|kpi|cartes?|mesures?|"
    r"d[eé]bits?|rsrp|rsrq|sinr|latence|handover|setup|release|rétention|retention|"
    # agrégats
    r"top\s*\d*|max|min|moyenne?|moyen|dominant|principal|"
    r"comparer?|ratio|distribution|r[eé]partition|histogramme|"
    # radio / strat
    r"stratégie|strat[eé]gie|mobilité|mobilit[eé]|timers?|contrôle\s+de\s+puissance|"
    # pourcentage / parts
    r"pourcentage|part|%"
    r")\b",
    re.IGNORECASE,
)


def classify_intent_heuristic(question: str) -> Literal["conversation", "analyse", "unknown"]:
    """Classification rapide par regex. Retourne `unknown` quand aucune
    des deux familles de patterns ne matche sur une question longue
    (> 3 mots) — l'appelant déclenchera alors le fallback LLM.

    Règles tie-breaker :
    - Si **les deux** familles matchent (ex. « Bonjour, combien
      d'opérateurs ? »), ANALYSE l'emporte — on ne vole pas d'infos à
      l'utilisateur sous prétexte qu'il a été poli.
    - Question très courte (≤ 3 mots) sans match ANALYSE → CONVERSATION
      (hypothèse : smalltalk).
    """
    q = question.strip()
    if not q:
        return "conversation"
    has_ana = bool(_ANALYSIS_RE.search(q))
    has_conv = bool(_CONVERSATION_RE.search(q))
    if has_ana:
        return "analyse"
    if has_conv:
        return "conversation"
    if len(q.split()) <= 3:
        return "conversation"
    return "unknown"


def classify_intent(db: Session, question: str) -> Intent:
    """Classification complète : heuristique d'abord, LLM en fallback.

    Le LLM fallback est optionnel (si désactivé / indisponible on reste
    sur ANALYSE par défaut — plus d'info visible côté UI qu'une
    conversation vide pour une question réelle).
    """
    h = classify_intent_heuristic(question)
    if h != "unknown":
        return h

    # Import local pour éviter le cycle app.services.intent <-> app.services.llm_client
    from app.services.llm_client import call_llm_classify

    resp = call_llm_classify(db, question)
    if resp is None:
        # LLM désactivé / erreur → défaut safe = ANALYSE (comportement
        # historique). Un faux positif ANALYSE affiche un panneau à n=0 ;
        # un faux négatif CONVERSATION masque des infos — ce dernier est
        # pire.
        return "analyse"
    r = resp.strip().upper()
    if "CONVERSATION" in r:
        return "conversation"
    if "ANAL" in r:  # ANALYSE / ANALYSIS / variantes
        return "analyse"
    return "analyse"
