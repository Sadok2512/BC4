"""Task throughput from mean DRATE bps; DSUMMARY is never an octet source."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session



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
            "dt_s": round(self.t_stop - self.t_start, 3) if self.t_stop is not None and self.t_start is not None else None,
            "bytes_sum": self.bytes_sum,
            "direction": self.direction,
            "thrpt_mbps": None if self.thrpt_mbps is None else round(self.thrpt_mbps, 3),
            "verdict": self.verdict,
            "reason": self.reason,
        }


def compute_transfers(db: Session, project_id: str) -> list[Transfer]:
    """Compatibility adapter shared by KPI availability and population.

    Missing boundaries/samples are retained as rejected transfers, never fabricated.
    No physical cap discards an observed throughput.
    """
    from app.services.task_run import load_tasks
    from statistics import mean
    result=[]
    for t in load_tasks(db, project_id):
        if t['task_type'] not in ('HTTP_DL','HTTP_UL'): continue
        values=[s['bps'] for s in t['_samples'] if s['bps'] is not None and s['bps']>=0]
        value=mean(values)/1_000_000 if values else (8*t['bytes_dcomp']/t['duration_s']/1_000_000 if t['bytes_dcomp'] is not None and t['duration_s'] is not None and t['duration_s']>0 else None)
        result.append(Transfer(capture_id=t['capture_id'], seq_start=t['seq_start'],
            seq_stop=t['seq_dcomp'] if t['seq_dcomp'] is not None else t['seq_end'],
            t_start=t['_start'],t_stop=t['_end'],bytes_sum=t['bytes_dcomp'],
            direction='dl' if t['task_type']=='HTTP_DL' else 'ul',
            service_action_start=t['task_type'],service_action_stop='DCOMP',
            thrpt_mbps=value,verdict='proven' if t['status']=='ok' else 'rejected',
            reason=t['reason'] or ('mean(DRATE.bps)' if values else '8*bytes_dcomp/duration_s')))
    return result


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
