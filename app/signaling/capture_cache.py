"""Capture-local caches invalidated by the decoder reparse stamp."""
from dataclasses import dataclass
from collections import OrderedDict
from threading import Lock
from typing import Any, Callable

from sqlalchemy import text


@dataclass(frozen=True)
class CaptureStamp:
    decoder_version: str
    decoded_at: Any
    event_count: int
    raw_count: int
    max_seq: int


_CLOCKS: OrderedDict[tuple[str, str, str], tuple[CaptureStamp, tuple]] = OrderedDict()
_LOCK = Lock()


def capture_stamp(db, project_id: str, capture_id: str) -> CaptureStamp:
    row = db.execute(text("""SELECT c.decoder_version, c.decoded_at,
        (SELECT count(*) FROM stg_event e
         WHERE e.project_id=c.project_id AND e.capture_id=c.capture_id) AS event_count,
        (SELECT count(*) FROM stg_event_raw r
         WHERE r.project_id=c.project_id AND r.capture_id=c.capture_id) AS raw_count,
        (SELECT COALESCE(max(r.seq),-1) FROM stg_event_raw r
         WHERE r.project_id=c.project_id AND r.capture_id=c.capture_id) AS max_seq
      FROM nmf_capture c
      WHERE c.project_id=:pid AND c.capture_id=:cap"""),
      {"pid": project_id, "cap": capture_id}).mappings().one_or_none()
    if row is None:
        # Let the endpoint's normal capture/clock validation produce its
        # established 404 contract. This value can never collide with a real
        # decoded capture.
        return CaptureStamp("missing", None, -1, -1, -1)
    return CaptureStamp(
        str(row["decoder_version"] or "unknown"), row["decoded_at"],
        int(row["event_count"]), int(row["raw_count"]), int(row["max_seq"]),
    )


def shared_clock(db, project_id: str, capture_id: str, build: Callable[[], tuple]) -> tuple:
    """Reuse one clock for population() and clock(), never across a reparse.

    The public cache identity is the requested
    ``(project_id, capture_id, decoder_version)``. ``decoded_at`` and source
    cardinality are compared inside the entry because reparsing with the same
    decoder version must invalidate the value too.
    """
    stamp = capture_stamp(db, project_id, capture_id)
    key = (project_id, capture_id, stamp.decoder_version)
    with _LOCK:
        cached = _CLOCKS.get(key)
        if cached is not None and cached[0] == stamp:
            _CLOCKS.move_to_end(key)
            return cached[1]
    value = build()
    with _LOCK:
        _CLOCKS[key] = (stamp, value)
        _CLOCKS.move_to_end(key)
        while len(_CLOCKS)>32:_CLOCKS.popitem(last=False)
    return value


def clear_capture(project_id: str, capture_id: str) -> None:
    """Explicit invalidation hook for import/reparse flows and tests."""
    with _LOCK:
        for key in [key for key in _CLOCKS if key[:2] == (project_id, capture_id)]:
            del _CLOCKS[key]
