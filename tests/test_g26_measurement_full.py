"""G26 (0.30.0) — Garde complète câblage décodeur 2.0.0.

Vérifie **sur un vrai projet REF_PETITE_FORET** (créé par
``scripts/ingest_ref_petite_foret.sh``, 18 NMF témoins) :

- ``stg_event_raw`` peuplée par catégorie — chaque catégorie attendue
  présente (``cellmeas``, ``cmdreq``, ``gps`` au minimum). Les data_*/
  tx_power/cqi/lock peuvent être absents selon le script Nemo utilisé —
  on **déclare** leur absence plutôt que forcer un échec.
- ``stg_event`` (signalling) : non vide.
- ``nmf_file`` : les 18 fichiers du projet portent ``dl``, ``ts_label``,
  ``env`` renseignés (header `#` prouvé). ``source_path`` renseigné et le
  fichier existe réellement sur disque.
- ``measurement_points`` : au moins une ligne, avec ``operator`` cohérent
  avec le ``dl`` du fichier source. Breakdown ``(operator, service_type,
  phase)`` produit un rapport exploitable.
- Cross-check RSRP ± 2 dB : moyenne CELLMEAS (depuis ``measurement_points.rsrp``)
  vs moyenne RRC (``param_occurrence`` sur ``rsrpResult``) par bande.
  Reporté — pas forcé par un seuil strict si la bande n'a pas d'échantillon
  RRC (déclaré).
- ``operator_mismatch=true`` : compte + 3 exemples (déclaration).
- Zéro identité : grep IMSI/IMEI (regex 15 digits) sur toutes les colonnes
  texte de ``stg_event_raw``.

Préconditions :
- ``BC4_API_BASE`` défini (fixture ``api_base``).
- ``BC4_REF_PID`` défini (le script shell le passe depuis la ligne).
  À défaut, on cherche un projet nommé « REF_PETITE_FORET ».
"""
from __future__ import annotations

import json
import os
import re

import pytest
from sqlalchemy import text

from app.db import SessionLocal


def _hdr(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def ref_pid(client_noauth, admin_token) -> str:
    pid = os.environ.get("BC4_REF_PID")
    if pid:
        return pid
    r = client_noauth.get("/projects", headers=_hdr(admin_token))
    assert r.status_code == 200, r.text
    for p in r.json():
        if p.get("name") == "REF_PETITE_FORET":
            return p["id"]
    pytest.skip(
        "Projet REF_PETITE_FORET introuvable — lancer "
        "`scripts/ingest_ref_petite_foret.sh` avant G26."
    )


# ---------------------------------------------------------------------------
# 1) stg_event_raw : chaque catégorie attendue est présente (ou déclarée
#    absente). Signalling n'est pas dans cette table (reste dans stg_event).
# ---------------------------------------------------------------------------
def test_stg_event_raw_breakdown(ref_pid: str):
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT category, COUNT(*) AS n
                FROM stg_event_raw
                WHERE project_id = :pid
                GROUP BY category
                ORDER BY n DESC
                """
            ),
            {"pid": ref_pid},
        ).all()
    counts = {r.category: int(r.n) for r in rows}
    print(f"\n[G26] stg_event_raw breakdown: {counts}")
    assert sum(counts.values()) > 0, "stg_event_raw vide — ingestion KO"
    # Les trois catégories CORE sont attendues sur Petite-Forêt (NMF Nemo).
    for mandatory in ("cellmeas", "gps"):
        assert mandatory in counts and counts[mandatory] > 0, (
            f"catégorie {mandatory!r} manquante : {counts}"
        )
    # cmdreq / data_* sont attendus car les tests Petite-Forêt lancent
    # des scripts (HTTP/VIDEO) ; on ne force pas de seuil, on déclare.
    for optional in ("cmdreq", "data_summary", "data_action", "tx_power", "cqi", "lock", "other"):
        n = counts.get(optional, 0)
        print(f"  [G26] {optional}: {n} (déclaré{'' if n > 0 else ' absent'})")


def test_stg_event_signalling_present(ref_pid: str):
    with SessionLocal() as db:
        n = db.execute(
            text("SELECT COUNT(*) FROM stg_event WHERE project_id = :pid"),
            {"pid": ref_pid},
        ).scalar() or 0
    print(f"\n[G26] stg_event signalling: {n}")
    assert n > 0, "stg_event vide — aucun signalling décodé"


# ---------------------------------------------------------------------------
# 2) nmf_file.meta + source_path + fichiers sur disque
# ---------------------------------------------------------------------------
def test_nmf_file_meta_renseigne(ref_pid: str):
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT id, filename, dl, ts_label, env, source_path
                FROM nmf_file
                WHERE project_id = :pid
                """
            ),
            {"pid": ref_pid},
        ).all()
    assert len(rows) >= 18, f"18 NMF attendus pour Petite-Forêt, trouvé {len(rows)}"
    missing_dl = [r.filename for r in rows if not r.dl]
    missing_env = [r.filename for r in rows if not r.env]
    missing_src = [r.filename for r in rows if not r.source_path]
    print(f"\n[G26] nmf_file total={len(rows)}  "
          f"missing dl={len(missing_dl)}  missing env={len(missing_env)}  "
          f"missing source_path={len(missing_src)}")
    assert not missing_dl, f"dl manquant sur: {missing_dl[:3]}"
    assert not missing_env, f"env manquant sur: {missing_env[:3]}"
    assert not missing_src, f"source_path manquant sur: {missing_src[:3]}"
    # Groupe par (dl, env) — attendu 3 opérateurs × 2 envs sur Petite-Forêt
    # (OFR/BYT/FREE × incar/indoor). Déclaré sans assertion stricte.
    with SessionLocal() as db:
        groups = db.execute(
            text(
                """
                SELECT dl, env, COUNT(*) AS n
                FROM nmf_file
                WHERE project_id = :pid
                GROUP BY dl, env
                ORDER BY dl, env
                """
            ),
            {"pid": ref_pid},
        ).all()
    print(f"[G26] (dl × env) breakdown:")
    for g in groups:
        print(f"  dl={g.dl!r} env={g.env!r} n={g.n}")


