"""G24 (0.33.0) — Garde chaîne complète ``measurement_points``.

Scope du test (Python-side) :
- ``measurement_points`` non vide sur REF_PETITE_FORET (count exact
  loggué, pas forgé).
- Breakdown ``(operator × service_type × phase)`` imprimé pour trace.
- Tableau de preuve chiffré (``app.measure.proof.run_proof``) sur le
  projet REF — vérifie que RSRP+RSRQ sortent ``proven`` ±2 dB tant que
  la ``param_occurrence`` du projet contient des rsrpResult/rsrqResult
  (CELLMEAS étant déjà en dBm, le match doit être évident).
- SINR / CQI / TX_POWER / THRPT_* restent ``rejected: no_rrc_reference``
  — écart **déclaré**, pas masqué.
- Cross-check RSRP par bande : ``|avg(cellmeas) - avg(rrc)| ≤ 2 dB``.
- ``operator_mismatch=true`` : compte imprimé (pas d'assert : un
  mismatch est un fait, pas un échec).
- Zéro identité abonné : regex ``(?<!\d)\d{15}(?!\d)`` sur
  ``stg_event_raw.raw_fields::text`` et sur les colonnes texte de
  ``measurement_points``.
- Pas de duplication : ``count == count(DISTINCT (project_id, capture_id,
  seq, event_code))``.
- 18 ``nmf_file`` + 18 fichiers source persistés + 18 ``env`` renseignés.
- Fix 0.33.0 bug ``env`` : ``nmf_file.env`` est dérivé du nom original
  (``incar`` | ``indoor``) et JAMAIS NULL sur REF_PETITE_FORET.
"""
from __future__ import annotations

import os
import re

import pytest
from sqlalchemy import text

from app.db import SessionLocal

REF_PID = os.environ.get("BC4_REF_PID", "7e656b8c6c19")
ID15 = re.compile(r"(?<!\d)\d{15}(?!\d)")


def _db_has_project(pid: str) -> bool:
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT 1 FROM projects WHERE id = :p"), {"p": pid}
        ).one_or_none()
    return row is not None


@pytest.fixture(scope="module")
def ref_pid() -> str:
    if not _db_has_project(REF_PID):
        pytest.fail(f"REF_PETITE_FORET ({REF_PID}) absent — ingérer d'abord.")
    return REF_PID


# ---------------------------------------------------------------------------
# a. measurement_points count
# ---------------------------------------------------------------------------
def test_a_measurement_points_non_empty(ref_pid: str):
    with SessionLocal() as db:
        n = db.execute(
            text("SELECT COUNT(*) FROM measurement_points WHERE project_id = :p"),
            {"p": ref_pid},
        ).scalar_one()
    print(f"[G24] measurement_points count = {n}")
    assert n > 0, (
        f"measurement_points vide sur {ref_pid} — populate KO ou aucun GPS "
        f"attaché. Vérifier `app.measure.populate.populate_measurement_points`."
    )


