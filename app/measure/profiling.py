"""Profilage par plage des champs CELLMEAS/CQI/TX (0.39.0).

Doctrine (correctif cahier des charges 0.39.0) :
`cell0_rsrp_dbm`, `cell0_rsrq_db`, `cell0_sinr_db` sont des étiquettes
amont décodeur qui ne reflètent **pas** le contenu réel : sur REF, la
colonne `cell0_rsrp_dbm` tient en fait un RSSI (avg -68 dBm), tandis
que `cell0_rsrq_db` tient le vrai RSRP (avg -100 dBm, cohérent à 1 dB
près avec `measResultPCell/rsrpResult` RRC). On re-mappe donc **par le
contenu** : pour chaque métrique (RSSI / RSRP / RSRQ / SINR), on choisit
le champ CELLMEAS dont la **plus grande proportion** de valeurs tombe
dans la plage 3GPP de la métrique.

Points durs :
- `650400`, `50001..50010` etc. sont des placeholders décodeur : exclus
  avant comptage (`ranges.is_placeholder`).
- Un même champ ne peut porter deux métriques — on prend la plus
  spécifique en premier (`RSRQ` est plus étroit que `SINR`, cf. ordre).
- Si **aucun** champ ne couvre une métrique à ≥ 50 % → métrique
  déclarée indisponible (NULL à l'aval). Jamais mappée à l'aveugle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.measure.ranges import CQI, RSRP, RSRQ, RSSI, SINR, TX_POWER, Range, is_placeholder


# Fraction minimale de valeurs dans la plage pour accepter un champ. 50%
# est volontairement conservateur — un vrai champ RSSI/RSRP/RSRQ/SINR a
# typiquement ≥ 80% de ses valeurs dans sa plage (sinon ce n'est pas le
# bon champ).
MIN_FRACTION = 0.50
PROFILE_SAMPLE_LIMIT = 5000


# Clés candidates à sonder sur raw_fields CELLMEAS. On inclut les
# positions brutes (`cell0_c7..c10`) qui portent souvent la SINR réelle
# (sur REF : SINR → `cell0_c9`).
CELLMEAS_FIELD_CANDIDATES: tuple[str, ...] = (
    "cell0_rsrp_dbm",
    "cell0_rsrq_db",
    "cell0_sinr_db",
    "cell0_rssi_dbm",
    "cell0_c7",
    "cell0_c8",
    "cell0_c9",
    "cell0_c10",
)


@dataclass
class FieldProfile:
    """Profil d'un champ : combien de valeurs tombent dans chaque plage 3GPP."""
    field: str
    n_total: int
    n_valid: int                   # hors placeholders
    n_rssi: int
    n_rsrp: int
    n_rsrq: int
    n_sinr: int
    avg: float | None
    min_v: float | None
    max_v: float | None

    def fraction_in(self, rng: Range) -> float:
        """Fraction des valeurs valides tombant dans `rng`. 0 si rien."""
        if self.n_valid == 0:
            return 0.0
        return {
            "RSSI": self.n_rssi,
            "RSRP": self.n_rsrp,
            "RSRQ": self.n_rsrq,
            "SINR": self.n_sinr,
        }[rng.label] / self.n_valid


def _fetch_values(
    db: Session, project_id: str, event_code: str, field: str, limit: int,
) -> list[float]:
    """Lit un échantillon de `raw_fields->>field` sur `stg_event_raw` pour
    un `event_code` donné, converti en float. Ordre `(capture_id, seq)`.

    0.45.2 — Filtre system='LTE' sur CELLMEAS. Nemo CELLMEAS NR a un
    ordre de colonnes DIFFÉRENT de CELLMEAS LTE : appliquer le mapping
    LTE sur une ligne NR fait tomber des ARFCN (~650 400) dans la colonne
    `cell0_rsrp_dbm`, ce qui pollue le profil (avg +96 774 dBm au lieu
    de −90 dBm). On restreint le profil CELLMEAS **au corpus prouvé**
    (LTE), le mapping NR est un lot séparé (bug decoder 2.0.0).
    """
    extra = ""
    params: dict[str, object] = {"pid": project_id, "ec": event_code, "f": field, "lim": limit}
    if event_code == "CELLMEAS":
        extra = " AND system = 'LTE'"
    rows = db.execute(
        text(
            f"""
            SELECT raw_fields ->> :f
            FROM stg_event_raw
            WHERE project_id = :pid
              AND event_code = :ec
              AND raw_fields ->> :f IS NOT NULL
              {extra}
            ORDER BY capture_id, seq
            LIMIT :lim
            """
        ),
        params,
    ).all()
    out: list[float] = []
    for (v,) in rows:
        try:
            out.append(float(str(v).strip()))
        except (TypeError, ValueError):
            continue
    return out


