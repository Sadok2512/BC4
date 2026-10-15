"""G6 — upload de la référence cellulaire sur un lot témoin.

- Rejoue un petit CSV calibré (lignes conformes + rejets variés) ;
- vérifie que l'ImportReport renvoyé correspond au comptage réel ;
- vérifie l'idempotence (deuxième upload du même CSV ne duplique rien) ;
- vérifie bands_unmapped (bande hors table → écart ouvert déclaré) ;
- vérifie l'historique /imports et /summary.
"""

from __future__ import annotations

import io

import pytest
from sqlalchemy import text

from app.db import SessionLocal


SAMPLE_HEADER = (
    "id,snapshot_date,rat,vendor,sac_ci_eci,nci,enodebid,pci,band,techno,"
    "earfcn,azimuth,tilt,height,coverage,cell_class,etat_fonctionnement,"
    "nom_upr,nom_dr,plaque_site,id_site,site_name,sector,cell_op_leader,"
    "cat_arcep_code,longitude,latitude"
)

SAMPLE_ROWS = [
    # id, snapshot, rat, vendor, eci, nci, enb, pci, band, techno, earfcn, az, tilt, h, cov, class, etat, upr, dr, plaque, site_id, site, sect, lead, arcep, lng, lat
    "c-001,2026-10-01,4G,Ericsson,41000001,,10001,21,LTE800,LTE,6400,120,2,30,outdoor,macro,OPERATIONAL,UPR-A,DR-IDF,Paris,SITE-01,Paris Opéra,1,Orange,01/ Top15,2.3350,48.8700",
    "c-002,2026-10-01,4G,Nokia,41000002,,10002,42,LTE1800,LTE,1850,240,3,25,outdoor,macro,OPERATIONAL,UPR-A,DR-IDF,Paris,SITE-01,Paris Opéra,2,Orange,01/ Top15,2.3400,48.8650",
    "c-003,2026-10-01,5G,Huawei,,51000003,,133,NR_3500,NR,632000,0,4,35,outdoor,macro,OPERATIONAL,UPR-B,DR-ARA,Lyon,SITE-02,Lyon Part-Dieu,1,SFR,02/ 200-400 K,4.8520,45.7600",
    # Unknown band → bands_unmapped should carry it ; cat_arcep = `(null)` littéral → bucket __null
    "c-004,2026-10-01,4G,Nokia,41000004,,10003,55,LTE_900,LTE,3700,180,2,22,outdoor,macro,SWITCHED_OFF,UPR-A,DR-IDF,Paris,SITE-03,Paris Nord,1,Orange,(null),2.3500,48.8800",
    # Bad position (lat 27 → hors France)
    "c-005,2026-10-01,4G,Ericsson,41000005,,10005,10,LTE800,LTE,6400,0,0,0,outdoor,macro,OPERATIONAL,UPR-A,DR-IDF,Paris,SITE-04,Alger,1,Orange,07/ Hors Agglo,3.0,27.0",
    # Missing eci on 4G
    "c-006,2026-10-01,4G,Ericsson,,,10006,10,LTE800,LTE,6400,0,0,0,outdoor,macro,OPERATIONAL,UPR-A,DR-IDF,Paris,SITE-05,Noname,1,Orange,01/ Top15,2.35,48.86",
    # Missing nci on 5G
    "c-007,2026-10-01,5G,Nokia,,,,10,NR_3500,NR,632000,0,0,0,outdoor,macro,OPERATIONAL,UPR-B,DR-ARA,Lyon,SITE-06,Noname,1,SFR,02/ 200-400 K,4.85,45.76",
    # Bad rat
    "c-008,2026-10-01,3G,Ericsson,41000008,,10008,10,LTE800,LTE,6400,0,0,0,outdoor,macro,OPERATIONAL,UPR-A,DR-IDF,Paris,SITE-07,Noname,1,Orange,01/ Top15,2.35,48.86",
    # Missing id
    ",2026-10-01,4G,Ericsson,41000009,,10009,10,LTE800,LTE,6400,0,0,0,outdoor,macro,OPERATIONAL,UPR-A,DR-IDF,Paris,SITE-08,Noname,1,Orange,01/ Top15,2.35,48.86",
]


def _csv_blob() -> bytes:
    return ("\n".join([SAMPLE_HEADER, *SAMPLE_ROWS, ""])).encode("utf-8")


def _reset_cell_ref() -> None:
    with SessionLocal() as db:
        db.execute(text("TRUNCATE TABLE cell_ref"))
        db.execute(text("TRUNCATE TABLE reference_import"))
        db.commit()


@pytest.fixture()
def clean_db():
    _reset_cell_ref()
    yield
    _reset_cell_ref()