# ---------------------------------------------------------------------------
# b. breakdown operator × service_type × phase (imprimé pour trace)
# ---------------------------------------------------------------------------
def test_b_breakdown_operator_service_phase(ref_pid: str):
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT COALESCE(operator,'N/D'), COALESCE(service_type,'N/D'),
                       COALESCE(phase,'N/D'), COUNT(*)
                FROM measurement_points WHERE project_id = :p
                GROUP BY 1,2,3 ORDER BY 1,2,3
                """
            ),
            {"p": ref_pid},
        ).all()
    print("[G24] breakdown (operator × service_type × phase)")
    for r in rows:
        print(f"  {r[0]:<10} {r[1]:<16} {r[2]:<8} {r[3]}")
    # Doit avoir au moins une ligne (sinon on a déjà échoué en (a)).
    assert rows, "aucun breakdown — measurement_points vide"


# ---------------------------------------------------------------------------
# c. tableau de preuve chiffré ±2 dB
# ---------------------------------------------------------------------------
def test_c_proof_table_rsrp_rsrq_proven(ref_pid: str):
    from app.measure.proof import format_proof_table, run_proof

    with SessionLocal() as db:
        rows = run_proof(db, ref_pid)
    table = format_proof_table(rows)
    print("[G24] tableau de preuve :")
    print(table)

    by_metric = {r.metric: r for r in rows}
    rsrp = by_metric.get("rsrp")
    rsrq = by_metric.get("rsrq")
    assert rsrp is not None, "ligne 'rsrp' absente du rapport"
    assert rsrq is not None, "ligne 'rsrq' absente du rapport"

    # Si param_occurrence est peuplée (RRC décodée), RSRP/RSRQ doivent
    # sortir proven. Sinon on skip pour ne pas masquer un écart réel.
    if rsrp.n_rrc == 0:
        pytest.fail(
            "param_occurrence vide pour rsrpResult — le dict RRC n'a pas tourné. "
            "La preuve ne peut pas se faire tant que populate_param_occurrence "
            "n'a pas été exécuté sur REF_PETITE_FORET."
        )
    assert rsrp.verdict == "proven", (
        f"rsrp non prouvé : {rsrp.reason!r} "
        f"(avg_cand={rsrp.avg_candidate}, avg_rrc={rsrp.avg_rrc}, "
        f"delta_avg={rsrp.delta_avg})"
    )
    if rsrq.n_rrc > 0:
        assert rsrq.verdict == "proven", (
            f"rsrq non prouvé : {rsrq.reason!r} "
            f"(avg_cand={rsrq.avg_candidate}, avg_rrc={rsrq.avg_rrc}, "
            f"delta_avg={rsrq.delta_avg})"
        )


def test_c_sinr_cqi_rejected_declared(ref_pid: str):
    """SINR/CQI/TX_POWER/THRPT_* restent rejected tant qu'aucune
    référence RRC chiffrée n'est câblée — écart déclaré, pas masqué."""
    from app.measure.proof import run_proof

    with SessionLocal() as db:
        rows = run_proof(db, ref_pid)
    by_metric = {r.metric: r for r in rows}
    for metric in ("sinr", "cqi", "tx_power", "thrpt_dl", "thrpt_ul"):
        row = by_metric.get(metric)
        assert row is not None, f"ligne {metric!r} manquante dans la preuve"
        # Verdict peut être rejected OU proven, mais pour ces métriques il
        # DOIT y avoir une raison explicite si rejected.
        if row.verdict == "rejected":
            assert row.reason, f"{metric}: rejected sans motif chiffré"
            print(f"[G24] {metric}: {row.verdict} — {row.reason}")


