"""Enrichissement dictionnaire v2 (0.45.0).

À partir de ``(path, value, message)`` **bruts** de param_occurrence,
calcule :
- ``param_key`` : chemin canonique (CHOICE collapsé, index drops).
- ``display_name`` : dernier segment ASN.1 lisible.
- ``choice_of`` : nom du CHOICE parent si la feuille est une alt
  d'un CHOICE connu.
- ``discriminators`` : jsonb {bearer, rlc_mode, direction, event, …}.
- ``origin`` : network_config | ue_capability | ue_report.
- ``is_identifier`` : True si la feuille est une identité technique
  (exclue de la vue catalog, incluse dans raw).
- ``functional_group`` : groupe pré-calculé pour l'arbre catalog.

Discipline :
- Le path brut ``param_occurrence.path`` reste INCHANGÉ (view=raw).
- ``param_key`` est une PROJECTION calculée depuis le path, pas une
  réécriture. Les CHOICE alternatives (``/setup/``, ``/am/``,
  ``/eventA3/``, ``/measObjectEUTRA/``) sont supprimées du path
  canonique ; leurs valeurs rejoignent ``discriminators`` ou
  ``choice_of``.
- Aucun paramètre inventé : si une règle ne matche pas, ``param_key``
  = path tel quel, ``functional_group`` = ``Autres``, les autres
  colonnes restent NULL. Jamais un défaut déduit.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Origin inference depuis le message porteur
# ---------------------------------------------------------------------------

_ORIGIN_BY_MESSAGE: dict[str, str] = {
    # Network configuration : annonces et config dédiée.
    "SystemInformationBlockType1":        "network_config",
    "SystemInformation - SIB2":           "network_config",
    "SystemInformation - SIB3":           "network_config",
    "SystemInformation - SIB4":           "network_config",
    "SystemInformation - SIB5":           "network_config",
    "SystemInformation - SIB6":           "network_config",
    "SystemInformation - SIB7":           "network_config",
    "SystemInformation - SIB24":          "network_config",
    "SystemInformation - SIB2,SIB3":      "network_config",
    "SystemInformation - SIB4,SIB5":      "network_config",
    "RRCConnectionSetup":                 "network_config",
    "RRCConnectionReconfiguration":       "network_config",
    "RRCConnectionReconfigurationComplete": "network_config",  # ACK, mais config propagée
    "RRCConnectionRelease":               "network_config",
    "RRCConnectionReestablishment":       "network_config",
    "SecurityModeCommand":                "network_config",
    "UEInformationRequest":               "network_config",
    "Paging":                             "network_config",
    # UE capability : capacités déclarées par le terminal.
    "UECapabilityInformation":            "ue_capability",
    "UECapabilityEnquiry":                "ue_capability",
    "UE-NR-Capability":                   "ue_capability",
    "UE-MRDC-Capability":                 "ue_capability",
    "UE-EUTRA-Capability":                "ue_capability",
    # UE report : mesures/stats rapportées par le terminal.
    "MeasurementReport":                  "ue_report",
    "UEInformationResponse":              "ue_report",
    "MeasReportMRDC":                     "ue_report",
    "ULInformationTransferMRDC":          "ue_report",
    "SCGFailureInformationNR":            "ue_report",
    "RRCConnectionSetupComplete":         "ue_report",
}


def infer_origin(message: str | None) -> str:
    """Retourne l'``origin`` depuis le message porteur. ``network_config``
    par défaut (jamais d'invention : on choisit le défaut le plus
    conservateur — comparable entre opérateurs par défaut)."""
    if not message:
        return "network_config"
    # Match exact d'abord
    if message in _ORIGIN_BY_MESSAGE:
        return _ORIGIN_BY_MESSAGE[message]
    # Préfixe UE-*-Capability → ue_capability
    if message.startswith("UE-") and "Capability" in message:
        return "ue_capability"
    # SystemInformation* → network_config
    if message.startswith("SystemInformation"):
        return "network_config"
    return "network_config"


# ---------------------------------------------------------------------------
# Identifiants techniques (exclus de la vue catalog)
# ---------------------------------------------------------------------------

_IDENTIFIER_SUFFIXES = {
    "rrc-TransactionIdentifier",
    "measId", "measObjectId", "reportConfigId",
    "drb-Identity", "srb-Identity",
    "logicalChannelIdentity", "eps-BearerIdentity",
    "sCellIndex", "bwp-Id",
    "sk-Counter", "sk-Counter-r15",
    "newUE-Identity",
    "c-RNTI", "shortMAC-I",
    "s-TMSI", "m-TMSI", "mmec",
    "ue-Identity",
    "shortI-RNTI", "fullI-RNTI",
    "cellIndex",
    "logicalChannelGroup",
    "securityConfigHO",
    "selectedPLMN-Identity",
}


def is_identifier(last_segment: str) -> bool:
    """``True`` si le dernier segment du path est un identifiant
    technique à exclure de l'arbre Paramètres."""
    return last_segment in _IDENTIFIER_SUFFIXES


