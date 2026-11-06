import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
from kf_health_cache import HealthCache


class HealthCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.cache = HealthCache(ttl=10, workers=2, limit=3, clock=lambda: self.now)

    def tearDown(self):
        self.cache.close()

    def test_ttl_force_and_defensive_copy(self):
        calls = []
        def loader(key):
            calls.append(key)
            return {'containers': [len(calls)]}
        first = self.cache.get('site', loader)
        first['containers'].append('caller mutation')
        self.assertEqual(self.cache.get('site', loader), {'containers': [1]})
        self.now = 10
        self.assertEqual(self.cache.get('site', loader), {'containers': [2]})
        self.assertEqual(self.cache.get('site', loader, force=True), {'containers': [3]})

    def test_concurrent_callers_share_a_probe(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        def loader(key):
            calls.append(key)
            started.set()
            self.assertTrue(release.wait(3))
            return {'state': 'active'}
        with ThreadPoolExecutor(max_workers=5) as callers:
            futures = [callers.submit(self.cache.get, 'same', loader) for _ in range(5)]
            self.assertTrue(started.wait(2))
            release.set()
            self.assertEqual([f.result() for f in futures], [{'state': 'active'}] * 5)
        self.assertEqual(calls, ['same'])

    def test_invalidation_during_probe_does_not_return_stale_state(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        def loader(key):
            calls.append(key)
            if len(calls) == 1:
                started.set()
                self.assertTrue(release.wait(3))
                return 'old'
            return 'new'
        with ThreadPoolExecutor(max_workers=1) as callers:
            pending = callers.submit(self.cache.get, ('demo', 80), loader)
            self.assertTrue(started.wait(2))
            self.cache.invalidate(lambda key: key[0] == 'demo')
            release.set()
            self.assertEqual(pending.result(), 'new')
        self.assertEqual(len(calls), 2)

    def test_failed_probe_can_retry_and_batch_workers_are_bounded(self):
        with self.assertRaises(OSError):
            self.cache.get('bad', lambda key: (_ for _ in ()).throw(OSError('probe failed')))
        self.assertEqual(self.cache.get('bad', lambda key: 'recovered'), 'recovered')
        lock = threading.Lock()
        active, maximum = [0], [0]
        barrier = threading.Barrier(2)
        def loader(key):
            with lock:
                active[0] += 1
                maximum[0] = max(maximum[0], active[0])
            barrier.wait(timeout=3)
            with lock:
                active[0] -= 1
            return key
        self.assertEqual(self.cache.many(range(6), loader), {k: k for k in range(6)})
        self.assertEqual(maximum[0], 2)
        self.assertLessEqual(len(self.cache.values), 3)


if __name__ == '__main__':
    unittest.main()
