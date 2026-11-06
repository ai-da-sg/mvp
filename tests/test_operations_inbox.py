import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
from kf_ai import AIError
from kf_operations_inbox import build_inbox, InboxAcknowledgements
from kf_tool_runtime import ActionConflict


class OperationsInboxTests(unittest.TestCase):
    def source(self, **changes):
        data = dict(sites=[{'slug': 'demo', 'company': 'Demo', 'domain': 'demo.test', 'port': 80,
                           'state': 'active', 'http': 200, 'days_left': 5}],
                    domains=[], jobs=[], actions=[], workflows=[], publications=[],
                    backups={'demo': 1793923200}, now=1793923200)
        data.update(changes)
        return build_inbox(**data)

    def test_current_health_expiry_and_archived_visibility(self):
        sites = [{'slug': 'demo', 'port': 80, 'http': 0, 'state': 'stopped', 'days_left': -2},
                 {'slug': 'old', 'port': 80, 'http': 0, 'state': 'stopped', 'archived': True},
                 {'slug': 'suspended', 'port': 80, 'http': 0, 'billing_status': 'suspended'}]
        items = self.source(sites=sites)
        self.assertEqual({x['code'] for x in items}, {'site_unreachable', 'service_expiry'})
        self.assertTrue(all(x['slug'] == 'demo' for x in items))
        self.assertTrue(any(x['slug'] == 'old' for x in self.source(sites=sites, include_archived=True)))
        domains = [{'slug': 'independent', 'domain': 'standalone.sg', 'company': 'Standalone',
                    'manage': {'expires': '2020-01-01'}}]
        item = next(x for x in self.source(domains=domains) if x['kind'] == 'domain')
        self.assertEqual(item['route'], 'domain')
        self.assertEqual(item['slug'], '')
        self.assertEqual(item['domain'], 'standalone.sg')

    def test_signals_are_redacted_and_successful_inspection_supersedes_old_result(self):
        actions = [dict(id='old', slug='demo', tool='site.https', state='succeeded', updated=1,
                        result={'ok': False, 'api_key': 'secret'}),
                   dict(id='new', slug='demo', tool='site.https', state='succeeded', updated=2,
                        result={'ok': True, 'certificate_days': 80}),
                   dict(id='mail', slug='demo', tool='mail.send', state='uncertain', updated=3,
                        error='secret password', arguments={'token': 'secret'})]
        items = self.source(actions=actions)
        self.assertNotIn('inspection', [x['kind'] for x in items])
        self.assertEqual(next(x for x in items if x['kind'] == 'action')['reference'], 'mail')
        self.assertNotIn('secret', json.dumps(items))
        actions.append(dict(id='delivery', slug='demo', tool='mail.status', state='succeeded', updated=4,
                            result={'delivered': False, 'recipient': 'private@example.test'}))
        items = self.source(actions=actions)
        self.assertTrue(any(x['code'] == 'mail_delivery_failed' for x in items))
        self.assertNotIn('private@example', json.dumps(items))

    def test_completed_workflow_removes_its_failed_step_signal(self):
        items = self.source(actions=[dict(id='step', slug='demo', tool='site.generate', state='failed', workflow_id='flow')],
                            workflows=[dict(id='flow', slug='demo', state='completed')])
        self.assertFalse(any(x['kind'] in {'action', 'workflow'} for x in items))

    def test_acknowledgements_are_personal_versioned_and_reversible(self):
        with tempfile.TemporaryDirectory() as root:
            store = InboxAcknowledgements(root)
            items = self.source(jobs=[dict(id='job', slug='demo', status='failed', updated=1)])
            item = next(x for x in items if x['kind'] == 'generation')
            with self.assertRaises(ActionConflict):
                store.acknowledge('ops', item, 'stale')
            store.acknowledge('ops', item, item['revision'])
            self.assertNotIn(item, store.filter('ops', items))
            self.assertIn(item, store.filter('other', items))
            changed = self.source(jobs=[dict(id='job', slug='demo', status='failed', updated=2)])
            self.assertTrue(any(x['kind'] == 'generation' for x in store.filter('ops', changed)))
            store.acknowledge('ops', item, item['revision'], restore=True)
            self.assertIn(item, store.filter('ops', items))
            critical = next(x for x in items if x['kind'] == 'service')
            with self.assertRaises(AIError):
                store.acknowledge('ops', critical, critical['revision'])


if __name__ == '__main__':
    unittest.main()
