"""Tables déclarées (0.30.0) — conversions prouvées pour `measurement_points`.

Chaque entrée est fondée sur une preuve explicite (nom de fichier, ligne
CSV, docstring du décodeur). Aucune heuristique « raisonnable mais non
prouvée » ne figure ici — si une entrée manque, le champ aval reste
NULL plutôt que d'être forgé.
"""

from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# #DL → opérateur. Depuis bc4-decoder 2.0.0, meta.dl porte la chaîne brute
# du header #DL. Les 4 valeurs ci-dessous sont celles observées sur le
# corpus Petite-Forêt (fichiers Nemo Handy). Toute autre valeur reste
# `None` → operator=None, operator_source='none'.
# ---------------------------------------------------------------------------
DL_TO_OPERATOR: Final[dict[str, str]] = {
    "OFR": "Orange",
    "BYT": "Bouygues",
    "FREE": "Free",
    "SFR": "SFR",
}


def operator_from_dl(dl: str | None) -> str | None:
    """Retourne le libellé opérateur depuis #DL, ou None hors table."""
    if not dl:
        return None
    return DL_TO_OPERATOR.get(dl.strip().upper())


# ---------------------------------------------------------------------------
# PLMN → opérateur FR (les 4 MNO). Volontairement court : les PLMN MVNO/
# étrangers restent `None` (le mismatch n'est levé QUE si le SIB1 décode
# un PLMN MNO FR différent de celui du #DL — pas de faux-positif MVNO).
# ---------------------------------------------------------------------------
PLMN_TO_OPERATOR: Final[dict[str, str]] = {
    "20801": "Orange",
    "20802": "Orange",
    "20810": "SFR",
    "20813": "SFR",
    "20820": "Bouygues",
    "20821": "Bouygues",
    "20888": "Bouygues",
    "20815": "Free",
    "20816": "Free",
}


def operator_from_plmn(plmn: str | None) -> str | None:
    if not plmn:
        return None
    return PLMN_TO_OPERATOR.get(str(plmn).strip())


# ---------------------------------------------------------------------------
# system_code → RAT libellé. `system_code` est f[2] / rat_code (f[3]) selon
# l'event. Côté 2.0.0, _CAT_BY_CODE et SYSNAME exposent déjà '7'→'LTE' et
# '9'→'NR'. On garde la table ici pour la lecture directe de raw_fields
# (où rat_code vaut '7' ou '9' en str).
# ---------------------------------------------------------------------------
_RAT_CODE_TO_RAT: Final[dict[str, str]] = {
    "7": "LTE",
    "9": "NR",
}


def rat_from_code(code: str | None) -> str | None:
    if code is None:
        return None
    return _RAT_CODE_TO_RAT.get(str(code).strip())


# ---------------------------------------------------------------------------
# service_name / service_action → service_type (table déclarée, ordre
# significatif : premier match gagnant). Si aucun match → NULL.
#
# NOTE : les regex sont volontairement conservatrices (pas de typo
# compréhensive). Un libellé terrain qui échappe à cette table ressort
# `service_type=None` — déclaration d'écart, pas invention.
# ---------------------------------------------------------------------------
SERVICE_TYPE_RULES: Final[list[tuple[str, str]]] = [
    (r"HTTP\s*DL",     "HTTP_DOWNLOAD"),
    (r"HTTP\s*UL",     "HTTP_UPLOAD"),
    (r"MOC|MTC|VOICE", "VOICE_CALL"),
    (r"SMS",           "SMS"),
    (r"VIDEO|YOUTUBE", "VIDEO_STREAM"),
    (r"PING",          "PING"),
    (r"FTP\s*DL",      "FTP_DOWNLOAD"),
    (r"FTP\s*UL",      "FTP_UPLOAD"),
    (r"IPERF",         "IPERF"),
]

_SERVICE_RULES_COMPILED: Final[list[tuple[re.Pattern, str]]] = [
    (re.compile(pat, re.I), tag) for pat, tag in SERVICE_TYPE_RULES
]


def service_type_from(service_name: str | None, service_action: str | None) -> str | None:
    """Déduit `service_type` depuis `service_name` d'abord, puis
    `service_action`. Jamais deviné : si aucun match, retourne None."""
    for haystack in (service_name, service_action):
        if not haystack:
            continue
        for pat, tag in _SERVICE_RULES_COMPILED:
            if pat.search(haystack):
                return tag
    return None


# ---------------------------------------------------------------------------
# service_action → phase. Doctrine : un `Start*` (hors `StartRepeat`)
# ouvre une phase 'active' ; `Stop*` la ferme ; `Wait` indique une phase
# de pause ; tout le reste (ou action inconnue) = 'idle'.
# ---------------------------------------------------------------------------
def phase_from_action(action: str | None) -> str:
    if action is None:
        return "idle"
    a = action.strip()
    if not a:
        return "idle"
    if a.startswith("Start") and a != "StartRepeat":
        return "active"
    if a.startswith("Stop"):
        return "idle"
    if a == "Wait":
        return "wait"
    return "idle"


# ---------------------------------------------------------------------------
# EARFCN → bande LTE. Importe la fonction existante
# `app.dict.decode.band_from_earfcn` pour éviter la divergence. On ré-expose
# ici pour que `populate.py` consomme un symbole stable.
# ---------------------------------------------------------------------------
from app.dict.decode import band_from_earfcn  # noqa: E402

__all__ = [
    "DL_TO_OPERATOR",
    "PLMN_TO_OPERATOR",
    "SERVICE_TYPE_RULES",
    "band_from_earfcn",
    "operator_from_dl",
    "operator_from_plmn",
    "phase_from_action",
    "rat_from_code",
    "service_type_from",
]
