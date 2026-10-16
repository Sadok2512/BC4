"""Compose la réponse `AssistantResponse` à partir d'un `AgentRun` (0.25.1).

0.25.1 — **blocs typés** : chaque outil mappe DÉTERMINISTIQUEMENT vers un
type de bloc, pas une invention du LLM. Un `render_hint` optionnel
porté par le résultat peut sur-charger ; sinon dispatch par nom d'outil.

Mapping tool → block type :
- `list_bands`, `list_operators`, `top_rrc_messages`, `compare_operators`,
  `geo_breakdown`, `arcep_breakdown` → `BlockChart(bar)` + `BlockTable` compagnon
- `rrc_param_distribution` → `BlockChart(bar)` (histogramme visuel) + `BlockTable`
- `get_project_context` → `BlockText` (métadonnées projet, pas un chart)
- `compare_distributions` → `BlockText` (verdict seul, pas de data)
- `map_metric` → `BlockMap` (0.25.1 : signature préparée, outil pas livré)

Discipline :
- Chaque bloc porte `source_id = result_id` du moteur.
- n=0 / rows vides → `BlockText` **déclaratif** « n=0 — donnée indisponible »,
  JAMAIS un graphe vide.
- null (NULL en base) → `"N/D"` au rendu (bar.categories, table.rows),
  JAMAIS 0.
- Les résultats avec `error` sont **SILENCIEUX** côté UI : le LLM les a
  déjà vus dans son tool_message et a replanifié. Ne pas polluer la UI
  avec « plan rejeté … ».
"""

from __future__ import annotations

from typing import Any

from app.assistant.loop import AgentRun
from app.schemas.assistant import (
    BlockChart,
    BlockMap,
    BlockSummary,
    BlockTable,
    BlockText,
    ChartSeries,
    Claim,
    Evidence,
    EvidencePeriod,
    SummaryItem,
    TableColumn,
)
from app.schemas.common import MeasurementPoint as MpSchema


# ---------------------------------------------------------------------------
# Dispatch tool → render type
# ---------------------------------------------------------------------------
# Un outil retourne toujours le MÊME TYPE de bloc visuel ; le LLM ne
# choisit pas la représentation.
# ---------------------------------------------------------------------------

_RENDER_BY_TOOL: dict[str, str] = {
    "list_bands":             "bar",
    "list_operators":         "bar",
    "top_rrc_messages":       "bar",
    "compare_operators":      "bar",   # bars côte-à-côte
    "geo_breakdown":          "bar",
    "arcep_breakdown":        "bar",
    "rrc_param_distribution": "histogram",  # rendu bar visuel, sémantique distrib
    "compare_distributions":  "verdict_only",
    "get_project_context":    "context",
    "map_metric":             "map",
    "throughput_stats":       "bar",
    "radio_quality_stats":    "bar",
}

# Pour chaque render type, (x_axis_dim, y_measure, unit).
# Le `x_axis_dim` est la dimension à mettre en abscisse ; `y_measure`
# est la clé de mesure côté résultat. On tire ça des `plan.dimensions`
# et `plan.measures` à l'exécution.
_NULL_LABEL = "N/D"


# ---------------------------------------------------------------------------
# Helpers de construction
# ---------------------------------------------------------------------------


def _cell(v: Any) -> str | float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return float(v)
    return str(v)


def _table_from_rows(rows: list[dict], source_id: str, heading: str) -> BlockTable | None:
    """Table-compagnon pour tout bloc chart (facultative). None si vide."""
    if not rows:
        return None
    first = rows[0]
    cols = [
        TableColumn(
            key=k, label=k,
            numeric=isinstance(first[k], (int, float)) and not isinstance(first[k], bool),
        )
        for k in first.keys()
    ]
    norm = [{k: _cell(r.get(k)) for k in first.keys()} for r in rows]
    return BlockTable(heading=heading, columns=cols, rows=norm, source_id=source_id)


def _n_zero_block(result_id: str, heading: str, reason: str = "") -> BlockText:
    """Déclare n=0 côté UI, jamais un graphe vide."""
    text = "n=0 — donnée indisponible pour ce périmètre (jamais inventée)."
    if reason:
        text = f"{text} {reason}"
    return BlockText(
        heading=heading,
        claims=[Claim(text=text, kind="OBSERVED", source_id=result_id)],
    )


