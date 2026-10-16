"""Importer offline — xlsx utilisateur → ``app/kpi/catalog_v2.json`` (0.40.0).

Source autoritaire : ``catalog/BC4_Catalogue_KPI_LTE_NR_ENDC_Agreges.xlsx``.
Feuille ``Catalogue KPI``, 4 colonnes : ``KPI code | KPI name | Techno |
Catégorie``. 208 entrées.

Discipline :
- Nettoyage **tracé** dans le JSON généré :
    - normalisation du préfixe ``EN-DC_`` → ``ENDC_`` (reporté dans
      ``normalizations``).
    - dédoublons déterministes (ex. ``LTE_RRC_SETUP_SR`` ≡ ``LTE_RRC_SR``)
      réduits à UN enregistrement canonique + une liste d'``aliases``.
- Checksum SHA-256 du xlsx reporté dans le JSON (``source_xlsx_sha256``).
- Un code hors de la grammaire 3GPP (``*_SR`` sans frères, Nature inconnue,
  Famille vide…) → **ne provoque PAS d'exception** : il est inséré avec
  ``available_check.kind = "always_unavailable"`` et une ``reason``
  explicite. L'écart est **déclaré**, jamais inventé.
- Les enrichissements (``formula / source / unit / available_check /
  service_scope``) sont calculés par règles mécaniques sur le code et
  la nature. Toute règle non prouvée côté décodeur retombe sur
  ``PENDING`` (métrique mesurée) ou ``UNVALIDATED`` (rate) — jamais
  AVAILABLE spéculatif.

Lancer en local :

    python scripts/import_kpi_catalog_v2.py \
        --xlsx /home/devmat/BC4/catalog/BC4_Catalogue_KPI_LTE_NR_ENDC_Agreges.xlsx \
        --out /home/devmat/BC4/bc4-back/app/kpi/catalog_v2.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Dédoublons connus (xlsx 2026-10-16 — 208 entrées).
#
# Chaque entrée : ``canonical`` conservé, ``alias`` listé dans
# ``canonical.aliases``. On garde l'identité LTE/NR/ENDC du canonical ;
# un alias **n'est pas une entrée** du catalogue public (le loader ne
# l'expose pas comme KPI distinct, il le résout vers le canonical).
# ---------------------------------------------------------------------------

_ALIAS_RULES: list[tuple[str, str]] = [
    # (alias, canonical)
    # RRC Setup Success Rate : la version courte et la version longue
    # ont strictement le même "KPI name" dans le xlsx.
    ("LTE_RRC_SR",                      "LTE_RRC_SETUP_SR"),
    ("NR_RRC_SR",                       "NR_RRC_SETUP_SR"),
    # RACH Success Rate : courte vs explicite.
    ("LTE_RACH_SR",                     "LTE_RACH_ACCESS_SR"),
    ("NR_RACH_SR",                      "NR_RACH_ACCESS_SR"),
    # Handover SR : variantes HO_* vs *_HANDOVER_* (même sémantique).
    ("LTE_INTRA_FREQUENCY_HANDOVER_SR", "LTE_HO_INTRA_SR"),
    ("LTE_INTER_FREQUENCY_HANDOVER_SR", "LTE_HO_INTER_SR"),
    ("LTE_INTER_RAT_HANDOVER_SR",       "LTE_HO_IRAT_SR"),
    ("NR_INTRA_FREQUENCY_HANDOVER_SR",  "NR_HO_INTRA_SR"),
    ("NR_INTER_FREQUENCY_HANDOVER_SR",  "NR_HO_INTER_SR"),
    ("NR_INTER_RAT_HANDOVER_SR",        "NR_HO_IRAT_SR"),
    # HTTP DL/UL Transfer SR vs DL/UL Data SR — doublon fonctionnel
    # (même KPI, deux dénominations). On garde la forme HTTP (plus
    # proche du contrat Nemo DSUMMARY).
    ("LTE_DL_DATA_SR",                  "LTE_HTTP_DL_TRANSFER_SR"),
    ("LTE_UL_DATA_SR",                  "LTE_HTTP_UL_TRANSFER_SR"),
    ("NR_DL_DATA_SR",                   "NR_HTTP_DL_TRANSFER_SR"),
    ("NR_UL_DATA_SR",                   "NR_HTTP_UL_TRANSFER_SR"),
]

ALIAS_MAP = {alias: canon for alias, canon in _ALIAS_RULES}


# ---------------------------------------------------------------------------
# Normalisation de code (traçage dans ``normalizations``).
# ---------------------------------------------------------------------------


def _normalize_code(raw: str) -> tuple[str, str | None]:
    """Retourne ``(canonical_code, note)`` où ``note`` est non vide si
    une transformation a été appliquée."""
    if not raw:
        return "", "code vide (ligne ignorée)"
    code = str(raw).strip()
    if code.startswith("EN-DC_"):
        return "ENDC_" + code[len("EN-DC_"):], f"'EN-DC_' → 'ENDC_' ({code})"
    if code.startswith("EN-DC"):
        # Ex. "EN-DC_LAT_HTTP_RESPONSE" déjà couvert ci-dessus. Sinon
        # on normalise la partie techno en 'ENDC'.
        return "ENDC" + code[len("EN-DC"):], f"'EN-DC' → 'ENDC' ({code})"
    return code, None


# ---------------------------------------------------------------------------
# Techno (déclaré dans la colonne Techno ; les alias EN-DC héritent).
# ---------------------------------------------------------------------------

_TECHNO_MAP = {
    "LTE": "LTE",
    "NR": "NR",
    "EN-DC": "ENDC",
    "ENDC": "ENDC",
    "Agrégé": "AGGREGATE",
}


# ---------------------------------------------------------------------------
# Service scope.
# ---------------------------------------------------------------------------

_SERVICE_DATA = ("HTTP_DOWNLOAD", "HTTP_UPLOAD")
_SERVICE_VOICE = ("VOICE",)
_SERVICE_ALL: tuple[str, ...] = ()  # tuple vide = applicable à tous les services

# Familles → service scope.
_FAMILY_SCOPE = {
    "DL": _SERVICE_DATA,
    "UL": _SERVICE_DATA,
    "Débit applicatif": _SERVICE_DATA,
    "DMS DL": _SERVICE_DATA,
    "DMS UL": _SERVICE_DATA,
    "Latence": _SERVICE_DATA,
    "Data": _SERVICE_DATA,
    "Sessions": _SERVICE_DATA,
    "Bearers": _SERVICE_DATA,
    "Voix": _SERVICE_VOICE,
    # Les familles ci-dessous sont transverses (couverture / mobilité /
    # qualité radio) et s'évaluent quel que soit le service actif.
    "Qualité radio": _SERVICE_ALL,
    "Mobilité": _SERVICE_ALL,
    "Rétention": _SERVICE_ALL,
    "Accessibilité": _SERVICE_ALL,
    "Carrier Aggregation": _SERVICE_ALL,
    "MIMO": _SERVICE_ALL,
    "SCG": _SERVICE_ALL,
    "Usage": _SERVICE_ALL,
}


# ---------------------------------------------------------------------------
# Enrichissement par code.
# ---------------------------------------------------------------------------


# Compteurs RRC prouvés par le décodeur 2.0.0 (events signalling décodés
# dans `stg_event.message`).
_RRC_MESSAGE_BY_CODE_SUFFIX = {
    # Setup
    "RRC_ATTEMPTS":       "RRCConnectionRequest",
    "RRC_SUCCESS":        "RRCConnectionSetupComplete",
    "RRC_FAILURES":       None,  # pas d'event de rejet prouvé — UNAVAILABLE
    "RRC_SETUP_COUNT":    "RRCConnectionSetup",
    # Reestablishment
    "RRC_REEST_ATTEMPTS": "RRCConnectionReestablishmentRequest",
    "RRC_REEST_SUCCESS":  "RRCConnectionReestablishmentComplete",
    "RRC_REEST_FAILURES": None,  # rejet non prouvé
    "RRC_REEST_COUNT":    "RRCConnectionReestablishment",
    # Reconfiguration (mobilityControlInfo = handover)
    "HO_COUNT":           None,  # géré via `path_contains` ci-dessous
}

# Compteurs *autres* : events dont la position/sémantique n'est pas prouvée
# par le décodeur 2.0.0. On déclare UNAVAILABLE avec raison plutôt que
# d'inventer un mapping.
_COUNT_UNPROVEN = {
    # RACH : stg_event_raw.category=cmdreq ne porte pas d'identificateur
    # "attempt/success/failure" prouvé.
    "RACH_ATTEMPTS", "RACH_SUCCESS", "RACH_FAILURES",
    # E-RAB : pas d'event bearer dans le décodeur 2.0.0.
    "ERAB_ATTEMPTS", "ERAB_SUCCESS", "ERAB_FAILURES",
    # Data transfer : DAA/DREQ/DCOMP positions non prouvées (écart 0.24.0).
    "DL_DATA_ATTEMPTS", "DL_DATA_SUCCESS", "DL_DATA_FAILURES",
    "UL_DATA_ATTEMPTS", "UL_DATA_SUCCESS", "UL_DATA_FAILURES",
    # HO par type (intra/inter/irat) : le décodeur a un COUNT global via
    # mobilityControlInfo mais pas de distinction intra/inter/irat prouvée.
    "HO_INTRA_ATTEMPTS", "HO_INTRA_SUCCESS", "HO_INTRA_FAILURES",
    "HO_INTER_ATTEMPTS", "HO_INTER_SUCCESS", "HO_INTER_FAILURES",
    "HO_IRAT_ATTEMPTS",  "HO_IRAT_SUCCESS",  "HO_IRAT_FAILURES",
}


# Mesures radio adossées à `measurement_points`. Clé = suffixe EXACT du
# code (dans le xlsx, les codes radio sont ``*_RF_SINR / *_RF_CQI /
# *_RF_RSSI`` — pas ``SINR`` nu). Valeur = (colonne mp, source, unité).
_MP_METRIC_BY_SUFFIX = {
    "RF_SINR":           ("sinr",     "measurement_points.sinr",     "dB"),
    "RF_CQI":            ("cqi",      "measurement_points.cqi",      "indice"),
    "RF_RSSI":           ("rssi",     "measurement_points.rssi",     "dBm"),
    "UE_TX_POWER":       ("tx_power", "measurement_points.tx_power", "dBm"),
    "DL_APPLICATION_THR": ("dl",       "measurement_points.dl",       "Mbit/s"),
    "UL_APPLICATION_THR": ("thrpt_ul", "measurement_points.thrpt_ul", "Mbit/s"),
    "DL_HTTP_THR":        ("dl",       "measurement_points.dl",       "Mbit/s"),
    "UL_HTTP_THR":        ("thrpt_ul", "measurement_points.thrpt_ul", "Mbit/s"),
}

# Mesures radio adossées à `param_occurrence` (RRC autoritaire) — 0.37.1
# a câblé RSRP/RSRQ sur `measResultPCell`.
_RRC_MEAS_BY_SUFFIX = {
    "RF_RSRP": {
        "path_pattern": "%measResultPCell/rsrpResult",
        "message":      "MeasurementReport",
        "unit":          "dBm",
        "convert":       "idx − 141 dBm (3GPP TS 36.133 §9.1.4)",
    },
    "RF_RSRQ": {
        "path_pattern": "%measResultPCell/rsrqResult",
        "message":      "MeasurementReport",
        "unit":          "dB",
        "convert":       "(idx / 2) − 20 dB (3GPP TS 36.133 §9.1.7)",
    },
}


# Latences — colonnes non peuplées côté décodeur 2.0.0 (écart 0.24.0).
_LATENCY_CODES = (
    "LAT_HTTP_RESPONSE", "LAT_TRANSFER_SETUP", "LAT_RTT",
)


def _enrich(code: str, name: str, techno: str, nature: str, family: str) -> dict[str, Any]:
    """Retourne les champs enrichis pour un KPI canonique."""

    enriched: dict[str, Any] = {
        "formula":           None,
        "source":            None,
        "unit":              None,
        "available_check":   {"kind": "always_unavailable", "reason": "règle non définie"},
        "service_scope":     list(_FAMILY_SCOPE.get(family, _SERVICE_ALL)),
    }

    # Techno NR / ENDC : actuellement AUCUN NMF témoin NR / EN-DC n'a été
    # ingéré avec succès (REF = LTE pur). On refuse de simuler l'available —
    # UNAVAILABLE déclaré avec raison technologie. **Early return** : si
    # on laissait tomber dans les branches Compteur/Mesure plus bas, un
    # suffixe partagé (ex. ``RRC_ATTEMPTS``) renverrait AVAILABLE sur un
    # event LTE présent en base, ce qui serait un FAUX POSITIF NR.
    if techno in ("NR", "ENDC") and nature != "KPI calculé":
        return {
            "formula":         None,
            "source":          "(indisponible : technologie absente du corpus)",
            "unit":            None,
            "available_check": {
                "kind":   "always_unavailable",
                "reason": (
                    f"aucun NMF {techno} ingéré avec succès dans le corpus "
                    "actuel (REF = LTE uniquement)."
                ),
            },
            "service_scope":   list(_FAMILY_SCOPE.get(family, _SERVICE_ALL)),
        }

    # --- KPI calculé → UNVALIDATED tant que les frères n'ont pas de
    # contrat tentative/réussite CERTIFIÉ côté décodeur. ----------------
    if nature == "KPI calculé":
        enriched["unit"] = "%"
        enriched["formula"] = "100 × SUCCESS / ATTEMPTS (frères Compteur du catalogue)"
        enriched["source"] = "(compteurs frères — contrat non certifié)"
        enriched["available_check"] = {
            "kind": "always_unvalidated",
            "reason": (
                "le contrat tentative/réussite/échec n'est pas certifié "
                "par le décodeur 2.0.0 ; un taux n'est pas calculé "
                "tant que ses frères ne sont pas prouvés."
            ),
        }
        # Agrégés calculés : DMS (débit APP ≥ seuil).
        if code.startswith("AGG_DMS_"):
            m = re.match(r"AGG_DMS_(DL|UL)_(\d+)_MBPS", code)
            if m:
                direction = "dl" if m.group(1) == "DL" else "thrpt_ul"
                seuil = int(m.group(2))
                enriched["formula"] = (
                    f"100 × count(measurement_points.{direction} ≥ {seuil}) "
                    f"/ count(measurement_points.{direction} IS NOT NULL)"
                )
                enriched["source"] = f"measurement_points.{direction} (Mbit/s)"
                enriched["unit"] = "%"
                enriched["available_check"] = {
                    "kind": "mp_metric",
                    "arg": direction,
                    "reason_if_null": (
                        f"measurement_points.{direction} NULL partout — "
                        "mapping DSUMMARY non prouvé (écart 0.24.0, "
                        "lot 0.39.0 en cours)."
                    ),
                }
                enriched["service_scope"] = list(_SERVICE_DATA)
        return enriched

    # --- Compteur ------------------------------------------------------
    if nature == "Compteur":
        enriched["unit"] = "occurrences"
        # Code form : <TECH>_<FEATURE>_<SUFFIX>
        suffix = _suffix_from_code(code)

        if suffix == "HO_COUNT":
            enriched["source"] = "param_occurrence (path LIKE %mobilityControlInfo%)"
            enriched["formula"] = (
                "COUNT(DISTINCT stg_event_id) WHERE path LIKE "
                "'%mobilityControlInfo%'"
            )
            enriched["available_check"] = {
                "kind": "param_path_ilike",
                "arg": "%mobilityControlInfo%",
                "reason_if_absent": "aucun handover décodé dans ce projet",
            }
            return enriched

        msg = _RRC_MESSAGE_BY_CODE_SUFFIX.get(suffix)
        if msg is not None:
            enriched["source"] = f"stg_event (message={msg})"
            enriched["formula"] = (
                f"COUNT(DISTINCT stg_event.id) WHERE message = '{msg}'"
            )
            enriched["available_check"] = {
                "kind": "param_message_eq",
                "arg": msg,
                "reason_if_absent": f"aucune occurrence RRC pour message={msg!r}",
            }
            return enriched

        if suffix in _COUNT_UNPROVEN:
            enriched["source"] = "(indisponible : event / position non prouvée)"
            enriched["available_check"] = {
                "kind": "always_unavailable",
                "reason": (
                    f"compteur {suffix} non adossé à un event prouvé par "
                    "le décodeur 2.0.0 (écarts 0.24.0 / 0.33.0 : "
                    "RACH/E-RAB/DATA_* et HO par type intra/inter/irat "
                    "sans distinction certifiée)."
                ),
            }
            return enriched

        # Fallback : compteur inconnu → UNAVAILABLE déclaré.
        enriched["source"] = "(indisponible : règle non définie)"
        enriched["available_check"] = {
            "kind": "always_unavailable",
            "reason": f"compteur {code} sans règle de rattachement événementielle.",
        }
        return enriched

    # --- Métrique mesurée ---------------------------------------------
    if nature == "Métrique mesurée":
        suffix = _suffix_from_code(code)

        # RRC autoritaire (RSRP/RSRQ serving via measResultPCell).
        if suffix in _RRC_MEAS_BY_SUFFIX:
            m = _RRC_MEAS_BY_SUFFIX[suffix]
            enriched["unit"] = m["unit"]
            enriched["source"] = (
                f"param_occurrence (path LIKE {m['path_pattern']!r}, "
                f"message={m['message']!r} — RRC autoritaire, "
                f"{m['convert']})"
            )
            enriched["formula"] = (
                "percentile_cont sur CAST(value_converted AS DOUBLE PRECISION) "
                f"filtré par path LIKE {m['path_pattern']!r}"
            )
            enriched["available_check"] = {
                "kind": "param_path_ilike",
                "arg": m["path_pattern"],
                "reason_if_absent": (
                    f"aucune occurrence RRC pour path LIKE {m['path_pattern']!r}"
                ),
            }
            return enriched

        # Agrégats App Throughput — distribution tous opérateurs.
        if code in ("AGG_APP_DL_THR", "AGG_APP_UL_THR"):
            col = "dl" if code.endswith("DL_THR") else "thrpt_ul"
            enriched["unit"] = "Mbit/s"
            enriched["source"] = f"measurement_points.{col} (DSUMMARY-derived)"
            enriched["formula"] = (
                f"percentile_cont sur measurement_points.{col} (tous opérateurs)"
            )
            enriched["available_check"] = {
                "kind": "mp_metric",
                "arg": col,
                "reason_if_null": (
                    f"measurement_points.{col} NULL partout — mapping "
                    "DSUMMARY non prouvé (lot 0.39.0 en cours)."
                ),
            }
            enriched["service_scope"] = list(_SERVICE_DATA)
            return enriched

        # Agrégat latence applicative — mp.latency (non peuplée dans
        # le corpus actuel ; déclarée PENDING avec source visible, pas
        # UNAVAILABLE : la règle est bien câblée, c'est la colonne qui
        # attend le mapping DAA/DCOMP).
        if code == "AGG_APP_LATENCY":
            enriched["unit"] = "ms"
            enriched["source"] = "measurement_points.latency (DAA/DCOMP-derived)"
            enriched["formula"] = (
                "percentile_cont sur measurement_points.latency "
                "(tous opérateurs)"
            )
            enriched["available_check"] = {
                "kind": "mp_metric",
                "arg": "latency",
                "reason_if_null": (
                    "measurement_points.latency NULL partout — latence "
                    "pas encore extraite des events data_* (écart 0.24.0)."
                ),
            }
            enriched["service_scope"] = list(_SERVICE_DATA)
            return enriched

        # Latences : colonnes non peuplées.
        if suffix in _LATENCY_CODES:
            col = "latency"
            enriched["unit"] = "ms"
            enriched["source"] = f"measurement_points.{col} (si DAA/DCOMP mappés)"
            enriched["formula"] = f"percentile_cont sur measurement_points.{col}"
            enriched["available_check"] = {
                "kind": "mp_metric",
                "arg": col,
                "reason_if_null": (
                    f"measurement_points.{col} NULL partout — latence pas "
                    "encore extraite des events data_* (écart 0.24.0)."
                ),
            }
            enriched["service_scope"] = list(_SERVICE_DATA)
            return enriched

        # Autres mesures adossées à mp.
        if suffix in _MP_METRIC_BY_SUFFIX:
            col, src, unit = _MP_METRIC_BY_SUFFIX[suffix]
            enriched["unit"] = unit
            enriched["source"] = src
            enriched["formula"] = f"percentile_cont sur {src}"
            enriched["available_check"] = {
                "kind": "mp_metric",
                "arg": col,
                "reason_if_null": (
                    f"{src} NULL partout — mapping décodeur non prouvé "
                    "(écart 0.24.0 / 0.25.0, lot 0.39.0 en cours)."
                ),
            }
            # service_scope : hérité du family (DL/UL/Débit → data).
            return enriched

        # Fallback mesure : UNAVAILABLE déclaré.
        enriched["source"] = "(indisponible : règle non définie)"
        enriched["available_check"] = {
            "kind": "always_unavailable",
            "reason": (
                f"métrique mesurée {code} sans mapping prouvé côté décodeur."
            ),
        }
        return enriched

    # Fallback nature inconnue.
    return enriched


def _suffix_from_code(code: str) -> str:
    """Retire le préfixe techno (``LTE_|NR_|ENDC_``) pour obtenir le
    suffixe « sens ». Préserve le code complet pour les codes AGG_* qui
    n'ont pas de préfixe techno."""
    for prefix in ("LTE_", "NR_", "ENDC_"):
        if code.startswith(prefix):
            return code[len(prefix):]
    return code


