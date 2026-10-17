"""Décodage ASN.1 d'un event RRC (LTE ou NR) via pycrate + aplatissement
en liste `(path, value)`. Logique dérivée de
`/home/devmat/BC4/decoder-archive/build_dict.py` — la deny-list `DENY`
(regex d'identités d'abonné) et le `walk()` sont RÉUTILISÉS tels quels.

Table PDU :
- LTE : 6 canaux (BCCH-BCH/2, BCCH-SCH/2, CCCH/1, CCCH/2, DCCH/1, DCCH/2).
- NR  : mêmes 6 canaux + IEs capability (`UE-NR-Capability IE`,
  `UE-MRDC-Capability IE`, `FreqBandList IE`).

Band mapping EARFCN → bande (6 bornes LTE FR), repris de l'archive.
L'archive utilise `OPS` 5 PLMN ; ici on délègue l'opérateur à
`bc4_enrich.PLMN_TO_OPERATOR` (table FR plus large, 11 PLMN).

Jamais d'invention : un message dont le canal/direction n'est pas dans
la table PDU sort `error="canal inconnu"`. Un décodage pycrate qui
plante sort `error="échec"` — l'event est compté dans `n_params_failed`,
PAS inséré en base. Pas de masquage silencieux.
"""
from __future__ import annotations

import re
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Deny-list identités d'abonné : regex EXACTE de l'archive
# (`/home/devmat/BC4/decoder-archive/build_dict.py` ligne 14-16).
# INTERDICTION DE MODIFIER cette regex sans fermer formellement un écart.
# ---------------------------------------------------------------------------
DENY = re.compile(
    r"ue-Identity|s-TMSI|m-TMSI|mmec|imsi|randomValue|newUE-Identity|c-RNTI|shortMAC|"
    r"dedicatedInfoNAS|registeredMME|gummei|nextHopChaining|ue-CapabilityRAT-Container|"
    r"ueCapabilityRAT|lateNonCriticalExtension|nonCriticalExtension$|ng-5G-S-TMSI|"
    r"fullI-RNTI|shortI-RNTI|dedicatedNAS|registeredAMF|guami",
    re.I,
)

# Clés « conteneur » à aplatir sans contribuer au path (CHOICE/wrapper).
DROP = {"message", "c1", "criticalExtensions"}

# Messages à SKIP (Paging LTE : contient uniquement des identités d'abonné ;
# NAS : hors scope RRC, chiffré de bout en bout).
SKIP_MSG: set[str] = {"Paging"}


# ---------------------------------------------------------------------------
# Bande via EARFCN LTE (bornes archive + extension). Dérivation NR = ARFCN
# déléguée à `bc4_enrich.band_from_freq`.
_LTE_BANDS: list[tuple[int, int, str]] = [
    (0, 599, "B1"),
    (1200, 1949, "B3"),
    (2750, 3449, "B7"),
    (3450, 3799, "B8"),
    (6150, 6449, "B20"),
    (9210, 9659, "B28"),
]


def band_from_earfcn(earfcn: Any) -> str | None:
    try:
        e = int(str(earfcn).strip())
    except (TypeError, ValueError):
        return None
    for lo, hi, b in _LTE_BANDS:
        if lo <= e <= hi:
            return b
    return None


# ---------------------------------------------------------------------------
# Walk aplati — repris de l'archive (`walk()`, lignes 28-54). On préserve :
# - le filtrage DENY sur chaque clé (dict + CHOICE),
# - l'aplatissement des conteneurs DROP (nommés `message`/`c1`/
#   `criticalExtensions`) sans contribuer au path,
# - l'émission des BIT STRING courts en binaire (`0b…`), des BIT STRING
#   longs en `bits(n)`, et des champs à valeur `None` comme `"présent"`.
# ---------------------------------------------------------------------------
def walk(v: Any, path: list[str], out: list[tuple[list[str], Any]]) -> None:
    if isinstance(v, dict):
        for k, x in v.items():
            if k in DROP:
                walk(x, path, out)
            elif not DENY.search(k):
                walk(x, path + [k], out)
    elif isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str):
        if v[0] in DROP:
            walk(v[1], path, out)
        elif not DENY.search(v[0]):
            if v[1] is None:
                out.append((path, v[0]))
            else:
                walk(v[1], path + [v[0]], out)
    elif isinstance(v, list):
        # 0.42.0 — PLMN MCC/MNC = SEQUENCE SIZE (3) OF MCC-MNC-Digit.
        # Pycrate renvoie une liste d'entiers 0..9 ; on la concatène en
        # UNE chaîne (ex. [2,0,8] → "208"), sinon l'`UniqueConstraint
        # (project_id, stg_event_id, path)` ne garde que le premier digit
        # et on perd l'identité PLMN (bug 0.41.0, exposé par l'audit SIB1).
        if v and all(isinstance(x, int) and 0 <= x <= 9 for x in v):
            out.append((path, "".join(str(x) for x in v)))
            return
        for x in v:
            walk(x, path, out)
    elif isinstance(v, (bytes, bytearray)):
        return
    elif isinstance(v, tuple):
        # BIT STRING pycrate = (val:int, len:int).
        # 0.44.0 (G9) — TOUTE longueur de BIT STRING → **entier décimal**.
        # L'ancien émetteur « 0b… » pour BIT STRING courts (≤16 bits)
        # créait 2319 lignes param_occurrence inutilisables côté KPI
        # (TAC rendu `0b0001011100011001` au lieu de `5913`). On émet
        # systématiquement la valeur entière.
        if len(v) == 2 and isinstance(v[0], int) and isinstance(v[1], int):
            out.append((path, str(v[0])))
        else:
            out.append((path, str(v)))
    elif v is None:
        out.append((path, "présent"))
    else:
        out.append((path, v))