def _bar_from_rows(
    rows: list[dict],
    *,
    source_id: str,
    heading: str,
    x_axis_key: str,
    y_axis_key: str,
    unit: str = "occurrences",
) -> BlockChart | None:
    """BlockChart(bar) : categories = valeurs de `x_axis_key`, series =
    une seule série nommée `y_axis_key`. NULL → `_NULL_LABEL`."""
    if not rows:
        return None
    categories: list[str] = []
    data: list[float | None] = []
    sample_count = 0
    for r in rows:
        xv = r.get(x_axis_key)
        yv = r.get(y_axis_key)
        categories.append(_NULL_LABEL if xv is None else str(xv))
        if yv is None:
            data.append(None)
        else:
            try:
                data.append(float(yv))
                sample_count += int(yv) if yv is not None else 0
            except (TypeError, ValueError):
                data.append(None)
    return BlockChart(
        chart="bar",
        heading=heading,
        x_label=x_axis_key,
        y_label=y_axis_key,
        unit=unit,
        categories=categories,
        series=[ChartSeries(name=y_axis_key, data=data)],
        sample_count=sample_count,
        source_id=source_id,
    )


def _histogram_from_distribution(
    rows: list[dict],
    *,
    source_id: str,
    heading: str,
) -> BlockChart | None:
    """BlockChart(bar) utilisé en histogramme : abscisse = valeur
    convertie (3GPP) quand dispo, sinon value brute. ordre = ordre
    des rows (déjà trié par le moteur ORDER BY count DESC — pour un
    histogramme on préfère l'ordre numérique mais on garde ce que le
    moteur a renvoyé, ne pas inventer un sort LLM-side)."""
    if not rows:
        return None
    categories: list[str] = []
    data: list[float | None] = []
    total = 0
    for r in rows:
        vc = r.get("value_converted")
        vr = r.get("value_raw")
        label = vc if vc is not None else (vr if vr is not None else _NULL_LABEL)
        categories.append(str(label))
        c = r.get("count")
        if c is None:
            data.append(None)
        else:
            try:
                data.append(float(c))
                total += int(c)
            except (TypeError, ValueError):
                data.append(None)
    return BlockChart(
        chart="bar",  # rendu "bar" côté UI — un histogramme est visuellement une suite de barres
        heading=heading,
        x_label="valeur",
        y_label="occurrences",
        unit="occurrences",
        categories=categories,
        series=[ChartSeries(name="count", data=data)],
        sample_count=total,
        source_id=source_id,
    )


def _heading_for(tool_name: str, result: dict) -> str:
    plan = result.get("plan") or {}
    filters = plan.get("filters") or []
    filt_summary = ", ".join(
        f"{f.get('dim')}={f.get('value') or f.get('values')}"
        for f in filters[:3]
    )
    base = {
        "list_operators":          "Opérateurs présents",
        "list_bands":              "Bandes présentes",
        "top_rrc_messages":        "Messages RRC les plus fréquents",
        "rrc_param_distribution":  "Distribution du paramètre",
        "compare_operators":       "Comparaison opérateurs",
    }.get(tool_name, f"Résultat {tool_name}")
    if filt_summary:
        return f"{base} — {filt_summary}"
    return base


# ---------------------------------------------------------------------------
# Composers par type de rendu
# ---------------------------------------------------------------------------


