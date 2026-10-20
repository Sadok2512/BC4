"""Bounded, short-lived catalogue cache; never caches errors or crosses projects."""
from collections import OrderedDict
from concurrent.futures import Future
from threading import Lock
from time import monotonic
from copy import deepcopy


class CatalogCache:
    def __init__(self, ttl=30, capacity=64, clock=monotonic):
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