def profile_field(
    db: Session, project_id: str, event_code: str, field: str,
    limit: int = PROFILE_SAMPLE_LIMIT,
) -> FieldProfile:
    vals = _fetch_values(db, project_id, event_code, field, limit)
    valid = [v for v in vals if not is_placeholder(v)]
    n_total = len(vals)
    n_valid = len(valid)
    if not valid:
        return FieldProfile(
            field=field, n_total=n_total, n_valid=0,
            n_rssi=0, n_rsrp=0, n_rsrq=0, n_sinr=0,
            avg=None, min_v=None, max_v=None,
        )
    return FieldProfile(
        field=field,
        n_total=n_total,
        n_valid=n_valid,
        n_rssi=sum(1 for v in valid if RSSI.contains(v)),
        n_rsrp=sum(1 for v in valid if RSRP.contains(v)),
        n_rsrq=sum(1 for v in valid if RSRQ.contains(v)),
        n_sinr=sum(1 for v in valid if SINR.contains(v)),
        avg=sum(valid) / len(valid),
        min_v=min(valid),
        max_v=max(valid),
    )


@dataclass
class ProofResult:
    field: str
    n_pairs: int
    median_abs_delta: float | None
    p90_abs_delta: float | None
    verdict: str
    reason: str


@dataclass
class CellmeasMapping:
    """Mapping métrique → champ CELLMEAS pour un projet.

    0.44.0 — RSRP choisi par **preuve** (`prove_rsrp_per_event`), pas
    par heuristique. RSRQ/SINR/RSSI : plage 3GPP + cohérence (RSRQ
    strictement ∈ [-20,-3], SINR corrélé positivement au RSRP serving,
    RSSI ≥ RSRP serving).
    """
    rssi: str | None
    rsrp: str | None
    rsrq: str | None
    sinr: str | None
    profiles: list[FieldProfile]
    debug: list[str]
    # 0.44.0 — Preuves par champ pour RSRP ; persistées dans
    # cellmeas_profile par populate.
    rsrp_proofs: list["ProofResult"] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.rsrp_proofs is None:
            self.rsrp_proofs = []