def _compose_bar(tool_name: str, rid: str, result: dict) -> list:
    """Dispatch bar : list_*, top_rrc, compare_operators, breakdowns."""
    heading = _heading_for(tool_name, result)

    if tool_name == "compare_operators":
        # Aggrège les sous-résultats en un seul bar chart.
        comparison = result.get("comparison") or []
        categories: list[str] = []
        data: list[float | None] = []
        for sub in comparison:
            op_filters = (sub.get("plan") or {}).get("filters") or []
            op = next((f.get("value") for f in op_filters if f.get("dim") == "operator"), None)
            categories.append(op or _NULL_LABEL)
            # count = somme des rows (en pratique 1 row par groupe)
            total = 0
            for r in sub.get("rows") or []:
                v = r.get("count")
                if v is not None:
                    try:
                        total += int(v)
                    except (TypeError, ValueError):
                        pass
            data.append(float(total) if total else 0.0)
        if not categories:
            return [_n_zero_block(rid, heading)]
        verdict = result.get("verdict")
        reason = result.get("reason") or ""
        bar = BlockChart(
            chart="bar",
            heading=heading,
            x_label="operator",
            y_label="count",
            unit="occurrences",
            categories=categories,
            series=[ChartSeries(name="count", data=data)],
            sample_count=int(sum(d for d in data if d is not None)),
            source_id=rid,
        )
        blocks: list = [bar]
        # Table compagnon
        tbl_rows = [{"operator": c, "count": d} for c, d in zip(categories, data)]
        tbl = _table_from_rows(tbl_rows, source_id=rid, heading=f"{heading} — table")
        if tbl is not None:
            blocks.append(tbl)
        # Verdict de comparabilité
        if verdict:
            kind = "INTERPRETED" if verdict == "COMPARABLE" else "UNAVAILABLE"
            blocks.append(
                BlockText(
                    heading="Verdict de comparabilité",
                    claims=[Claim(text=f"[{verdict}] {reason}", kind=kind, source_id=rid)],
                )
            )
        return blocks

    # Cas générique : résultat avec rows + plan.dimensions[0] + measures[0].
    rows = result.get("rows") or []
    plan = result.get("plan") or {}
    dims = plan.get("dimensions") or []
    meas = plan.get("measures") or ["count"]
    if not rows:
        return [_n_zero_block(rid, heading)]
    x = dims[0] if dims else "x"
    y = meas[0] if meas else "count"
    bar = _bar_from_rows(rows, source_id=rid, heading=heading, x_axis_key=x, y_axis_key=y)
    blocks: list = []
    if bar is not None:
        blocks.append(bar)
    tbl = _table_from_rows(rows, source_id=rid, heading=f"{heading} — table")
    if tbl is not None:
        blocks.append(tbl)
    return blocks


def _compose_histogram(tool_name: str, rid: str, result: dict) -> list:
    """Pour rrc_param_distribution : rows = [{value_raw, value_converted, count}]."""
    heading = _heading_for(tool_name, result)
    rows = result.get("rows") or []
    if not rows:
        return [_n_zero_block(rid, heading)]
    hist = _histogram_from_distribution(rows, source_id=rid, heading=heading)
    blocks: list = []
    if hist is not None:
        blocks.append(hist)
    tbl = _table_from_rows(rows, source_id=rid, heading=f"{heading} — table")
    if tbl is not None:
        blocks.append(tbl)
    return blocks


def _compose_context(tool_name: str, rid: str, result: dict) -> list:
    """BlockText pour `get_project_context` — métadonnées projet."""
    heading = "Contexte projet"
    claims = []
    for k, lbl in (
        ("name", "Nom"),
        ("period_start", "Début"),
        ("period_end", "Fin"),
    ):
        v = result.get(k)
        if v:
            claims.append(Claim(text=f"{lbl} : {v}", kind="OBSERVED", source_id=rid))
    for k, lbl in (
        ("operators_declared", "Opérateurs déclarés"),
        ("technologies", "Technologies"),
        ("bands_declared", "Bandes déclarées"),
    ):
        v = result.get(k)
        if v:
            claims.append(Claim(text=f"{lbl} : {', '.join(str(x) for x in v)}", kind="OBSERVED", source_id=rid))
    if not claims:
        claims = [Claim(text="Contexte projet vide.", kind="UNAVAILABLE", source_id=rid)]
    return [BlockText(heading=heading, claims=claims)]


def _compose_verdict_only(tool_name: str, rid: str, result: dict) -> list:
    """compare_distributions : rend uniquement le verdict en BlockText."""
    verdict = result.get("verdict") or "NOT_COMPARABLE"
    reason = result.get("reason") or ""
    kind = "INTERPRETED" if verdict == "COMPARABLE" else "UNAVAILABLE"
    return [
        BlockText(
            heading="Verdict de comparabilité",
            claims=[Claim(text=f"[{verdict}] {reason}", kind=kind, source_id=rid)],
        )
    ]


def _compose_default(tool_name: str, rid: str, result: dict) -> list:
    """Fallback : table seule (ancien comportement 0.25.0)."""
    heading = _heading_for(tool_name, result)
    rows = result.get("rows") or []
    if not rows:
        return [_n_zero_block(rid, heading)]
    tbl = _table_from_rows(rows, source_id=rid, heading=heading)
    return [tbl] if tbl is not None else []


