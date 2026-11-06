import copy
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
from kf_ai import AIError
from kf_publications import PublicationConflict, PublicationStore


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        site = self.base / 'sites' / 'demo'
        site.mkdir(parents=True)
        (site / 'meta.json').write_text('{}')
        self.store = PublicationStore(self.base, 'demo')
        self.before = {'pages': {'home': {'content': 'private before', 'id': 12}}, 'design': None}
        self.after = {'pages': {'home': {'content': 'private after', 'id': 12}}, 'design': None}

    def tearDown(self):
        self.tmp.cleanup()

    def publication(self, state='published'):
        item = self.store.begin('operator', ['home'], self.before)
        self.store.result(item['id'], 'home', state == 'published', '' if state == 'published' else 'write failed')
        return self.store.finish(item['id'], state, self.after)

    def test_private_durable_snapshot_and_redacted_history(self):
        with self.store.locked():
            item = self.publication()
        fresh = PublicationStore(self.base, 'demo')
        self.assertEqual(fresh.get(item['id'])['before'], self.before)
        self.assertEqual(stat.S_IMODE(self.store.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.store._path(item['id']).stat().st_mode), 0o600)
        history = fresh.history()
        self.assertEqual(history[0]['results'][0]['stage'], 'home')
        self.assertNotIn('private', json.dumps(history))
        self.assertNotIn('before', history[0])

    def test_mutations_require_lock_and_concurrent_publish_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.store.begin('operator', ['home'], self.before)
        other = PublicationStore(self.base, 'demo')
        with self.store.locked():
            with self.assertRaises(PublicationConflict):
                with other.locked():
                    self.fail('The second publisher acquired the site lock')
            self.store.begin('operator', ['home'], self.before)
            with self.assertRaises(PublicationConflict):
                self.store.begin('operator', ['home'], self.before)

    def test_abandoned_publish_is_interrupted_and_never_retried(self):
        with self.store.locked():
            item = self.store.begin('operator', ['home'], self.before)
            self.store.result(item['id'], 'home', True)
        other = PublicationStore(self.base, 'demo')
        with other.locked():
            interrupted = other.get(item['id'])
            self.assertEqual(interrupted['state'], 'interrupted')
            self.assertEqual(interrupted['interrupted_operation'], 'publishing')
            self.assertEqual(len(interrupted['results']), 1)
            with self.assertRaises(PublicationConflict):
                other.restore(item['id'], version=interrupted['version'], user='operator',
                              confirmed=True, capture=lambda: self.after,
                              apply=lambda _: self.fail('Unverified restore was executed'))

    def test_restore_checks_confirmation_version_and_current_content(self):
        with self.store.locked():
            item = self.publication('partial')
            common = dict(version=item['version'], user='operator', confirmed=True,
                          capture=lambda: self.after, apply=lambda _: self.fail('Unexpected write'))
            for changed in [dict(confirmed=False), dict(version=0), dict(version=True),
                            dict(capture=lambda: {'pages': {'home': 'new manual edit'}})]:
                with self.assertRaises(AIError):
                    self.store.restore(item['id'], **(common | changed))
            self.assertEqual(self.store.get(item['id'])['state'], 'partial')

    def test_verified_restore_preserves_original_snapshot_and_actor(self):
        with self.store.locked():
            item = self.publication()
            live = copy.deepcopy(self.after)
            def apply(snapshot):
                live.clear()
                live.update(snapshot)
            result = self.store.restore(item['id'], version=item['version'], user='admin',
                                        confirmed=True, capture=lambda: live, apply=apply)
            self.assertEqual(live, self.before)
            self.assertEqual(result['state'], 'restored')
            self.assertEqual(result['restored_by'], 'admin')
            self.assertEqual(result['after'], self.after)
            self.assertEqual(result['before'], self.before)
            with self.assertRaises(PublicationConflict):
                self.store.restore(item['id'], version=result['version'], user='admin',
                                   confirmed=True, capture=lambda: live, apply=apply)

    def test_restore_failure_and_failed_readback_are_never_success(self):
        for raises in (True, False):
            with self.subTest(raises=raises), self.store.locked():
                item = self.publication()
                def apply(_):
                    if raises:
                        raise OSError('WordPress unavailable')
                with self.assertRaises((OSError, AIError)):
                    self.store.restore(item['id'], version=item['version'], user='admin',
                                       confirmed=True, capture=lambda: self.after, apply=apply)
                saved = self.store.get(item['id'])
                self.assertEqual(saved['state'], 'restore_failed')
                self.assertEqual(saved['before'], self.before)

    def test_invalid_paths_and_non_finite_or_oversized_snapshots(self):
        for slug in ('../demo', 'missing', 'demo/../../elsewhere'):
            with self.assertRaises(AIError):
                PublicationStore(self.base, slug)
        with self.assertRaises(AIError):
            self.store.get('../meta')
        with self.store.locked():
            for snapshot in ([], {'value': float('nan')}, {'html': 'x' * (self.store.MAX_SNAPSHOT_BYTES + 1)}):
                with self.assertRaises(AIError):
                    self.store.begin('operator', ['home'], snapshot)
            self.assertEqual(self.store.history(), [])

    def test_failed_restore_can_retry_only_from_verified_failure_state(self):
        with self.store.locked():
            item = self.publication()
            live = copy.deepcopy(self.after)
            def interrupted(snapshot):
                live['design'] = {'partially_restored': True}
                raise OSError('Connection lost during recovery')
            with self.assertRaises(OSError):
                self.store.restore(item['id'], version=item['version'], user='admin',
                                   confirmed=True, capture=lambda: live, apply=interrupted)
            failed = self.store.get(item['id'])
            self.assertEqual(failed['after'], self.after)
            self.assertEqual(failed['recovery_after'], live)
            self.assertTrue(self.store.history()[0]['can_restore'])
            def finish(snapshot):
                live.clear()
                live.update(snapshot)
            result = self.store.restore(item['id'], version=failed['version'], user='admin',
                                        confirmed=True, capture=lambda: live, apply=finish)
            self.assertEqual(result['state'], 'restored')
            self.assertEqual(live, self.before)

    def test_tampered_backup_is_not_applied(self):
        with self.store.locked():
            item = self.publication()
            item['before']['pages']['home']['content'] = 'tampered'
            self.store._path(item['id']).write_text(json.dumps(item))
            with self.assertRaisesRegex(AIError, '快照校验失败'):
                self.store.restore(item['id'], version=item['version'], user='admin',
                                   confirmed=True, capture=lambda: self.after,
                                   apply=lambda _: self.fail('Tampered snapshot applied'))


if __name__ == '__main__':
    unittest.main()