def test_upload_witness_batch(client, admin_headers, clean_db):
    files = {"file": ("witness.csv", _csv_blob(), "text/csv")}
    r = client.post("/reference/cell/upload", files=files, headers=admin_headers)
    assert r.status_code == 200, r.text
    report = r.json()

    # ----- Chiffres doivent coller au contenu du CSV ligne par ligne -----
    assert report["rows_read"] == len(SAMPLE_ROWS)
    assert report["rows_loaded"] == 4  # c-001..c-004
    assert report["rows_rejected"] == len(SAMPLE_ROWS) - 4
    assert report["rejected_by_reason"] == {
        "bad_position": 1,
        "missing_eci": 1,
        "missing_nci": 1,
        "bad_rat": 1,
        "missing_id": 1,
    }
    assert report["by_rat"] == {"4G": 3, "5G": 1}
    assert report["bands_unmapped"] == {"LTE_900": 1}, "bande hors table doit être déclarée"
    assert report["etat_breakdown"] == {"OPERATIONAL": 3, "SWITCHED_OFF": 1}
    # Zone ARCEP (0.7.1) : 2 lignes `01/ Top15`, 1 ligne `02/ 200-400 K`,
    # 1 ligne source `(null)` littéral → bucket `__null`. Les libellés
    # source sont persistés tels quels, pas de normalisation.
    assert report["arcep_breakdown"] == {
        "01/ Top15": 2,
        "02/ 200-400 K": 1,
        "__null": 1,
    }
    # Garde-fou : la somme des buckets ARCEP == rows_loaded (comptage réel).
    assert sum(report["arcep_breakdown"].values()) == report["rows_loaded"]
    # ECI/NCI distincts
    assert report["distinct_eci"] == 3  # c-001, c-002, c-004
    assert report["distinct_nci"] == 1  # c-003
    assert report["snapshot_date"] == "2026-10-01"

    # ----- La ligne reference_import est écrite -----
    r2 = client.get("/reference/cell/imports", headers=admin_headers)
    assert r2.status_code == 200
    hist = r2.json()
    assert len(hist) == 1
    assert hist[0]["filename"] == "witness.csv"
    assert hist[0]["status"] == "completed"
    assert hist[0]["rows_loaded"] == 4

    # ----- Rejouer : idempotence sur id -----
    r3 = client.post(
        "/reference/cell/upload",
        files={"file": ("witness.csv", _csv_blob(), "text/csv")},
        headers=admin_headers,
    )
    assert r3.status_code == 200
    with SessionLocal() as db:
        n = db.execute(text("SELECT COUNT(*) FROM cell_ref")).scalar()
    assert n == 4, "upsert idempotent : le même CSV ne doit pas dupliquer"

    # ----- Summary -----
    r4 = client.get("/reference/cell/summary", headers=admin_headers)
    assert r4.status_code == 200
    summary = r4.json()
    assert summary["total"] == 4
    bands = {b["key"]: b["count"] for b in summary["by_band_3gpp"]}
    # LTE800→B20, LTE1800→B3, NR_3500→n78, LTE_900→N/D (unmapped)
    assert bands.get("B20") == 1
    assert bands.get("B3") == 1
    assert bands.get("n78") == 1
    assert bands.get("N/D") == 1
    # Zone ARCEP exposée via /summary (dimension orthogonale à la géo).
    # Les lignes NULL tombent sous `N/D` (via `_bucket()`), pas sous
    # `__null` qui est la clé du rapport d'import.
    arcep = {b["key"]: b["count"] for b in summary["arcep_breakdown"]}
    assert arcep.get("01/ Top15") == 2
    assert arcep.get("02/ 200-400 K") == 1
    assert arcep.get("N/D") == 1
    assert sum(arcep.values()) == summary["total"]


def test_band_map_contract():
    """G6-mapping : la table de mapping 3GPP est verrouillée.
    Toute addition/suppression doit passer par le CHANGELOG (bump) et
    casser ce test — jamais une édition silencieuse."""
    from app.services.cell_ref_ingest import BAND_MAP
    assert BAND_MAP == {
        "LTE700": "B28",
        "LTE800": "B20",
        "LTE900": "B8",
        "LTE1800": "B3",
        "LTE2100": "B1",
        "LTE2600": "B7",
        "NR_700": "n28",
        "NR_1400": "n75",
        "NR_1800": "n3",
        "NR_2100": "n1",
        "NR_2600": "n7",
        "NR_3500": "n78",
        "NR_26_GHZ_000": "n258",
    }


def test_upload_bad_header_422(client, admin_headers, clean_db):
    bad = b"foo,bar\n1,2\n"
    r = client.post(
        "/reference/cell/upload",
        files={"file": ("bad.csv", bad, "text/csv")},
        headers=admin_headers,
    )
    assert r.status_code == 422
    with SessionLocal() as db:
        n = db.execute(text("SELECT COUNT(*) FROM cell_ref")).scalar()
    assert n == 0, "en-tête non conforme : rien n'a été inséré"
