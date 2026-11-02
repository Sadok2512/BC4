"""In-memory and persisted Metrics catalogue cache helpers."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from concurrent.futures import Future
from copy import deepcopy
from threading import Lock
from time import monotonic

from sqlalchemy import text
from sqlalchemy.orm import Session


# 0.74.2 (A) — TTL 30s → 600s. User navigation en session restait coûteuse à
# chaque nouvelle page si > 30s écoulé : premier appel cold = ~60s sur TEST2.
class CatalogCache:
    def __init__(self, ttl=600, capacity=64, clock=monotonic):
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self.lock = Lock()
        self.ready = OrderedDict()
        self.pending = {}

    def get(self, key, load):
        with self.lock:
            cached = self.ready.get(key)
            if cached and self.clock() < cached[0]:
                self.ready.move_to_end(key)
                return deepcopy(cached[1])
            self.ready.pop(key, None)
            future = self.pending.get(key)
            owner = future is None
            if owner:
                future = self.pending[key] = Future()
        if not owner:
            return deepcopy(future.result())
        try:
            value = load()
            with self.lock:
                self.ready[key] = (self.clock() + self.ttl, deepcopy(value))
                while len(self.ready) > self.capacity:
                    self.ready.popitem(last=False)
            future.set_result(value)
            return deepcopy(value)
        except BaseException as error:
            future.set_exception(error)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)


catalog_cache = CatalogCache()


PROJECT_SCOPE = "project"


def cache_scope_key(capture_ids: Sequence[str] = ()) -> str:
    """Return a deterministic key for a project or capture-set catalogue."""
    captures = tuple(sorted(set(capture_ids)))
    return PROJECT_SCOPE if not captures else f"captures:{','.join(captures)}"


def cache_generation_stamp(
    db: Session,
    project_id: str,
    catalog_version: str,
    *,
    scope_key: str = PROJECT_SCOPE,
) -> str:
    """Fingerprint every input that changes one cached catalogue payload."""
    decode_stamp = db.execute(text("""
        SELECT md5(coalesce(string_agg(
          capture_id || ':' || decoder_version || ':' || coalesce(decoded_at::text,''),
          ',' ORDER BY capture_id),''))
        FROM nmf_capture WHERE project_id=:pid
    """), {"pid": project_id}).scalar_one()
    identity_stamp = db.execute(text("""
        SELECT md5(count(*)::text || ':' || coalesce(max(built_at)::text,''))
        FROM nmf_cell_identity WHERE project_id=:pid
    """), {"pid": project_id}).scalar_one()
    return (
        f"{decode_stamp}|identity={identity_stamp}|cat={catalog_version}"
        f"|scope={scope_key}"
    )