# ---------------------------------------------------------------------------
# CHOICE collapse — segments à retirer du param_key
# ---------------------------------------------------------------------------

# Segments CHOICE communs à retirer. On garde ``choice_of`` = nom du
# segment PARENT de celui qu'on retire.
_CHOICE_SEGMENTS: set[str] = {
    # Alternatives drx-Config / phr-Config / mac-MainConfig
    "setup", "release",
    # Alternatives RLC
    "am", "um-Bi-Directional", "um-Uni-Directional-UL", "um-Uni-Directional-DL",
    # Alternatives headerCompression / securityConfig
    "notUsed", "rohc",
    # Alternatives measObject (CHOICE renvoyé en discriminator)
    "measObjectEUTRA", "measObjectUTRA", "measObjectNR-r15",
    # Alternatives reportConfig
    "reportConfigEUTRA", "reportConfigInterRAT",
    # Alternatives triggerType / triggerQuantity / reportQuantity
    "event", "periodical",
    # Alternatives eventId (A1..A6, B1, B2) — gardées dans discriminators.event
    "eventA1", "eventA2", "eventA3", "eventA4", "eventA5", "eventA6",
    "eventB1", "eventB2",
    # Alternatives redirectedCarrierInfo
    "eutra", "utra-FDD", "utra-TDD", "geran", "nr-r15",
    # Alternatives CA / BWP
    "sameAsTriggerQuantity", "both",
    # cqi-FormatIndicatorPeriodic
    "widebandCQI", "subbandCQI",
    # Alternatives gpConfig
    "gp0", "gp1",
    # NR drx-onDurationTimer
    "subMilliSeconds", "milliSeconds",
}


_SF_PATTERN = re.compile(r"^sf\d+$")
_PSF_PATTERN = re.compile(r"^psf\d+$")
_MS_PATTERN = re.compile(r"^ms\d+$")


def _is_choice_segment(seg: str) -> bool:
    """``True`` si ce segment est une alternative CHOICE à collapser.

    Détecte en plus les patterns numériques ASN.1 (``sf*``, ``psf*``,
    ``ms*``) qui apparaissent typiquement comme alternatives d'un
    CHOICE de type timer/cycle.
    """
    if seg in _CHOICE_SEGMENTS:
        return True
    if _SF_PATTERN.match(seg) or _PSF_PATTERN.match(seg) or _MS_PATTERN.match(seg):
        return True
    return False


# ---------------------------------------------------------------------------
# Discriminator extraction depuis le path brut
# ---------------------------------------------------------------------------

_RLC_MODE_FROM_SEGMENT = {
    "am":                      "AM",
    "um-Bi-Directional":       "UM",
    "um-Uni-Directional-UL":   "UM",
    "um-Uni-Directional-DL":   "UM",
}

_DIRECTION_FROM_SEGMENT = {
    "dl-AM-RLC": "DL", "ul-AM-RLC": "UL",
    "dl-UM-RLC": "DL", "ul-UM-RLC": "UL",
    "um-Uni-Directional-UL": "UL",
    "um-Uni-Directional-DL": "DL",
}

