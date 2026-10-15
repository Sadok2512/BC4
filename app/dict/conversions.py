"""Conversions 3GPP (TS 36.133 / TS 38.133).

Expose `convert(path_last_segment, raw_value) -> (converted, unit) | None`.
Chaque règle est APPLIQUÉE au segment feuille (`split("/")[-1]`) et à
la valeur BRUTE pycrate (le plus souvent un entier). Si la valeur n'est
pas convertible (non-numérique ou hors domaine typé 3GPP), on retourne
`None` — aucune invention, le path reste insérée sans `value_converted`.

Références :
- rsrp-Result (0..97)       → `idx - 141` dBm                 (TS 36.133 §9.1.4)
- rsrq-Result (0..34)       → `idx / 2 - 20` dB               (TS 36.133 §9.1.7)
- a3-Offset (-30..+30)      → `× 0.5` dB                      (TS 36.331 §6.3.5)
- q-RxLevMin (-70..-22)     → `× 2` dBm                       (TS 36.331 §6.3.4 ; TS 36.133)
- threshold-RSRP            → `idx - 140` dBm                 (TS 36.133 §9.1.4 / TS 38.133)
- q-Hyst                    → `× 1` dB                        (TS 36.331 §6.3.4)
- s-Measure                 → `idx - 140` dBm                 (TS 36.331 §6.3.5)
- rsrp-ThresholdSSB         → `idx - 140` dBm                 (TS 38.133 §10.1.6)
- rsrq-ThresholdSSB         → `idx / 2 - 20` dB               (TS 38.133 §10.1.7)
"""
from __future__ import annotations

from typing import Any


def _as_int(raw: Any) -> int | None:
    """Convertit la valeur brute pycrate en entier si possible."""
    if isinstance(raw, bool):
        # Évite que True/False ne soient traités comme 1/0 numériques.
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _rsrp_result(raw: Any) -> tuple[str, str] | None:
    i = _as_int(raw)
    if i is None or not (0 <= i <= 97):
        return None
    return (f"{i - 141}", "dBm")


def _rsrq_result(raw: Any) -> tuple[str, str] | None:
    i = _as_int(raw)
    if i is None or not (0 <= i <= 34):
        return None
    v = i / 2 - 20
    return (f"{v:g}", "dB")


def _a3_offset(raw: Any) -> tuple[str, str] | None:
    i = _as_int(raw)
    if i is None or not (-30 <= i <= 30):
        return None
    v = i * 0.5
    return (f"{v:g}", "dB")


def _q_rx_lev_min(raw: Any) -> tuple[str, str] | None:
    i = _as_int(raw)
    if i is None or not (-70 <= i <= -22):
        return None
    v = i * 2
    return (f"{v}", "dBm")


def _idx_minus_140(raw: Any) -> tuple[str, str] | None:
    i = _as_int(raw)
    if i is None or not (0 <= i <= 127):
        return None
    return (f"{i - 140}", "dBm")


def _q_hyst(raw: Any) -> tuple[str, str] | None:
    # Enum pycrate : certaines builds retournent une chaîne "dB1"/"dB2"/…
    # Pour les cas numériques, on considère la valeur comme dB directement
    # (×1). On évite d'inventer une conversion si la valeur arrive sous
    # forme d'enum string (laissée telle quelle, pas de converted).
    i = _as_int(raw)
    if i is None or not (0 <= i <= 30):
        return None
    return (f"{i}", "dB")


def _rsrq_threshold_ssb(raw: Any) -> tuple[str, str] | None:
    i = _as_int(raw)
    if i is None or not (0 <= i <= 127):
        return None
    v = i / 2 - 20
    return (f"{v:g}", "dB")


# Table : nom de segment feuille (exact, insensible à la casse) → fonction.
_RULES: dict[str, Any] = {
    "rsrp-Result": _rsrp_result,
    "rsrq-Result": _rsrq_result,
    "rsrpResult": _rsrp_result,
    "rsrqResult": _rsrq_result,
    "a3-Offset": _a3_offset,
    "q-RxLevMin": _q_rx_lev_min,
    "qRxLevMin": _q_rx_lev_min,
    "threshold-RSRP": _idx_minus_140,
    "thresholdRSRP": _idx_minus_140,
    "s-Measure": _idx_minus_140,
    "sMeasure": _idx_minus_140,
    "rsrp-ThresholdSSB": _idx_minus_140,
    "rsrpThresholdSSB": _idx_minus_140,
    "rsrq-ThresholdSSB": _rsrq_threshold_ssb,
    "rsrqThresholdSSB": _rsrq_threshold_ssb,
    "q-Hyst": _q_hyst,
    "qHyst": _q_hyst,
}


def convert(path_last_segment: str, raw_value: Any) -> tuple[str, str] | None:
    """Retourne `(value_converted, unit_converted)` pour un segment feuille
    reconnu — None sinon. Jamais d'invention : si la règle ne s'applique
    pas, on sort None, pas d'approximation.
    """
    fn = _RULES.get(path_last_segment)
    if fn is None:
        return None
    try:
        return fn(raw_value)
    except Exception:
        return None
