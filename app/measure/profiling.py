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
    un `event_code` donné, converti en float. Ordre `(capture_id, seq)`."""
    rows = db.execute(
        text(
            """
            SELECT raw_fields ->> :f
            FROM stg_event_raw
            WHERE project_id = :pid
              AND event_code = :ec
              AND raw_fields ->> :f IS NOT NULL
            ORDER BY capture_id, seq
            LIMIT :lim
            """
        ),
        {"pid": project_id, "ec": event_code, "f": field, "lim": limit},
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
class CellmeasMapping:
    """Mapping métrique → champ CELLMEAS pour un projet, choisi par le
    CONTENU. `None` = métrique indisponible (aucun champ ne couvre à
    ≥ MIN_FRACTION)."""
    rssi: str | None
    rsrp: str | None
    rsrq: str | None
    sinr: str | None
    profiles: list[FieldProfile]
    debug: list[str]


def profile_cellmeas(db: Session, project_id: str) -> CellmeasMapping:
    """Scanne les champs candidats de CELLMEAS pour ce projet et affecte,
    pour chaque métrique, le champ dont la plus grande fraction de valeurs
    valides tombe dans la plage 3GPP correspondante.

    Ordre d'affectation : **RSRQ (plage la plus étroite), puis SINR, RSRP,
    RSSI** — chaque métrique « verrouille » son champ pour les suivantes
    (un champ ne peut porter qu'une métrique).
    """
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
