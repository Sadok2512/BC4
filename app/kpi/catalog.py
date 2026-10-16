"""Catalogue KPI versionné (0.35.0).

Chaque KPI porte : `code`, `name`, `family`, `techno`, `nature`
(distribution | count | rate), `unit`, `source` (métrique canonique
ou dataset), `formula`, `definition`, `available_check` (règle de
calcul du statut par projet, pas une valeur).

Règles de statut (correctif de la spec) :
- `nature=distribution` ou `count` adossée à `param_occurrence` →
  AVAILABLE ssi des lignes correspondent au `path`/`message` pour ce
  projet, sinon UNAVAILABLE(raison).
- `nature=distribution` adossée à `measurement_points` → AVAILABLE
  ssi la colonne métrique est non-NULL sur ≥ 1 ligne du projet,
  sinon PENDING(raison : mapping Phase 1 non prouvé).
- `nature=rate` → **UNVALIDATED** fixe. Jamais calculé : le contrat
  (tentative, réussite, échec) n'est pas certifié par le décodeur. Un
  rate honnête se refuse plutôt qu'il ne s'invente.
- Pas de source du tout (SMS, EN-DC sans event mesure NR) → UNAVAILABLE
  avec raison explicite.

Discipline : aucune ligne ici ne fabrique une valeur. Le statut est
calculé à la lecture ; la valeur est calculée par `service.compute_kpi`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Version du catalogue — bumpée à chaque PR qui ajoute/retire/modifie un
# KPI ou une règle de statut. Exposée via /kpi/catalog pour tracer le lot.
KPI_CATALOG_VERSION = "0.35.0"

Nature = Literal["distribution", "count", "rate"]
Status = Literal["AVAILABLE", "PENDING", "UNVALIDATED", "UNAVAILABLE"]


@dataclass(frozen=True)
class KpiDef:
    """Définition statique d'un KPI. Immuable, lu-seul."""

    code: str
    name: str
    family: str
    techno: str                 # "LTE" | "NR" | "LTE/NR" | "Voix" | "Toutes"
    nature: Nature
    unit: str
    source: str                 # texte court — table / event canonique
    formula: str                # formule human-readable (pour UI "voir sources")
    definition: str             # une ligne, pour tooltip
    # Rule de disponibilité ; interprétée par `service.compute_status` :
    #   "param_path"          → regarde param_occurrence.path (eq|ilike)
    #   "param_message"       → regarde param_occurrence.message (eq)
    #   "mp_metric"           → regarde measurement_points.<col> IS NOT NULL
    #   "always_unvalidated"  → statut forcé UNVALIDATED (rate non certifié)
    #   "always_unavailable"  → statut forcé UNAVAILABLE (aucune source)
    availability: str
    # Argument pour la règle (nom du path / message / colonne). Peut être
    # une liste séparée par `|` pour un ILIKE à alternatives.
    availability_arg: str | None = None
    # Opérateur SQL pour la règle `param_path` : "eq" (défaut) ou "ilike".
    availability_op: str = "eq"
    # Raison lisible quand UNAVAILABLE / UNVALIDATED par construction.
    unavailable_reason: str | None = None


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
# Ordre d'affichage des familles côté UI.
FAMILIES_ORDER: tuple[str, ...] = (
    "Accessibilité",
    "Rétention",
    "Mobilité",
    "Débit",
    "Qualité radio",
    "Voix",
    "NR/EN-DC",
)


