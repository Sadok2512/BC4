"""G15 (0.14.0) — Fix bug mirror captures + PLMN non catalogué visible
+ doctrine opérateur = PLMN primaire du SIB1 (bc4-enrich 1.2.0).

Numéroté G15 car G13 (périmètre) et G14 (dictionnaire) sont pris.

Vérifications
-------------
(a) Fix bug mirror : refresh d'un projet seedé B0 (`n_captures_ingest=0`)
    laisse `captures` **inchangé**. Avant 0.14.0, la garde
    `is not None` écrasait à 0.
(b) Doctrine MVNO NON étiqueté : un SIB1 LTE encodé avec un PLMN
    hors des 11 MNO (`20825`, ex-Lyca Mobile) ne doit **pas** être
    mappé dans `operator_by_plmn`. L'enrich l'expose en
    `plmns_unknown`, et `app/ingest/nmf.py` le rend sous la forme
    `"PLMN 20825 (non catalogué)"` dans `project.operators`.
(c) PLMN inconnu visible : un ctx avec un PLMN hors table (`20899`) fait
    que `project.operators` contient `"PLMN 20899 (non catalogué)"`
    (via la logique nmf.py section post-enrich). Pas un N/D silencieux.
(d) TEST2 reste cohérent après re-refresh :
    operators = `["Bouygues","Free","Orange"]`, captures=9.
(e) Couverture 11 MNO : la table `PLMN_TO_OPERATOR` contient
    exactement les 11 PLMN MNO FR métropole, chacun au bon libellé.
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


def _encode_lte_sib1(mcc, mnc, cell_id_int: int = 0) -> str:
    """SIB1 LTE minimale avec le PLMN donné. Même pattern que G13."""
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


# ---------------------------------------------------------------------------
# (a) Fix bug mirror captures
# ---------------------------------------------------------------------------

def test_mirror_bug_fix_seeded_project_captures_unchanged():
    """Un projet seedé B0 (`n_captures_ingest=0`) doit garder ses captures
    seedés après `refresh_project_summary`."""
    from app.ingest.nmf import refresh_project_summary
    from app.models import Project

    with SessionLocal() as db:
        p = (
            db.query(Project).filter(Project.id == "idf-t3-2026").one_or_none()
        )
        if p is None:
            pytest.skip("Projet seedé Paris 2026 Q1 absent — garde impossible.")
        captures_before = p.captures
        n_captures_ingest_before = p.n_captures_ingest
        # Pré-condition du bug : captures seedé > 0 et n_captures_ingest = 0.
        assert captures_before and captures_before > 0, (
            f"Pré-condition violée : captures seedé attendu > 0, got {captures_before}"
        )
        assert n_captures_ingest_before == 0, (
            "Pré-condition violée : le bug se reproduit UNIQUEMENT si "
            f"n_captures_ingest=0 (ici {n_captures_ingest_before})."
        )

        refresh_project_summary(db, p)

        # Après fix : captures seedé inchangé.
        captures_after = p.captures
        assert captures_after == captures_before, (
            f"Bug mirror REPARU : captures passé de {captures_before} à {captures_after} "
            f"(n_captures_ingest={p.n_captures_ingest})"
        )


# ---------------------------------------------------------------------------
# (b) Doctrine 1.2.0 : un PLMN hors des 11 MNO n'est PAS étiqueté par
#     la marque hébergée — il remonte en « PLMN XXXXX (non catalogué) ».
# ---------------------------------------------------------------------------

def test_enrich_v12_mvno_plmn_not_mapped_falls_back_to_unknown():
    """`20825` (ex-Lyca Mobile) doit rester dans `plmns_unknown` et
    N'EST PAS mappé dans `operator_by_plmn`. L'étiquette finale visible
    côté bc4-back sera `"PLMN 20825 (non catalogué)"`."""
    import bc4_enrich

    assert bc4_enrich.__version__ == "bc4-enrich 1.2.0", bc4_enrich.__version__
    # Garde dure : aucun MVNO ne doit figurer dans la table.
    assert "20825" not in bc4_enrich.PLMN_TO_OPERATOR, (
        "Doctrine 1.2.0 violée : 20825 ne doit plus être catalogué "
        f"(got {bc4_enrich.PLMN_TO_OPERATOR.get('20825')!r})"
    )

    sib1_hex = _encode_lte_sib1([2, 0, 8], [2, 5], 42)  # MCC=208, MNC=25 → 20825
    events = [
        {
            "system": "LTE",
            "freq": "6300",
            "message": "SystemInformationBlockType1",
            "payload_hex": sib1_hex,
        }
    ]
    ctx = bc4_enrich.detect_context(events)

    assert ctx["operator_by_plmn"] == {}, ctx["operator_by_plmn"]
    assert ctx["operators"] == []
    assert "20825" in ctx["plmns_unknown"], ctx["plmns_unknown"]


def test_enrich_v12_covers_all_mno_plmns():
    """La table `PLMN_TO_OPERATOR` contient exactement les 11 PLMN MNO
    FR métropole, chacun au bon libellé. Aucune entrée MVNO."""
    import bc4_enrich

    expected = {
        # Orange
        "20801": "Orange",
        "20802": "Orange",
        # SFR
        "20809": "SFR",
        "20810": "SFR",
        "20811": "SFR",
        "20813": "SFR",
        # Bouygues
        "20820": "Bouygues",
        "20821": "Bouygues",
        "20888": "Bouygues",
        # Free
        "20815": "Free",
        "20816": "Free",
    }
    assert bc4_enrich.PLMN_TO_OPERATOR == expected, (
        f"Table PLMN_TO_OPERATOR divergente : "
        f"got {sorted(bc4_enrich.PLMN_TO_OPERATOR.items())}, "
        f"expected {sorted(expected.items())}"
    )
    assert len(bc4_enrich.PLMN_TO_OPERATOR) == 11


# ---------------------------------------------------------------------------
# (c) PLMN inconnu visible dans project.operators
# ---------------------------------------------------------------------------

def test_unknown_plmn_visible_in_project_operators():
    """Un PLMN hors table doit remonter en « PLMN XXXXX (non catalogué) »
    dans `project.operators`, pas disparaître en N/D silencieux.

    On construit un projet jetable avec un stg_event SIB1 porteur d'un
    PLMN inconnu (`20899`), on lance `refresh_project_summary`, et on
    vérifie l'étiquette.
    """
    from app.ingest.nmf import refresh_project_summary
    from app.models import Project

    pid = f"g15-unk-{uuid.uuid4().hex[:8]}"
    sib1_hex = _encode_lte_sib1([2, 0, 8], [9, 9], 123)  # 20899 (hors table)

    with SessionLocal() as db:
        # Projet minimal (schéma B0 — champs obligatoires peuplés en
        # neutre). On N'EST PAS en train de tester l'ingestion, juste
        # la boucle refresh.
        db.execute(
            text(
                "INSERT INTO projects "
                "(id, name, geography, center_lng, center_lat, operators, "
                " technologies, services, bands, departements, period_start, "
                " period_end, captures, imported_at, status, status_ingest, "
                " technos_seen, created_at) "
                "VALUES (:id, :name, 'G15-fixture', 0.0, 0.0, "
                "cast('[]' as json), cast('[]' as json), cast('[]' as json), "
                "cast('[]' as json), cast('[]' as json), '2026-01-01', "
                "'2026-01-31', 0, '2026-01-31', 'processing', 'draft', "
                "cast('{}' as json), NOW())"
            ),
            {"id": pid, "name": pid},
        )
        # Un nmf_file factice (FK obligatoire) + un stg_event SIB1 LTE
        # porteur du payload inconnu.
        fid = f"g15-f-{uuid.uuid4().hex[:8]}"
        db.execute(
            text(
                "INSERT INTO nmf_file "
                "(id, project_id, filename, size_bytes, sha256, uploaded_at, "
                " status, n_captures, n_events, n_gps) "
                "VALUES (:fid, :pid, 'g15.nmf', 0, :sha, NOW(), 'ready', "
                "0, 1, 0)"
            ),
            {"fid": fid, "pid": pid, "sha": fid},
        )
        db.execute(
            text(
                "INSERT INTO stg_event "
                "(project_id, nmf_file_id, capture_id, seq, event_code, "
                " system, message, freq, payload_hex) "
                "VALUES (:pid, :fid, :cap, 1, 'RRCSM', 'LTE', "
                "'SystemInformationBlockType1', '6300', :hex)"
            ),
            {"pid": pid, "fid": fid, "cap": "g15unk00001", "hex": sib1_hex},
        )
        db.commit()

        try:
            p = db.query(Project).filter(Project.id == pid).one()
            refresh_project_summary(db, p)
            ops = list(p.operators or [])
            assert any("PLMN 20899 (non catalogué)" == o for o in ops), (
                f"Attendu « PLMN 20899 (non catalogué) » dans project.operators, got {ops}"
            )
            # Et operators_plmn doit garder la trace brute.
            assert "20899" in (p.operators_plmn or {}), p.operators_plmn
        finally:
            db.execute(text("DELETE FROM stg_event WHERE project_id = :pid"), {"pid": pid})
            db.execute(text("DELETE FROM nmf_file WHERE project_id = :pid"), {"pid": pid})
            db.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": pid})
            db.commit()


# ---------------------------------------------------------------------------
# (d) TEST2 reste cohérent après re-refresh
# ---------------------------------------------------------------------------

def test_test2_stays_coherent_after_refresh():
    """TEST2 est le seul projet avec ingest réel. Après re-refresh,
    operators doit rester {Bouygues, Free, Orange} et captures = 9."""
    from app.ingest.nmf import refresh_project_summary
    from app.models import Project

    with SessionLocal() as db:
        p = db.query(Project).filter(Project.name == "TEST2").one_or_none()
        if p is None:
            pytest.skip("TEST2 absent — garde impossible.")

        captures_before = p.captures
        operators_before = sorted(p.operators or [])

        refresh_project_summary(db, p)

        assert p.captures == captures_before, (
            f"TEST2 captures changé : {captures_before} → {p.captures}"
        )
        # TEST2 doit toujours contenir au minimum les 3 MNO observés en live.
        ops_after = set(p.operators or [])
        assert {"Bouygues", "Free", "Orange"} <= ops_after, (
            f"TEST2 operators dégradés : before={operators_before}, after={sorted(ops_after)}"
        )
