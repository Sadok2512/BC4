"""Preuve de mapping ``raw_fields → measurement_points`` (0.33.0).

Doctrine stricte : **avant** de mapper un champ de ``stg_event_raw.raw_fields``
vers une métrique ``measurement_points.{rsrp, rsrq, sinr, cqi, tx_power,
thrpt_dl, thrpt_ul}``, le mapping doit être **prouvé chiffré** contre la
source RRC décodée (``param_occurrence.value_converted``) sur le MÊME
projet. Un champ non prouvé = NULL **déclaré** à l'aval.

Méthode (strictement par le CONTENU) :

1. Pour chaque métrique candidate, on prend un échantillon de
   ``stg_event_raw`` (catégorie attendue, ex. ``cellmeas``) et de
   ``param_occurrence`` (chemin attendu, ex. ``rsrpResult$`` sur serving
   PCell). Les distributions sont comparées **sans appariement temporel**
   (RRC et CELLMEAS sont deux sources parallèles ; on compare leurs
   statistiques globales sur la même capture pour éviter d'inventer un
   lien ``(capture_id, seq)`` fictif entre deux events qui n'en ont pas).
2. Deux agrégats sont calculés : ``avg`` et ``p50`` (médiane). Preuve
   ``±2 dB`` : ``|avg(candidate) − avg(rrc)| ≤ 2 dB`` ET ``|p50(candidate)
   − p50(rrc)| ≤ 2 dB``.
3. Verdict : ``proven`` ou ``rejected``. Un verdict ``rejected`` ne
   masque jamais le candidat — il reste visible dans le tableau de
   preuve, pour que l'écart soit **déclaré** et pas enfoui.
4. La table ``MEASUREMENT_MAPPING`` consommée par
   ``app.measure.populate.populate_measurement_points`` **ne contient
   que les champs ``proven``**. Les ``rejected`` restent NULL à l'aval
   (jamais mappés à l'aveugle).

Les débits (``thrpt_dl`` / ``thrpt_ul``) ne sont **pas prouvés** par
cette boucle RRC (il n'existe pas d'équivalent RRC natif). Ils restent
``rejected: no_rrc_reference`` tant qu'une référence externe n'est pas
câblée (ex. iPerf GT dans le script NEMO). Mêmes règles pour ``cqi`` et
``tx_power`` : s'il n'y a pas de référence RRC chiffrée, on **déclare**
l'écart ouvert plutôt que d'inventer.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


DELTA_DB_TOLERANCE: float = 2.0  # Preuve ±2 dB (seuil doctrine).
PROOF_SAMPLE_LIMIT: int = 2000   # Lignes max par source par métrique.


@dataclass
class ProofRow:
    """Verdict chiffré pour UN champ candidat vs UNE référence RRC."""
    metric: str                        # ``rsrp`` / ``rsrq`` / ``sinr`` / …
    candidate_field: str               # ex. ``cell0_rsrp_dbm``
    candidate_category: str            # ex. ``cellmeas``
    rrc_path_regex: str | None         # ex. ``rsrpResult$`` (serving)
    n_candidate: int
    n_rrc: int
    avg_candidate: float | None
    avg_rrc: float | None
    p50_candidate: float | None
    p50_rrc: float | None
    delta_avg: float | None
    delta_p50: float | None
    tolerance_db: float
    verdict: str                       # ``proven`` | ``rejected``
    reason: str                        # motif de rejet si verdict=rejected

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "candidate_field": self.candidate_field,
            "candidate_category": self.candidate_category,
            "rrc_path_regex": self.rrc_path_regex,
            "n_candidate": self.n_candidate,
            "n_rrc": self.n_rrc,
            "avg_candidate": self.avg_candidate,
            "avg_rrc": self.avg_rrc,
            "p50_candidate": self.p50_candidate,
            "p50_rrc": self.p50_rrc,
            "delta_avg": self.delta_avg,
            "delta_p50": self.delta_p50,
            "tolerance_db": self.tolerance_db,
            "verdict": self.verdict,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Table des candidats à prouver. L'ordre est significatif : premier
# candidat prouvé pour UNE métrique = mapping gagnant. Les candidats
# suivants restent dans le rapport (traçabilité) mais ne sont pas
# re-mappés.
# ---------------------------------------------------------------------------

CANDIDATES: list[dict[str, str]] = [
    # RSRP serving (PCell) depuis CELLMEAS vs rsrpResult (PCell) RRC.
    {"metric": "rsrp", "field": "cell0_rsrp_dbm", "category": "cellmeas",
     "rrc_path": "measResultPCell/rsrpResult$"},
    # RSRQ serving (PCell).
    {"metric": "rsrq", "field": "cell0_rsrq_db", "category": "cellmeas",
     "rrc_path": "measResultPCell/rsrqResult$"},
    # SINR : pas de référence RRC canonique en LTE Rel-8 (rs-sinr-r13
    # existe en LTE-A mais pas peuplé sur le corpus). Déclaré ``rejected:
    # no_rrc_reference`` par la boucle de preuve si n_rrc=0.
    {"metric": "sinr", "field": "cell0_sinr_db", "category": "cellmeas",
     "rrc_path": "rs-sinr-r13$"},
    # CQI : pas de référence RRC chiffrée partagée. Déclaré ouvert si
    # pas de match côté param_occurrence.
    {"metric": "cqi", "field": "cell0_c7", "category": "cellmeas",
     "rrc_path": "cqi-Report"},
    # TX Power : pas de référence RRC comparable (c'est une mesure UE,
    # pas une valeur dans un message RRC décodé). Déclaré ouvert.
    {"metric": "tx_power", "field": "c4", "category": "tx_power",
     "rrc_path": None},
    # Débit DL/UL : pas de référence RRC. Déclaré ouvert.
    {"metric": "thrpt_dl", "field": "bytes_transferred", "category": "data_summary",
     "rrc_path": None},
    {"metric": "thrpt_ul", "field": "bytes_transferred", "category": "data_summary",
     "rrc_path": None},
]


# ---------------------------------------------------------------------------
# Helpers de calcul statistique (tolérants au bruit).
# ---------------------------------------------------------------------------

def _to_floats(values: list[Any]) -> list[float]:
    """Convertit une liste de str/None en floats, drop les None/invalides.
    Jamais 0 par défaut : un échec de parse = valeur ignorée, pas forgée."""
    out: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            s = str(v).strip()
            if not s:
                continue
            out.append(float(s))
        except (TypeError, ValueError):
            continue
    return out


def _stats(xs: list[float]) -> tuple[float | None, float | None]:
    """Retourne (avg, p50) ou (None, None) si vide. Jamais 0 par défaut."""
    if not xs:
        return (None, None)
    return (statistics.fmean(xs), statistics.median(xs))


# ---------------------------------------------------------------------------
# Collecte des échantillons.
# ---------------------------------------------------------------------------

def _fetch_candidate_values(
    db: Session, project_id: str, category: str, field_name: str, limit: int
) -> list[Any]:
    """Lit ``raw_fields->>field_name`` sur un échantillon ``stg_event_raw``.

    Ordre canonique ``(capture_id, seq)`` strict — jamais ``ts``.
    """
    rows = db.execute(
        text(
            """
            SELECT raw_fields ->> :field AS v
            FROM stg_event_raw
            WHERE project_id = :pid AND category = :cat
              AND raw_fields ->> :field IS NOT NULL
            ORDER BY capture_id, seq
            LIMIT :lim
            """
        ),
        {"pid": project_id, "cat": category, "field": field_name, "lim": limit},
    ).all()
    return [r[0] for r in rows]


def _fetch_rrc_values(
    db: Session, project_id: str, path_regex: str, limit: int
) -> list[Any]:
    """Lit ``value_converted`` sur ``param_occurrence.path ~ path_regex``.

    Jamais appariement avec les CELLMEAS : on compare les distributions.
    """
    rows = db.execute(
        text(
            """
            SELECT value_converted
            FROM param_occurrence
            WHERE project_id = :pid
              AND path ~ :pat
              AND value_converted IS NOT NULL
            ORDER BY id
            LIMIT :lim
            """
        ),
        {"pid": project_id, "pat": path_regex, "lim": limit},
    ).all()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Boucle de preuve.
# ---------------------------------------------------------------------------

def run_proof(
    db: Session,
    project_id: str,
    tolerance_db: float = DELTA_DB_TOLERANCE,
    sample_limit: int = PROOF_SAMPLE_LIMIT,
) -> list[ProofRow]:
    """Exécute la boucle de preuve pour tous les candidats.

    Chaque entrée de ``CANDIDATES`` produit UN ``ProofRow`` chiffré.
    """
    results: list[ProofRow] = []
    for cand in CANDIDATES:
        metric = cand["metric"]
        field_name = cand["field"]
        category = cand["category"]
        rrc_path = cand.get("rrc_path")

        cand_raw = _fetch_candidate_values(
            db, project_id, category, field_name, sample_limit
        )
        cand_fx = _to_floats(cand_raw)

        rrc_fx: list[float] = []
        if rrc_path:
            rrc_raw = _fetch_rrc_values(db, project_id, rrc_path, sample_limit)
            rrc_fx = _to_floats(rrc_raw)

        avg_c, p50_c = _stats(cand_fx)
        avg_r, p50_r = _stats(rrc_fx)

        # Verdict : exige n_candidate > 0 ET n_rrc > 0 ET |delta| ≤ tol.
        verdict = "rejected"
        reason = ""
        delta_avg: float | None = None
        delta_p50: float | None = None

        if not cand_fx:
            reason = "no_candidate_sample"
        elif rrc_path is None:
            reason = "no_rrc_reference"
        elif not rrc_fx:
            reason = "no_rrc_sample"
        else:
            assert avg_c is not None and avg_r is not None
            assert p50_c is not None and p50_r is not None
            delta_avg = avg_c - avg_r
            delta_p50 = p50_c - p50_r
            if abs(delta_avg) <= tolerance_db and abs(delta_p50) <= tolerance_db:
                verdict = "proven"
                reason = ""
            else:
                reason = (
                    f"delta_out_of_tolerance "
                    f"avg={delta_avg:+.2f}dB p50={delta_p50:+.2f}dB "
                    f"tol=±{tolerance_db:.1f}dB"
                )

        results.append(
            ProofRow(
                metric=metric,
                candidate_field=field_name,
                candidate_category=category,
                rrc_path_regex=rrc_path,
                n_candidate=len(cand_fx),
                n_rrc=len(rrc_fx),
                avg_candidate=avg_c,
                avg_rrc=avg_r,
                p50_candidate=p50_c,
                p50_rrc=p50_r,
                delta_avg=delta_avg,
                delta_p50=delta_p50,
                tolerance_db=tolerance_db,
                verdict=verdict,
                reason=reason,
            )
        )
    return results


def mapping_from_proof(rows: list[ProofRow]) -> dict[str, dict[str, str]]:
    """Produit la table ``MEASUREMENT_MAPPING`` : ``{metric → {category,
    field}}`` ne contenant que les candidats ``proven``.

    Si une même ``metric`` a plusieurs lignes ``proven``, la première est
    retenue (ordre de ``CANDIDATES``, qui est significatif).
    """
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        if r.verdict != "proven":
            continue
        if r.metric in out:
            continue
        out[r.metric] = {
            "category": r.candidate_category,
            "field": r.candidate_field,
        }
    return out


def format_proof_table(rows: list[ProofRow]) -> str:
    """Formate le rapport en table ASCII (pour G24 + CHANGELOG)."""
    headers = [
        "metric", "field", "n_cand", "n_rrc",
        "avg_cand", "avg_rrc", "Δavg", "Δp50",
        "verdict", "reason",
    ]
    def _fmt(v: float | None, nd: int = 2) -> str:
        return "—" if v is None else f"{v:+.{nd}f}" if nd else f"{v:.{nd}f}"

    lines: list[str] = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for r in rows:
        lines.append(
            "| " + " | ".join([
                r.metric,
                r.candidate_field,
                str(r.n_candidate),
                str(r.n_rrc),
                _fmt(r.avg_candidate),
                _fmt(r.avg_rrc),
                _fmt(r.delta_avg),
                _fmt(r.delta_p50),
                r.verdict,
                r.reason or "",
            ]) + " |"
        )
    return "\n".join(lines)
