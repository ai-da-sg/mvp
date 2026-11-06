"""Read-only operational signals and per-operator acknowledgements.

No provider calls or execution tickets are created by this module. The caller
supplies records already filtered by the operator's access rights.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import threading
import time
from pathlib import Path

from kf_ai import AIError, atomic_json, read_json
from kf_tool_runtime import fingerprint, ActionConflict

_LOCK = threading.RLock()


def build_inbox(*, sites, domains, jobs, actions, workflows, publications, backups,
                include_archived=False, now=None):
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, timezone(timedelta(hours=8))).date()
    all_sites = {s['slug']: s for s in sites}
    visible = {k: s for k, s in all_sites.items() if include_archived or not s.get('archived')}
    items = []

    def add(kind, ref, slug, code, route, severity='warning', source=None, **details):
        source = source or {}
        site = visible.get(slug, {})
        item = {'id': kind + ':' + str(ref), 'kind': kind, 'reference': str(ref), 'slug': slug,
                'company': site.get('company', source.get('company', slug)),
                'domain': site.get('domain', source.get('domain', '')), 'archived': bool(site.get('archived')),
                'code': code, 'route': route, 'severity': severity, 'details': details,
                'updated': source.get('updated', source.get('created', 0)),
                'acknowledge': kind in {'generation', 'action', 'workflow', 'publication', 'inspection'}}
        item['revision'] = fingerprint(item)
        items.append(item)

    for slug, site in visible.items():
        if site.get('port') and site.get('billing_status') != 'suspended' and site.get('state') != 'provisioning':
            if site.get('health_error'):
                add('site', slug, slug, 'health_unknown', 'automation')
            elif not 200 <= int(site.get('http') or 0) < 400:
                add('site', slug, slug, 'site_unreachable', 'automation', 'critical', http=site.get('http', 0))
        days = site.get('days_left')
        if days is not None and days <= 30:
            add('service', slug, slug, 'service_expiry', 'client', 'critical' if days < 0 else 'warning', days=days)
        if site.get('port') and site.get('state') == 'active':
            stamp = backups.get(slug)
            if stamp is None or now - stamp >= 7 * 86400:
                add('backup', slug, slug, 'content_snapshot_old' if stamp else 'content_snapshot_missing',
                    'layout', 'info', days=int((now-stamp)/86400) if stamp else None)
    for domain in domains:
        slug = domain.get('site_slug', '')
        if slug and slug not in visible:
            continue
        try:
            days = (datetime.strptime(domain.get('manage', {}).get('expires', ''), '%Y-%m-%d').date() - today).days
        except (TypeError, ValueError):
            continue
        if days <= 30:
            add('domain', domain['slug'], slug, 'domain_expiry', 'domain',
                'critical' if days < 0 else 'warning', source=domain, days=days)
    for job in jobs:
        if job.get('slug') in visible and job.get('status') == 'failed':
            add('generation', job['id'], job['slug'], 'generation_failed', 'ai', source=job)
    completed = {w['id'] for w in workflows if w.get('state') == 'completed'}
    latest = {}
    for action in actions:
        slug, tool = action.get('slug'), action.get('tool', '')
        if slug not in visible or action.get('workflow_id') in completed:
            continue
        if action.get('state') in {'failed', 'uncertain', 'interrupted'}:
            add('action', action['id'], slug, 'action_attention', 'automation', source=action,
                state=action['state'], tool=tool)
        if action.get('state') == 'succeeded' and tool in {'site.https', 'dns.inspect', 'mail.inspect', 'maintenance.inspect', 'mail.status'}:
            key = (slug, tool)
            if action.get('updated', 0) >= latest.get(key, {}).get('updated', 0):
                latest[key] = action
    for (slug, tool), action in latest.items():
        result = action.get('result') or {}
        https = result if tool == 'site.https' else result.get('https', {})
        bad_checks = sum(c.get('status') in {'warn', 'fail'} for c in result.get('checks', []))
        code = None
        if https and (not https.get('ok') or https.get('certificate_days', 999) <= 30):
            code = 'https_attention'
        elif tool == 'mail.status' and result.get('delivered') is not True:
            code = 'mail_delivery_failed' if result.get('delivered') is False else 'mail_delivery_unknown'
        elif bad_checks:
            code = 'inspection_attention'
        if code:
            add('inspection', action['id'], slug, code, 'automation', source=action,
                checks=bad_checks, tool=tool, checked_at=action.get('updated', 0))
    for workflow in workflows:
        if workflow.get('slug') in visible and workflow.get('state') in {'failed', 'paused', 'waiting'}:
            add('workflow', workflow['id'], workflow['slug'], 'workflow_attention', 'automation',
                source=workflow, state=workflow['state'])
    for record in publications:
        if record.get('slug') in visible and record.get('state') in {'partial', 'failed', 'interrupted', 'restore_failed'}:
            add('publication', record['id'], record['slug'], 'publication_attention', 'layout',
                source=record, state=record['state'])
    rank = {'critical': 0, 'warning': 1, 'info': 2}
    return sorted(items, key=lambda x: (rank[x['severity']], x['company'], x['id']))


class InboxAcknowledgements:
    def __init__(self, base):
        self.path = Path(base) / 'console' / 'operations-acknowledgements.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def locked(self):
        with _LOCK, self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def filter(self, user, items):
        with self.locked():
            known = read_json(self.path, {}).get(user, {})
        return [item for item in items if known.get(item['id'], {}).get('revision') != item['revision']]

    def acknowledge(self, user, item, revision, restore=False):
        if not item.get('acknowledge'):
            raise AIError('此事项需要修复后自动消除，不能标记已知悉')
        if revision != item.get('revision'):
            raise ActionConflict('待办事项已变化，请刷新后再处理')
        with self.locked():
            data = read_json(self.path, {})
            known = data.setdefault(user, {})
            if restore:
                known.pop(item['id'], None)
            else:
                known[item['id']] = {'revision': revision, 'at': time.time()}
            if len(known) > 500:
                data[user] = dict(sorted(known.items(), key=lambda x: x[1]['at'], reverse=True)[:500])
            atomic_json(self.path, data)
