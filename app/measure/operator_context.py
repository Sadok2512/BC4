"""Fill missing measurement operators from proven per-capture PLMN context."""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dict.populate import _build_sib1_index
from app.measure.mapping import operator_from_dl


@dataclass(frozen=True)
class OperatorContext:
    seq: int
    operator: str
    system: str


def resolve_operator_context(
    timeline: list[OperatorContext], seq: int, tech: str | None
) -> tuple[str | None, str]:
    """Resolve the latest proven PLMN, or the first proof for capture preamble."""
    if not timeline:
        return None, "none"
    positions = [item.seq for item in timeline]
    index = bisect_right(positions, seq) - 1
    if index < 0:
        return timeline[0].operator, "sib1_next"
    context = timeline[index]
    if (tech or "").upper() == "NR" and context.system == "LTE":
        return context.operator, "lte_anchor"
    return context.operator, "sib1"


def _timelines(db: Session, project_id: str) -> dict[str, list[OperatorContext]]:
    rows = db.execute(text("""
        SELECT id,capture_id,seq,system,message,freq,pci,payload_hex
        FROM stg_event
        WHERE project_id=:pid AND message IS NOT NULL
          AND (message LIKE '%%SystemInformationBlockType1%%'
               OR message LIKE '%%SIB1%%'
               OR message LIKE '%%SystemInformation1%%')
    """), {"pid": project_id}).all()
    index = _build_sib1_index(rows)
    timelines: dict[str, list[OperatorContext]] = defaultdict(list)
    for (capture_id, system), entries in index["per_cap"].items():
        for seq, operator, _band, _plmn in entries:
            if operator:
                timelines[str(capture_id)].append(
                    OperatorContext(int(seq), str(operator), str(system))
                )
    for capture_id in timelines:
        timelines[capture_id].sort(key=lambda item: (item.seq, item.system))
    return dict(timelines)


def _file_operators(db: Session, project_id: str) -> dict[str, str]:
    rows = db.execute(text("""
        SELECT DISTINCT r.capture_id,n.dl
        FROM stg_event_raw r JOIN nmf_file n ON n.id=r.nmf_file_id
        WHERE r.project_id=:pid
    """), {"pid": project_id}).all()
    candidates: dict[str, set[str]] = defaultdict(set)
    for capture_id, dl in rows:
        operator = operator_from_dl(dl)
        if operator:
            candidates[str(capture_id)].add(operator)
    return {
        capture_id: next(iter(operators))
        for capture_id, operators in candidates.items()
        if len(operators) == 1
    }


def backfill_operator_context(db: Session, project_id: str) -> dict[str, int]:
    """Update only NULL operators; existing file/SIB1 assignments are preserved."""
    timelines = _timelines(db, project_id)
    file_operators = _file_operators(db, project_id)
    rows = db.execute(text("""
        SELECT id,capture_id,seq,coalesce(rat,tech) tech
        FROM measurement_points
        WHERE project_id=:pid AND operator IS NULL
        ORDER BY capture_id,seq,id
    """), {"pid": project_id}).mappings().all()
    updates: list[dict[str, object]] = []
    by_source: dict[str, int] = defaultdict(int)
    for row in rows:
        capture_id = str(row["capture_id"] or "")
        operator = file_operators.get(capture_id)
        source = "file_context" if operator else "none"
        if not operator:
            operator, source = resolve_operator_context(
                timelines.get(capture_id, []), int(row["seq"] or 0), row["tech"]
            )
        if operator:
            updates.append({"id": row["id"], "operator": operator, "source": source})
            by_source[source] += 1
    if updates:
        db.execute(text("""
            UPDATE measurement_points
            SET operator=:operator,operator_source=:source
            WHERE id=:id AND operator IS NULL
        """), updates)
    return {
        "missing_before": len(rows),
        "updated": len(updates),
        "missing_after": len(rows) - len(updates),
        **{f"source_{source}": count for source, count in sorted(by_source.items())},
    }