_EVENT_PATTERN = re.compile(r"^event([AB]\d(?:_\d)?)$")


def extract_discriminators(path_segments: list[str]) -> dict[str, Any]:
    """Lit les discriminants depuis les segments du path. Jamais inventé :
    seuls les segments présents produisent une entrée.

    0.45.1 — Les discriminants sont **hérités** le long du path : un
    discriminant extrait d'un ancêtre (``reportConfigToAddModList[i] →
    event``, ``drb-ToAddModList → bearer``, ``measObjectToAddModList →
    measObject_type``) s'applique à TOUTES les feuilles de ce sous-arbre.
    Le walker produit les segments dans l'ordre racine → feuille ; on
    accumule au fur et à mesure et on renvoie l'état final.
    """
    d: dict[str, Any] = {}
    for seg in path_segments:
        # Bearer : SRB* / DRB*
        if seg.startswith("srb-ToAddModList") or seg == "srb-Identity":
            d.setdefault("bearer_kind", "SRB")
        if seg.startswith("drb-ToAddModList") or seg == "drb-Identity":
            d.setdefault("bearer_kind", "DRB")
        # RLC mode (le DERNIER vu l'emporte si le path traverse plusieurs
        # modes — en pratique un path ne traverse qu'une seule alt RLC).
        if seg in _RLC_MODE_FROM_SEGMENT:
            d["rlc_mode"] = _RLC_MODE_FROM_SEGMENT[seg]
        # Direction (DL/UL)
        if seg in _DIRECTION_FROM_SEGMENT:
            d["direction"] = _DIRECTION_FROM_SEGMENT[seg]
        # Event A1..A6 / B1/B2 — hérité pour toutes les feuilles sœurs
        # (hysteresis, timeToTrigger, triggerQuantity, reportAmount,
        # reportInterval, maxReportCells) sous le même reportConfig.
        m = _EVENT_PATTERN.match(seg)
        if m:
            d["event"] = m.group(1)
        # measObject CHOICE — hérité par les feuilles de la cellule.
        if seg == "measObjectEUTRA":   d["measObject_type"] = "EUTRA"
        if seg == "measObjectUTRA":    d["measObject_type"] = "UTRA"
        if seg == "measObjectNR-r15":  d["measObject_type"] = "NR"
        # reportConfig CHOICE — hérité.
        if seg == "reportConfigEUTRA":    d["reportConfig_type"] = "EUTRA"
        if seg == "reportConfigInterRAT": d["reportConfig_type"] = "InterRAT"
        # Scell / BWP : marqueur booléen (le vrai index est une sœur
        # ``sCellIndex`` / ``bwp-Id`` — on ne la joint pas ici,
        # elle apparaît comme KPI séparé).
        if seg == "sCellToAddModList":   d.setdefault("has_scell", True)
        if seg.startswith("BWP"):        d.setdefault("has_bwp",   True)
    return d


# ---------------------------------------------------------------------------
# param_key = path canonique (CHOICE collapsés)
# ---------------------------------------------------------------------------


def canonical_param_key(path: str) -> tuple[str, str | None, str]:
    """Retourne ``(param_key, choice_of, display_name)``.

    - ``param_key`` : chemin canonique sans les segments CHOICE **ni**
      les index de liste ``[i]`` (ces derniers restent dans ``path``
      pour la contrainte d'unicité).
    - ``choice_of`` : nom du dernier segment supprimé (le CHOICE parent)
      si une alt a été collapsée, sinon ``None``.
    - ``display_name`` : dernier segment du param_key.
    """
    segs = path.split("/")
    kept: list[str] = []
    last_choice_parent: str | None = None
    for seg in segs:
        # 0.45.1 — Drop les index de liste [i] : le param_key canonique
        # agrège les feuilles reportConfig[0]..[N] sous une seule clé.
        if seg.startswith("[") and seg.endswith("]"):
            continue
        if _is_choice_segment(seg):
            # On note le segment PRÉCÉDENT comme choice_of si pas déjà
            # vu — c'est le nom du CHOICE qui contenait cette alt.
            if kept and last_choice_parent is None:
                last_choice_parent = kept[-1]
            continue
        kept.append(seg)
    param_key = "/".join(kept) if kept else path
    display_name = kept[-1] if kept else segs[-1]
    return param_key, last_choice_parent, display_name