def profile_cellmeas(db: Session, project_id: str) -> CellmeasMapping:
    """0.44.0 — Choisit **par la preuve** pour RSRP ; par plage 3GPP +
    cohérence pour RSRQ/SINR/RSSI. Jamais par heuristique « meilleure
    moyenne ».
    """
    from app.measure.proof import prove_rsrp_per_event

    profiles = [
        profile_field(db, project_id, "CELLMEAS", f)
        for f in CELLMEAS_FIELD_CANDIDATES
    ]
    assigned: dict[str, str] = {}
    taken: set[str] = set()
    debug: list[str] = []
    rsrp_proofs: list[ProofResult] = []

    # ---------------------------------------------------------------
    # 1) RSRP par la PREUVE : pour chaque champ dont ≥ 50 % des valeurs
    # tombent dans la plage RSRP, on exécute `prove_rsrp_per_event`.
    # Retenu : premier dont `verdict == proven` (median|Δ| ≤ 2 dB).
    # ---------------------------------------------------------------
    rsrp_candidates = [
        p for p in profiles
        if p.n_valid > 100 and p.fraction_in(RSRP) >= MIN_FRACTION
    ]
    # Ordre priorité : fraction RSRP décroissante → plus propre.
    rsrp_candidates.sort(key=lambda p: -p.fraction_in(RSRP))
    for p in rsrp_candidates:
        pr = prove_rsrp_per_event(db, project_id, p.field, seq_window=100)
        rsrp_proofs.append(
            ProofResult(
                field=p.field,
                n_pairs=pr.n_pairs,
                median_abs_delta=pr.median_abs_delta,
                p90_abs_delta=None,  # non calculé par prove_rsrp_per_event
                verdict=pr.verdict,
                reason=pr.reason,
            )
        )
        if pr.verdict == "proven" and "rsrp" not in assigned:
            assigned["rsrp"] = p.field
            taken.add(p.field)
            debug.append(
                f"rsrp ← {p.field} (verdict=proven, n_pairs={pr.n_pairs}, "
                f"median|Δ|={pr.median_abs_delta:.2f} dB)"
            )
    if "rsrp" not in assigned:
        debug.append("rsrp ← aucun candidat ne passe la preuve ±2 dB")

    # ---------------------------------------------------------------
    # 2) RSSI : « serving » dans [−120, −20], avg ≥ −90 (jamais confondu
    # avec RSRP). Doit être ≥ RSRP sur le même event — vérifié par
    # cohérence post-mapping sur quelques lignes (déclaratif ici).
    # ---------------------------------------------------------------
    for p in profiles:
        if p.field in taken or p.n_valid == 0:
            continue
        if (
            p.fraction_in(RSSI) >= MIN_FRACTION
            and p.avg is not None
            and p.avg > -90.0
            and p.avg < -20.0
        ):
            assigned["rssi"] = p.field
            taken.add(p.field)
            debug.append(
                f"rssi ← {p.field} (avg={p.avg:+.2f} dBm, "
                f"frac_rssi={p.fraction_in(RSSI):.0%})"
            )
            break
    if "rssi" not in assigned:
        debug.append("rssi ← aucun candidat ∈ [-120,-20] avec avg > -90")

    # ---------------------------------------------------------------
    # 3) RSRQ : strictement ∈ [−20, −3], avg ∈ [−20, −3]. Jamais SINR.
    # ---------------------------------------------------------------
    for p in profiles:
        if p.field in taken or p.n_valid == 0:
            continue
        frac_rsrq = p.fraction_in(RSRQ)
        if (
            frac_rsrq >= MIN_FRACTION
            and p.avg is not None
            and -20.0 <= p.avg <= -3.0
        ):
            assigned["rsrq"] = p.field
            taken.add(p.field)
            debug.append(
                f"rsrq ← {p.field} (avg={p.avg:+.2f} dB, "
                f"frac_rsrq={frac_rsrq:.0%})"
            )
            break
    if "rsrq" not in assigned:
        debug.append("rsrq ← aucun candidat ∈ [-20,-3] avec avg conforme")

    # ---------------------------------------------------------------
    # 4) SINR : ∈ [−20, +30], avg ≥ −3 (positif typique en bon signal,
    # corrélé positivement au RSRP serving). Doit sortir du range RSRQ.
    # ---------------------------------------------------------------
    for p in profiles:
        if p.field in taken or p.n_valid == 0:
            continue
        if (
            p.fraction_in(SINR) >= MIN_FRACTION
            and p.avg is not None
            and p.avg >= -3.0
            and p.avg <= 30.0
        ):
            assigned["sinr"] = p.field
            taken.add(p.field)
            debug.append(
                f"sinr ← {p.field} (avg={p.avg:+.2f} dB, "
                f"frac_sinr={p.fraction_in(SINR):.0%})"
            )
            break
    if "sinr" not in assigned:
        debug.append("sinr ← aucun candidat ∈ [-20,+30] avec avg ≥ -3")

    # c8 : avg ≈ −3,1 → zone frontière RSRQ/SINR → marqué 'ambigu'
    for p in profiles:
        if p.field == "cell0_c8" and p.field not in taken and p.avg is not None:
            debug.append(
                f"ambigu: cell0_c8 (avg={p.avg:+.2f}) non affecté — "
                f"zone frontière RSRQ/SINR"
            )

    return CellmeasMapping(
        rssi=assigned.get("rssi"),
        rsrp=assigned.get("rsrp"),
        rsrq=assigned.get("rsrq"),
        sinr=assigned.get("sinr"),
        profiles=profiles,
        debug=debug,
        rsrp_proofs=rsrp_proofs,
    )


