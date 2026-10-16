"""Catalogue de métriques canoniques (0.28.0 — Assistant V3).

**Pourquoi V3 impose un catalogue** : avant 0.28.0, l'Intent du LLM
pouvait mélanger des unités incomparables (ms + kB + booléens) parce
que la métrique n'était qu'une chaîne libre. Désormais chaque métrique
porte une **identité canonique** (`key`), une **classe de
comparabilité** et un **chemin de résolution** dans la DB. Deux
métriques de classes différentes ne sont **jamais** jointes.

Un terme utilisateur ambigu (ex. « RLC ») qui matche plusieurs chemins
ASN.1 distincts dans `param_occurrence.path` déclenche une
**clarification** côté intent — il n'y a pas de choix implicite.

Discipline : **jamais inventé**. Si la métrique n'a pas de métrique
canonique correspondante dans ce catalogue → l'Intent remonte
`UNAVAILABLE` avec raison explicite ; aucune substitution autorisée.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ComparabilityClass = Literal[
    "COUNT",          # occurrences, pur comptage — toujours recomposable
    "OFFSET_HALF_DB", # a3-Offset, offsets 3GPP (valeur ASN.1 × 0.5 dB)
    "TIMER_MS",       # millisecondes directes (vrai timer)
    "RSRP_DBM",       # dBm — RSRP serving / neighbour
    "RSRQ_DB",
    "SINR_DB",
    "CQI_IDX",        # indice 0..15
    "THRPT_MBPS",     # Mbit/s
    "BYTES",
    "BOOLEAN",
    "ENUM",           # enum ASN.1 (dl-Bandwidth: n100, n75...)
    "RAW_STRING",     # chaîne ASN.1 brute, pas de conversion
]

# 0.29.1 — Nature du paramètre.
# - `config`  : paramètre de CONFIGURATION RRC (seuil, offset, timer
#   de reselection, etc.). N'EST PAS une grandeur mesurée côté terminal
#   ; parler de « latence », « débit », « qualité » à son sujet est FAUX.
# - `measurement` : grandeur radio MESURÉE par le terminal
#   (RSRP, RSRQ, SINR, CQI, débits, …). On peut la décrire comme un
#   phénomène observable.
# - `count` : pur comptage d'occurrences (volume de messages, nb de
#   bandes, nb d'opérateurs). Pas une physique.
ParameterNature = Literal["config", "measurement", "count"]


@dataclass(frozen=True)
class CanonicalMetric:
    """Identité canonique d'une métrique BC4.

    - `key` : identifiant programmatique stable (sélectionné dans la
      cat enum).
    - `display` : libellé UI lisible humain.
    - `unit` : unité physique après conversion 3GPP.
    - `comparability_class` : classe de comparabilité. Deux métriques
      de classes différentes NE sont PAS comparables.
    - `source_dataset` : `rrc_dict` | `measurements`.
    - `path_match` : liste de patterns `path LIKE` pour résoudre dans
      `param_occurrence`. S'il y a > 1 match distinct au niveau DB,
      l'Intent remonte `AMBIGUOUS`.
    - `message_match` : filtre `message` RRC optionnel (ex.
      `MeasurementReport` pour exclure la config dans
      `rrcConnectionReconfiguration`).
    - `exclude_path_patterns` : patterns à EXCLURE (ex. éviter de
      compter les thresholds config comme des mesures).
    - `convert_rule` : règle de conversion 3GPP affichée côté UI.
    - `recomposable` : True si la mesure peut être recomposée depuis
      des sous-agrégats (count), False pour percentiles / moyennes.
    - `available_check` : nom du check à exécuter pour vérifier que
      la mesure est effectivement peuplée dans le projet
      (dataset non vide avec les contraintes). `None` = pas de check
      spécifique au-delà du dataset.
    """

    key: str
    display: str
    unit: str
    comparability_class: ComparabilityClass
    source_dataset: Literal["rrc_dict", "measurements"]
    # 0.29.1 — Nature : "config" (seuil/offset/timer RRC — pas une
    # grandeur mesurée côté terminal), "measurement" (grandeur radio
    # mesurée : RSRP, RSRQ, SINR, débits…), "count" (pur volume).
    # Un paramètre `config` NE PEUT PAS être décrit comme un phénomène
    # physique (latence, débit, qualité) — interdit par la narration et
    # le vérificateur.
    nature: ParameterNature = "config"
    path_match: tuple[str, ...] = field(default_factory=tuple)
    message_match: str | None = None
    exclude_path_patterns: tuple[str, ...] = field(default_factory=tuple)
    convert_rule: str | None = None
    recomposable: bool = False
    available_check: str | None = None
    # Mots-clés utilisateur qui PEUVENT désigner cette métrique.
    # Utilisés dans l'intent parser pour résolution lexicale.
    user_terms: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Catalogue : métriques canoniques exposées à l'intent
# ---------------------------------------------------------------------------

CATALOG: dict[str, CanonicalMetric] = {
    # --- Métriques COUNT / listing dim (toujours dispo si dataset non vide) ---
    # IMPORTANT : les user_terms ne doivent PAS contenir de patterns
    # « par X » (c'est un pattern de group_by, pas de métrique). Sinon
    # une question « débits par opérateur » match 2 métriques (débit
    # + operator_count) et devient faussement ambiguë.
    "operator_count": CanonicalMetric(
        key="operator_count",
        display="Nombre d'occurrences RRC par opérateur",
        unit="occurrences",
        comparability_class="COUNT",
        source_dataset="rrc_dict",
        nature="count",
        recomposable=True,
        user_terms=("opérateurs", "operators"),
    ),
    "band_count": CanonicalMetric(
        key="band_count",
        display="Nombre d'occurrences RRC par bande",
        unit="occurrences",
        comparability_class="COUNT",
        source_dataset="rrc_dict",
        nature="count",
        recomposable=True,
        user_terms=("bandes", "bands"),
    ),
    "rrc_message_count": CanonicalMetric(
        key="rrc_message_count",
        display="Volume de messages RRC",
        unit="occurrences",
        comparability_class="COUNT",
        source_dataset="rrc_dict",
        nature="count",
        recomposable=True,
        user_terms=("messages RRC", "signalisation RRC", "top messages"),
    ),
    # --- Paramètres de CONFIGURATION mobilité RRC (nature=config) ---
    # IMPORTANT : a3-Offset est un OFFSET en dB (×0.5), pas une latence
    # ni un timer. Toute description « ms », « temps », « latence »
    # est FAUSSE — interceptée par la narration et le vérificateur.
    "a3Offset": CanonicalMetric(
        key="a3Offset",
        display="a3-Offset (seuil event A3, décalage neighbour vs serving)",
        unit="dB",
        comparability_class="OFFSET_HALF_DB",
        source_dataset="rrc_dict",
        nature="config",
        path_match=("%a3-Offset%",),
        exclude_path_patterns=("%Threshold%", "%threshold%"),
        convert_rule="valeur ASN.1 × 0.5 dB (3GPP TS 36.331 §6.3.5, ReportConfigEUTRA)",
        recomposable=False,
        user_terms=("a3-offset", "a3offset", "a3", "event A3", "offset A3"),
    ),
    "a5Threshold1": CanonicalMetric(
        key="a5Threshold1",
        display="a5-Threshold1 (seuil serving event A5)",
        unit="dBm",
        comparability_class="RSRP_DBM",
        source_dataset="rrc_dict",
        nature="config",
        path_match=("%a5-Threshold1%",),
        convert_rule="seuil RSRP 3GPP : index − 141 dBm (TS 36.133 §9.1.4)",
        recomposable=False,
        user_terms=("a5-threshold1", "a5Threshold1", "a5 serving"),
    ),
    # --- Grandeurs MESURÉES (nature=measurement) ---
    "rsrpServing": CanonicalMetric(
        key="rsrpServing",
        display="RSRP serving (dBm)",
        unit="dBm",
        comparability_class="RSRP_DBM",
        source_dataset="rrc_dict",
        nature="measurement",
        path_match=(
            "%measResultPCell/rsrpResult",
            "%measResultServingCell%rsrpResult%",
            "%measResultServingMOList%rsrp%",
        ),
        message_match="MeasurementReport",
        convert_rule="RSRP 3GPP : index − 141 dBm (TS 36.133 §9.1.4)",
        recomposable=False,
        user_terms=("rsrp", "serving rsrp", "rsrp serving", "niveau"),
    ),
    "throughputDL": CanonicalMetric(
        key="throughputDL",
        display="Débit descendant (DL)",
        unit="Mbit/s",
        comparability_class="THRPT_MBPS",
        source_dataset="measurements",
        nature="measurement",
        convert_rule="colonne `measurement_points.dl` (Mbit/s) — NULL tant que Phase 1 mapping décodeur n'est pas livrée",
        recomposable=False,
        available_check="dl_populated",
        user_terms=("débits", "debit", "débit DL", "throughput", "downlink", "DL"),
    ),
    "throughputUL": CanonicalMetric(
        key="throughputUL",
        display="Débit montant (UL)",
        unit="Mbit/s",
        comparability_class="THRPT_MBPS",
        source_dataset="measurements",
        nature="measurement",
        convert_rule="colonne `measurement_points.thrpt_ul` (Mbit/s) — NULL tant que Phase 1 non livrée",
        recomposable=False,
        available_check="thrpt_ul_populated",
        user_terms=("débit UL", "uplink", "UL"),
    ),
    # 0.31.0 — Extensions radio + mobilité + événements RRC.
    # Nature `measurement` quand la grandeur est mesurée par le terminal
    # et sourcée directement par le RRC dict (RSRP serving idx-141 dBm,
    # RSRQ serving (idx/2)-20 dB) OU par measurement_points (SINR L1,
    # CQI reporting) — ces dernières marquées UNAVAILABLE tant que la
    # Phase 1 décodeur ne les a pas peuplées.
    "rsrqServing": CanonicalMetric(
        key="rsrqServing",
        display="RSRQ serving (dB)",
        unit="dB",
        comparability_class="RSRQ_DB",
        source_dataset="rrc_dict",
        nature="measurement",
        path_match=(
            "%measResultPCell/rsrqResult",
            "%measResultServingCell%rsrqResult%",
            "%measResultServingMOList%rsrq%",
        ),
        message_match="MeasurementReport",
        convert_rule="RSRQ 3GPP : (index / 2) − 20 dB (TS 36.133 §9.1.7)",
        recomposable=False,
        user_terms=("rsrq", "rsrq serving", "qualité"),
    ),
    "sinrServing": CanonicalMetric(
        key="sinrServing",
        display="SINR serving (dB)",
        unit="dB",
        comparability_class="SINR_DB",
        source_dataset="measurements",
        nature="measurement",
        convert_rule="colonne `measurement_points.sinr` (dB) — NULL tant que Phase 1 mapping décodeur n'est pas livrée",
        recomposable=False,
        available_check="sinr_populated",
        user_terms=("sinr", "snr", "signal to noise"),
    ),
    "cqiServing": CanonicalMetric(
        key="cqiServing",
        display="CQI serving",
        unit="indice 0..15",
        comparability_class="CQI_IDX",
        source_dataset="measurements",
        nature="measurement",
        convert_rule="colonne `measurement_points.cqi` — NULL tant que Phase 1 mapping décodeur n'est pas livrée",
        recomposable=False,
        available_check="cqi_populated",
        user_terms=("cqi", "channel quality"),
    ),
    "latencyServing": CanonicalMetric(
        key="latencyServing",
        display="Latence (ms)",
        unit="ms",
        comparability_class="TIMER_MS",
        source_dataset="measurements",
        nature="measurement",
        convert_rule="colonne `measurement_points.latency` (ms) — NULL tant que Phase 1 non livrée",
        recomposable=False,
        available_check="latency_populated",
        user_terms=("latence", "latency", "ping", "rtt"),
    ),
    # --- Événements de mobilité & setup (counts de messages RRC) ---
    "rrcSetupCount": CanonicalMetric(
        key="rrcSetupCount",
        display="Nombre de setups RRC",
        unit="occurrences",
        comparability_class="COUNT",
        source_dataset="rrc_dict",
        nature="count",
        message_match="RRCConnectionSetup",
        recomposable=True,
        available_check="message_present:RRCConnectionSetup",
        user_terms=("rrc setup", "rrcsetup", "setup rrc", "connexion rrc"),
    ),
    "rrcReconfCount": CanonicalMetric(
        key="rrcReconfCount",
        display="Nombre de reconfigurations RRC",
        unit="occurrences",
        comparability_class="COUNT",
        source_dataset="rrc_dict",
        nature="count",
        message_match="RRCConnectionReconfiguration",
        recomposable=True,
        available_check="message_present:RRCConnectionReconfiguration",
        user_terms=("rrc reconfig", "reconfiguration rrc", "rrcconnectionreconfiguration"),
    ),
    "rrcMeasReportCount": CanonicalMetric(
        key="rrcMeasReportCount",
        display="Nombre de MeasurementReport",
        unit="occurrences",
        comparability_class="COUNT",
        source_dataset="rrc_dict",
        nature="count",
        message_match="MeasurementReport",
        recomposable=True,
        available_check="message_present:MeasurementReport",
        user_terms=("measurement report", "mesure report", "measurementreport"),
    ),
    "handoverCount": CanonicalMetric(
        key="handoverCount",
        display="Nombre de handovers (RRCConnectionReconfiguration avec mobilityControlInfo)",
        unit="occurrences",
        comparability_class="COUNT",
        source_dataset="rrc_dict",
        nature="count",
        path_match=("%mobilityControlInfo%",),
        recomposable=True,
        available_check="path_present:mobilityControlInfo",
        user_terms=("handover", "ho", "basculement"),
    ),
    "reestablishmentCount": CanonicalMetric(
        key="reestablishmentCount",
        display="Nombre de RRCConnectionReestablishment",
        unit="occurrences",
        comparability_class="COUNT",
        source_dataset="rrc_dict",
        nature="count",
        message_match="RRCConnectionReestablishment",
        recomposable=True,
        available_check="message_present:RRCConnectionReestablishment",
        user_terms=("reestablishment", "ré-établissement", "reest"),
    ),
    # --- Topologie (counts purs) ---
    "earfcnCount": CanonicalMetric(
        key="earfcnCount",
        display="EARFCN distincts par projet",
        unit="occurrences",
        comparability_class="COUNT",
        source_dataset="rrc_dict",
        nature="count",
        recomposable=True,
        user_terms=("earfcn", "arfcn", "frequencies"),
    ),
    "pciCount": CanonicalMetric(
        key="pciCount",
        display="PCI distincts par projet",
        unit="occurrences",
        comparability_class="COUNT",
        source_dataset="rrc_dict",
        nature="count",
        recomposable=True,
        user_terms=("pci", "cellule physique"),
    ),
}


# 0.29.1 — Termes de phénomène interdits selon la nature.
# Si la narration les contient alors que la métrique n'est pas de la
# bonne nature, le vérificateur rejette.
FORBIDDEN_PHENOMENA_FOR_CONFIG = (
    "latence", "latency",
    "temps de latence", "temps de réponse",
    "débit", "débits", "throughput", "bandwidth",
    "qualité radio", "qualité de signal",
    "couverture radio", "zone de couverture",
    "signal fort", "signal faible",
)
FORBIDDEN_PHENOMENA_FOR_COUNT = (
    "latence", "latency",
    "temps de latence",
    "qualité radio",
    "couverture",
)


# Alias / mots-clés → clé canonique.
# Utilisé par le parser lexical de l'intent.
def resolve_user_term(term: str) -> list[str]:
    """Retourne les clés canoniques qui matchent `term`. Si > 1 → ambigu.

    **Règle de matching stricte** (0.28.0) : évite les faux positifs
    des unigrammes courants (« par », « des », …).

    - Si `term` est un n-gram (contient un espace) → match ssi `term`
      est contenu dans un `user_term` (le user_term couvre le concept).
    - Si `term` est un unigramme → match ssi EXACT (ou user_term exact
      à casse près). Pas de substring sur unigramme.
    """
    tnorm = (term or "").strip().lower()
    if not tnorm:
        return []
    is_ngram = " " in tnorm or "-" in tnorm
    hits: list[str] = []
    for key, m in CATALOG.items():
        for u in m.user_terms:
            ul = u.lower()
            matched = False
            if is_ngram:
                # n-gram : accepte substring dans les deux sens pour tolérer
                # ponctuation (ex. "a3-offset" ≡ "a3 offset").
                if tnorm == ul or tnorm in ul or ul in tnorm:
                    matched = True
            else:
                # unigramme : match EXACT uniquement
                if tnorm == ul:
                    matched = True
            if matched:
                hits.append(key)
                break
    seen = set()
    out: list[str] = []
    for h in hits:
        if h not in seen:
            out.append(h)
            seen.add(h)
    return out


def are_comparable(a: CanonicalMetric, b: CanonicalMetric) -> bool:
    """Deux métriques sont comparables ssi même classe de comparabilité."""
    return a.comparability_class == b.comparability_class


def catalog_summary() -> dict:
    """Vue publique du catalogue pour `discover_schema` / debug."""
    return {
        k: {
            "display": m.display,
            "unit": m.unit,
            "comparability_class": m.comparability_class,
            "source_dataset": m.source_dataset,
            "convert_rule": m.convert_rule,
            "recomposable": m.recomposable,
            "has_availability_check": m.available_check is not None,
            "user_terms": list(m.user_terms),
        }
        for k, m in CATALOG.items()
    }
