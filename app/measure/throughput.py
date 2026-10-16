"""Débit DL/UL reconstitué depuis DSUMMARY + CMDREQ (0.39.0).

Il n'existe **aucune** référence RRC pour un débit : la preuve ±2 dB
par distribution ne s'applique pas. On calcule donc le débit depuis la
chaîne décodée Nemo elle-même :

- `CMDREQ.service_action='StartHTTPTransfer' / 'StopHTTPTransfer'`
  bornent un transfert, dans une même capture (`capture_id` fixé,
  ordre `(capture_id, seq)` strict).
- Entre `Start` et `Stop`, on **somme** `raw_fields.bytes_transferred`
  des DSUMMARY présents (unités : octets, cumulé par le décodeur).
- Débit applicatif : `thrpt_dl = 8 × bytes / Δt / 1e6`  (Mbit/s),
  où `Δt` est l'écart temporel `t_stop − t_start` en secondes
  (parsé depuis `raw_fields.ts` au format `HH:MM:SS.mmm`).
- **Plage physique** 0..300 Mbit/s. Hors plage → transfert ignoré,
  **déclaré** dans le rapport (`rejected: thrpt_out_of_range`).
- La direction (DL/UL) est inférée de `service_action` : contient
  `HTTPTransfer` ou `HTTP_DL` → DL ; `HTTPUpload` ou `HTTP_UL` → UL ;
  sinon le transfert reste typé `generic` et le débit est attribué à
  `thrpt_dl` par défaut (déclaré via `direction_source`).

Attribution côté `measurement_points` : pour chaque transfert prouvé,
on UPDATE `measurement_points.dl` (resp. `thrpt_ul`) sur les lignes
dont `(capture_id, seq)` tombent dans la fenêtre `[seq_start, seq_stop]`.
`service_name` + `phase=active` sont posés par la boucle principale
de `populate_measurement_points` — pas de double emploi ici.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.measure.ranges import THRPT


# Marqueurs d'ouverture / fermeture d'un transfert. On matche sur
# `startswith('Start') and endswith('HTTPTransfer')` + variantes.
_START_HINTS = ("StartHTTPTransfer", "StartHTTPDL", "StartHTTPUL")
_STOP_HINTS = ("StopHTTPTransfer", "StopHTTPDL", "StopHTTPUL")


def _parse_ts_hms_ms(ts: str | None) -> float | None:
    """`'HH:MM:SS.mmm'` → secondes depuis minuit (float). None si invalide."""
    if not ts:
        return None
    try:
        hh, mm, ss = ts.strip().split(":")
        return int(hh) * 3600.0 + int(mm) * 60.0 + float(ss)
    except (ValueError, AttributeError):
        return None


def _direction_from_action(action: str) -> str:
    a = action.strip().lower()
    if "ul" in a or "upload" in a:
        return "ul"
    if "dl" in a or "download" in a or "transfer" in a:
        return "dl"
    return "dl"  # défaut applicatif HTTP = DL


@dataclass
class Transfer:
    capture_id: str
    seq_start: int
    seq_stop: int
    t_start: float
    t_stop: float
    bytes_sum: int
    direction: str                # 'dl' | 'ul'
    service_action_start: str
    service_action_stop: str
    thrpt_mbps: float | None      # None si hors plage ou Δt invalide
    verdict: str                  # 'proven' | 'rejected'
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "capture_id": self.capture_id,
            "seq_start": self.seq_start,
            "seq_stop": self.seq_stop,
            "dt_s": round(self.t_stop - self.t_start, 3),
            "bytes_sum": self.bytes_sum,
            "direction": self.direction,
            "thrpt_mbps": None if self.thrpt_mbps is None else round(self.thrpt_mbps, 3),
            "verdict": self.verdict,
            "reason": self.reason,
        }


def compute_transfers(db: Session, project_id: str) -> list[Transfer]:
    """Scanne CMDREQ Start/Stop + DSUMMARY, retourne un transfert par DSUMMARY.

    Pattern Nemo observé sur REF : les CMDREQ `Start/Stop HTTPTransfer`
    sont émis **immédiatement l'un après l'autre** (ts identique ou
    < 400 ms d'écart) comme marqueurs de commande. Le transfert réel se
    déroule entre un Start_i et le DSUMMARY_i (émis ~60 s plus tard,
    porteur de `bytes_transferred` cumulés). Puis arrive le Start_{i+1}.

    Algorithme :
      1. Pour chaque capture, suivre les événements dans l'ordre `seq`.
      2. Mémoriser le dernier `StartHTTP*` CMDREQ (ts + seq + action).
      3. À chaque DSUMMARY : si un Start récent existe, construire un
         transfert `thrpt = 8 × bytes / Δt` avec `Δt = ts_DSUM − ts_Start`.
      4. Attribution côté mp : fenêtre `[seq_Start, seq_DSUM]`.
      5. Un DSUMMARY sans Start récent → ignoré (jamais inventé).

    Plage physique 0..300 Mbit/s. Hors plage → `rejected: out_of_range`.
    """
    rows = db.execute(
        text(
            """
            SELECT capture_id, seq, event_code, ts, raw_fields
            FROM stg_event_raw
            WHERE project_id = :pid
              AND event_code IN ('CMDREQ', 'DSUMMARY')
            ORDER BY capture_id, seq
            """
        ),
        {"pid": project_id},
    ).all()

    transfers: list[Transfer] = []
    last_start_by_cap: dict[str, dict[str, Any]] = {}

    for r in rows:
        cap_id = str(r.capture_id)
        seq = int(r.seq)
        rf = r.raw_fields if isinstance(r.raw_fields, dict) else {}
        if r.event_code == "CMDREQ":
            action = str(rf.get("service_action") or "")
            if any(action.startswith(h) for h in _START_HINTS):
                last_start_by_cap[cap_id] = {
                    "seq_start": seq,
                    "t_start": _parse_ts_hms_ms(rf.get("ts")),
                    "action": action,
                }
            # Stop CMDREQ est un marqueur de commande (ts == Start sur REF),
            # on l'ignore pour le débit : le vrai « stop » est le DSUMMARY.
            continue
        # DSUMMARY : clôture le transfert ouvert sur cette capture.
        start_info = last_start_by_cap.get(cap_id)
        if start_info is None:
            continue  # DSUMMARY sans Start précédent — jamais rattaché
        t_dsum = _parse_ts_hms_ms(rf.get("ts"))
        t_start = start_info["t_start"]
        try:
            bytes_sum = max(int(float(rf.get("bytes_transferred") or 0)), 0)
        except (TypeError, ValueError):
            bytes_sum = 0
        dt = (t_dsum - t_start) if (t_start is not None and t_dsum is not None) else None
        action_start = start_info["action"]
        direction = _direction_from_action(action_start)
        seq_start = start_info["seq_start"]
        # Chaque DSUMMARY est consommé une fois : on retire le Start pour
        # que le DSUMMARY suivant ne récupère pas la même borne.
        last_start_by_cap.pop(cap_id, None)
        if dt is None or dt <= 0:
            transfers.append(
                Transfer(
                    capture_id=cap_id, seq_start=seq_start, seq_stop=seq,
                    t_start=t_start or 0.0, t_stop=t_dsum or 0.0,
                    bytes_sum=bytes_sum, direction=direction,
                    service_action_start=action_start, service_action_stop="DSUMMARY",
                    thrpt_mbps=None, verdict="rejected",
                    reason=f"dt_invalid: dt={dt!r}",
                )
            )
            continue
        mbps = 8.0 * bytes_sum / dt / 1_000_000.0
        if not THRPT.contains(mbps):
            transfers.append(
                Transfer(
                    capture_id=cap_id, seq_start=seq_start, seq_stop=seq,
                    t_start=t_start, t_stop=t_dsum,
                    bytes_sum=bytes_sum, direction=direction,
                    service_action_start=action_start, service_action_stop="DSUMMARY",
                    thrpt_mbps=mbps, verdict="rejected",
                    reason=f"thrpt_out_of_range: {mbps:.2f} Mbit/s ∉ [{THRPT.lo:.0f}, {THRPT.hi:.0f}]",
                )
            )
            continue
        transfers.append(
            Transfer(
                capture_id=cap_id, seq_start=seq_start, seq_stop=seq,
                t_start=t_start, t_stop=t_dsum,
                bytes_sum=bytes_sum, direction=direction,
                service_action_start=action_start, service_action_stop="DSUMMARY",
                thrpt_mbps=mbps, verdict="proven", reason="",
            )
        )
    return transfers


def apply_transfers_to_measurement_points(
    db: Session, project_id: str, transfers: list[Transfer],
) -> dict[str, int]:
    """UPDATE `measurement_points.{dl,thrpt_ul}` pour chaque transfert
    prouvé. Attribution par `(capture_id, seq_start <= seq <= seq_stop)`.
    Les lignes hors fenêtre d'un transfert prouvé restent **NULL**
    (déclaré). Retourne un rapport `{n_proven, n_rejected, n_rows_dl,
    n_rows_ul}`."""
    report = {"n_proven": 0, "n_rejected": 0, "n_rows_dl": 0, "n_rows_ul": 0}
    for t in transfers:
        if t.verdict != "proven" or t.thrpt_mbps is None:
            report["n_rejected"] += 1
            continue
        report["n_proven"] += 1
        col = "dl" if t.direction == "dl" else "thrpt_ul"
        res = db.execute(
            text(
                f"""
                UPDATE measurement_points
                SET {col} = :v
                WHERE project_id = :pid
                  AND capture_id = :cap
                  AND seq BETWEEN :s0 AND :s1
                """
            ),
            {
                "pid": project_id,
                "cap": t.capture_id,
                "s0": t.seq_start,
                "s1": t.seq_stop,
                "v": float(t.thrpt_mbps),
            },
        )
        n = res.rowcount or 0
        if t.direction == "dl":
            report["n_rows_dl"] += n
        else:
            report["n_rows_ul"] += n
    db.commit()
    return report


def format_transfer_table(transfers: list[Transfer]) -> str:
    hdr = [
        "capture_id", "seq_start", "seq_stop", "dt_s", "bytes_sum",
        "direction", "thrpt_mbps", "verdict", "reason",
    ]
    out: list[str] = []
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "|".join("---" for _ in hdr) + "|")
    for t in transfers:
        d = t.as_dict()
        out.append(
            "| "
            + " | ".join(
                [
                    d["capture_id"][:12],
                    str(d["seq_start"]),
                    str(d["seq_stop"]),
                    str(d["dt_s"]),
                    str(d["bytes_sum"]),
                    d["direction"],
                    "—" if d["thrpt_mbps"] is None else f"{d['thrpt_mbps']:.2f}",
                    d["verdict"],
                    d["reason"],
                ]
            )
            + " |"
        )
    return "\n".join(out)
