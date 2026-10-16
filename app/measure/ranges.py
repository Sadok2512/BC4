"""Plages 3GPP physiques pour validation `par le CONTENU` (0.39.0).

Doctrine : un nom de champ (ex. `cell0_rsrp_dbm`) peut être trompeur
(convention amont décodeur). On valide **par la plage physique** d'une
mesure 3GPP, pas par le label du champ.

Références :
- RSSI serving : TS 36.214 §5.1.3, pratique de drive -120..-20 dBm.
- RSRP : TS 36.133 §9.1.4 — report range idx 0..97 → -140..-44 dBm.
- RSRQ : TS 36.133 §9.1.7 — report range idx 0..34 → -19.5..-3 dB.
- SINR : TS 36.214 §5.1.4 (RS-SINR r13) — report range idx 0..127 → -23..+40 dB
  ; en pratique drive -20..+30 dB (bornes avec marge honnête).
- CQI : TS 36.213 Table 7.2.3-1 — indice 0..15.
- TX power UE LTE : TS 36.101 §6.2.5 — -40..+23 dBm (Power Class 3 : max 23 dBm).
- Débit DL app : plage pratique 0..300 Mbit/s (haut : CA 4CC Cat.9+).

Les plages sont **inclusives** et volontairement permissives : les
outliers physiques réels (rare) ne sont PAS filtrés, seules les valeurs
grossièrement hors plage (placeholder décodeur `650400`, `50001`,
`50002`, …) le sont.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Range:
    lo: float
    hi: float
    unit: str
    label: str

    def contains(self, v: float | None) -> bool:
        if v is None:
            return False
        try:
            return self.lo <= float(v) <= self.hi
        except (TypeError, ValueError):
            return False


# Plages 3GPP primaires (ordre significatif : plus spécifique en premier).
RSSI = Range(lo=-120.0, hi=-20.0, unit="dBm", label="RSSI")
RSRP = Range(lo=-140.0, hi=-44.0, unit="dBm", label="RSRP")
RSRQ = Range(lo=-20.0, hi=-3.0, unit="dB", label="RSRQ")
SINR = Range(lo=-20.0, hi=30.0, unit="dB", label="SINR")

CQI = Range(lo=0.0, hi=15.0, unit="indice 0..15", label="CQI")
TX_POWER = Range(lo=-40.0, hi=23.0, unit="dBm", label="TX_POWER")

# Débit DL/UL applicatif reconstitué (8*bytes/Δt). Plage drive LTE.
THRPT = Range(lo=0.0, hi=300.0, unit="Mbit/s", label="THRPT")


# Marqueurs clairement placeholders du décodeur Nemo (jamais une mesure).
# `650400` = l'exemple rencontré sur REF (CELLMEAS tronqué) ; `50001..50010`
# = codes contrôle non physiques. On neutralise par la plage, pas par
# l'énumération.
def is_placeholder(v: float | None) -> bool:
    """Valeur manifestement non physique (hors tout plage radio connue)."""
    if v is None:
        return True
    try:
        f = float(v)
    except (TypeError, ValueError):
        return True
    # Au-dessus de +50 dBm (impossible UE) ou en-dessous de -200 dBm.
    return f > 50.0 or f < -200.0


def in_any_radio_range(v: float | None) -> bool:
    """Vrai si la valeur tombe dans au moins une plage radio connue."""
    if v is None or is_placeholder(v):
        return False
    return (
        RSSI.contains(v)
        or RSRP.contains(v)
        or RSRQ.contains(v)
        or SINR.contains(v)
        or CQI.contains(v)
        or TX_POWER.contains(v)
    )
