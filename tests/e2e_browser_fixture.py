"""Real application HTTP server with disposable account/data files; no mocked handlers."""
import json
import os
from pathlib import Path
import sys
from test_ai import ConsoleTests

fixture = ConsoleTests()
fixture.setUp()
m = fixture.m
writing_server = None
try:
    if os.environ.get('KF_E2E_GEO_ALIAS') == '1':
        # The main installation registers clone-lab sites as same-slug aliases.
        # Exercise the real filesystem layout rather than only plain directories.
        shared = fixture.base / 'shared-install' / 'sites'
        shared.mkdir(parents=True)
        (fixture.base / 'sites/demo').rename(shared / 'demo')
        (fixture.base / 'sites/demo').symlink_to(shared / 'demo', target_is_directory=True)
        # Seed a publication journal entry for report-linking tests. This fixture
        # does not claim a live WordPress publication or a business improvement.
        journal=m.kf_publications.PublicationStore(fixture.base,'demo')
        with journal.locked():
            publication=journal.begin('ops-test',['home'],{'pages':{}})
            journal.result(publication['id'],'home',True)
            journal.finish(publication['id'],'published',{'pages':{}})
    if os.environ.get('KF_E2E_REAL_AI_BASE'):
        # Explicit opt-in only: use the existing configured upstream in a disposable app.
        source = Path(os.environ['KF_E2E_REAL_AI_BASE']).resolve() / 'console'
        config = json.loads((source/'ai-config.json').read_text())
        secrets = json.loads((source/'ai-secrets.json').read_text())
        profile_id = os.environ.get('KF_E2E_REAL_AI_PROFILE') or config['default_profile']
        profile = next((p for p in config['profiles'] if p['id']==profile_id), None)
        if profile is None:
            raise RuntimeError('Select an existing real profile for the live test')
        m.ai_store().configure(dict(profile, api_key=secrets.get(profile_id, '')))
        m.ai_store().configure(dict(action='default', id=profile_id))
    if os.environ.get('KF_E2E_GEO_COLLECTION') == 'fixture':
        # Deterministic provider response; real HTTP handlers, vault and journal.
        # Live upstream verification uses KF_E2E_GEO_COLLECTION=live instead.
        from test_geo_collection import response
        def geo_fixture_response(provider,config,question):
            import time
            time.sleep(1)
            return response(provider)
        m.geo_collector().transport=geo_fixture_response
    if os.environ.get('KF_E2E_WRITING') == '1':
        # A local model protocol fixture: real HTTP through the application and
        # model adapter, deterministic text rather than a paid upstream model.
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        class WritingHandler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                context = json.loads(request['messages'][1]['content'])
                result = 'Suggested '+context['context']['field']+' for '+context['context'].get('company', 'Demo')
                payload = json.dumps({'choices':[{'finish_reason':'stop','message':{'content':result}}]}).encode()
                self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload)
        writing_server = ThreadingHTTPServer(('127.0.0.1',0), WritingHandler)
        threading.Thread(target=writing_server.serve_forever,daemon=True).start()
        m.ai_store().configure(dict(id='writing',name='Local protocol fixture',protocol='openai_chat',model='test',base_url='http://127.0.0.1:'+str(writing_server.server_port)+'/v1'))
    (m.CONSOLE / 'providers.js').symlink_to(Path(__file__).resolve().parents[1] / 'console/providers.js')
    if os.environ.get('KF_E2E_PAGES') == '1':
        draft=json.loads(json.dumps(fixture.original))
        draft['pages']=[p for p in draft['pages'] if p['slug']=='home']
        m.kf_ai.atomic_json(m.draft_path('demo'),draft)
    if os.environ.get('KF_E2E_DOMAIN') == '1':
        # Register a domain for UI coverage; no upstream service is contacted.
        meta_path = fixture.base / 'sites/demo/meta.json'
        meta = json.loads(meta_path.read_text())
        meta['port'] = 9
        meta_path.write_text(json.dumps(meta))
    users = m.load_users()
    users['mfa-test'] = dict(users['ops-test'], mfa_secret='JBSWY3DPEHPK3PXP')
    m._write(m.USERS_F, users)
    if os.environ.get('KF_E2E_DNS') == '1':
        # Real local zone storage and execution; only external authority/observation
        # are fixed for the reserved .test domain. No public DNS is modified.
        local = m.dnsmod()
        local.update_zones(lambda zones: zones.update(demo=local.new_zone('example.test','192.0.2.1')))
        m.kf_dns_provider.DNSProviders(m.BASE,local).configure({'provider':'local'},m.automation_context('demo'))
        m.kf_dns_provider.authority = lambda domain: {'state':'ok','zone':domain,'nameservers':sorted([local.NS1,local.NS2]),'provider':'local'}
        m.kf_dns_provider.query = lambda *args: {'state':'unknown','values':[]}
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
    if writing_server:
        writing_server.shutdown(); writing_server.server_close()
    fixture.tearDown()
