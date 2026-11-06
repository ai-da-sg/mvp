"""Bounded health probes with TTL caching and one in-flight probe per key."""
import copy
from concurrent.futures import Future, ThreadPoolExecutor
import threading
import time


class HealthCache:
    def __init__(self, ttl=10, workers=4, limit=256, clock=time.monotonic):
        self.ttl, self.limit, self.clock = ttl, limit, clock
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='site-health')
        self.lock = threading.Lock()
        self.values, self.pending, self.versions = {}, {}, {}

    def invalidate(self, predicate=lambda key: True):
        with self.lock:
            for key in set(self.values) | set(self.pending):
                if predicate(key):
                    self.values.pop(key, None)
                    self.versions[key] = self.versions.get(key, 0) + 1

    def _future(self, key, loader, force):
        with self.lock:
            generation = self.versions.get(key, 0)
            cached = self.values.get(key)
            if not force and cached and self.clock() - cached[0] < self.ttl:
                future = Future()
                future.set_result(copy.deepcopy(cached))
                return future, generation, True
            pending = self.pending.get(key)
            if pending and pending[1] == generation:
                return pending[0], generation, False
            future = self.pool.submit(self._probe, loader, key)
            self.pending[key] = (future, generation)
            return future, generation, False

    def _probe(self, loader, key):
        value = loader(key)
        return self.clock(), value

    def _resolve(self, key, request, loader):
        future, generation, cached = request
        try:
            completed_at, value = future.result()
        except Exception:
            with self.lock:
                if self.pending.get(key) == (future, generation):
                    self.pending.pop(key, None)
            raise
        with self.lock:
            valid = self.versions.get(key, 0) == generation
            if valid and not cached and self.pending.get(key) == (future, generation):
                self.values[key] = (completed_at, copy.deepcopy(value))
                self.pending.pop(key, None)
                while len(self.values) > self.limit:
                    oldest = min(self.values, key=lambda k: self.values[k][0])
                    self.values.pop(oldest)
                    if oldest not in self.pending:
                        self.versions.pop(oldest, None)
        if not valid:
            # A start/stop operation invalidated a probe in flight. Do not let
            # that older result overwrite or be returned as the new state.
            return self.get(key, loader)
        return copy.deepcopy(value)

    def get(self, key, loader, force=False):
        return self._resolve(key, self._future(key, loader, force), loader)

    def many(self, keys, loader, force=False):
        requests = {key: self._future(key, loader, force) for key in dict.fromkeys(keys)}
        return {key: self._resolve(key, request, loader) for key, request in requests.items()}

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