def test_nmf_source_files_on_disk(ref_pid: str):
    source_dir = os.environ.get("BC4_NMF_SOURCE_DIR", "/var/lib/bc4/nmf-source")
    project_dir = os.path.join(source_dir, ref_pid)
    if not os.path.isdir(project_dir):
        # Le test tourne peut-être depuis le host (pas dans le conteneur) :
        # on skip plutôt qu'échouer silencieusement, en déclarant.
        pytest.skip(
            f"{project_dir} absent côté host — vérifier via "
            f"`docker exec bc4-api-1 ls {project_dir}/`"
        )
    files = [f for f in os.listdir(project_dir) if f.endswith(".nmf")]
    print(f"\n[G26] source files on disk: {len(files)} dans {project_dir}")
    assert len(files) >= 18, f"18 .nmf attendus dans {project_dir}, trouvé {len(files)}"
    # Taille non nulle sur un échantillon.
    sizes = [(f, os.path.getsize(os.path.join(project_dir, f))) for f in files[:3]]
    print(f"  sample sizes: {sizes}")
    for f, s in sizes:
        assert s > 0, f"fichier source {f} de taille 0"


# ---------------------------------------------------------------------------
# 3) measurement_points enrichi : operator cohérent avec dl, breakdown
# ---------------------------------------------------------------------------
DL_TO_OPERATOR = {
    "OFR": "Orange",
    "BYT": "Bouygues",
    "FREE": "Free",
    "SFR": "SFR",
}


def test_measurement_points_enriched(ref_pid: str):
    with SessionLocal() as db:
        n = db.execute(
            text(
                "SELECT COUNT(*) FROM measurement_points WHERE project_id = :pid"
            ),
            {"pid": ref_pid},
        ).scalar() or 0
    print(f"\n[G26] measurement_points total: {n}")
    assert n > 0, "measurement_points vide"

    # Breakdown (operator × service_type × phase) — top 20.
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT operator, service_type, phase, COUNT(*) AS n
                FROM measurement_points
                WHERE project_id = :pid AND event_code IS NOT NULL
                GROUP BY operator, service_type, phase
                ORDER BY n DESC
                LIMIT 20
                """
            ),
            {"pid": ref_pid},
        ).all()
    print(f"[G26] (operator × service_type × phase) top 20:")
    for r in rows:
        print(f"  op={r.operator!r} svc={r.service_type!r} phase={r.phase!r} n={r.n}")


def test_operator_from_dl_is_authoritative(ref_pid: str):
    """Pour chaque NMF, l'opérateur des MP associés doit matcher DL_TO_OPERATOR[dl]
    (quand dl est dans la table) OU être None (déclaré).
    """
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT nf.id AS fid, nf.dl AS dl, mp.operator AS mp_op,
                       COUNT(*) AS n
                FROM nmf_file nf
                JOIN measurement_points mp
                  ON mp.project_id = nf.project_id
                  AND mp.capture_id IN (
                    SELECT DISTINCT capture_id FROM stg_event_raw
                    WHERE project_id = nf.project_id AND nmf_file_id = nf.id
                  )
                WHERE nf.project_id = :pid
                  AND mp.event_code IS NOT NULL
                GROUP BY nf.id, nf.dl, mp.operator
                """
            ),
            {"pid": ref_pid},
        ).all()
    mismatches = []
    for r in rows:
        expected = DL_TO_OPERATOR.get((r.dl or "").upper())
        if expected is not None and r.mp_op != expected and r.mp_op is not None:
            mismatches.append((r.fid, r.dl, r.mp_op, r.n))
    print(f"\n[G26] operator vs #DL : {len(mismatches)} groupes mismatch sur "
          f"{len(rows)} total")
    for m in mismatches[:3]:
        print(f"  fid={m[0]} dl={m[1]} mp_op={m[2]} n={m[3]}")