def _compose_bar_grouped(
    rows: list[dict],
    *,
    source_id: str,
    heading: str,
    group_dim: str,      # ex. "operator"
    series_dim: str,     # ex. "value_converted" (ou "value_raw" fallback)
    series_fallback_dim: str | None,
    measure_key: str = "count",
    unit: str = "occurrences",
) -> BlockChart | None:
    """0.29.0 — Bar GROUPÉ : categories = valeurs distinctes de
    `group_dim`, series = une par valeur distincte de `series_dim`.

    Idéal pour `compare op × value_converted` : on voit la distribution
    de valeurs POUR CHAQUE opérateur côte à côte, au lieu d'une liste
    plate (op,count) qui répète « Orange » plusieurs fois.
    """
    if not rows:
        return None
    # Collecte categories (groupes) et séries (valeurs).
    groups: list[str] = []
    series_keys: list[str] = []
    bucket: dict[tuple[str, str], float] = {}
    for r in rows:
        g = r.get(group_dim)
        s_val = r.get(series_dim)
        if (s_val is None or s_val == "") and series_fallback_dim:
            s_val = r.get(series_fallback_dim)
        g_str = _NULL_LABEL if g is None else str(g)
        s_str = _NULL_LABEL if s_val is None else str(s_val)
        if g_str not in groups:
            groups.append(g_str)
        if s_str not in series_keys:
            series_keys.append(s_str)
        try:
            v = float(r.get(measure_key) or 0)
        except (TypeError, ValueError):
            v = 0.0
        bucket[(g_str, s_str)] = bucket.get((g_str, s_str), 0.0) + v
    # Tri des groupes par total décroissant.
    group_totals = {
        g: sum(bucket.get((g, s), 0.0) for s in series_keys) for g in groups
    }
    groups.sort(key=lambda g: -group_totals[g])
    series_total_sum = 0
    series = []
    for s in series_keys:
        data = [bucket.get((g, s), 0.0) for g in groups]
        series_total_sum += int(sum(data))
        series.append(ChartSeries(name=s, data=data))
    return BlockChart(
        chart="bar",
        heading=heading,
        x_label=group_dim,
        y_label=measure_key,
        unit=unit,
        categories=groups,
        series=series,
        sample_count=series_total_sum,
        source_id=source_id,
    )


def _compose_map(tool_name: str, rid: str, result: dict) -> list:
    """0.26.0 — Carte agrégée géolocalisée.

    Attendu : `result["aggregated_points"]` = cellules MeasurementPoint-shaped
    (lat/lng/operator/tech/service/band/rsrp/…). On construit un
    `BlockMap` avec `metric="rsrp"` (unique métrique 0.26.0) +
    `unit="dBm"` + `value_range` + `grid`.
    """
    heading = f"Carte RSRP — grille {result.get('grid',{}).get('bins_decimals','?')} décimales"
    cells = result.get("aggregated_points") or result.get("rows") or []
    if not cells:
        return [_n_zero_block(rid, heading, reason=result.get("warnings", [""])[0])]

    # Chaque cellule déjà en forme MeasurementPoint (map_metric les a
    # construits conformes). Pydantic BlockMap valide à la construction.
    try:
        mp_points = [MpSchema(**{k: v for k, v in c.items() if k != "n"}) for c in cells]
    except Exception as exc:
        return [
            BlockText(
                heading=heading,
                claims=[
                    Claim(
                        text=f"Rendu carte indisponible : {exc!r}",
                        kind="UNAVAILABLE",
                        source_id=rid,
                    )
                ],
            )
        ]

    center = tuple(result.get("center") or [0.0, 0.0])
    if len(center) != 2:
        center = (0.0, 0.0)
    value_range = result.get("value_range")
    if isinstance(value_range, list) and len(value_range) == 2:
        value_range = (float(value_range[0]), float(value_range[1]))
    else:
        value_range = None

    block = BlockMap(
        heading=heading,
        metric="rsrp",
        points=mp_points,
        center=center,
        source_id=rid,
        unit=result.get("unit"),
        value_range=value_range,
        grid=result.get("grid"),
    )

    # Table compagnon : lat, lon, operator, band, rsrp, n
    tbl_rows = []
    for c in cells:
        tbl_rows.append({
            "lat": c.get("lat"),
            "lon": c.get("lng"),
            "operator": c.get("operator"),
            "band": c.get("band"),
            "rsrp": c.get("rsrp"),
            "n": c.get("n"),
        })
    tbl = _table_from_rows(
        tbl_rows,
        source_id=rid,
        heading=f"Cellules agrégées — table (n total = {result.get('total_observations', 0)})",
    )
    out: list = [block]
    if tbl is not None:
        out.append(tbl)
    return out