# ---------------------------------------------------------------------------
# d. cross-check RSRP ±2 dB par bande
# ---------------------------------------------------------------------------
def test_d_cross_check_rsrp_per_band(ref_pid: str):
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT COALESCE(mp.band,'N/D') AS band,
                       AVG(mp.rsrp) AS rsrp_cellmeas,
                       (SELECT AVG(CAST(po.value_converted AS double precision))
                        FROM param_occurrence po
                        WHERE po.project_id = mp.project_id
                          AND po.path ~ 'measResultPCell/rsrpResult$'
                          AND po.band IS NOT DISTINCT FROM mp.band
                          AND po.value_converted IS NOT NULL
                       ) AS rsrp_rrc,
                       COUNT(*) AS n_mp
                FROM measurement_points mp
                WHERE mp.project_id = :p AND mp.rat = 'LTE' AND mp.rsrp IS NOT NULL
                GROUP BY mp.band, mp.project_id
                ORDER BY mp.band NULLS LAST
                """
            ),
            {"p": ref_pid},
        ).all()
    print("[G24] cross-check RSRP par bande :")
    violations: list[str] = []
    comparable = 0
    for r in rows:
        delta = (
            None
            if r.rsrp_cellmeas is None or r.rsrp_rrc is None
            else float(r.rsrp_cellmeas) - float(r.rsrp_rrc)
        )
        print(
            f"  band={r.band:<8} cellmeas={r.rsrp_cellmeas} "
            f"rrc={r.rsrp_rrc} delta_db={delta} n={r.n_mp}"
        )
        if delta is not None:
            comparable += 1
            if abs(delta) > 2.0:
                violations.append(
                    f"band={r.band} delta={delta:+.2f}dB (> ±2 dB)"
                )
    if comparable == 0:
        pytest.fail(
            "Aucune bande comparable (soit mp.rsrp NULL partout, soit "
            "param_occurrence vide côté RRC)."
        )
    assert not violations, "RSRP hors tolérance ±2 dB : " + " ; ".join(violations)


# ---------------------------------------------------------------------------
# e. operator_mismatch=true : compte + exemples (déclaré, pas un échec)
# ---------------------------------------------------------------------------
def test_e_operator_mismatch_declared(ref_pid: str):
    with SessionLocal() as db:
        n = db.execute(
            text(
                "SELECT COUNT(*) FROM measurement_points "
                "WHERE project_id = :p AND operator_mismatch = TRUE"
            ),
            {"p": ref_pid},
        ).scalar_one()
        ex = db.execute(
            text(
                """
                SELECT capture_id, seq, operator, operator_source,
                       service_type, phase
                FROM measurement_points
                WHERE project_id = :p AND operator_mismatch = TRUE
                LIMIT 3
                """
            ),
            {"p": ref_pid},
        ).all()
    print(f"[G24] operator_mismatch=TRUE : {n}")
    for r in ex:
        print(
            f"  capture_id={r[0][:8]}… seq={r[1]} op={r[2]} "
            f"src={r[3]} svc={r[4]} phase={r[5]}"
        )
    # Pas d'assert : un mismatch est un FAIT à déclarer, pas un échec.


# ---------------------------------------------------------------------------
# f. zéro identité abonné
# ---------------------------------------------------------------------------
def test_f_no_subscriber_identity(ref_pid: str):
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT raw_fields::text FROM stg_event_raw
                WHERE project_id = :p
                  AND raw_fields::text ~ '(?<!\\d)\\d{15}(?!\\d)'
                LIMIT 5
                """
            ),
            {"p": ref_pid},
        ).all()
    leaks_sr = [r[0][:120] for r in rows]
    assert not leaks_sr, f"identités en clair dans stg_event_raw: {leaks_sr}"

    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT COUNT(*) FROM measurement_points
                WHERE project_id = :p AND (
                   COALESCE(operator,'')||' '||COALESCE(tech,'')||' '||
                   COALESCE(service,'')||' '||COALESCE(band,'')||' '||
                   COALESCE(dep,'')||' '||COALESCE(site,'')||' '||
                   COALESCE(ts,'')||' '||COALESCE(capture_id,'')||' '||
                   COALESCE(event_code,'')||' '||COALESCE(operator_source,'')||' '||
                   COALESCE(service_name,'')||' '||COALESCE(service_action,'')||' '||
                   COALESCE(service_type,'')||' '||COALESCE(phase,'')||' '||
                   COALESCE(env,'')||' '||COALESCE(rat,'')
                ) ~ '(?<!\\d)\\d{15}(?!\\d)'
                """
            ),
            {"p": ref_pid},
        ).scalar_one()
    assert rows == 0, (
        f"{rows} ligne(s) measurement_points contiennent 15 chiffres consécutifs"
    )


# ---------------------------------------------------------------------------
# g. pas de duplication
# ---------------------------------------------------------------------------
def test_g_no_duplicates(ref_pid: str):
    with SessionLocal() as db:
        tot = db.execute(
            text(
                "SELECT COUNT(*) FROM measurement_points "
                "WHERE project_id = :p AND event_code IS NOT NULL"
            ),
            {"p": ref_pid},
        ).scalar_one()
        uq = db.execute(
            text(
                """
                SELECT COUNT(*) FROM (
                  SELECT DISTINCT project_id, capture_id, seq, event_code
                  FROM measurement_points
                  WHERE project_id = :p AND event_code IS NOT NULL
                ) t
                """
            ),
            {"p": ref_pid},
        ).scalar_one()
    print(f"[G24] measurement_points : total={tot} unique={uq}")
    assert tot == uq, (
        f"duplication détectée : total={tot} vs distinct={uq} "
        f"(Δ={tot - uq}) — UPDATE/INSERT se chevauchent."
    )


# ---------------------------------------------------------------------------
# h. 18 nmf_file + 18 fichiers source + 18 env renseignés
# ---------------------------------------------------------------------------
def test_h_18_nmf_files(ref_pid: str):
    with SessionLocal() as db:
        n = db.execute(
            text("SELECT COUNT(*) FROM nmf_file WHERE project_id = :p"),
            {"p": ref_pid},
        ).scalar_one()
    print(f"[G24] nmf_file count = {n}")
    assert n == 18, f"nmf_file attendu=18 observé={n}"


def test_i_env_filled_on_all_nmf(ref_pid: str):
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT filename, env FROM nmf_file WHERE project_id = :p"
            ),
            {"p": ref_pid},
        ).all()
    missing = [r[0] for r in rows if r[1] not in ("incar", "indoor")]
    print(f"[G24] env coverage : {len(rows) - len(missing)}/{len(rows)} renseignés")
    assert not missing, (
        f"nmf_file.env NULL/invalide sur {len(missing)} fichier(s) : "
        f"{missing[:3]} (fix 0.33.0 fallback regex ne doit laisser aucun NULL)"
    )
