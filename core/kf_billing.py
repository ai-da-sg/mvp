"""Invoice adjustments and recoverable, idempotent payment/renewal writes.

The console also holds its shared file lock around mutations so legacy ledger
and site writers cannot interleave with these operations in the same process.
"""
import copy
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import fcntl
from pathlib import Path
import re
import threading
import uuid

from kf_ai import AIError, atomic_json, read_json
from kf_tool_runtime import ActionConflict

SGT = timezone(timedelta(hours=8))
_LOCK = threading.RLock()


def money(value):
    try:
        if isinstance(value, bool):
            raise ValueError()
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 100000000:
            raise ValueError()
        return float(amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
    except (ValueError, InvalidOperation):
        raise AIError('Invalid amount') from None


def due_date(value):
    if value == '':
        return ''
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise AIError('Invalid due date')
    try:
        date.fromisoformat(value)
    except ValueError:
        raise AIError('Invalid due date') from None
    return value


def add_years(value, years):
    day = date.fromisoformat(value)
    try:
        return day.replace(year=day.year + years).isoformat()
    except ValueError:
        return day.replace(year=day.year + years, day=28).isoformat()


class Billing:
    def __init__(self, base, clock=None):
        self.base = Path(base)
        self.root = self.base / 'console'
        self.root.mkdir(parents=True, exist_ok=True)
        self.invoices = self.root / 'invoices.json'
        self.ledger = self.root / 'ledger.json'
        self.pending = self.root / 'billing-pending'
        self.pending.mkdir(exist_ok=True)
        self.clock = clock or (lambda: datetime.now(SGT))

    @contextmanager
    def locked(self):
        with _LOCK, (self.root / 'billing.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _path(self, no):
        if not isinstance(no, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', no):
            raise AIError('Invalid invoice')
        return self.pending / (no + '.json')

    def _find(self, no):
        self._path(no)
        items = read_json(self.invoices, [])
        item = next((x for x in items if x['no'] == no), None)
        if item is None:
            raise AIError('Invoice not found')
        return items, item

    def public(self, items):
        today = self.clock().date().isoformat()
        return [dict(x, version=x.get('version', 0), due_date=x.get('due_date', ''),
                     overdue=x.get('status') != 'paid' and bool(x.get('due_date')) and x['due_date'] < today,
                     processing=self._path(x['no']).exists()) for x in items]

    def create(self, slug, company, domain, plan, settings, kind='new', years=0, user='', apply_renewal=False):
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,19}', slug):
            raise AIError('Invalid site')
        if kind == 'renewal' and (type(years) is not int or not 1 <= years <= 5):
            raise AIError('Renewal years must be between 1 and 5')
        with self.locked():
            items = read_json(self.invoices, [])
            existing = next((x for x in items if x.get('slug') == slug and x.get('kind') == 'renewal' and x.get('status') != 'paid'), None) if kind == 'renewal' else None
            if existing:
                if int(existing.get('years') or 1) != years:
                    raise ActionConflict('A renewal invoice already exists for a different period')
                if self._path(existing['no']).exists():
                    return self._finish(existing['no'])
                if apply_renewal and not existing.get('renewal_applied'):
                    self._begin(existing, user, payment=False)
                    return self._finish(existing['no'])
                return copy.deepcopy(existing)
            year = self.clock().year
            numbers = [int(m.group(1)) for x in items if (m := re.fullmatch(rf'KF-{year}-(\d+)', x.get('no', '')))]
            no = f'KF-{year}-{max(numbers, default=0)+1:04d}'
            subtotal = money(Decimal(str(money(plan['price']))) * (years if kind == 'renewal' else 1))
            gst = money(Decimal(str(subtotal)) * Decimal(str(settings.get('gst_rate', 0)))) if settings.get('gst_enabled') else 0
            item = dict(no=no, slug=slug, company=company, domain=domain, plan_id=plan['id'], plan_name=plan['name'],
                        plan_specs=plan.get('specs', ''), subtotal=subtotal, gst=gst, total=money(Decimal(str(subtotal))+Decimal(str(gst))),
                        status='unpaid', issued_at=self.clock().strftime('%Y-%m-%d %H:%M'), paid_at='',
                        kind=kind, years=years, version=0, due_date='', history=[])
            items.append(item)
            atomic_json(self.invoices, items)
            if apply_renewal:
                self._begin(item, user, payment=False)
                return self._finish(no)
            return copy.deepcopy(item)

    def adjust(self, no, version, subtotal, gst, due, reason, user):
        amount, tax, due = money(subtotal), money(gst), due_date(due)
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise AIError('An adjustment reason is required (maximum 500 characters)')
        with self.locked():
            items, item = self._find(no)
            if item.get('status') == 'paid' or self._path(no).exists():
                raise ActionConflict('Paid or processing invoices cannot be adjusted')
            if type(version) is not int or item.get('version', 0) != version:
                raise ActionConflict('Invoice changed; refresh before saving')
            before = {k: item.get(k, '') for k in ('subtotal', 'gst', 'total', 'due_date')}
            after = dict(subtotal=amount, gst=tax, total=money(Decimal(str(amount))+Decimal(str(tax))), due_date=due)
            if before == after:
                raise AIError('No invoice changes')
            item.setdefault('history', []).append(dict(event='adjustment', at=self.clock().isoformat(), by=user,
                                                       reason=reason.strip(), before=before, after=after))
            item.update(after, version=version+1)
            atomic_json(self.invoices, items)
            return copy.deepcopy(item)

    def _begin(self, item, user, payment):
        money(item['total'])
        intent = dict(id=uuid.uuid4().hex, no=item['no'], version=item.get('version', 0), payment=payment,
                      by=user, at=self.clock().strftime('%Y-%m-%d %H:%M'), renewal=None)
        if item.get('kind') == 'renewal' and not item.get('renewal_applied'):
            path = self.base / 'sites' / item['slug'] / 'billing.json'
            billing = read_json(path, {})
            before = billing.get('expires', '')
            # Validate legacy data before creating any payment intent or ledger entry.
            try:
                due_date(before)
                base = max(before or self.clock().date().isoformat(), self.clock().date().isoformat())
                after = add_years(base, int(item.get('years') or 1))
            except (AIError, ValueError, TypeError, OverflowError):
                raise AIError('Invalid service expiry; review before renewing') from None
            intent['renewal'] = {'before': before, 'after': after}
        atomic_json(self._path(item['no']), intent)

    def _finish(self, no):
        intent = read_json(self._path(no), None)
        items, item = self._find(no)
        if item.get('last_billing_operation') == intent['id']:
            self._path(no).unlink()
            return copy.deepcopy(item)
        if item.get('version', 0) != intent['version']:
            raise ActionConflict('Invoice changed during processing; review required')
        if intent['payment']:
            rows = read_json(self.ledger, [])
            if not any(x.get('payment_invoice') == no for x in rows):
                rows.append(dict(id='PAY-'+no, payment_invoice=no, slug=item['slug'], type='topup', amount=item['total'],
                                 category='服务费', note='账单 '+no+' 已付款', ts=intent['at'], by=intent['by']))
                atomic_json(self.ledger, rows)
        if intent['renewal']:
            path = self.base / 'sites' / item['slug'] / 'billing.json'
            billing = read_json(path, {})
            applied = billing.setdefault('renewal_invoices', [])
            if no not in applied:
                if billing.get('expires', '') != intent['renewal']['before']:
                    raise ActionConflict('Service expiry changed during processing; review required')
                billing['expires'] = intent['renewal']['after']
                if billing.get('status') != 'suspended':
                    billing['status'] = 'active'
                applied.append(no)
                atomic_json(path, billing)
            item['renewal_applied'] = True
            item['renewal_expires'] = intent['renewal']['after']
        if intent['payment']:
            item.update(status='paid', paid_at=intent['at'])
        item.setdefault('history', []).append(dict(event='payment' if intent['payment'] else 'renewal', at=intent['at'], by=intent['by']))
        item.update(version=intent['version']+1, last_billing_operation=intent['id'])
        atomic_json(self.invoices, items)
        self._path(no).unlink()
        return copy.deepcopy(item)

    def pay(self, no, user, version=None):
        with self.locked():
            _, item = self._find(no)
            if self._path(no).exists():
                # Finish an interrupted renewal before starting its payment.
                item = self._finish(no)
            if item.get('status') == 'paid':
                return copy.deepcopy(item)
            if version is not None and (type(version) is not int or item.get('version', 0) != version):
                raise ActionConflict('Invoice changed; refresh before saving')
            self._begin(item, user, payment=True)
            return self._finish(no)