# ---------------------------------------------------------------------------
# Groupe fonctionnel (mapping statique inspiré de dict_tree.html)
# ---------------------------------------------------------------------------
#
# Chaque entrée : (regex sur param_key OU message, groupe).
# L'ordre importe : on prend le premier match.
#

_FUNCTIONAL_GROUPS: list[tuple[re.Pattern[str], str]] = [
    # LTE SIB1
    (re.compile(r"systemInformationBlockType1/cellAccessRelatedInfo/cellIdentity"), "Identité cellule"),
    (re.compile(r"systemInformationBlockType1/cellAccessRelatedInfo/plmn-Identity"), "Identité cellule"),
    (re.compile(r"systemInformationBlockType1/cellAccessRelatedInfo/trackingAreaCode"), "Identité cellule"),
    (re.compile(r"systemInformationBlockType1/cellAccessRelatedInfo"), "Identité cellule"),
    (re.compile(r"systemInformationBlockType1/freqBandIndicator"), "Identité cellule"),
    # LTE SIB2 — Accès & timers
    (re.compile(r"ue-TimersAndConstants/|t30\d|t31\d|n31\d"), "Accès & timers"),
    (re.compile(r"rach-ConfigCommon|prach-Config"), "Accès & timers"),
    (re.compile(r"uplinkPowerControlCommon|p0-Nominal"), "Accès & timers"),
    (re.compile(r"pcch-Config|defaultPagingCycle|nB$"), "Accès & timers"),
    # LTE SIB3 — Resélection intra
    (re.compile(r"q-Hyst|s-Intra|s-NonIntra|threshServing|cellReselectionPriority|t-Reselection"), "Resélection"),
    # LTE SIB5 — Resélection inter
    (re.compile(r"interFreqCarrierFreqList"), "Resélection"),
    # Bearers PDCP / RLC
    (re.compile(r"pdcp-Config|headerCompression|rohc|statusReportRequired|pdcp-SN-Size"), "Bearers / PDCP"),
    (re.compile(r"rlc-Config|t-Reordering|t-StatusProhibit|t-PollRetransmit|pollPDU|pollByte|maxRetxThreshold|sn-FieldLength|t-Reassembly"), "Bearers / RLC"),
    (re.compile(r"logicalChannelConfig|prioritisedBitRate|bucketSizeDuration"), "Bearers / canal logique"),
    (re.compile(r"srb-ToAddModList|drb-ToAddModList"), "Bearers"),
    # MAC-DRX
    (re.compile(r"drx-Config|onDurationTimer|drx-InactivityTimer|drx-RetransmissionTimer|longDRX-Cycle|shortDRX-Cycle|drxShortCycleTimer|drxStartOffset|drx-LongCycle|drx-ShortCycle|drx-HARQ-RTT|drx-SlotOffset"), "MAC-DRX"),
    # MAC-autres
    (re.compile(r"ul-SCH-Config|periodicBSR-Timer|retxBSR-Timer|ttiBundling|phr-Config|periodicPHR-Timer|prohibitPHR-Timer|dl-PathlossChange|timeAlignmentTimer|sr-ProhibitTimer|bsr-Config|tag-Config"), "MAC-autres"),
    # Mesures-objets
    (re.compile(r"measObjectToAddModList|measObjectEUTRA|measObjectUTRA|measObjectNR"), "Mesures-objets"),
    # Mesures-critères
    (re.compile(r"reportConfigToAddModList|reportConfigEUTRA|reportConfigInterRAT|a3-Offset|a4-Threshold|a5-Threshold|a6-Offset|hysteresis|timeToTrigger|triggerQuantity|reportQuantity|maxReportCells|reportInterval|reportAmount|threshold-RSRP|threshold-RSRQ"), "Mesures-critères"),
    (re.compile(r"measIdToAddModList|measId$"), "Mesures-liaison"),
    (re.compile(r"quantityConfig|filterCoefficient"), "Mesures-quantité"),
    (re.compile(r"measGapConfig|gapOffset|s-Measure"), "Mesures-gaps"),
    # Handover
    (re.compile(r"mobilityControlInfo|targetPhysCellId|t304|rach-ConfigDedicated"), "Handover"),
    # PHY
    (re.compile(r"pucch-Config|pusch-Config|pdsch-Config|pdcch-Config|cqi-Report|soundingRS|antennaInfo|transmissionMode|schedulingRequestConfig|srs-Config|csi-"), "PHY"),
    # EN-DC
    (re.compile(r"nr-Config-r15|nr-SecondaryCellGroup|endc-|nr-RadioBearerConfig|tdm-PatternConfig|fr1-Gap"), "EN-DC"),
    # CA
    (re.compile(r"sCellToAddModList|cellIdentification|radioResourceConfigCommonSCell|radioResourceConfigDedicatedSCell"), "CA"),
    # Sécurité
    (re.compile(r"cipheringAlgorithm|integrityProtAlgorithm|securityConfig|SecurityModeCommand"), "Sécurité"),
    # Release
    (re.compile(r"releaseCause|redirectedCarrierInfo|idleModeMobility|t320|extendedWaitTime"), "Release"),
    # Capacities
    (re.compile(r"supportedBandList|supportedBandCombination|featureGroupIndicators|rf-Parameters|phyLayerParameters|measParameters|accessStratumRelease|ue-Category|supportedModulation"), "Capacités"),
    # Reports (mesures rapportées)
    (re.compile(r"measResultPCell|measResultServing|measResultNeighCell|measResultListEUTRA|measResultListNR|measResultForECID|locationInfo"), "Mesures rapportées"),
    (re.compile(r"rach-Report|rlf-Report|measResultLastServCell"), "Mesures rapportées"),
    # NR
    (re.compile(r"spCellConfig|reconfigurationWithSync|absoluteFrequencySSB|ssb-Position|subcarrierSpacing|tdd-UL-DL-Config"), "PSCell NR"),
    (re.compile(r"BWP-Downlink|BWP-Uplink|initialDownlinkBWP|initialUplinkBWP|locationAndBandwidth|cyclicPrefix"), "BWP & PHY NR"),
    (re.compile(r"rlc-BearerToAddModList"), "Bearers / RLC NR"),
    (re.compile(r"RadioBearerConfig|sdap-Config"), "Bearers / PDCP NR"),
    # NR DRX
    (re.compile(r"drx-onDurationTimer|drx-LongCycleStartOffset"), "MAC-DRX NR"),
]


def functional_group(param_key: str, message: str | None) -> str:
    for rx, group in _FUNCTIONAL_GROUPS:
        if rx.search(param_key):
            return group
    if message and message.startswith("UECapability"):
        return "Capacités"
    return "Autres"


# ---------------------------------------------------------------------------
# API principale
# ---------------------------------------------------------------------------


def enrich(path: str, message: str | None) -> dict[str, Any]:
    """Calcule l'ensemble des colonnes v2 pour une ligne param_occurrence."""
    segs = path.split("/")
    param_key, choice_of, display_name = canonical_param_key(path)
    last_seg = segs[-1] if segs else path
    discs = extract_discriminators(segs)
    origin = infer_origin(message)
    identif = is_identifier(last_seg)
    group = functional_group(param_key, message)
    return {
        "param_key":        param_key,
        "display_name":     display_name,
        "choice_of":        choice_of,
        "discriminators":   discs or None,
        "origin":           origin,
        "is_identifier":    identif,
        "functional_group": group,
    }
