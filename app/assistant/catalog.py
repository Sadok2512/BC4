"""Catalogue sémantique de l'Assistant V2 (0.25.0).

Rôle : table de vérité **versionnée en code** des dimensions, mesures,
règles de conversion 3GPP, et vues analytiques approuvées. Le LLM NE
VOIT JAMAIS un nom de table / colonne / fonction SQL direct ; il ne
parle qu'avec ce catalogue (via `discover_schema()`), puis émet un
PLAN structuré que `engine.execute_analytical_query` compile en SQL
paramétré.

Pourquoi en code et pas en DB :
- Changement = PR relue, pas une ligne de settings qu'un admin pousse.
- Audit git = lineage complet.
- Pas de permission dynamique à vérifier.

Discipline :
- Chaque mesure expose son `sql` (toujours scalaire agrégable), son
  `unit`, sa `conversion_3gpp` (texte libre pour UI), son `lineage`
  (vue d'origine).
- Chaque dimension expose son `column`, son `null_label` (COALESCE au
  rendu, jamais `0`), ses `allowed_filter_ops`.
- Les **tables sensibles** (`app_user`, `settings_llm`, `nmf_file`…)
  ne figurent **pas** dans `DATASETS` → requête les référençant REJETÉE.
- Les mesures qui ne sont PAS re-combinables arithmétiquement
  (percentiles, moyennes pondérées par dénominateurs inégaux) portent
  `recomposable=False` → le moteur rejette un GROUP BY sur sous-groupes
  d'une telle mesure sans méthode validée (jamais de moyenne de moyennes).
"""

from __future__ import annotations

from typing import Any, Literal


# ---------------------------------------------------------------------------
# DATASETS — vues analytiques approuvées
# ---------------------------------------------------------------------------
# Chaque dataset est une **vue logique** scopée projet. L'engine prépend
# toujours `WHERE project_id = :pid`. Jamais exposées au LLM par leur
# nom de table réel ; le LLM ne connaît que `dataset`.
# ---------------------------------------------------------------------------

DATASETS: dict[str, dict[str, Any]] = {
    "rrc_dict": {
        "description": (
            "Dictionnaire RRC décodé : chaque ligne = une occurrence de "
            "paramètre dans un message RRC (op/band attribués via SIB1 "
            "précédent). Base pour top messages, distributions de valeurs, "
            "paramètres de mobilité / timers / power control."
        ),
        "source_table": "param_occurrence",
        "project_scoped": True,
        "dimensions": {
            "operator",
            "band",
            "system",
            "message",
            "param_path",
            "value_raw",
            "value_converted",
        },
        "measures": {"count"},
    },
    "measurements": {
        "description": (
            "Points de mesure radio (lat/lng + opérateur SIB1 + bande + "
            "métriques RSRP/RSRQ/SINR/CQI/débit DL/UL). Base pour cartes, "
            "KPI débits, qualité radio. Les colonnes métriques Phase 1 "
            "sont NULL tant que le mapping décodeur n'est pas prouvé "
            "(voir CHANGELOG 0.24.0)."
        ),
        "source_table": "measurement_points",
        "project_scoped": True,
        "dimensions": {"operator", "band", "system", "dep"},
        "measures": {
            "count",
            "rsrp_avg", "rsrp_p10", "rsrp_p50", "rsrp_p90",
            "rsrq_avg", "sinr_avg", "cqi_avg",
            "dl_avg", "dl_p50",
            "thrpt_ul_avg",
            "tx_power_avg",
            "latency_avg",
        },
    },
}


# ---------------------------------------------------------------------------
# DIMENSIONS — regroupements autorisés
# ---------------------------------------------------------------------------

