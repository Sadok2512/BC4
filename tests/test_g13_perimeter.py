"""G13 (0.12.0) — Jointure cells Orange ↔ cell_ref → project.perimeter.

Tests :
- bc4-enrich 1.1.0 : `detect_context` extrait `ctx["cells"]` depuis
  un SIB1 LTE encodé avec cellIdentity.
- `_compute_perimeter` sur une liste de cells vide → `cells_total=0`,
  `label="N/D"`, `zone_source="none"`.
- `_compute_perimeter` avec cells Orange + cell_ref peuplée en base →
  `label` lisible (DR/plaques réels), taux de jointure correct.
- Cell Orange SANS ligne cell_ref → `cells_orange_unjoined > 0`,
  déclaré, pas comblé par heuristique.
- Cell non-Orange → compte dans `cells_other`, pas jointe (déclaré).
"""

from __future__ import annotations

import os
import sys
import uuid

import pytest
from sqlalchemy import text

from app.db import SessionLocal

_DECODER_PATH = os.environ.get("BC4_NMF_DECODER_PATH", "/opt/nmf_decoder")
if _DECODER_PATH not in sys.path:
    sys.path.insert(0, _DECODER_PATH)
if "/home/devmat/BC4/decoder" not in sys.path:
    sys.path.insert(0, "/home/devmat/BC4/decoder")


def _encode_lte_sib1(mcc, mnc, cell_id_int: int) -> str:
    """Encode une SIB1 LTE avec PLMN + cellIdentity donnés."""
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
            "cellIdentity": (cell_id_int, 28),
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


def test_enrich_v11_exposes_cells():
    import bc4_enrich

    # 1.1.0+ : la clé `cells` doit être présente (1.2.0 chaîne et étend
    # la table PLMN, mais la sortie `cells` reste la même).
    assert bc4_enrich.__version__ >= "bc4-enrich 1.1.0", bc4_enrich.__version__
    hex_payload = _encode_lte_sib1([2, 0, 8], [0, 1], 41000001)
    events = [
        {
            "system": "LTE",
            "freq": "6300",
            "message": "SystemInformationBlockType1",
            "payload_hex": hex_payload,
        }
    ]
    ctx = bc4_enrich.detect_context(events)
    assert ctx["cells"] == [{"rat": "LTE", "plmn": "20801", "cell_id": "41000001"}]


def test_compute_perimeter_empty_cells_declares_none():
    from app.ingest.nmf import _compute_perimeter

    with SessionLocal() as db:
        peri = _compute_perimeter(db, [])
    assert peri["cells_total"] == 0
    assert peri["label"] == "N/D"
    assert peri["zone_source"] == "none"
    assert peri["join_rate_pct"] is None


def test_compute_perimeter_non_orange_not_attributable():
    """Cellule SFR → `cells_other`, pas de jointure (cell_ref ne couvre
    que Orange). Déclaré, pas comblé."""
    from app.ingest.nmf import _compute_perimeter

    with SessionLocal() as db:
        peri = _compute_perimeter(
            db,
            [{"rat": "LTE", "plmn": "20810", "cell_id": "88888888"}],
        )
    assert peri["cells_total"] == 1
    assert peri["cells_orange"] == 0
    assert peri["cells_other"] == 1
    assert peri["cells_joined"] == 0
    assert peri["label"] == "N/D"
    assert peri["zone_source"] == "none"


def test_compute_perimeter_orange_joined_against_cell_ref():
    """Insère une ligne cell_ref Orange, lance la jointure, vérifie que
    `project.perimeter` reflète la ligne (DR/plaque/arcep réels)."""
    from app.ingest.nmf import _compute_perimeter

    eci = f"77{uuid.uuid4().int % 1_000_000:06d}"
    with SessionLocal() as db:
        db.execute(
            text(
                "INSERT INTO cell_ref (id, rat, eci, nci, dor, dr, plaque, site_id, "
                "site_name, arcep_zone, coverage) VALUES "
                "(:id, '4G', :eci, NULL, 'UPR-Test', 'DR-G13', 'Plaque-G13', "
                "'S-G13', 'Site G13', '01/ Top15', 'outdoor')"
            ),
            {"id": f"g13-{eci}", "eci": eci},
        )
        db.commit()
        try:
            peri = _compute_perimeter(
                db,
                [
                    {"rat": "LTE", "plmn": "20801", "cell_id": eci},
                    # Une cellule Orange non joignable → unjoined
                    {"rat": "LTE", "plmn": "20801", "cell_id": "99999999"},
                ],
            )
        finally:
            db.execute(text("DELETE FROM cell_ref WHERE id = :id"), {"id": f"g13-{eci}"})
            db.commit()

    assert peri["cells_total"] == 2
    assert peri["cells_orange"] == 2
    assert peri["cells_joined"] == 1
    assert peri["cells_orange_unjoined"] == 1
    assert peri["join_rate_pct"] == 50.0
    assert "DR-G13" in peri["drs"]
    assert "Plaque-G13" in peri["plaques"]
    assert "UPR-Test" in peri["dors"]
    assert "01/ Top15" in peri["arcep_zones"]
    assert "outdoor" in peri["coverage"]
    assert peri["label"] == "DR-G13"
    assert peri["zone_source"] == "cell_ref_exact"