# ---------------------------------------------------------------------------
# Chargement xlsx
# ---------------------------------------------------------------------------


def _load_xlsx(path: Path) -> list[dict[str, Any]]:
    import openpyxl  # type: ignore
    wb = openpyxl.load_workbook(str(path), data_only=True)
    if "Catalogue KPI" not in wb.sheetnames:
        raise RuntimeError(
            f"feuille 'Catalogue KPI' absente — feuilles trouvées : "
            f"{wb.sheetnames}"
        )
    ws = wb["Catalogue KPI"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=2):
        if not row or row[0] is None:
            continue
        code_raw, name, techno, categorie = row[:4]
        if not isinstance(code_raw, str) or not isinstance(name, str):
            continue
        parts = [p.strip() for p in (categorie or "").split("/")]
        nature = parts[0] if parts else ""
        family = parts[1] if len(parts) > 1 else ""
        out.append({
            "row": i,
            "code_raw":  code_raw,
            "name":      name.strip(),
            "techno":    (techno or "").strip(),
            "nature":    nature,
            "family":    family,
            "categorie": (categorie or "").strip(),
        })
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _operational_extras() -> list[dict[str, Any]]:
    """KPI opérationnels **dérivés** (hors xlsx), ajoutés après le
    catalogue xlsx. Chaque entrée est explicitement marquée
    ``source_type = "operational"`` pour la traçabilité : ils ne font
    pas partie des 208 lignes xlsx autoritaires, mais apparaissent dans
    l'arbre LTE/NR pour exposer les dimensions non-RRC du système.

    0.42.2 — Ajout de ``LTE_ECGI`` + ``NR_NCGI`` (identifiant global
    cellule). Dérivés depuis SIB1 ``cellIdentity`` + ``plmn-Identity``
    (``populate_ecgi``), peuplés sur ``measurement_points.ecgi``.
    """
    return [
        {
            "code":    "LTE_ECGI",
            "name":    "LTE ECGI — Cellules distinctes observées",
            "techno":  "LTE",
            "nature":  "Compteur",
            "family":  "Mobilité",
            "aliases": [],
            "formula": "COUNT(DISTINCT measurement_points.ecgi)",
            "source":  (
                "measurement_points.ecgi — dérivé SIB1 (PLMN + cellIdentity, "
                "3GPP TS 36.401 §6.2.1), propagé par populate_ecgi en ordre "
                "(capture_id, seq)."
            ),
            "unit":    "cellules",
            "available_check": {
                "kind": "mp_ecgi_distinct",
                "reason_if_null": (
                    "measurement_points.ecgi NULL partout — SIB1 non "
                    "décodé ou populate_ecgi pas exécuté."
                ),
            },
            "service_scope": [],
            "source_type":   "operational",
        },
        {
            "code":    "NR_NCGI",
            "name":    "NR NCGI — Cellules 5G distinctes observées",
            "techno":  "NR",
            "nature":  "Compteur",
            "family":  "Mobilité",
            "aliases": [],
            "formula": "COUNT(DISTINCT measurement_points.ecgi WHERE tech='NR')",
            "source":  (
                "measurement_points.ecgi — dérivé SIB1-NR (PLMN + NCI 36 "
                "bits, 3GPP TS 38.413 §9.3.1.7). Propagation NR non "
                "livrée tant qu'aucun NMF NR n'est ingéré."
            ),
            "unit":    "cellules",
            "available_check": {
                "kind": "always_unavailable",
                "reason": (
                    "aucun NMF NR ingéré avec succès dans le corpus "
                    "actuel (REF = LTE uniquement) ; propagation NCGI "
                    "attend un release du décodeur NR."
                ),
            },
            "service_scope": [],
            "source_type":   "operational",
        },
    ]