# L'ancien bloc ci-dessous est désactivé.
def _legacy_disabled_profile_cellmeas(db: Session, project_id: str) -> CellmeasMapping:
    profiles = [
        profile_field(db, project_id, "CELLMEAS", f)
        for f in CELLMEAS_FIELD_CANDIDATES
    ]
    assigned: dict[str, str] = {}
    taken: set[str] = set()

    # Ordre : du plus spécifique au plus large.
    order = (
        ("rsrq", RSRQ),
        ("sinr", SINR),
        ("rsrp", RSRP),
        ("rssi", RSSI),
    )
    debug: list[str] = []
    for metric_name, rng in order:
        best: FieldProfile | None = None
        best_frac = 0.0
        for p in profiles:
            if p.field in taken or p.n_valid == 0:
                continue
            frac = p.fraction_in(rng)
            # Désambiguïsation : si SINR et RSRQ sont tous deux « hauts »
            # sur un champ (plages chevauchantes [-20,-3] ⊂ [-20,30]), on
            # préfère le candidat dont la plage la plus étroite (RSRQ) a
            # une couverture dominante, i.e. la différence RSRQ-SINR est
            # positive. Pour RSRP vs RSSI (chevauchement [-120,-44]),
            # idem : on compare les fractions.
            # 0.39.0 — Désambiguïsation RSRQ vs SINR par la MOYENNE.
            # Les plages RSRQ [-20,-3] et SINR [-20,+30] se chevauchent ;
            # fraction_in() seul ne discrimine pas. On regarde l'avg :
            #  - avg < -3 dB → zone RSRQ.
            #  - avg ≥ -3 dB → zone SINR (positif typique en bon signal).
            if metric_name == "rsrq":
                if p.avg is None or p.avg >= -3.0:
                    continue
            if metric_name == "sinr":
                if p.avg is None or p.avg < -3.0:
                    continue
            if metric_name == "rsrp":
                # RSRP n'a de sens que si le champ EXCLUT la zone RSSI
                # haute [-44, -20] : on tolère un peu, mais le signal
                # pur est que les valeurs se concentrent en-dessous de -44.
                # Si avg > -50 c'est très probablement du RSSI, pas RSRP.
                if p.avg is not None and p.avg > -50.0:
                    continue
            if metric_name == "rssi":
                # Idem miroir : RSSI « serving » est au-dessus de -120 et
                # typiquement avg autour de -70. Un champ dont l'avg est
                # < -90 est plus RSRP que RSSI.
                if p.avg is not None and p.avg < -90.0:
                    continue
            if frac >= MIN_FRACTION and frac > best_frac:
                best = p
                best_frac = frac
        if best is not None:
            assigned[metric_name] = best.field
            taken.add(best.field)
            debug.append(
                f"{metric_name} ← {best.field} (frac={best_frac:.2%}, "
                f"n_valid={best.n_valid}, avg={best.avg:+.2f} {rng.unit})"
            )
        else:
            debug.append(f"{metric_name} ← aucun candidat ≥ {MIN_FRACTION:.0%} dans {rng.label}")

    return CellmeasMapping(
        rssi=assigned.get("rssi"),
        rsrp=assigned.get("rsrp"),
        rsrq=assigned.get("rsrq"),
        sinr=assigned.get("sinr"),
        profiles=profiles,
        debug=debug,
    )


def format_profile_table(mapping: CellmeasMapping) -> str:
    lines: list[str] = []
    headers = ["field", "n_valid", "avg", "min", "max", "%RSSI", "%RSRP", "%RSRQ", "%SINR"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for p in mapping.profiles:
        if p.n_total == 0:
            continue
        row = [
            p.field,
            str(p.n_valid),
            f"{p.avg:+.2f}" if p.avg is not None else "—",
            f"{p.min_v:+.2f}" if p.min_v is not None else "—",
            f"{p.max_v:+.2f}" if p.max_v is not None else "—",
            f"{p.fraction_in(RSSI):.0%}",
            f"{p.fraction_in(RSRP):.0%}",
            f"{p.fraction_in(RSRQ):.0%}",
            f"{p.fraction_in(SINR):.0%}",
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("**Mapping choisi :**")
    for d in mapping.debug:
        lines.append(f"- {d}")
    return "\n".join(lines)
