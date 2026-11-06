from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import kf_billing as billing
from kf_ai import atomic_json, read_json, AIError
from kf_tool_runtime import ActionConflict


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.store = billing.Billing(self.base, lambda: datetime(2026, 11, 6, tzinfo=timezone.utc))
        self.site = self.base / 'sites/demo/billing.json'
        atomic_json(self.site, {'expires': '2027-01-01', 'status': 'active', 'domain': {'registrar': 'Preserved'}})
        self.plan = {'id': 'annual', 'name': 'Annual', 'price': 100}
        self.config = {'gst_enabled': True, 'gst_rate': .09}

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, **kw):
        return self.store.create('demo', 'Demo', 'demo.test', self.plan, self.config, **kw)

    def test_adjustment_history_due_date_and_paid_protection(self):
        invoice = self.create()
        changed = self.store.adjust(invoice['no'], 0, '120.005', '10.80', '2026-11-01', 'Additional work', 'finance')
        self.assertEqual(changed['total'], 130.81)
        self.assertTrue(self.store.public([changed])[0]['overdue'])
        self.assertEqual(changed['history'][0]['before']['total'], 109)
        with self.assertRaises(ActionConflict):
            self.store.adjust(invoice['no'], 0, 100, 9, '', 'Stale', 'admin')
        paid = self.store.pay(invoice['no'], 'finance', 1)
        self.assertFalse(self.store.public([paid])[0]['overdue'])
        with self.assertRaises(ActionConflict):
            self.store.adjust(invoice['no'], 2, 100, 9, '', 'Change paid', 'finance')
        self.store.pay(invoice['no'], 'finance')
        self.assertEqual(len(read_json(self.store.ledger, [])), 1)

    def test_manual_multiyear_renewal_and_payment_extend_only_once(self):
        item = self.create(kind='renewal', years=3, user='ops', apply_renewal=True)
        self.assertEqual(item['subtotal'], 300)
        self.assertEqual(item['total'], 327)
        self.assertEqual(read_json(self.site, {})['expires'], '2030-01-01')
        again = self.create(kind='renewal', years=3, apply_renewal=True)
        self.assertEqual(again['no'], item['no'])
        with self.assertRaises(ActionConflict):
            self.create(kind='renewal', years=2, apply_renewal=True)
        self.store.pay(item['no'], 'finance', item['version'])
        self.assertEqual(read_json(self.site, {})['expires'], '2030-01-01')
        self.assertEqual(read_json(self.site, {})['domain']['registrar'], 'Preserved')

    def test_interrupted_payment_retries_without_duplicate_income_or_renewal(self):
        item = self.create(kind='renewal', years=1)
        original = billing.atomic_json
        def fail_invoice(path, data):
            if Path(path) == self.store.invoices:
                raise OSError('Disk failure')
            original(path, data)
        with patch.object(billing, 'atomic_json', side_effect=fail_invoice):
            with self.assertRaises(OSError):
                self.store.pay(item['no'], 'finance')
        self.assertEqual(len(read_json(self.store.ledger, [])), 1)
        self.assertEqual(read_json(self.site, {})['expires'], '2028-01-01')
        self.assertTrue(self.store.public(read_json(self.store.invoices, []))[0]['processing'])
        restored = billing.Billing(self.base).pay(item['no'], 'finance', 0)
        self.assertEqual(restored['status'], 'paid')
        self.assertEqual(read_json(self.site, {})['expires'], '2028-01-01')
        self.assertEqual(len(read_json(self.store.ledger, [])), 1)
        self.assertFalse(self.store.public([restored])[0]['processing'])

    def test_historical_paid_invoices_are_not_replayed(self):
        item = self.create()
        item['status'] = 'paid'
        atomic_json(self.store.invoices, [item])
        self.store.pay(item['no'], 'admin')
        self.assertFalse(self.store.ledger.exists())

    def test_invalid_legacy_expiry_does_not_start_payment(self):
        item = self.create(kind='renewal', years=1)
        for expiry in ('tomorrow', '2026-02-30', '9999-12-31', None):
            atomic_json(self.site, {'expires': expiry})
            with self.assertRaises(AIError):
                self.store.pay(item['no'], 'finance')
            self.assertFalse(self.store.ledger.exists())
            self.assertFalse(self.store._path(item['no']).exists())
            self.assertEqual(read_json(self.store.invoices, [])[0]['status'], 'unpaid')

    def test_invalid_money_dates_and_expiry_conflicts(self):
        for value in ('NaN', 'Infinity', -1, True, 'invalid'):
            with self.assertRaises(AIError):
                billing.money(value)
        for value in ('2026-02-30', 'tomorrow', None):
            with self.assertRaises(AIError):
                billing.due_date(value)
        self.assertEqual(billing.add_years('2024-02-29', 1), '2025-02-28')
        item = self.create(kind='renewal', years=1)
        with self.store.locked():
            self.store._begin(item, 'finance', payment=True)
        atomic_json(self.site, {'expires': '2031-01-01'})
        with self.assertRaises(ActionConflict):
            self.store.pay(item['no'], 'finance')
        self.assertEqual(read_json(self.site, {})['expires'], '2031-01-01')