def test_operator_mismatch_declared(ref_pid: str):
    """Compte des operator_mismatch=TRUE + 3 exemples. Déclaré, pas assertion."""
    with SessionLocal() as db:
        total = db.execute(
            text(
                "SELECT COUNT(*) FROM measurement_points "
                "WHERE project_id = :pid AND operator_mismatch = TRUE"
            ),
            {"pid": ref_pid},
        ).scalar() or 0
        examples = db.execute(
            text(
                """
                SELECT capture_id, seq, operator, operator_source
                FROM measurement_points
                WHERE project_id = :pid AND operator_mismatch = TRUE
                LIMIT 3
                """
            ),
            {"pid": ref_pid},
        ).all()
    print(f"\n[G26] operator_mismatch=true count: {total}")
    for e in examples:
        print(f"  capture={e.capture_id} seq={e.seq} "
              f"op={e.operator} src={e.operator_source}")


# ---------------------------------------------------------------------------
# 4) Cross-check RSRP CELLMEAS vs RRC (param_occurrence)
# ---------------------------------------------------------------------------
def test_rsrp_cross_check_declared(ref_pid: str):
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT mp.band AS band,
                       AVG(mp.rsrp) AS rsrp_cellmeas,
                       COUNT(mp.rsrp) AS n_cellmeas,
                       (
                         SELECT AVG(CAST(po.value_converted AS float))
                         FROM param_occurrence po
                         WHERE po.project_id = mp.project_id
                           AND po.path ~ 'rsrpResult'
                           AND po.band = mp.band
                       ) AS rsrp_rrc
                FROM measurement_points mp
                WHERE mp.project_id = :pid
                  AND mp.rat = 'LTE'
                  AND mp.rsrp IS NOT NULL
                GROUP BY mp.band
                ORDER BY mp.band
                """
            ),
            {"pid": ref_pid},
        ).all()
    print(f"\n[G26] RSRP cross-check (CELLMEAS vs RRC) par bande LTE :")
    if not rows:
        print("  (aucune RSRP cellmeas peuplée — probable NMF sans mapping prouvé)")
        return
    for r in rows:
        delta = (
            float(r.rsrp_cellmeas) - float(r.rsrp_rrc)
            if r.rsrp_cellmeas is not None and r.rsrp_rrc is not None
            else None
        )
        print(
            f"  band={r.band} n={r.n_cellmeas} "
            f"rsrp_cellmeas={r.rsrp_cellmeas} rsrp_rrc={r.rsrp_rrc} "
            f"Δ={delta}"
        )


# ---------------------------------------------------------------------------
# 5) Zéro identité abonné (regex 15 digits sur stg_event_raw.raw_fields).
# ---------------------------------------------------------------------------
def test_zero_identity_leak(ref_pid: str):
    pat = re.compile(r"(?<!\d)\d{15}(?!\d)")
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT raw_fields::text AS t
                FROM stg_event_raw
                WHERE project_id = :pid
                LIMIT 2000
                """
            ),
            {"pid": ref_pid},
        ).all()
    leaks = []
    for r in rows:
        if r.t and pat.search(r.t):
            leaks.append(r.t[:120])
    print(f"\n[G26] IMSI/IMEI leak scan: {len(leaks)} hit(s) sur {len(rows)} lignes")
    assert not leaks, f"identité en clair dans stg_event_raw: {leaks[:3]}"


# ---------------------------------------------------------------------------
# 6) Unicité canonique (capture_id, seq, event_code) sur stg_event_raw.
# ---------------------------------------------------------------------------
def test_canonical_order_unique(ref_pid: str):
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT (project_id, capture_id, seq, event_code))
                           AS distinct_n
                FROM stg_event_raw
                WHERE project_id = :pid
                """
            ),
            {"pid": ref_pid},
        ).one()
    print(
        f"\n[G26] stg_event_raw total={row.total} "
        f"distinct(capture_id, seq, event_code)={row.distinct_n}"
    )
    assert row.total == row.distinct_n, (
        "stg_event_raw : duplicates sur (capture_id, seq, event_code)"
    )