DIMENSIONS: dict[str, dict[str, Any]] = {
    "operator": {
        "column": "operator",
        "null_label": "non attribué",
        "allowed_filter_ops": ("eq", "in"),
        "description": "Opérateur attribué via PLMN primaire du SIB1 précédent (MNO FR : Orange, SFR, Bouygues, Free).",
    },
    "band": {
        "column": "band",
        "null_label": "non attribuée",
        "allowed_filter_ops": ("eq", "in"),
        "description": "Bande LTE (Bxx) ou NR (nXX) dérivée de l'EARFCN/NR-ARFCN via bc4_enrich.",
    },
    "system": {
        "column": "system",
        "null_label": "non attribué",
        "allowed_filter_ops": ("eq", "in"),
        "description": "Système radio : LTE ou NR.",
    },
    "message": {
        "column": "message",
        "null_label": "N/D",
        "allowed_filter_ops": ("eq", "in", "contains"),
        "description": "Nom du message RRC (ex. MeasurementReport, RRCConnectionReconfiguration).",
    },
    "param_path": {
        "column": "path",
        "null_label": "N/D",
        "allowed_filter_ops": ("eq", "in", "contains"),
        "description": "Chemin ASN.1 du paramètre RRC (ex. reportConfigEUTRA.a3-Offset).",
    },
    "value_raw": {
        "column": "value",
        "null_label": "N/D",
        "allowed_filter_ops": ("eq", "in"),
        "description": "Valeur brute ASN.1 décodée (chaîne, pas de conversion 3GPP).",
    },
    "value_converted": {
        "column": "value_converted",
        "null_label": "N/D",
        "allowed_filter_ops": ("eq", "in"),
        "description": "Valeur convertie en unité 3GPP (ex. rsrpResult → dBm).",
    },
    "dep": {
        "column": "dep",
        "null_label": "non renseigné",
        "allowed_filter_ops": ("eq", "in"),
        "description": "Département FR (depuis cell_ref).",
    },
}


# ---------------------------------------------------------------------------
# MESURES — expressions SQL safe (jamais de chaîne LLM)
# ---------------------------------------------------------------------------
# Clés :
# - `sql` : expression scalaire agrégable. Jamais de sous-requête, jamais
#   de fonction dangereuse. Compilée telle quelle avec paramètres bind.
# - `unit` : unité 3GPP (dBm, dB, Mbit/s, ms, occurrences, aucune).
# - `conversion_3gpp` : texte libre d'affichage UI.
# - `lineage` : dataset d'origine (vient de DATASETS).
# - `null_safe` : True ⇒ COUNT(expr IS NOT NULL) exposé en parallèle.
# - `recomposable` : False pour percentiles / moyennes qui NE peuvent PAS
#   être arithmétiquement recombinés depuis des sous-agrégats sans
#   dénominateurs. L'engine rejette toute recomposition non prouvée.
# - `requires_group` : la liste minimale de dimensions obligatoires
#   pour que la mesure soit sémantiquement correcte (vide = libre).
# ---------------------------------------------------------------------------

MEASURES: dict[str, dict[str, Any]] = {
    "count": {
        "sql": "COUNT(*)",
        "unit": "occurrences",
        "conversion_3gpp": "aucune (comptage brut)",
        "lineage": None,  # applicable à tout dataset
        "null_safe": True,
        "recomposable": True,  # somme de sous-counts = count total
    },
    "part_pct": {
        "sql": "100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0)",
        "unit": "%",
        "conversion_3gpp": "aucune (part relative dans le dénominateur affiché)",
        "lineage": None,
        "null_safe": True,
        "recomposable": False,  # dépend du dénominateur
        "note": "Toujours affichée avec son dénominateur (n total).",
    },
    # --- RSRP ---
    "rsrp_avg": {
        "sql": "AVG(rsrp)",
        "unit": "dBm",
        "conversion_3gpp": "aucune (RSRP est déjà en dBm côté measurement_points)",
        "lineage": "measurements",
        "null_safe": True,
        "recomposable": False,  # moyenne non pondérée invalide — doit se recalculer sur observations
    },
    "rsrp_p10": {"sql": "percentile_cont(0.10) WITHIN GROUP (ORDER BY rsrp)", "unit": "dBm", "conversion_3gpp": "aucune", "lineage": "measurements", "null_safe": True, "recomposable": False},
    "rsrp_p50": {"sql": "percentile_cont(0.50) WITHIN GROUP (ORDER BY rsrp)", "unit": "dBm", "conversion_3gpp": "aucune", "lineage": "measurements", "null_safe": True, "recomposable": False},
    "rsrp_p90": {"sql": "percentile_cont(0.90) WITHIN GROUP (ORDER BY rsrp)", "unit": "dBm", "conversion_3gpp": "aucune", "lineage": "measurements", "null_safe": True, "recomposable": False},
    "rsrq_avg": {"sql": "AVG(rsrq)", "unit": "dB", "conversion_3gpp": "aucune", "lineage": "measurements", "null_safe": True, "recomposable": False},
    "sinr_avg": {"sql": "AVG(sinr)", "unit": "dB", "conversion_3gpp": "aucune", "lineage": "measurements", "null_safe": True, "recomposable": False},
    "cqi_avg": {"sql": "AVG(cqi)", "unit": "indice 0..15", "conversion_3gpp": "aucune (indice CQI 3GPP)", "lineage": "measurements", "null_safe": True, "recomposable": False},
    "dl_avg": {"sql": "AVG(dl)", "unit": "Mbit/s", "conversion_3gpp": "la colonne `dl` est en Mbit/s si Phase 1 l'a renseignée ; NULL sinon", "lineage": "measurements", "null_safe": True, "recomposable": False},
    "dl_p50": {"sql": "percentile_cont(0.50) WITHIN GROUP (ORDER BY dl)", "unit": "Mbit/s", "conversion_3gpp": "aucune", "lineage": "measurements", "null_safe": True, "recomposable": False},
    "thrpt_ul_avg": {"sql": "AVG(thrpt_ul)", "unit": "Mbit/s", "conversion_3gpp": "Phase 1 pending", "lineage": "measurements", "null_safe": True, "recomposable": False},
    "tx_power_avg": {"sql": "AVG(tx_power)", "unit": "dBm", "conversion_3gpp": "Phase 1 pending", "lineage": "measurements", "null_safe": True, "recomposable": False},
    "latency_avg": {"sql": "AVG(latency)", "unit": "ms", "conversion_3gpp": "aucune", "lineage": "measurements", "null_safe": True, "recomposable": False},
}