def path_matches_deny(path: list[str]) -> bool:
    """Filet final : un path aplati complet NE doit JAMAIS contenir un
    segment qui matche DENY. Même règle, deux niveaux (walk + ici).
    """
    for seg in path:
        if DENY.search(seg):
            return True
    return False


# ---------------------------------------------------------------------------
# Résolution de la table PDU pycrate (lazy — évite d'importer pycrate à
# l'import du module si le code ne décode pas).
# ---------------------------------------------------------------------------
_PDU_CACHE: dict[str, dict] = {}


def _lte_pdu_table() -> dict:
    if "LTE" in _PDU_CACHE:
        return _PDU_CACHE["LTE"]
    from pycrate_asn1dir.RRCLTE import EUTRA_RRC_Definitions as D

    table = {
        ("BCCH-BCH", "2"): D.BCCH_BCH_Message,
        ("BCCH-SCH", "2"): D.BCCH_DL_SCH_Message,
        ("CCCH", "2"): D.DL_CCCH_Message,
        ("CCCH", "1"): D.UL_CCCH_Message,
        ("DCCH", "2"): D.DL_DCCH_Message,
        ("DCCH", "1"): D.UL_DCCH_Message,
    }
    _PDU_CACHE["LTE"] = table
    return table


def _nr_pdu_table() -> dict:
    if "NR" in _PDU_CACHE:
        return _PDU_CACHE["NR"]
    from pycrate_asn1dir.RRCNR import NR_RRC_Definitions as N

    table = {
        ("BCCH-BCH", "2"): N.BCCH_BCH_Message,
        ("BCCH-SCH", "2"): N.BCCH_DL_SCH_Message,
        ("CCCH", "1"): N.UL_CCCH_Message,
        ("CCCH", "2"): N.DL_CCCH_Message,
        ("DCCH", "1"): N.UL_DCCH_Message,
        ("DCCH", "2"): N.DL_DCCH_Message,
    }
    _PDU_CACHE["NR"] = table
    return table


def _nr_ie_table() -> dict:
    if "NR_IE" in _PDU_CACHE:
        return _PDU_CACHE["NR_IE"]
    from pycrate_asn1dir.RRCNR import NR_RRC_Definitions as N

    table = {
        "UE-NR-Capability IE": N.UE_NR_Capability,
        "UE-MRDC-Capability IE": N.UE_MRDC_Capability,
        "FreqBandList IE": N.FreqBandList,
    }
    _PDU_CACHE["NR_IE"] = table
    return table


def resolve_pdu(system: str, channel: str | None, direction: str | None, message: str) -> Any | None:
    """Retourne le PDU pycrate pour (system, channel, direction) ou None."""
    if system == "LTE":
        return _lte_pdu_table().get((channel or "", direction or ""))
    if system == "NR":
        # Les IEs capability sont directement adressés par leur `message`
        # (ex. "UE-NR-Capability IE") — pas par le canal.
        ie = _nr_ie_table().get(message)
        if ie is not None:
            return ie
        return _nr_pdu_table().get((channel or "", direction or ""))
    return None


# ---------------------------------------------------------------------------
# Décodage event + aplatissement
# ---------------------------------------------------------------------------
def decode_event(
    system: str,
    channel: str | None,
    direction: str | None,
    message: str | None,
    payload_hex: str | None,
) -> dict:
    """Décode un event RRC. Retourne :
      - `ok=True`, `paths=[(path:list[str], value:Any), …]` si décodé,
      - `ok=False`, `error="skip"|"canal inconnu"|"échec"|"no_payload"`
        sinon. Jamais d'exception propagée.
    """
    msg = (message or "").strip()
    if not msg:
        return {"ok": False, "error": "no_message"}
    if msg in SKIP_MSG:
        return {"ok": False, "error": "skip"}
    if not payload_hex:
        return {"ok": False, "error": "no_payload"}
    pdu = resolve_pdu(system, channel, direction, msg)
    if pdu is None:
        return {"ok": False, "error": "canal inconnu"}
    try:
        payload = bytes.fromhex(payload_hex.strip())
    except ValueError:
        return {"ok": False, "error": "hex invalide"}
    try:
        pdu.from_uper(payload)
        value = pdu.get_val()
    except Exception:
        return {"ok": False, "error": "échec"}
    out: list[tuple[list[str], Any]] = []
    walk(value, [], out)
    return {"ok": True, "paths": out}


def iter_params_from_event(
    system: str,
    channel: str | None,
    direction: str | None,
    message: str | None,
    payload_hex: str | None,
) -> Iterator[tuple[str, Any]]:
    """Itère les paires `(path_str, value_raw)` d'un event, après deny-list.
    Les paths vides sont ignorés. Les paths dont un segment matche DENY
    sont rejetés silencieusement (compté par l'appelant).
    """
    res = decode_event(system, channel, direction, message, payload_hex)
    if not res.get("ok"):
        return
    for path, val in res["paths"]:
        if not path:
            continue
        if path_matches_deny(path):
            continue
        yield "/".join(path), val