CATALOG: tuple[KpiDef, ...] = (
    # -------- Accessibilité --------
    KpiDef(
        code="RRC_SETUP_COUNT",
        name="RRC Connection Setup — volume",
        family="Accessibilité",
        techno="LTE/NR",
        nature="count",
        unit="occurrences",
        source="param_occurrence (message=RRCConnectionSetup)",
        formula="COUNT(DISTINCT stg_event_id) WHERE message = 'RRCConnectionSetup'",
        definition="Nombre d'événements RRC Connection Setup décodés.",
        availability="param_message",
        availability_arg="RRCConnectionSetup",
    ),
    KpiDef(
        code="RRC_SETUP_SR",
        name="RRC Setup Success Rate",
        family="Accessibilité",
        techno="LTE/NR",
        nature="rate",
        unit="%",
        source="(indisponible)",
        formula="succès / (succès + échecs)",
        definition="Taux de succès RRC Setup — refusé tant que la paire tentative/réussite n'est pas certifiée.",
        availability="always_unvalidated",
        unavailable_reason="contrat tentative/réussite non certifié par le décodeur (jamais inventé)",
    ),
    KpiDef(
        code="RRC_SETUP_TIME",
        name="RRC Setup Time",
        family="Accessibilité",
        techno="LTE/NR",
        nature="distribution",
        unit="ms",
        source="(indisponible)",
        formula="Δt(request → complete) par capture",
        definition="Distribution du délai RRC Setup — refusée tant que les deux bornes temporelles ne sont pas prouvées.",
        availability="always_unvalidated",
        unavailable_reason="paire request/complete non certifiée côté décodeur",
    ),

    # -------- Rétention --------
    KpiDef(
        code="RRC_REEST_COUNT",
        name="RRC Reestablishment — volume",
        family="Rétention",
        techno="LTE/NR",
        nature="count",
        unit="occurrences",
        source="param_occurrence (message=RRCConnectionReestablishment%)",
        formula="COUNT(DISTINCT stg_event_id) WHERE message ILIKE 'RRCConnectionReestablishment%'",
        definition="Nombre d'événements RRC Reestablishment décodés (toutes variantes).",
        availability="param_message_ilike",
        availability_arg="RRCConnectionReestablishment%",
    ),
    KpiDef(
        code="DROP_CALL_RATE",
        name="Drop Call Rate",
        family="Rétention",
        techno="Voix",
        nature="rate",
        unit="%",
        source="(indisponible)",
        formula="drops / appels établis",
        definition="Taux de drop sur appels voix — refusé tant que la détection de drop n'est pas certifiée.",
        availability="always_unvalidated",
        unavailable_reason="détection drop/complétion non certifiée",
    ),
    KpiDef(
        code="RRC_ABNORMAL_RELEASE",
        name="RRC Abnormal Release",
        family="Rétention",
        techno="LTE/NR",
        nature="rate",
        unit="%",
        source="(indisponible)",
        formula="releases anormaux / releases totaux",
        definition="Part des releases RRC anormaux — refusé tant que la typologie release n'est pas certifiée.",
        availability="always_unvalidated",
        unavailable_reason="typologie release (normal/abnormal) non certifiée",
    ),

    # -------- Mobilité --------
    KpiDef(
        code="HO_COUNT",
        name="Handover — volume",
        family="Mobilité",
        techno="LTE/NR",
        nature="count",
        unit="occurrences",
        source="param_occurrence (path contient mobilityControlInfo)",
        formula="COUNT(DISTINCT stg_event_id) WHERE path ILIKE '%mobilityControlInfo%'",
        definition="Nombre d'événements porteurs d'un IE mobilityControlInfo (preuve d'ordre de HO).",
        availability="param_path",
        availability_arg="%mobilityControlInfo%",
        availability_op="ilike",
    ),
    KpiDef(
        code="HO_SR",
        name="Handover Success Rate",
        family="Mobilité",
        techno="LTE/NR",
        nature="rate",
        unit="%",
        source="(indisponible)",
        formula="HO complete / HO command",
        definition="Taux de succès HO — refusé tant que la paire command/complete n'est pas certifiée.",
        availability="always_unvalidated",
        unavailable_reason="paire command/complete non certifiée",
    ),
    KpiDef(
        code="A3_OFFSET_DIST",
        name="A3 Offset — distribution",
        family="Mobilité",
        techno="LTE",
        nature="distribution",
        unit="dB",
        source="param_occurrence (path contient a3-Offset)",
        formula="value_converted (valeur ASN.1 × 0.5 dB, TS 36.331)",
        definition="Distribution de l'offset A3 configuré (demi-dB côté ASN.1).",
        availability="param_path",
        availability_arg="%a3-Offset%",
        availability_op="ilike",
    ),
    KpiDef(
        code="THRESHOLD_RSRP_BY_EVENT",
        name="Threshold RSRP by event",
        family="Mobilité",
        techno="LTE",
        nature="distribution",
        unit="dBm",
        source="param_occurrence (path contient threshold%RSRP, dim=event)",
        formula="value_converted (idx - 140 dBm) regroupé par type d'event (A1/A2/B1…)",
        definition="Seuil RSRP configuré par type d'événement de mesure.",
        availability="param_path",
        availability_arg="%threshold%RSRP%",
        availability_op="ilike",
    ),
    KpiDef(
        code="HYSTERESIS_DIST",
        name="Hysteresis — distribution",
        family="Mobilité",
        techno="LTE/NR",
        nature="distribution",
        unit="dB",
        source="param_occurrence (path contient hysteresis)",
        formula="value_converted (ASN.1 × 0.5 dB)",
        definition="Distribution de l'hystérésis configurée sur les events de mesure.",
        availability="param_path",
        availability_arg="%hysteresis%",
        availability_op="ilike",
    ),
    KpiDef(
        code="TTT_DIST",
        name="Time To Trigger — distribution",
        family="Mobilité",
        techno="LTE/NR",
        nature="distribution",
        unit="ms",
        source="param_occurrence (path contient timeToTrigger)",
        formula="value_converted (enum TS 36.331 → ms)",
        definition="Distribution du timeToTrigger configuré.",
        availability="param_path",
        availability_arg="%timeToTrigger%",
        availability_op="ilike",
    ),

    # -------- Débit --------
    KpiDef(
        code="THR_DL_APP",
        name="Throughput DL (app)",
        family="Débit",
        techno="LTE/NR",
        nature="distribution",
        unit="Mbit/s",
        source="measurement_points.dl (reconstruit 8 × octets DSUMMARY / Δt)",
        formula="8 × octets(DSUMMARY) / Δt → percentile_cont(0.50)",
        definition="Débit descendant applicatif, Mbit/s.",
        availability="mp_metric",
        availability_arg="dl",
        unavailable_reason="measurement_points.dl NULL — mapping Phase 1 non prouvé",
    ),
    KpiDef(
        code="THR_UL",
        name="Throughput UL (app)",
        family="Débit",
        techno="LTE/NR",
        nature="distribution",
        unit="Mbit/s",
        source="measurement_points.thrpt_ul",
        formula="percentile_cont(0.50) WITHIN GROUP (ORDER BY thrpt_ul)",
        definition="Débit montant applicatif, Mbit/s.",
        availability="mp_metric",
        availability_arg="thrpt_ul",
        unavailable_reason="measurement_points.thrpt_ul NULL — mapping Phase 1 non prouvé",
    ),
    KpiDef(
        code="THR_MAC_RLC_PDCP",
        name="Throughput MAC/RLC/PDCP",
        family="Débit",
        techno="LTE/NR",
        nature="distribution",
        unit="Mbit/s",
        source="(champ Nemo à prouver)",
        formula="à définir après mapping Phase 2 (field Nemo prouvé)",
        definition="Débits de couche L2/L3 — en attente de preuve du champ Nemo correspondant.",
        availability="always_unavailable",
        unavailable_reason="aucun champ measurement_points mappé pour MAC/RLC/PDCP",
    ),
    KpiDef(
        code="THR_PCTL",
        name="Throughput — P10/P50/P90",
        family="Débit",
        techno="LTE/NR",
        nature="distribution",
        unit="Mbit/s",
        source="measurement_points.dl (percentiles)",
        formula="percentile_cont(0.10|0.50|0.90) WITHIN GROUP (ORDER BY dl)",
        definition="Percentiles de débit DL — même source que THR_DL_APP, trois percentiles.",
        availability="mp_metric",
        availability_arg="dl",
        unavailable_reason="measurement_points.dl NULL — mapping Phase 1 non prouvé",
    ),

    # -------- Qualité radio --------
    KpiDef(
        code="RSRP_DIST",
        name="RSRP — distribution",
        family="Qualité radio",
        techno="LTE",
        nature="distribution",
        unit="dBm",
        source="param_occurrence.measResultPCell/rsrpResult (RRC MeasurementReport, idx - 141 dBm)",
        formula="percentile_cont sur value_converted des param_occurrence (serving PCell)",
        definition=(
            "Distribution RSRP servant (dBm) décodée depuis les MeasurementReport "
            "RRC — source authoritative. Le mapping vers measurement_points.rsrp "
            "(candidat CELLMEAS) reste gaté par preuve ±2 dB ; non prouvé = NULL."
        ),
        availability="param_path",
        availability_arg="%measResultPCell/rsrpResult",
        availability_op="ilike",
    ),
    KpiDef(
        code="RSRQ_DIST",
        name="RSRQ — distribution",
        family="Qualité radio",
        techno="LTE",
        nature="distribution",
        unit="dB",
        source="param_occurrence.measResultPCell/rsrqResult (RRC MeasurementReport, idx/2 - 20 dB)",
        formula="percentile_cont sur value_converted des param_occurrence (serving PCell)",
        definition="Distribution RSRQ servant (dB) décodée depuis MeasurementReport RRC.",
        availability="param_path",
        availability_arg="%measResultPCell/rsrqResult",
        availability_op="ilike",
    ),
    KpiDef(
        code="SINR_DIST",
        name="SINR — distribution",
        family="Qualité radio",
        techno="LTE/NR",
        nature="distribution",
        unit="dB",
        source="measurement_points.sinr (preuve ±2 dB vs rs-sinr-r13)",
        formula="percentile_cont(0.10|0.50|0.90) WITHIN GROUP (ORDER BY sinr)",
        definition=(
            "Distribution SINR (dB). rs-sinr-r13 est LTE-A non peuplé "
            "systématiquement — reste PENDING tant que la preuve ±2 dB "
            "n'aboutit pas pour le projet."
        ),
        availability="mp_metric",
        availability_arg="sinr",
        unavailable_reason="measurement_points.sinr NULL — rs-sinr-r13 absent du corpus / preuve non aboutie",
    ),
    KpiDef(
        code="CQI_DIST",
        name="CQI — distribution",
        family="Qualité radio",
        techno="LTE/NR",
        nature="distribution",
        unit="indice 0..15",
        source="measurement_points.cqi (preuve ±2 dB vs cqi-Report)",
        formula="percentile_cont(0.10|0.50|0.90) WITHIN GROUP (ORDER BY cqi)",
        definition=(
            "Distribution CQI (indice 3GPP). Pas de référence RRC chiffrée "
            "comparable sur le corpus LTE Rel-8 — reste PENDING tant que la "
            "preuve n'aboutit pas."
        ),
        availability="mp_metric",
        availability_arg="cqi",
        unavailable_reason="measurement_points.cqi NULL — pas de référence RRC chiffrée pour preuve ±2 dB",
    ),
    KpiDef(
        code="TXPOWER_DIST",
        name="UE TX Power — distribution",
        family="Qualité radio",
        techno="LTE/NR",
        nature="distribution",
        unit="dBm",
        source="measurement_points.tx_power",
        formula="percentile_cont(0.10|0.50|0.90) WITHIN GROUP (ORDER BY tx_power)",
        definition="Distribution de la puissance d'émission UE (dBm).",
        availability="mp_metric",
        availability_arg="tx_power",
        unavailable_reason="measurement_points.tx_power NULL",
    ),

    # -------- Voix --------
    KpiDef(
        code="CALL_SETUP_SR",
        name="Call Setup Success Rate",
        family="Voix",
        techno="Voix",
        nature="rate",
        unit="%",
        source="(indisponible)",
        formula="appels établis / appels tentés",
        definition="Taux de succès d'établissement d'appel — contrat tentative/succès non certifié.",
        availability="always_unvalidated",
        unavailable_reason="contrat tentative/réussite non certifié",
    ),
    KpiDef(
        code="CALL_SETUP_TIME",
        name="Call Setup Time",
        family="Voix",
        techno="Voix",
        nature="distribution",
        unit="s",
        source="(indisponible)",
        formula="Δt(request → active)",
        definition="Délai d'établissement d'appel — bornes non certifiées.",
        availability="always_unvalidated",
        unavailable_reason="bornes request/active non certifiées",
    ),
    KpiDef(
        code="CALL_DROP_RATE",
        name="Call Drop Rate",
        family="Voix",
        techno="Voix",
        nature="rate",
        unit="%",
        source="(indisponible)",
        formula="drops / appels établis",
        definition="Taux de drop appel voix — refusé tant que drop vs release normal n'est pas distingué.",
        availability="always_unvalidated",
        unavailable_reason="distinction drop/release non certifiée",
    ),
    KpiDef(
        code="SMS_SR",
        name="SMS Success Rate",
        family="Voix",
        techno="Voix",
        nature="rate",
        unit="%",
        source="(aucun event SMS cartographié)",
        formula="SMS envoyés / SMS tentés",
        definition="Taux de succès SMS — aucun event cartographié dans la chaîne.",
        availability="always_unavailable",
        unavailable_reason="aucun event SMS dans le décodeur / measurement_points",
    ),

    # -------- NR / EN-DC --------
    KpiDef(
        code="SS_RSRP_DIST",
        name="SS-RSRP — distribution (NR)",
        family="NR/EN-DC",
        techno="NR",
        nature="distribution",
        unit="dBm",
        source="(aucun event mesure NR mappé vers measurement_points)",
        formula="percentile_cont(0.10|0.50|0.90) WITHIN GROUP (ORDER BY rsrp WHERE tech='NR')",
        definition="Distribution SS-RSRP NR — en attente d'un event mesure NR mappé.",
        availability="always_unavailable",
        unavailable_reason="aucun event mesure NR cartographié vers measurement_points",
    ),
    KpiDef(
        code="ENDC_SCG_ADD",
        name="EN-DC SCG addition — volume",
        family="NR/EN-DC",
        techno="NR",
        nature="count",
        unit="occurrences",
        source="(aucun event EN-DC cartographié)",
        formula="COUNT(DISTINCT stg_event_id) WHERE message ILIKE '%SCG%ADD%'",
        definition="Volume d'ajouts SCG EN-DC — aucun event cartographié.",
        availability="always_unavailable",
        unavailable_reason="aucun event EN-DC SCG dans le décodeur",
    ),
)


KPI_BY_CODE: dict[str, KpiDef] = {k.code: k for k in CATALOG}


# ---------------------------------------------------------------------------
# Garde-fou catalogue : chaque family listée doit exister dans FAMILIES_ORDER.
# ---------------------------------------------------------------------------

_declared_families = {k.family for k in CATALOG}
_missing = _declared_families - set(FAMILIES_ORDER)
if _missing:
    raise RuntimeError(
        f"KPI catalog : familles non listées dans FAMILIES_ORDER : {_missing}"
    )