# ---------------------------------------------------------------------------
# Opérations de filtre autorisées
# ---------------------------------------------------------------------------

FILTER_OPS = {
    "eq": ("=", 1),           # column = value
    "in": ("IN", "list"),     # column IN (:v1, :v2, …)
    "contains": ("LIKE", 1),  # column LIKE %value% (texte libre dim seulement)
    "is_null": ("IS NULL", 0),
    "is_not_null": ("IS NOT NULL", 0),
}


# ---------------------------------------------------------------------------
# Tables / colonnes / fonctions explicitement BANNIES
# ---------------------------------------------------------------------------
# Un plan compilé qui ferait référence à ces identifiants (même par
# ricochet d'un dataset-sélecteur futur) est rejeté avant exécution.
# Le mot est cherché dans le SQL FINAL compilé (défense en profondeur).
# ---------------------------------------------------------------------------

BANNED_IDENTIFIERS = {
    # tables sensibles — identité, authent, secrets
    "app_user", "users", "settings_llm", "nmf_file",
    # fonctions pouvant exécuter du code / modifier l'état
    "pg_sleep", "pg_read_file", "pg_ls_dir", "pg_terminate_backend",
    "copy", "lo_import", "lo_export", "lo_open",
    "truncate", "drop", "alter", "create", "grant", "revoke",
    "insert", "update", "delete",
    # identités abonné potentiellement présentes dans un payload non-mappé
    "imsi", "imei", "imeisv", "msisdn", "s_tmsi", "c_rnti", "guti", "ptmsi", "tmsi",
}


# ---------------------------------------------------------------------------
# Schéma public (`discover_schema`)
# ---------------------------------------------------------------------------
# Payload JSON que l'agent LLM reçoit comme contexte. Ne contient AUCUN
# nom de table réel, AUCUN SQL. Juste la grammaire autorisée.
# ---------------------------------------------------------------------------


Verdict = Literal["COMPARABLE", "COMPARABLE_WITH_LIMITATIONS", "NOT_COMPARABLE"]


def discover_schema() -> dict[str, Any]:
    """Grammaire autorisée pour un plan. Ne fuit AUCUN identifiant SQL."""
    return {
        "version": "0.25.0",
        "datasets": {
            name: {
                "description": d["description"],
                "project_scoped": d["project_scoped"],
                "dimensions": sorted(d["dimensions"]),
                "measures": sorted(d["measures"]),
            }
            for name, d in DATASETS.items()
        },
        "dimensions": {
            name: {
                "description": d["description"],
                "null_label": d["null_label"],
                "allowed_filter_ops": list(d["allowed_filter_ops"]),
            }
            for name, d in DIMENSIONS.items()
        },
        "measures": {
            name: {
                "unit": m["unit"],
                "conversion_3gpp": m["conversion_3gpp"],
                "recomposable": m["recomposable"],
                "note": m.get("note", ""),
            }
            for name, m in MEASURES.items()
        },
        "filter_ops": list(FILTER_OPS.keys()),
        "guarantees": [
            "project_id injecté côté serveur depuis la session — ignoré du plan.",
            "GROUP BY implicite si des mesures sont présentes (jamais de ligne brute).",
            "LIMIT max 1000 par plan.",
            "null → N/D rendu via COALESCE au SELECT, jamais 0.",
            "Mesures 'recomposable=False' refusent la recomposition multi-niveaux.",
            "Tables sensibles (app_user, settings_llm, nmf_file) jamais accessibles.",
        ],
    }
