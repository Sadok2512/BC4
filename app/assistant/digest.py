"""Digest tool_message pour la boucle agent (0.27.0).

**Levier n°1 de maîtrise des coûts** : avant 0.27.0, chaque appel
`dispatch_tool` renvoyait au LLM la liste complète des `rows` + les
métadonnées — en pratique jusqu'à 81 cellules carte, 50 valeurs de
distribution, etc. Cette table complète partait au LLM à CHAQUE étape
de la boucle (OpenAI relaie tous les tool_messages précédents). D'où
une entrée qui gonflait vite.

Désormais le LLM reçoit un **digest compact** par tool_result :
- `top_K` rows (K=10 par défaut)
- Stats clés (min/max count, min/max valeur, dénominateur, n)
- `result_id` (traçabilité intacte — le LLM peut toujours référencer)
- `truncated=True` si réduit (le LLM sait qu'il manque des données)

La donnée COMPLÈTE reste côté serveur (`AgentRun.results_by_id`)
et part telle quelle à `compose.py` + UI (BlockTable, BlockMap, etc).
**Aucun chiffre n'est inventé** : si le LLM cite une valeur, elle est
dans son digest (donc dans la source) ; le reste il réfère via le
result_id — la UI affiche la table complète.
"""

from __future__ import annotations

from typing import Any


DEFAULT_TOP_K = 10


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rows_stats(rows: list[dict], candidate_cols: tuple[str, ...]) -> dict[str, Any]:
    """min/max/sum sur chaque colonne numérique présente. Jamais inventé."""
    out: dict[str, Any] = {}
    for col in candidate_cols:
        vals = [_coerce_float(r.get(col)) for r in rows if r.get(col) is not None]
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        out[f"{col}_min"] = min(vals)
        out[f"{col}_max"] = max(vals)
        out[f"{col}_sum"] = sum(vals)
    return out


def make_digest(result: dict, tool_name: str, *, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """Compacte un résultat d'outil pour injection dans un tool_message
    LLM. **Preserve `result_id` et les chiffres citables** ; omet les
    rows au-delà du top_K et marque `truncated` si c'est le cas.
    """
    # Erreurs : passer tel quel — le LLM doit voir le refus pour replanifier.
    if "error" in result:
        return {"error": result["error"], "tool": tool_name}

    rid = result.get("result_id")
    rows = result.get("rows") or []
    total = len(rows)
    top_rows = rows[:top_k]
    truncated = total > top_k

    digest: dict[str, Any] = {
        "result_id": rid,
        "tool": tool_name,
        "dataset": result.get("dataset"),
        "n": result.get("n"),
        "denominator": result.get("denominator"),
        "date_range": result.get("date_range"),
        "filters_applied": result.get("filters_applied"),
        "top_rows": top_rows,
        "total_rows": total,
        "truncated": truncated,
    }
    if truncated:
        digest["note_truncation"] = (
            f"Rendu {top_k} des {total} lignes. La table complète est accessible "
            f"au compose via result_id={rid!s} — cite ce result_id, ne demande pas la liste."
        )

    # Stats sur colonnes numériques typiques (jamais inventées).
    stats = _rows_stats(rows, candidate_cols=("count", "rsrp", "value_avg", "n"))
    if stats:
        digest["stats"] = stats

    # Verdict si c'est un compare_* ou un retour validate_comparison.
    if "verdict" in result:
        digest["verdict"] = result["verdict"]
        digest["reason"] = result.get("reason")
        # denominators garde la trace par result_id même en digest.
        if result.get("denominators"):
            digest["denominators"] = result["denominators"]
        # compare_operators : agrège les sous-résultats en counts compacts.
        if result.get("comparison"):
            comp_digest = []
            for sub in result["comparison"]:
                sub_rows = sub.get("rows") or []
                total_count = 0
                for r in sub_rows:
                    try:
                        total_count += int(r.get("count") or 0)
                    except (TypeError, ValueError):
                        pass
                sub_filters = (sub.get("plan") or {}).get("filters") or []
                comp_digest.append({
                    "result_id": sub.get("result_id"),
                    "filters": sub_filters,
                    "count_total": total_count,
                    "denominator": sub.get("denominator"),
                })
            digest["comparison"] = comp_digest

    # Métadonnées carte (map_metric) : garder stats globales, PAS les
    # 81 cellules. Le LLM n'a pas à les relire.
    if "aggregated_points" in result:
        cells = result.get("aggregated_points") or []
        digest["cells_count"] = len(cells)
        digest["total_observations"] = result.get("total_observations")
        digest["value_range"] = result.get("value_range")
        digest["grid"] = result.get("grid")
        digest["unit"] = result.get("unit")
        # Pour un digest LLM : top 5 cellules par n (ordre moteur = DESC).
        compact_cells = []
        for c in cells[:5]:
            compact_cells.append({
                "lat": c.get("lat"),
                "lng": c.get("lng"),
                "operator": c.get("operator"),
                "band": c.get("band"),
                "rsrp": c.get("rsrp"),
                "n": c.get("n"),
            })
        digest["top_cells"] = compact_cells
        # Les top_rows contiendront aussi les cellules — déduplique en les
        # excluant pour ne pas dupliquer l'info dans le digest.
        if digest.get("top_rows") == cells[:top_k]:
            digest.pop("top_rows", None)
            digest["truncated"] = True

    # Contexte projet : get_project_context (pas de rows, metadata direct).
    if "operators_declared" in result:
        digest["operators_declared"] = result["operators_declared"]
        digest["technologies"] = result.get("technologies")
        digest["bands_declared"] = result.get("bands_declared")
        digest["project_name"] = result.get("name")
        digest["period_start"] = result.get("period_start")
        digest["period_end"] = result.get("period_end")

    # Warnings du moteur (recomposition stats, config LLM, etc.).
    if result.get("warnings"):
        digest["warnings"] = result["warnings"]

    return digest
