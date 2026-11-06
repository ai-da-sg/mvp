"""Real application HTTP server with disposable account/data files; no mocked handlers."""
import json
import os
from pathlib import Path
import sys
from test_ai import ConsoleTests

fixture = ConsoleTests()
fixture.setUp()
m = fixture.m
try:
    (m.CONSOLE / 'providers.js').symlink_to(Path(__file__).resolve().parents[1] / 'console/providers.js')
    if os.environ.get('KF_E2E_DOMAIN') == '1':
        # Register a domain for UI coverage; no upstream service is contacted.
        meta_path = fixture.base / 'sites/demo/meta.json'
        meta = json.loads(meta_path.read_text())
        meta['port'] = 9
        meta_path.write_text(json.dumps(meta))
    users = m.load_users()
    users['mfa-test'] = dict(users['ops-test'], mfa_secret='JBSWY3DPEHPK3PXP')
    m._write(m.USERS_F, users)
    if os.environ.get('KF_E2E_BILLING') == '1':
        from datetime import timedelta
        import kf_ai
        plan = m.plans()[0]
        kf_ai.atomic_json(m.SITES / 'demo/billing.json', {'plan_id': plan['id'], 'expires': m.datetime.now(m.SGT).date().isoformat(), 'status': 'active'})
        store = m.kf_billing.Billing(m.BASE)
        for title in ('Overdue invoice', 'Undated invoice', 'Paid invoice'):
            item = m.make_invoice('demo', title, 'example.test', dict(plan, price=100))
            if title.startswith('Overdue'):
                store.adjust(item['no'], 0, 100, 0, (m.datetime.now(m.SGT).date()-timedelta(days=1)).isoformat(), 'Fixture terms', 'admin')
            elif title.startswith('Paid'):
                store.pay(item['no'], 'admin')
        old = m.SITES / 'old-demo'
        old.mkdir()
        kf_ai.atomic_json(old / 'meta.json', {'company': 'Archived customer', 'port': 0})
        kf_ai.atomic_json(old / 'archive.json', {'archived': True})
        m.make_invoice('old-demo', 'Archived customer', 'old.test', dict(plan, price=100))
    if os.environ.get('KF_E2E_LEADS') == '1':
        # Exercise real HTTP, authorization and persistent follow-ups without
        # starting WordPress containers in CI. Live WP reads have opt-in proof.
        for slug in ('other', 'archived', 'broken'):
            site = m.SITES / slug
            site.mkdir()
            (site / 'meta.json').write_text(json.dumps({'company': slug, 'domain': slug+'.test', 'port': 0}))
        (m.SITES / 'archived/archive.json').write_text('{"archived":true}')
        failures = [0]
        def read_enquiries(site, page=1, lead_id=None):
            if site.name == 'broken' and not failures[0]:
                failures[0] += 1
                raise m.kf_leads.LeadReadError('Fixture unavailable')
            count = 102 if site.name == 'demo' else 1
            ids = [lead_id] if lead_id is not None and 1 <= lead_id <= count else (list(range(count, 0, -1))[(page-1)*100:page*100] if lead_id is None else [])
            items = [{'id': ident, 'title': 'Enquiry '+str(ident), 'email': 'test@example.test', 'phone': '',
                      'msg': '<script>window.leadUnsafe=true</script> Service enquiry', 'date': '2026-11-01 09:00:00', 'sent': '1'} for ident in ids]
            return {'items': items, 'total': count, 'has_more': page*100<count, 'checked_at': 1}
        m.kf_leads.read_page = read_enquiries
    if os.environ.get('KF_E2E_OPERATIONS') == '1':
        store = m.ai_store()
        job = store.create_job('demo', store.resolve('mock')[0], 'ops-test', 'existing')
        store.update_job(job['id'], status='failed', message='Private generation details')
    if os.environ.get('KF_E2E_PUBLICATION') == '1':
        # The fixture has no WordPress service; use its explicit in-memory
        # transport while exercising the real publication journal and HTTP UI.
        import kf_ai
        draft = json.loads(json.dumps(fixture.original))
        draft['pages'][0]['title'] = 'Publication recovery fixture'
        kf_ai.atomic_json(m.SITES / 'demo' / 'site-draft.json', draft)
        code, result = m.publish_site({'slug': 'demo'}, lambda *a, **kw: {'ok': True}, 'admin')
        assert code == 200, result
    # Deliberately provide no preauthenticated cookie: tests must log in through the UI.
    print(json.dumps({'origin': 'http://127.0.0.1:' + str(fixture.server.server_port),
                      'password': 'Test-Password-123'}), flush=True)
    sys.stdin.readline()
finally:
    fixture.tearDown()
