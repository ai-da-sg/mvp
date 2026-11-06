import base64
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import kf_leads as leads
from kf_ai import AIError
from kf_tool_runtime import ActionConflict


class LeadsTests(unittest.TestCase):
    def test_followups_are_versioned_persistent_and_site_scoped(self):
        with tempfile.TemporaryDirectory() as base:
            first = leads.Followups(base, 'demo')
            result = first.save(7, 'contacted', 'Call tomorrow', 0, 'ops')
            self.assertEqual(result['version'], 1)
            self.assertEqual(result['history'][0]['from'], 'new')
            self.assertEqual(leads.Followups(base, 'other').all(), {})
            with self.assertRaises(ActionConflict):
                first.save(7, 'closed', 'stale', 0, 'admin')
            result = leads.Followups(base, 'demo').save(7, 'won', 'Confirmed', 1, 'admin')
            self.assertEqual([h['by'] for h in result['history']], ['ops', 'admin'])
            self.assertEqual(first.all()['7']['status'], 'won')
            self.assertEqual(first.path.stat().st_mode & 0o777, 0o600)

    def test_invalid_or_empty_updates_do_not_write(self):
        with tempfile.TemporaryDirectory() as base:
            store = leads.Followups(base, 'demo')
            for args in [(True, 'new', 'note', 0), (1, 'bogus', '', 0), (1, 'new', '', 0),
                         (1, 'contacted', 'x'*2001, 0), (1, 'contacted', 'note', True)]:
                with self.assertRaises(AIError):
                    store.save(*args, 'ops')
            self.assertFalse(store.path.exists())

    def test_wordpress_read_uses_paged_query_without_shared_temp_file(self):
        with tempfile.TemporaryDirectory() as base, patch.object(leads, 'wp') as wp:
            wp.return_value = subprocess.CompletedProcess([], 0, json.dumps({'items': [{'id': 7}], 'total': 201}), '')
            page = leads.read_page(Path(base), 2)
            self.assertTrue(page['has_more'])
            self.assertEqual(page['page'], 2)
            self.assertEqual(wp.call_args.args[1], 'eval')
            self.assertEqual(list(Path(base).iterdir()), [])
            leads.read_page(Path(base), lead_id=7)
            encoded = re.search(r"base64_decode\('([^']+)'\)", wp.call_args.args[2]).group(1)
            query = json.loads(base64.b64decode(encoded))
            self.assertEqual(query['post__in'], [7])
            self.assertNotIn('p', query)  # Private enquiries must remain list queries.
            wp.return_value.returncode = 1
            with self.assertRaises(leads.LeadReadError):
                leads.read_page(Path(base))
            wp.return_value = subprocess.CompletedProcess([], 0, '{"items":[{"id":true}],"total":1}', '')
            with self.assertRaises(leads.LeadReadError):
                leads.read_page(Path(base))
