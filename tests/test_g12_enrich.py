"""G12 (0.11.0) — bc4_enrich : PLMN → opérateur + EARFCN/ARFCN → bande.

Vérifications :
- band_from_freq mappe correctement sur quelques EARFCN/ARFCN connus.
- detect_context sur un flux d'events sans payload → operators vide
  mais bands/technos remplis depuis freq.
- detect_context sur un SIB1 LTE **encodé pour Orange+SFR+Free+Bouygues**
  → operators = {Orange, SFR, Free, Bouygues} + plmns liste bien.
- Un fichier sans SIB1 → operators=[] (correct, pas une erreur).
"""

from __future__ import annotations

import os
import sys

import pytest

# Monte le chemin du décodeur (comme en prod via BC4_NMF_DECODER_PATH)
_DECODER_PATH = os.environ.get("BC4_NMF_DECODER_PATH", "/opt/nmf_decoder")
if _DECODER_PATH not in sys.path:
    sys.path.insert(0, _DECODER_PATH)
if "/home/devmat/BC4/decoder" not in sys.path:
    sys.path.insert(0, "/home/devmat/BC4/decoder")


def _encode_lte_sib1(mcc: list[int], mnc: list[int]) -> str:
    """Encode une SIB1 LTE minimale avec le PLMN donné. Retourne le hex UPER."""
    from pycrate_asn1dir.RRCLTE import EUTRA_RRC_Definitions as L

    msg = L.BCCH_DL_SCH_Message
    sib1 = {
        "cellAccessRelatedInfo": {
            "plmn-IdentityList": [
                {
                    "plmn-Identity": {"mcc": mcc, "mnc": mnc},
                    "cellReservedForOperatorUse": "notReserved",
                }
            ],
            "trackingAreaCode": (0x0001, 16),
            "cellIdentity": (0, 28),
            "cellBarred": "notBarred",
            "intraFreqReselection": "allowed",
            "csg-Indication": False,
        },
        "cellSelectionInfo": {"q-RxLevMin": -62},
        "freqBandIndicator": 20,
        "schedulingInfoList": [{"si-Periodicity": "rf8", "sib-MappingInfo": []}],
        "si-WindowLength": "ms20",
        "systemInfoValueTag": 0,
    }
    msg.set_val({"message": ("c1", ("systemInformationBlockType1", sib1))})
    return msg.to_uper().hex()


def test_band_from_freq_lte_nr():
    import bc4_enrich

    # LTE
    assert bc4_enrich.band_from_freq(3000, "LTE") == "B7"
    assert bc4_enrich.band_from_freq(6300, "LTE") == "B20"
    assert bc4_enrich.band_from_freq(9500, "LTE") == "B28"
    # NR
    assert bc4_enrich.band_from_freq(632628, "NR") == "n78"
    assert bc4_enrich.band_from_freq(155000, "NR") == "n28"
    # Hors plage
    assert bc4_enrich.band_from_freq(999999, "LTE") is None
    assert bc4_enrich.band_from_freq(None, "LTE") is None
    assert bc4_enrich.band_from_freq("abc", "LTE") is None


def test_plmn_table_covers_fr_operators():
    import bc4_enrich

    # Les 4 opérateurs FR doivent être présents.
    seen = set(bc4_enrich.PLMN_TO_OPERATOR.values())
    assert {"Orange", "SFR", "Bouygues", "Free"} <= seen


def test_detect_context_no_sib1_declares_empty_operators():
    import bc4_enrich

    events = [
        {"system": "LTE", "freq": "6300", "message": "MeasurementReport"},
        {"system": "NR", "freq": "632628", "message": "RRCReconfiguration"},
        {"system": "GSM", "freq": "100"},  # ignoré (techno hors scope)
    ]
    ctx = bc4_enrich.detect_context(events)
    assert ctx["operators"] == []  # écart déclaré, pas une erreur
    assert ctx["bands"] == ["B20", "n78"]
    assert ctx["technos"] == ["LTE", "NR"]
    assert ctx["n_sib1_lte"] == 0
    assert ctx["n_sib1_nr"] == 0


def test_detect_context_four_fr_operators():
    import bc4_enrich

    sib1_hex = {
        "Orange": _encode_lte_sib1([2, 0, 8], [0, 1]),
        "SFR": _encode_lte_sib1([2, 0, 8], [1, 0]),
        "Bouygues": _encode_lte_sib1([2, 0, 8], [2, 0]),
        "Free": _encode_lte_sib1([2, 0, 8], [1, 5]),
    }
    events = [
        {
            "system": "LTE",
            "freq": "6300",  # B20
            "message": "SystemInformationBlockType1",
            "payload_hex": h,
        }
        for h in sib1_hex.values()
    ]
    ctx = bc4_enrich.detect_context(events)
    assert set(ctx["operators"]) == {"Orange", "SFR", "Bouygues", "Free"}
    assert "B20" in ctx["bands"]
    assert ctx["technos"] == ["LTE"]
    assert ctx["n_sib1_lte"] == 4
    # PLMN bruts tracés aussi
    assert {"20801", "20810", "20820", "20815"} <= set(ctx["plmns"])


def test_detect_context_unknown_plmn_declares():
    """Un PLMN non répertorié FR doit tomber dans `plmns_unknown`,
    JAMAIS deviné comme un opérateur FR."""
    import bc4_enrich

    sib1_hex = _encode_lte_sib1([2, 2, 2], [9, 9])  # PLMN inconnu
    events = [
        {
            "system": "LTE",
            "freq": "6300",
            "message": "SystemInformationBlockType1",
            "payload_hex": sib1_hex,
        }
    ]
    ctx = bc4_enrich.detect_context(events)
    assert ctx["operators"] == []
    assert "22299" in ctx["plmns_unknown"]
