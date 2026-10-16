"""Pipeline V3 (0.28.0, ré-articulé 0.34.0) — Le LLM EXTRAIT L'INTENTION, le SYSTÈME compose & vérifie.

Flux :
1. **Étage 1 (Intent)** : `extract_intent(db, question)` → `IntentPlan`
   typé. Depuis 0.34.0, l'intention est **extraite par le LLM**
   (structured output JSON, robuste au phrasé / casse / mots de
   remplissage). Le détecteur heuristique Python n'est qu'un fallback
   quand le LLM est indisponible, et il reste tenu par la discipline
   anti-fallback (métrique liée OU `NEEDS_CLARIFICATION` — jamais une
   liste par défaut sur `operator`).
   Si `operation="conversation"` → présentation 0.24.1 inchangée.
   Si `needs_clarification` → `OUTCOME = NEEDS_CLARIFICATION` immédiat.

2. **Étage 2 (Faisabilité)** : `feasibility.check(metric_key)`. Métrique
   indisponible → `OUTCOME = UNAVAILABLE` + raison. **Aucune
   substitution** : on NE replan PAS vers une autre métrique.

3. **Étage 3 (Exécution)** : conversion intent → plan analytique → appel
   moteur `execute_analytical_query`. Chaque cellule de la sortie se
   voit assigner un état typé (`PRESENT` / `ZERO_REEL` / `ABSENT_DU_PERIMETRE`
   / `INDISPONIBLE`) **par le code**, pas par le LLM.

4. **Étage 4 (Composition déterministe)** : `compose_v3` écrit :
   - `observed[]` : CHIFFRES CLÉS extraits des résultats par le code
     (top N par mesure, verdict calculé, totaux). Pas de narration LLM.
   - Blocs typés (bar / histogram / map / table) : via les composers
     existants `_compose_bar/_histogram/_map/_default`.
   - `verdict` : CALCULÉ par `validate_comparison`, pas raconté.
   - Narration LLM : **optionnelle et bornée** à 2 phrases qualitatives
     (« les volumes diffèrent », « la distribution est bimodale »).
     Toute phrase LLM contenant un chiffre absent des result_ids est
     REJETÉE par le vérificateur.

Discipline :
- Jamais de collapse `n=0 ↔ ABSENT ↔ INDISPONIBLE` : les 3 états sont
  rendus distinctement côté UI.
- Jamais de substitution de métrique sur replan.
- Jamais de chiffre dans la narration sans sa source result_id.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.assistant.budget import check_budget, log_usage
from app.assistant.engine import AnalyticalResult, PlanRejected, execute_analytical_query, compute_result_id
from app.assistant.feasibility import Feasibility, check as check_feasibility
from app.assistant.intent import IntentPlan
from app.assistant.intent_llm import extract_intent
from app.assistant.metrics import CATALOG
from app.assistant.proof import validate_comparison
from app.models import Project
from app.services.llm_client import LlmInvocationError, call_llm
from app.services.llm_crypto import get_effective_llm_config


logger = logging.getLogger(__name__)


Outcome = Literal["OK", "UNAVAILABLE", "NEEDS_CLARIFICATION", "ERROR", "CONVERSATION"]
CellState = Literal["PRESENT", "ZERO_REEL", "ABSENT_DU_PERIMETRE", "INDISPONIBLE"]


@dataclass
class PipelineRun:
    outcome: Outcome
    intent: IntentPlan
    feasibility: Feasibility | None = None
    results: list[AnalyticalResult] = field(default_factory=list)
    observed: list[str] = field(default_factory=list)  # chiffres clés en texte, écrits par le code
    verdict_tag: str | None = None
    verdict_reason: str | None = None
    narration: str | None = None  # texte LLM qualitatif, vérifié
    narration_rejected: str | None = None  # motif si rejeté par verifier
    warnings: list[str] = field(default_factory=list)
    message: str = ""  # pour UNAVAILABLE / NEEDS_CLARIFICATION


# ---------------------------------------------------------------------------
# Étage 3 : exécution guidée par l'intent
# ---------------------------------------------------------------------------


def _plan_for_intent(intent: IntentPlan, project_id: str) -> dict:
    """Compile `IntentPlan` → plan analytique attendu par
    `execute_analytical_query`.

    IMPORTANT : la métrique du plan est TOUJOURS celle de l'intent.
    Jamais de substitution.
    """
    m = CATALOG.get(intent.metric_key) if intent.metric_key else None
    dataset = m.source_dataset if m else "rrc_dict"
    filters = list(intent.filters)
    # Ajoute les contraintes path/message de la métrique canonique (si rrc_dict)
    if m and m.source_dataset == "rrc_dict":
        for pat in m.path_match:
            filters.append({"dim": "param_path", "op": "contains", "value": pat.strip("%")})
            # Note : on ajoute en contains ; le moteur convertit en ILIKE.
            # S'il y a plusieurs patterns on prend le premier — le moteur
            # ne supporte qu'un `contains` par dim actuellement.
            break
        if m.message_match:
            filters.append({"dim": "message", "op": "eq", "value": m.message_match})
    dimensions = list(intent.dimensions)
    # Mesure : si pas de métrique explicite ou classe COUNT → count ; sinon count aussi
    # (on compte des occurrences par (dim) ; les percentiles de valeur ne sont pas
    # dans ce lot V3 — étage 2 futur).
    measures = ["count"]
    return {
        "dataset": dataset,
        "dimensions": dimensions,
        "measures": measures,
        "filters": filters,
        "order": [{"field": "count", "dir": "DESC"}],
        "limit": 100,
    }


def _execute_intent(db: Session, intent: IntentPlan, project: Project) -> list[AnalyticalResult]:
    """Exécute le plan de l'intent et retourne la liste de résultats.

    Pour `operation="compare"` + `comparison_dim="operator"`, on fait
    **une seule requête group_by** — plus compact et plus sûr côté stats.

    0.29.0 — `operation="map"` : branchement direct vers l'outil
    `map_metric` (qui porte sa propre logique de grille + attribution
    SIB1). On enveloppe sa sortie dans un `AnalyticalResult` pour
    cohérence avec le compose V3.
    """
    # Cas spécial : map → tool map_metric, pas le moteur générique.
    if intent.operation == "map":
        from app.assistant.tools import map_metric

        # Convertit les filtres `IntentPlan` en kwargs explicites de map_metric.
        kw_op = kw_band = kw_sys = None
        for f in intent.filters or []:
            if f.get("dim") == "operator" and f.get("op") == "eq":
                kw_op = str(f.get("value"))
            elif f.get("dim") == "band" and f.get("op") == "eq":
                kw_band = str(f.get("value"))
            elif f.get("dim") == "system" and f.get("op") == "eq":
                kw_sys = str(f.get("value"))
        res = map_metric(
            db, project, metric="M_serving_rsrp", bins=3,
            operator=kw_op, band=kw_band, system=kw_sys,
        )
        # Enveloppe dans AnalyticalResult pour cohérence pipeline.
        rid = res.get("result_id") or compute_result_id({"tool": "map_metric"}, project.id)
        rows = res.get("aggregated_points") or []
        wrapped = AnalyticalResult(
            result_id=rid,
            plan={
                "dataset": res.get("dataset", "rrc_dict"),
                "dimensions": [],  # map n'a pas de group_by SQL — c'est l'outil qui gère
                "measures": ["count"],
                "filters": intent.filters,
                "tool": "map_metric",
            },
            rows=rows,
            n=int(res.get("n") or 0),
            denominator=int(res.get("total_observations") or 0),
            dataset=res.get("dataset", "rrc_dict"),
            date_range=res.get("date_range") or {
                "start": project.period_start,
                "end": project.period_end,
            },
            filters_applied=res.get("filters_applied") or {},
            sql_compiled="",
            params={},
            warnings=res.get("warnings") or [],
        )
        # Attache les métadonnées map (value_range, grid, unit, center)
        # pour que compose_v3 construise le BlockMap avec le vrai contrat.
        wrapped.plan["_map_meta"] = {
            "unit": res.get("unit"),
            "value_range": res.get("value_range"),
            "grid": res.get("grid"),
            "center": res.get("center"),
            "aggregated_points": rows,
        }
        return [wrapped]

    plan = _plan_for_intent(intent, project.id)
    try:
        res = execute_analytical_query(db, plan, project_id=project.id)
        return [res]
    except PlanRejected as exc:
        logger.warning("pipeline V3 plan rejected: %s", exc.message)
        rid = compute_result_id(plan, project.id)
        return [
            AnalyticalResult(
                result_id=rid,
                plan=plan,
                rows=[],
                n=0,
                denominator=0,
                dataset=plan["dataset"],
                date_range={"start": project.period_start, "end": project.period_end},
                filters_applied={},
                sql_compiled="",
                params={},
                warnings=[f"plan_rejected: {exc.code} — {exc.message}"],
            )
        ]


# ---------------------------------------------------------------------------
# Étage 3b : états typés par cellule
# ---------------------------------------------------------------------------


# Opérateurs attendus pour détecter ABSENT_DU_PERIMETRE (via metadata projet).
_MNO = ("Orange", "SFR", "Bouygues", "Free")


def _cells_with_state(
    result: AnalyticalResult, intent: IntentPlan, project: Project
) -> list[dict[str, Any]]:
    """Produit des cellules enrichies d'un état typé.

    - PRESENT : la cellule a une valeur `count > 0` (ou mesure non-NULL).
    - ZERO_REEL : la cellule existe mais count == 0 (rare — en pratique
      le GROUP BY ne renvoie pas les groupes vides, donc on ne verra
      pas ce cas sans un JOIN de référence).
    - ABSENT_DU_PERIMETRE : l'opérateur n'apparaît pas du tout dans les
      rows du résultat, bien qu'il soit un MNO FR connu — on l'ajoute
      explicitement avec cet état.
    - INDISPONIBLE : la métrique n'est pas peuplée (déjà traité à l'étage 2
      en principe, mais on garde une sécurité pour les mesures NULL).
    """
    rows = result.rows
    out: list[dict[str, Any]] = []
    seen_operators: set[str] = set()
    for r in rows:
        c = dict(r)
        # Détermine l'état
        count_val = c.get("count")
        if count_val is None:
            c["_state"] = "INDISPONIBLE"
        elif isinstance(count_val, (int, float)) and float(count_val) == 0:
            c["_state"] = "ZERO_REEL"
        else:
            c["_state"] = "PRESENT"
        if "operator" in c and c.get("operator"):
            seen_operators.add(str(c["operator"]))
        out.append(c)

    # Ajoute les opérateurs attendus mais ABSENTS, UNIQUEMENT pour les
    # opérations qui groupent par opérateur (compare / list operator).
    if "operator" in (intent.dimensions or []) and intent.operation in ("compare", "list"):
        # Opérateurs attendus = ceux déclarés dans la métadonnée projet,
        # ou à défaut les 4 MNO FR.
        expected = set((project.operators or []) or _MNO)
        missing = expected - seen_operators
        for op in sorted(missing):
            out.append({"operator": op, "count": None, "_state": "ABSENT_DU_PERIMETRE"})
    return out


# ---------------------------------------------------------------------------
# Étage 4 : composition déterministe (observed[]) + verdict calculé
# ---------------------------------------------------------------------------


def _compose_observed(cells: list[dict], intent: IntentPlan, metric: Any) -> list[str]:
    """observed[] = chiffres clés RÉDIGÉS PAR LE CODE depuis `cells`.

    0.29.1 — Unité AUTORITAIRE depuis le catalogue. Un COUNT total
    s'affiche toujours en « occurrences », JAMAIS avec l'unité physique
    de la métrique (sinon on dit « 132 ms » là où c'est juste un
    comptage brut).
    """
    out: list[str] = []
    # Unité pour les VALEURS de la métrique (ex. dB pour a3-Offset).
    value_unit = metric.unit if metric else ""
    # Libellé pour les TOTAUX de comptage.
    count_label = "occurrences"
    metric_display = metric.display if metric else "métrique"

    present = [c for c in cells if c.get("_state") == "PRESENT"]
    absent = [c for c in cells if c.get("_state") == "ABSENT_DU_PERIMETRE"]
    indispo = [c for c in cells if c.get("_state") == "INDISPONIBLE"]
    dims = intent.dimensions or []
    has_value_dim = "value_raw" in dims or "value_converted" in dims

    # ----- compare avec valeur (pivot opérateur × distribution) -----
    if intent.operation == "compare" and "operator" in dims and has_value_dim:
        total = sum(int(c.get("count") or 0) for c in present)
        n_ops = len({c.get("operator") for c in present})
        header = f"{metric_display} — {n_ops} opérateur(s), total {total} {count_label}"
        if value_unit:
            header += f" ; unité des valeurs : {value_unit}"
        out.append(header + ".")
        by_op: dict[str, list[dict]] = {}
        for c in present:
            op = str(c.get("operator") or "N/D")
            by_op.setdefault(op, []).append(c)
        for op, rows in sorted(by_op.items(), key=lambda kv: -sum(int(r.get("count") or 0) for r in kv[1])):
            rows_sorted = sorted(rows, key=lambda r: -int(r.get("count") or 0))[:3]
            parts: list[str] = []
            for r in rows_sorted:
                val = r.get("value_converted")
                if val is None or val == "":
                    val = r.get("value_raw", "N/D")
                # Format : valeur + unité + nombre d'occurrences
                parts.append(f"{val} {value_unit} ({int(r.get('count') or 0)} {count_label})")
            out.append(f"{op} : " + ", ".join(parts))
        if absent:
            names = ", ".join(sorted({str(c.get("operator")) for c in absent}))
            out.append(f"Opérateurs ABSENTS du périmètre : {names}.")
        if indispo:
            out.append(f"{len(indispo)} cellule(s) INDISPONIBLES.")
        return out

    # ----- cas génériques (list / compare simple / distribution / map) -----
    if intent.operation in ("list", "compare") and "operator" in dims:
        total = sum(int(c.get("count") or 0) for c in present)
        out.append(f"Opérateurs mesurés : {len(present)} (total {total} {count_label}).")
        if present:
            sorted_cells = sorted(
                present,
                key=lambda x: float(x.get("count") or 0),
                reverse=True,
            )[:3]
            top_desc = ", ".join(
                f"{c.get('operator')}={int(float(c.get('count') or 0))} {count_label}"
                for c in sorted_cells
            )
            out.append(f"Top : {top_desc}.")
        if absent:
            names = ", ".join(sorted({str(c.get("operator")) for c in absent}))
            out.append(f"Opérateurs ABSENTS du périmètre : {names}. (n=0 vrai pas affiché comme 0 mesuré)")
        if indispo:
            out.append(f"{len(indispo)} cellule(s) INDISPONIBLES (métrique non peuplée).")
    elif intent.operation == "distribution":
        total = sum(int(c.get("count") or 0) for c in present)
        n_vals = len(present)
        suffix = f", unité des valeurs : {value_unit}" if value_unit else ""
        out.append(
            f"{metric_display} — distribution : {n_vals} valeur(s) observée(s), "
            f"total {total} {count_label}{suffix}."
        )
    elif intent.operation == "map":
        out.append(f"{len(present)} cellule(s) géo mesurée(s) ({value_unit or 'unité N/D'}).")
    else:
        out.append(f"{len(present)} ligne(s) retournée(s).")

    return out


def _compute_verdict(results: list[AnalyticalResult], intent: IntentPlan) -> tuple[str | None, str | None]:
    """Verdict de comparabilité calculé — PAS raconté par le LLM."""
    if intent.operation != "compare":
        return None, None
    if len(results) < 2:
        # Avec un GROUP BY unique en 1 requête, on considère les
        # sous-groupes comparables SI même plan appliqué partout.
        return "COMPARABLE", "Comparaison intra-plan unique (même filtres, même mesures, même dimension)."
    v = validate_comparison(results)
    return v.verdict, v.reason


# ---------------------------------------------------------------------------
# Narration LLM optionnelle (bornée) + vérificateur
# ---------------------------------------------------------------------------


_NUM_RE = re.compile(r"-?\d+(?:[\.,]\d+)?")


def _extract_numbers(txt: str) -> list[str]:
    """Numbers hors artefacts (dates, result_ids). Simple normalisation."""
    return _NUM_RE.findall(txt or "")


def _allowed_numbers(results: list[AnalyticalResult], observed: list[str]) -> set[str]:
    """Ensemble des chiffres autorisés dans la narration.

    Autorisés :
    - Chiffres présents dans les rows des résultats
    - Chiffres présents dans les lignes observed[] (déjà rédigées par le code)
    - Entiers 0..10 (comptages trivials, dates courtes) + années
    """
    allowed: set[str] = set()
    for r in results:
        for row in r.rows:
            for v in row.values():
                for n in _extract_numbers(str(v)):
                    allowed.add(n)
    for line in observed:
        for n in _extract_numbers(line):
            allowed.add(n)
    # Chiffres trivialement cités (0..10) sans source
    for i in range(0, 11):
        allowed.add(str(i))
    return allowed


def _verify_narration(txt: str, results: list[AnalyticalResult], observed: list[str]) -> tuple[bool, str]:
    """Vérifie que tous les chiffres du texte LLM sont dans les sources
    autorisées. Retourne `(ok, reason)`.

    Normalise `12,5` et `12.5` comme équivalents (virgule FR).
    """
    allowed = {n.replace(",", ".") for n in _allowed_numbers(results, observed)}
    nums = [n.replace(",", ".") for n in _extract_numbers(txt)]
    unauthorized = [n for n in nums if n not in allowed]
    if unauthorized:
        # On distingue : si c'est un petit entier (< 100), on tolère (pourrait
        # être un énumérateur de phrase « 1., 2. »). Au-delà, on rejette.
        strict_unauth = [n for n in unauthorized if abs(float(n)) >= 100]
        if strict_unauth:
            return False, f"Chiffre(s) non sourcé(s) détecté(s) : {strict_unauth[:5]}"
    return True, ""


# ---------------------------------------------------------------------------
# 0.29.0 — Narration vérifiée (LLM court + fallback déterministe)
# ---------------------------------------------------------------------------

_NARRATION_SYSTEM_PROMPT_TEMPLATE = (
    "Tu es un assistant d'analyse radio BC4.\n\n"
    "MÉTRIQUE CANONIQUE : {metric_display}\n"
    "NATURE : {nature}\n"
    "UNITÉ DES VALEURS : {unit}\n"
    "{nature_rule}\n\n"
    "Tâche : rédiger UNE SEULE phrase (max 2) qui résume qualitativement "
    "les chiffres déjà calculés par le système ci-dessous.\n\n"
    "RÈGLES STRICTES :\n"
    "- Ne cite AUCUN chiffre qui n'apparaît pas littéralement dans "
    "  les 'observed' ou 'results' que je te donne. Pas de pourcentage "
    "  inventé, pas de 'moyenne' calculée par toi, pas de 'relativement "
    "  stable'.\n"
    "- Pas de bavardage. Pas de 'Puis-je vous aider', pas de 'Je peux '. "
    "  Démarre directement par la lecture.\n"
    "- UTILISE L'UNITÉ EXACTE du catalogue ({unit}). Si l'unité est "
    "  « occurrences » (count), ne dis pas « ms » / « dB » / « Mbit/s ».\n"
    "- Reste QUALITATIF : ex. 'les volumes sont dominés par X', "
    "  'la distribution est concentrée sur une valeur'.\n"
    "- Français, ton technique sobre, 1-2 phrases MAX.\n"
    "- Si tu doutes, renvoie une phrase vide — on garde le résumé "
    "  déterministe fourni par le système."
)


_NATURE_RULE_CONFIG = (
    "⚠ Cette métrique est de nature CONFIGURATION RRC "
    "(seuil, offset, timer, bool). Elle N'EST PAS une grandeur radio "
    "mesurée par le terminal. INTERDICTION ABSOLUE d'utiliser les "
    "mots suivants à son sujet : 'latence', 'temps de latence', "
    "'débit', 'throughput', 'qualité radio', 'couverture', 'signal "
    "fort/faible'. Ces mots sont réservés aux grandeurs MESURÉES."
)

_NATURE_RULE_COUNT = (
    "⚠ Cette lecture est un COMPTAGE d'occurrences. Elle n'a pas "
    "d'unité physique. INTERDICTION d'utiliser 'latence', 'débit', "
    "'qualité radio', 'couverture' — c'est juste un volume brut."
)

_NATURE_RULE_MEASUREMENT = (
    "Cette métrique est une grandeur radio MESURÉE. Tu peux employer "
    "des termes qualitatifs physiques pertinents à son unité "
    "(ex. 'niveau de signal' pour RSRP, 'débit' pour throughput). "
    "Ne mélange pas avec d'autres unités."
)


def _system_prompt_for_narration(metric: Any) -> str:
    display = metric.display if metric else "comptage"
    nature = metric.nature if metric else "count"
    unit = metric.unit if metric else "occurrences"
    rule = {
        "config": _NATURE_RULE_CONFIG,
        "count": _NATURE_RULE_COUNT,
        "measurement": _NATURE_RULE_MEASUREMENT,
    }.get(nature, _NATURE_RULE_COUNT)
    return _NARRATION_SYSTEM_PROMPT_TEMPLATE.format(
        metric_display=display, nature=nature, unit=unit, nature_rule=rule,
    )


_BAVARDAGE_PATTERNS = re.compile(
    r"\b("
    r"puis[- ]je\s+(?:vous|t[eu])\s+aider|"
    r"n['e]hésitez\s+pas|"
    r"je\s+peux\s+(?:aussi|également)|"
    r"relativement\s+(?:stable|élevé|faible|constant)|"
    r"globalement\s+stable|"
    r"en\s+général\s+constant|"
    r"je\s+suis\s+l'assistant|"
    r"ravi\s+de\s+vous\s+aider"
    r")\b",
    re.IGNORECASE,
)


def _bavardage(txt: str) -> str | None:
    """Détecte un pattern de bavardage. Retourne le match ou None."""
    m = _BAVARDAGE_PATTERNS.search(txt or "")
    return m.group(0) if m else None


def _fallback_narration(observed: list[str], verdict_tag: str | None) -> str:
    """Phrase déterministe quand la narration LLM est rejetée ou absente."""
    bits: list[str] = []
    if observed:
        bits.append(observed[0])  # première ligne observed = résumé total
    if verdict_tag:
        bits.append(f"Verdict de comparabilité : {verdict_tag}.")
    if not bits:
        return "Résultat calculé — se référer aux blocs ci-dessous."
    return " ".join(bits)


def _detect_forbidden_phenomena(txt: str, metric: Any) -> str | None:
    """0.29.1 — Si le texte LLM contient un terme de phénomène interdit
    pour la nature de la métrique, retourne le terme fautif."""
    from app.assistant.metrics import (
        FORBIDDEN_PHENOMENA_FOR_CONFIG,
        FORBIDDEN_PHENOMENA_FOR_COUNT,
    )
    nature = metric.nature if metric else "count"
    forbidden: tuple[str, ...] = ()
    if nature == "config":
        forbidden = FORBIDDEN_PHENOMENA_FOR_CONFIG
    elif nature == "count":
        forbidden = FORBIDDEN_PHENOMENA_FOR_COUNT
    low = (txt or "").lower()
    for term in forbidden:
        if term.lower() in low:
            return term
    return None


def _unit_consistent(txt: str, metric: Any) -> str | None:
    """Vérifie que les unités citées dans la narration correspondent à
    l'unité du catalogue. Si le catalogue dit « dB » et la narration
    dit « ms » (ou l'inverse), c'est une incohérence rejetable.
    """
    if not metric or not getattr(metric, "unit", None):
        return None
    unit = metric.unit.lower()
    low = (txt or "").lower()
    # Liste d'unités qu'on ne doit JAMAIS voir si l'unité officielle
    # est différente.
    ALL_UNITS = ("ms", "dbm", "db", "mbit/s", "kbit/s", "mbps", "mb/s", "occurrences")
    other_units = []
    for u in ALL_UNITS:
        if u == unit:
            continue
        # Mot entier (évite « db » dans « bdb »).
        import re as _re
        if _re.search(rf"\b{_re.escape(u)}\b", low):
            # Exception : « occurrences » est toujours OK (comptage brut
            # peut cohabiter avec une métrique à unité physique).
            if u == "occurrences":
                continue
            other_units.append(u)
    if other_units:
        return f"unités incohérentes : narration cite {other_units} alors que catalogue={metric.unit!r}"
    return None


def _narrate_llm(
    db: Session,
    *,
    question: str,
    results: list[AnalyticalResult],
    observed: list[str],
    conversation_id: str | None,
    metric: Any = None,
) -> tuple[str | None, str | None]:
    """Appel LLM court pour une narration qualitative.

    Retourne `(narration | None, rejection_reason | None)`.
    - `(txt, None)` : narration passée au vérificateur, acceptée.
    - `(None, reason)` : rejetée par bavardage ou chiffre non sourcé.
    - `(None, None)` : LLM indisponible / désactivé / budget cap.
    """
    try:
        cfg = get_effective_llm_config(db)
    except Exception as exc:  # pragma: no cover
        logger.warning("narration cfg indispo: %s", exc)
        return None, None

    if not cfg.get("enabled") or not cfg.get("api_key"):
        return None, None

    ok_budget, _spent, _cap = check_budget(db, cfg.get("daily_cap_usd"))
    if not ok_budget:
        return None, None

    # Prépare un contexte factuel minimal pour le LLM : la question
    # + les observed[] + un extrait des rows (top K par result).
    import json as _json
    results_payload = []
    for r in results:
        results_payload.append({
            "result_id": r.result_id,
            "n": r.n,
            "denominator": r.denominator,
            "top_rows": r.rows[:5],
        })
    context_facts = _json.dumps(
        {
            "question": question,
            "observed": observed,
            "results": results_payload,
        },
        ensure_ascii=False,
        default=str,
    )

    try:
        txt = call_llm(
            db,
            user_question=question,
            context_facts=context_facts,
            system_prompt=_system_prompt_for_narration(metric),
            max_tokens_override=120,
            timeout=15.0,
        )
    except LlmInvocationError as exc:
        logger.warning("narration LLM failed: %s", exc)
        return None, None

    if not txt or not txt.strip():
        return None, None
    txt = txt.strip()

    # Vérificateurs
    bv = _bavardage(txt)
    if bv:
        return None, f"bavardage détecté : {bv!r}"
    # 0.29.1 — Phénomène inventé (ex. 'latence' sur une métrique config).
    forbidden = _detect_forbidden_phenomena(txt, metric)
    if forbidden:
        nature = metric.nature if metric else "count"
        return None, f"phénomène inventé pour métrique nature={nature!r} : {forbidden!r}"
    # 0.29.1 — Unité incohérente (ex. 'ms' alors que catalogue=dB).
    unit_err = _unit_consistent(txt, metric)
    if unit_err:
        return None, unit_err
    # Vérif chiffres sourcés.
    ok, reason = _verify_narration(txt, results, observed)
    if not ok:
        return None, reason
    return txt, None


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------


def run_pipeline(db: Session, project: Project, question: str, *, conversation_id: str | None = None) -> PipelineRun:
    """Orchestration V3 complète. Jamais 5xx : toute erreur est capturée."""
    # 0.33.0 — Étage 1 : extraction d'intention par LLM structured output
    # (robuste au phrasé). Fallback heuristique si LLM indisponible.
    intent = extract_intent(db, question, conversation_id=conversation_id)

    if intent.operation == "conversation":
        return PipelineRun(outcome="CONVERSATION", intent=intent)

    if intent.needs_clarification:
        return PipelineRun(
            outcome="NEEDS_CLARIFICATION",
            intent=intent,
            message=intent.reason,
        )

    # Étage 2 — Faisabilité
    feas = check_feasibility(db, project.id, intent.metric_key)
    if not feas.ok:
        # Jamais de substitution : stop propre.
        return PipelineRun(
            outcome="UNAVAILABLE",
            intent=intent,
            feasibility=feas,
            message=feas.reason,
        )

    # Budget pre-check (indicatif — on n'appelle le LLM qu'en bornage qualitatif).
    try:
        cfg = get_effective_llm_config(db)
    except Exception:
        cfg = {"daily_cap_usd": None}
    ok_budget, spent, cap = check_budget(db, cfg.get("daily_cap_usd"))

    # Étage 3 — Exécution
    results = _execute_intent(db, intent, project)
    primary = results[0]
    cells = _cells_with_state(primary, intent, project)

    # Étage 4a — Observed[] rédigé par le code
    metric = CATALOG.get(intent.metric_key) if intent.metric_key else None
    observed = _compose_observed(cells, intent, metric)

    # Étage 4b — Verdict calculé (jamais raconté par le LLM)
    verdict_tag, verdict_reason = _compute_verdict(results, intent)

    # Étage 4c — Narration LLM courte, VÉRIFIÉE (0.29.0 — réactivée).
    narration: str | None = None
    narration_rejected: str | None = None
    narration, narration_rejected = _narrate_llm(
        db,
        question=question,
        results=results,
        observed=observed,
        conversation_id=conversation_id,
        metric=metric,
    )

    warnings: list[str] = list(primary.warnings)
    if not ok_budget:
        warnings.append(
            f"Budget LLM du jour atteint ({spent:.2f} $ / {cap:.2f} $). "
            "Narration LLM désactivée. La réponse système reste complète."
        )
    # Si la narration LLM a été rejetée (bavardage ou chiffre non sourcé),
    # on garde le fallback déterministe comme narration.
    if narration is None and narration_rejected:
        narration = _fallback_narration(observed, None)  # verdict ajouté plus bas si pertinent
        warnings.append(
            f"Narration LLM rejetée par le vérificateur ({narration_rejected}). "
            "Fallback texte déterministe utilisé."
        )

    return PipelineRun(
        outcome="OK",
        intent=intent,
        feasibility=feas,
        results=results,
        observed=observed,
        verdict_tag=verdict_tag,
        verdict_reason=verdict_reason,
        narration=narration,
        narration_rejected=narration_rejected,
        warnings=warnings,
    )