def build(xlsx_path: Path) -> dict[str, Any]:
    raw = _load_xlsx(xlsx_path)

    normalizations: list[str] = []
    entries_by_code: dict[str, dict[str, Any]] = {}
    aliases_report: list[dict[str, str]] = []

    for r in raw:
        code, note = _normalize_code(r["code_raw"])
        if note:
            normalizations.append(note)
        techno = _TECHNO_MAP.get(r["techno"], r["techno"]) if r["techno"] else "UNKNOWN"
        nature = r["nature"]
        family = r["family"]
        name = r["name"]

        # Alias : résolution vers canonical.
        canonical = ALIAS_MAP.get(code)
        if canonical is not None:
            aliases_report.append({
                "alias":     code,
                "canonical": canonical,
                "reason":    "même KPI, deux dénominations dans le xlsx",
            })
            # On n'instancie PAS l'alias comme KPI.
            continue

        # Insertion ou merge (si doublon exact).
        if code in entries_by_code:
            # Idempotence : si le code apparaît deux fois en xlsx strictement
            # identique, on garde la première. Sinon, on signale.
            prev = entries_by_code[code]
            if prev["name"] != name or prev["techno"] != techno:
                aliases_report.append({
                    "alias":      code,
                    "canonical":  code,
                    "reason":     f"doublon xlsx (row {r['row']}) — "
                                  f"déjà vu avec name={prev['name']!r}",
                })
            continue

        enriched = _enrich(code, name, techno, nature, family)
        entry = {
            "code":    code,
            "name":    name,
            "techno":  techno,
            "nature":  nature,
            "family":  family,
            "aliases": [],
            **enriched,
        }
        entries_by_code[code] = entry

    # Attache les alias à leur canonical (quand il existe dans le catalogue).
    for a in aliases_report:
        canon = a["canonical"]
        if canon in entries_by_code and a["alias"] != canon:
            entries_by_code[canon]["aliases"].append(a["alias"])

    # 0.42.2 — Ajout des KPI opérationnels dérivés (hors xlsx). Chaque
    # entrée porte ``source_type="operational"`` pour la traçabilité ;
    # elle apparaît dans l'arbre LTE/NR aux côtés des 208 lignes xlsx.
    operational = _operational_extras()
    for e in operational:
        entries_by_code[e["code"]] = e

    return {
        "catalog_version":      "2.0.0",
        "source_xlsx":          xlsx_path.name,
        "source_xlsx_sha256":   _sha256(xlsx_path),
        "generated_from":       "scripts/import_kpi_catalog_v2.py",
        "total_input_rows":     len(raw),
        "canonical_count":      len(entries_by_code),
        "aliases_count":        len(aliases_report),
        "operational_count":    len(operational),
        "normalizations":       normalizations,
        "aliases":              aliases_report,
        "entries":              sorted(entries_by_code.values(), key=lambda e: e["code"]),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True, type=Path)
    ap.add_argument("--out",  required=True, type=Path)
    args = ap.parse_args()

    if not args.xlsx.exists():
        print(f"xlsx introuvable : {args.xlsx}", file=sys.stderr)
        return 2

    data = build(args.xlsx)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[import_kpi_catalog_v2] wrote {args.out} "
          f"({data['canonical_count']} canonical, "
          f"{data['aliases_count']} alias, "
          f"{len(data['normalizations'])} normalisations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
