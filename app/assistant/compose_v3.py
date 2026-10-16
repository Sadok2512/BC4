"""Composition V3 (0.28.0) : PipelineRun → blocks + evidence.

Déterministe : les chiffres sortent du moteur, pas du LLM. Les claims
OBSERVED viennent de `PipelineRun.observed` (déjà rédigés par le code).
Le verdict est rendu avec son tag (CALCULÉ, pas raconté).

Les blocs typés (bar / histogram / map / table) viennent du résultat
du moteur via les composers 0.25.1 réutilisés verbatim.
"""

from __future__ import annotations

from typing import Any

from app.assistant.compose import (
    _compose_bar,
    _compose_bar_grouped,
    _compose_default,
    _compose_histogram,
    _compose_map,
    _n_zero_block,
    _table_from_rows,
)
from app.assistant.pipeline import PipelineRun
from app.schemas.assistant import (
    BlockText,
    Claim,
    Evidence,
    EvidencePeriod,
)


def _state_badge(state: str) -> str:
    return {
        "PRESENT": "",
        "ZERO_REEL": "n=0 observé",
        "ABSENT_DU_PERIMETRE": "absent du périmètre",
        "INDISPONIBLE": "indisponible",
    }.get(state, "")


def compose_pipeline_response(run: PipelineRun, *, project, filters) -> dict:
    """Transforme `PipelineRun` en payload pour `AssistantResponse`."""
    blocks: list = []
    evidence: list[Evidence] = []
    warnings: list[str] = list(run.warnings)

    # ---------- OUTCOMES SPÉCIAUX ----------

    if run.outcome == "CONVERSATION":
        # Le dispatcher appelle `_build_conversation_response` à part
        # pour ce cas, donc on ne devrait pas arriver ici — safety net.
        from app.routes.assistant import _welcome_text  # type: ignore

        blocks.append(
            BlockText(
                heading="",
                claims=[Claim(text=_welcome_text(project), kind="INTERPRETED")],
            )
        )
        return {
            "blocks": blocks,
            "evidence": [],
            "warnings": warnings,
            "scenario": "conversation",
        }

    if run.outcome == "NEEDS_CLARIFICATION":
        blocks.append(
            BlockText(
                heading="Précision nécessaire",
                claims=[
                    Claim(
                        text=run.message or "Terme ambigu — précise la métrique souhaitée.",
                        kind="UNAVAILABLE",
                    )
                ],
            )
        )
        return {
            "blocks": blocks,
            "evidence": [],
            "warnings": warnings,
            "scenario": "v3_needs_clarification",
        }

    if run.outcome == "UNAVAILABLE":
        blocks.append(
            BlockText(
                heading="Métrique indisponible",
                claims=[
                    Claim(
                        text=run.message
                        or "La métrique demandée n'est pas disponible dans ce périmètre. "
                        "Aucune substitution automatique n'est appliquée (règle BC4).",
                        kind="UNAVAILABLE",
                    )
                ],
            )
        )
        return {
            "blocks": blocks,
            "evidence": [],
            "warnings": warnings,
            "scenario": "v3_unavailable",
        }

    # ---------- OUTCOME = OK ----------

    # 1) Résumé OBSERVED rédigé par le code (jamais par le LLM).
    observed_claims = []
    for line in run.observed:
        observed_claims.append(Claim(text=line, kind="OBSERVED"))
    if observed_claims:
        blocks.append(BlockText(heading="Résumé (chiffres clés)", claims=observed_claims))

    # 2) Verdict de comparabilité CALCULÉ.
    if run.verdict_tag:
        kind = "INTERPRETED" if run.verdict_tag == "COMPARABLE" else "UNAVAILABLE"
        blocks.append(
            BlockText(
                heading="Verdict de comparabilité",
                claims=[Claim(text=f"[{run.verdict_tag}] {run.verdict_reason or ''}", kind=kind)],
            )
        )

    # 3) Narration LLM VÉRIFIÉE (si acceptée). Si rejetée, warning serveur.
    if run.narration:
        blocks.append(
            BlockText(
                heading="Lecture qualitative",
                claims=[Claim(text=run.narration, kind="INTERPRETED")],
            )
        )
    if run.narration_rejected:
        warnings.append(
            "Narration LLM REJETÉE par le vérificateur : "
            f"{run.narration_rejected}. Les chiffres restent dans Résumé/Tables."
        )

    # 4) Blocs typés (bar / bar-grouped / histogram / map / table).
    #    Dispatch piloté par l'intent + plan.
    for res in run.results:
        rows = res.rows
        rid = res.result_id
        plan = res.plan or {}
        dims = plan.get("dimensions") or []
        has_value_dim = "value_raw" in dims or "value_converted" in dims

        # 0.29.0 — Map : construit un BlockMap depuis les méta portées
        # dans plan["_map_meta"] (map_metric a tout préparé).
        if run.intent.operation == "map" and plan.get("tool") == "map_metric":
            meta = plan.get("_map_meta") or {}
            map_result = {
                "aggregated_points": meta.get("aggregated_points") or rows,
                "unit": meta.get("unit"),
                "value_range": meta.get("value_range"),
                "grid": meta.get("grid"),
                "center": meta.get("center"),
                "total_observations": res.denominator,
                "n": res.n,
                "warnings": res.warnings,
            }
            new_blocks = _compose_map("map_metric", rid, map_result)
        # 0.29.0 — Compare opérateur × valeur : bar GROUPÉ + table.
        elif run.intent.operation == "compare" and "operator" in dims and has_value_dim:
            heading = f"Distribution par opérateur — {run.intent.metric_key or 'count'}"
            # Choix de la série : préfère value_converted (unités 3GPP),
            # fallback value_raw.
            series_dim = "value_converted" if "value_converted" in dims else "value_raw"
            series_fallback = "value_raw" if series_dim == "value_converted" else None
            bar = _compose_bar_grouped(
                rows,
                source_id=rid,
                heading=heading,
                group_dim="operator",
                series_dim=series_dim,
                series_fallback_dim=series_fallback,
            )
            tbl = _table_from_rows(rows, source_id=rid, heading=f"{heading} — table")
            new_blocks = []
            if bar is not None:
                new_blocks.append(bar)
            if tbl is not None:
                new_blocks.append(tbl)
            if not new_blocks:
                new_blocks = [_n_zero_block(rid, heading)]
        elif run.intent.operation == "distribution":
            new_blocks = _compose_histogram(
                "rrc_param_distribution",
                rid,
                {"plan": plan, "rows": rows},
            )
        elif "operator" in dims or "band" in dims or "message" in dims:
            new_blocks = _compose_bar(
                "list_operators" if "operator" in dims
                else ("list_bands" if "band" in dims else "top_rrc_messages"),
                rid,
                {"plan": plan, "rows": rows},
            )
        else:
            new_blocks = _compose_default("table", rid, {"plan": plan, "rows": rows})

        if not new_blocks and not rows:
            new_blocks = [_n_zero_block(rid, "Résultat")]
        blocks.extend(new_blocks)

        # Evidence
        date_range = res.date_range or {"start": None, "end": None}
        evidence.append(
            Evidence(
                source_id=rid,
                source_type="rrc_events" if res.dataset == "rrc_dict" else "measurement_points",
                label=f"{res.dataset} · {run.intent.operation}",
                sample_count=int(res.n or 0),
                aggregation="GROUP BY " + ",".join(dims) if dims else "count",
                period=EvidencePeriod(
                    start=date_range.get("start") or project.period_start,
                    end=date_range.get("end") or project.period_end,
                ),
            )
        )
        for w in res.warnings or []:
            if w not in warnings:
                warnings.append(w)

    # 5) Signalement explicite des cellules ABSENT_DU_PERIMETRE au-delà d'observed
    #    (évidence : opérateur hors projet jamais rendu « 0 »).
    #    Il est déjà cité dans observed[] si applicable.

    return {
        "blocks": blocks,
        "evidence": evidence,
        "warnings": warnings,
        "scenario": f"v3_{run.intent.operation}",
    }