_COMPOSERS: dict[str, Any] = {
    "bar": _compose_bar,
    "histogram": _compose_histogram,
    "context": _compose_context,
    "verdict_only": _compose_verdict_only,
    "map": _compose_map,          # 0.26.0 — RSRP agrégé
    # stat / line arriveront quand les outils correspondants seront livrés.
    "stat": _compose_default,
    "line": _compose_default,
}


# ---------------------------------------------------------------------------
# compose_response
# ---------------------------------------------------------------------------


def compose_response(
    run: AgentRun, *, project, filters, conversation_id: str
) -> dict:
    """Assemble les champs à passer à `AssistantResponse(...)`.

    0.25.1 — Dispatch déterministe par outil → block type.
    Les erreurs d'outil sont **silencieuses côté UI** (le LLM les a
    déjà vues dans son tool_message et replanifié ; une rejection
    affichée serait du bruit).
    """
    blocks: list[Any] = []
    evidence: list[Evidence] = []
    warnings: list[str] = list(run.warnings)
    rejections_replayed: int = 0  # Pour trace server-side.

    # 1) BlockText principal avec le texte LLM final.
    if run.final_text:
        claim = Claim(text=run.final_text, kind="INTERPRETED")
    elif run.error:
        claim = Claim(text=f"Assistant indisponible : {run.error}.", kind="UNAVAILABLE")
    elif run.tool_calls:
        claim = Claim(
            text="L'agent a collecté des résultats mais n'a pas rédigé de synthèse (MAX_STEPS atteint ou coupure LLM). "
                 "Les blocs ci-dessous proviennent directement des outils.",
            kind="UNAVAILABLE",
        )
    else:
        claim = Claim(text="Aucune analyse produite — réessaie ou précise ta question.", kind="UNAVAILABLE")
    blocks.append(BlockText(heading="Résumé", claims=[claim]))

    # 2) Un bloc typé par tool_call unique (dédup sur result_id).
    seen: set[str] = set()
    for tc in run.tool_calls:
        rid = tc["result_id"]
        if rid in seen:
            continue
        name = tc["name"]
        result = run.results_by_id.get(rid) or {}

        # 2a) Erreur outil (ex. plan rejeté) → SILENCIEUX côté UI.
        # Le LLM a vu l'erreur dans son tool_message et a replanifié.
        if result.get("error"):
            rejections_replayed += 1
            continue
        seen.add(rid)

        # 2b) Dispatch render par outil.
        render = _RENDER_BY_TOOL.get(name, "default")
        composer = _COMPOSERS.get(render, _compose_default)
        try:
            new_blocks = composer(name, rid, result)
        except Exception as exc:
            warnings.append(f"compose:{name}:{exc!r}")
            new_blocks = _compose_default(name, rid, result)
        blocks.extend(new_blocks)

        # 2c) Evidence (uniforme).
        plan = result.get("plan") or {}
        date_range = result.get("date_range") or {"start": None, "end": None}
        agg_dims = ",".join(plan.get("dimensions") or [])
        aggregation = f"GROUP BY {agg_dims}" if agg_dims else "count"
        evidence.append(
            Evidence(
                source_id=rid,
                source_type="rrc_events" if result.get("dataset") == "rrc_dict" else "measurement_points",
                label=f"{result.get('dataset','?')} · {_heading_for(name, result)}",
                sample_count=int(result.get("n") or 0),
                aggregation=aggregation,
                period=EvidencePeriod(
                    start=date_range.get("start") or project.period_start,
                    end=date_range.get("end") or project.period_end,
                ),
            )
        )
        for w in result.get("warnings") or []:
            if w not in warnings:
                warnings.append(w)

    # 3) Diagnostics.
    if rejections_replayed:
        warnings.append(
            f"{rejections_replayed} plan(s) rejeté(s) par le moteur et rejoué(s) par l'agent "
            "(silencieux côté UI — le texte final les a déjà intégrés)."
        )
    if not run.tool_calls and not run.error:
        warnings.append("Aucun outil appelé par l'agent — réponse texte seule, aucune donnée vérifiable.")

    return {
        "blocks": blocks,
        "evidence": evidence,
        "warnings": warnings,
        "scenario": "b2_agent" if run.tool_calls else "b2_text_only",
    }
