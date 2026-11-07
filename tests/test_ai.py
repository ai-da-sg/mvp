import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
import kf_ai as ai

PAGES = [{'slug': 'home', 'title': 'Home'}, {'slug': 'contact', 'title': 'Contact'}]


class ProviderTests(unittest.TestCase):
    def test_mock_and_validation(self):
        spec = ai.generate(ai.MOCK, '', '测试企业', '设计咨询；空间规划', PAGES, 'zh')
        self.assertEqual([p['slug'] for p in spec['pages']], ['home', 'contact'])
        self.assertIn('设计咨询', json.dumps(spec, ensure_ascii=False))
        for change in ('missing', 'duplicate', 'rich', 'bad_url', 'bad_items', 'unknown_field'):
            bad = copy.deepcopy(spec)
            if change == 'missing': bad['pages'].pop()
            if change == 'duplicate': bad['pages'].append(bad['pages'][0])
            if change == 'rich': bad['pages'][0]['sections'][0] = {'type': 'rich', 'html': '<script>x</script>'}
            if change == 'bad_url': bad['pages'][0]['sections'][0]['cta']['href'] = 'javascript:alert(1)'
            if change == 'bad_items': bad['pages'][0]['sections'][1]['items'] = 'not an array'
            if change == 'unknown_field': bad['pages'][0]['sections'][0]['onclick'] = 'x'
            with self.subTest(change=change), self.assertRaises(ai.AIError):
                ai.validate_spec(bad, PAGES)

    def test_all_template_sections_validate_and_unsafe_content_is_rejected(self):
        import kf_style_experience as experience
        page={'slug':'home','title':'Home','blueprint':list(experience.BLOCKS)}
        sections=experience.sample_sections({'name':'Studio','sector':'creative'},page)
        spec={'pages':[{'slug':'home','title':'Home','sections':sections}]}
        clean=ai.validate_spec(spec,[page])
        self.assertEqual({b['type'] for b in clean['pages'][0]['sections']},set(experience.BLOCKS))
        rich=next(b for b in sections if b['type']=='rich')
        rich['html']='<p>Keep this</p><script>alert(1)</script><img src=x onerror=alert(1)>'
        cleaned=ai.validate_spec(spec,[page])
        markup=next(b for b in cleaned['pages'][0]['sections'] if b['type']=='rich')['html']
        self.assertIn('Keep this',markup);self.assertNotIn('<script',markup);self.assertNotIn('onerror',markup)
        for block in [
            {'type':'band','src':'javascript:alert(1)'},
            {'type':'gallery','items':[{'src':'//evil.test/x','label':'Image'}]},
            {'type':'table','headers':['A','B'],'rows':[['Only one']]},
            {'type':'table','headers':['A']},
            {'type':'quotes','items':[{'text':'Quote','by':'Name','onclick':'bad'}]},
        ]:
            with self.subTest(block=block),self.assertRaises(ai.AIError):
                ai.validate_spec({'pages':[{'slug':'home','title':'Home','sections':[sections[0],block]}]},[page])

    def test_config_keys_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            store = ai.AIStore(d)
            body = dict(id='custom', name='Custom', protocol='openai_chat', model='model-test',
                        base_url='http://127.0.0.1:1234/v1', api_key='test-secret')
            public = store.configure(body)
            self.assertNotIn('test-secret', json.dumps(public))
            self.assertNotIn('api_key', (store.config_path).read_text())
            self.assertEqual(store.keys_path.stat().st_mode & 0o777, 0o600)
            store.configure(dict(body, api_key=''))
            self.assertEqual(store.resolve('custom')[1], 'test-secret')
            store.configure({'action': 'default', 'id': 'custom'})
            self.assertEqual(store.resolve(None)[0]['id'], 'custom')
            store.configure(dict(body, api_key='', clear_key=True))
            self.assertEqual(store.resolve('custom')[1], '')
            job = store.create_job('test', ai.MOCK, 'admin', 'existing')
            with self.assertRaises(ai.AIError): store.create_job('test', ai.MOCK, 'admin', 'existing')
            restored = ai.AIStore(d)
            self.assertEqual(restored.jobs()[0]['status'], 'interrupted')
            restored.configure({'action': 'delete', 'id': 'custom'})
            self.assertEqual(restored.resolve(None)[0]['id'], 'mock')

    def test_four_protocols_over_http(self):
        captured = []
        payload = json.dumps(ai.mock_spec('Test', 'Consultation', PAGES, 'en'))
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured.append((self.path, dict(self.headers), body))
                if 'redirect' in self.path:
                    self.send_response(302); self.send_header('Location', '/leaked'); self.end_headers(); return
                if 'fail' in self.path:
                    self.send_response(401); self.end_headers(); self.wfile.write(b'test-secret private error'); return
                if self.path.endswith('/chat/completions'):
                    response = {'choices': [{'finish_reason': 'stop', 'message': {'content': payload}}]}
                elif self.path.endswith('/responses'):
                    response = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': payload}]}]}
                elif self.path.endswith('/messages'):
                    response = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': payload}]}
                else:
                    response = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': payload}]}}]}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(response).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for protocol, suffix, auth in [('openai_chat', '/chat/completions', 'Authorization'),
                                          ('openai_responses', '/responses', 'Authorization'),
                                          ('anthropic', '/messages', 'X-api-key'),
                                          ('gemini', '/models/model-test:generateContent', 'X-goog-api-key')]:
                with self.subTest(protocol=protocol):
                    profile = ai.profile_config(dict(id='test', name='Test', protocol=protocol,
                        base_url='http://127.0.0.1:%d/v1' % server.server_port, model='model-test', json_mode=True))
                    out = ai.generate(profile, 'test-secret', 'Test', 'Consultation', PAGES, 'en')
                    self.assertEqual(len(out['pages']), 2)
                    path, headers, body = captured[-1]
                    self.assertTrue(path.endswith(suffix), path)
                    self.assertIn('test-secret', {k.lower(): v for k, v in headers.items()}[auth.lower()])
                    self.assertNotIn('test-secret', path)
                    if protocol == 'openai_chat':
                        self.assertEqual(body['messages'][0]['role'], 'system')
                        self.assertEqual(body['response_format']['type'], 'json_object')
                    if protocol == 'openai_responses': self.assertFalse(body['store'])
            for path in ('fail', 'redirect'):
                profile['base_url'] = 'http://127.0.0.1:%d/%s' % (server.server_port, path)
                before = len(captured)
                with self.assertRaises(ai.AIError) as err:
                    ai.complete(profile, 'test-secret', 'system', 'prompt')
                self.assertNotIn('test-secret', str(err.exception))
                self.assertEqual(len(captured), before + 1)
        finally:
            server.shutdown(); server.server_close()

    def test_no_silent_mock_fallback(self):
        with patch.object(ai, 'complete', return_value='not json'), self.assertRaises(ai.AIError):
            ai.generate(dict(ai.MOCK, protocol='openai_chat'), '', 'Test', 'Brief', PAGES, 'en')
        for base in ('https://key@example.com/v1', 'https://example.com?key=secret', 'file:///tmp/test'):
            with self.assertRaises(ai.AIError):
                ai.profile_config(dict(id='test', name='Test', protocol='openai_chat', base_url=base, model='test'))


class ConsoleTests(unittest.TestCase):
    def test_maintenance_reports_worker_failures_without_false_success(self):
        m = self.m
        for mode, result, report in [
            ('check', m.subprocess.CompletedProcess([], 1, '', 'private diagnostic'), {}),
            ('apply', m.subprocess.CompletedProcess([], 0, '{"ok":false}', ''), {}),
            ('check', m.subprocess.CompletedProcess([], 0, '{"ok":true}', ''), {'images':[{'ok':False}]}),
            ('apply', m.subprocess.CompletedProcess([], 0, '{"ok":true}', ''), {'apply_results':[{'ok':True,'http':503}]}),
        ]:
            m._write(m.UPDATES_F, report)
            with patch.object(m.subprocess, 'run', return_value=result):
                m.run_update(mode)
            status, data = self.request('/api/updates')
            self.assertEqual(status, 200)
            self.assertFalse(data['running'])
            self.assertTrue(data['error'])
            self.assertNotIn('private diagnostic', json.dumps(data))
        with patch.object(m.subprocess, 'run', side_effect=TimeoutError('private diagnostic')):
            m.run_update('check')
        self.assertTrue(self.request('/api/updates')[1]['error'])
        m._write(m.UPDATES_F, {'checked_at':'2026-11-07 00:00','images':[{'ok':True}]})
        with patch.object(m.subprocess, 'run', return_value=m.subprocess.CompletedProcess([], 0, '{"ok":true}', '')):
            m.run_update('check')
        self.assertEqual(self.request('/api/updates')[1]['error'], '')
        self.assertEqual(self.request('/api/updates',user='ops-test')[0], 403)

    def test_team_crud_versions_and_session_revocation(self):
        create = {'action': 'add', 'user': 'new-user', 'name': 'New user', 'role': 'ops'}
        self.assertEqual(self.request('/api/users', create, user='ops-test')[0], 403)
        self.assertEqual(self.request('/api/users', create)[0], 200)
        def record(name):
            return next(x for x in self.request('/api/users')[1]['items'] if x['user'] == name)
        original = record('new-user')
        self.assertFalse({'hash', 'salt', 'mfa_secret', 'recovery'} & set(original))
        self.cookies['new-user'] = 'kf_sid=' + self.m.new_session('new-user')
        update = dict(create, action='update', version=original['version'], role='finance', active=True)
        self.assertEqual(self.request('/api/users', update)[0], 200)
        self.assertEqual(self.request('/api/users', update)[0], 409)
        self.assertEqual(self.request('/api/state', user='new-user')[0], 401)
        current = record('new-user')
        delete = dict(action='delete', user='new-user', version=current['version'])
        self.assertEqual(self.request('/api/users', delete)[0], 400)
        self.assertEqual(self.request('/api/users', dict(delete, confirmed=True))[0], 200)
        self.assertNotIn('new-user', self.m.load_users())
        self.assertEqual(self.request('/api/users', create)[0], 200)
        self.assertEqual(self.request('/api/users', dict(delete, confirmed=True))[0], 409)
        admin = record('admin')
        for action in ('delete', 'disable', 'update'):
            body = dict(action=action, user='admin', version=admin['version'], confirmed=True,
                        name='Admin', role='ops', active=False)
            self.assertEqual(self.request('/api/users', body)[0], 400)
        self.assertEqual(self.request('/api/users', dict(create, user='bad user'))[0], 400)
        self.assertEqual(self.request('/api/users', dict(create, user='another', role='invalid'))[0], 400)
        audit_text = (self.base/'console/audit.log').read_text()
        for action in ('user_add', 'user_update', 'user_delete'):
            self.assertIn(action, audit_text)

    def test_prompt_delete_requires_admin_and_retains_reference_guard(self):
        body={'action':'delete','kind':'templates','id':'company','revision':1}
        for user in ('ops-test','finance-test'):
            self.assertEqual(self.request('/api/ai/prompts',body,user=user)[0],403)
        code,data=self.request('/api/ai/prompts',body)
        self.assertEqual(code,200,data)
        self.assertNotIn('company',[x['id'] for x in data['templates']])
        self.assertEqual(self.request('/api/ai/prompts',body)[0],409)
        self.assertEqual(self.request('/api/ai/prompts',{'action':'delete','kind':'modules','id':'quality','revision':2})[0],400)
        self.assertIn('delete',(self.base/'console/audit.log').read_text())

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base/'console').mkdir(); (self.base/'sites'/'demo').mkdir(parents=True)
        (self.base/'core').symlink_to(ROOT/'core', target_is_directory=True)
        (self.base/'theme').symlink_to(ROOT/'theme', target_is_directory=True)
        (self.base/'console'/'admin.pass').write_text('Test-Password-123')
        for filename in ('inflow.js','geo-analysis.js','geo-collection.js','geo.js','clients-ui.js','page-ui.js','design-ui.js','media-ui.js','dns-ui.js','billing.js','leads.js','ai-workflow.js','operations.js','publications.js','admin-ui.js','ai.js','style-browser.js','prompts.js','appearance.js','locale.js','domains.js','mcp.js','automation.js'):
            (self.base/'console'/filename).symlink_to(ROOT/'console'/filename)
        self.env = patch.dict(os.environ, {'KF_BASE': str(self.base)})
        self.env.start()
        spec = importlib.util.spec_from_file_location('kf_console_test', ROOT/'console'/'kf_console.py')
        self.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)
        m = self.m; m.ensure_admin()
        users = m.load_users()
        for name, role in [('ops-test','ops'), ('finance-test','finance')]:
            users[name] = dict(users['admin'], role=role)
        m._write(m.USERS_F, users)
        self.cookies = {name: 'kf_sid='+m.new_session(name) for name in users}
        self.original = ai.mock_spec('Original', 'Original brief', PAGES, 'en')
        ai.atomic_json(self.base/'sites/demo/site-spec.json', self.original)
        ai.atomic_json(self.base/'sites/demo/meta.json', {'company':'Demo', 'domain':'example.test', 'port':0})
        # This disposable console fixture has no WordPress process. Publication
        # transport is isolated here; real WordPress snapshot/restore has separate
        # integration coverage. HTTP authorization and journal persistence are real.
        class FixtureSnapshot:
            def __init__(adapter, slug, pages, design=False, navigation=False):
                adapter.slug, adapter.pages = slug, pages
            def capture(adapter):
                return {'pages': {p['slug']: p for p in m.read_spec(adapter.slug).get('pages', []) if p['slug'] in adapter.pages}}
            def remove_page(adapter, expected):
                return {}  # No WordPress in this disposable HTTP fixture.
            def restore(adapter, before, expected, created_ids):
                return before
        m.publication_adapter = FixtureSnapshot
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), m.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.m._HEALTH_CACHE.close()
        self.m._LEADS_CACHE.close(); self.env.stop(); self.tmp.cleanup()

    def request(self, path, data=None, user='admin'):
        headers = {'Content-Type':'application/json'}
        if user:
            headers['Cookie'] = self.cookies[user]
            headers['X-KF-CSRF'] = self.m.csrf_token(self.cookies[user])
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (self.server.server_port,path),
                                     data=json.dumps(data).encode() if data is not None else None, headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e: r = e
        raw = r.read()
        try: body = json.loads(raw)
        except ValueError: body = raw.decode()
        return r.status, body

    def test_inflow_http_permissions_and_site_context(self):
        self.assertEqual(self.request('/api/inflow/config',user='ops-test')[0],403)
        self.assertEqual(self.request('/api/inflow/workspace?slug=demo',user='finance-test')[0],403)
        status,data=self.request('/api/inflow/workspace?slug=demo',user='ops-test')
        self.assertEqual(status,200);self.assertEqual(data['site']['slug'],'demo')
        self.assertFalse(data['connection']['enabled']);self.assertIsNone(data['binding'])
        self.assertEqual(self.request('/api/inflow/connection',{'revision':0,'url':'http://127.0.0.1:3002','token':'umami_fixture','enabled':True},user='ops-test')[0],403)
        status,data=self.request('/api/inflow/connection',{'revision':0,'url':'http://127.0.0.1:3002','token':'umami_fixture','enabled':True})
        self.assertEqual(status,200);self.assertNotIn('umami_fixture',json.dumps(data))
        self.assertEqual(self.request('/api/inflow/report?slug=missing')[0],400)
        self.assertEqual(self.request('/api/inflow/bind',{'slug':'demo','revision':1})[0],400)
        self.assertEqual(self.request('/inflow/api/send',{'type':'event','payload':{}},user=None)[0],400)

    def test_payment_interruption_is_visible_and_resumes_through_http(self):
        item = self.m.make_invoice('demo', 'Demo', 'example.test', dict(self.m.plans()[0], price=100))
        original = self.m.kf_billing.atomic_json
        def fail_invoice(path, data):
            if Path(path) == self.m.INVOICES_F:
                raise OSError('Test write failure')
            original(path, data)
        with patch.object(self.m.kf_billing, 'atomic_json', side_effect=fail_invoice):
            self.assertEqual(self.request('/api/invoice/pay', {'no': item['no'], 'version': 0}, user='finance-test')[0], 503)
        self.assertTrue(self.request('/api/state')[1]['invoices'][0]['processing'])
        self.assertEqual(len(self.m.ledger()), 1)
        self.assertEqual(self.request('/api/invoice/pay', {'no': item['no'], 'version': 0}, user='finance-test')[0], 200)
        self.assertEqual(len(self.m.ledger()), 1)
        self.assertFalse(self.request('/api/state')[1]['invoices'][0]['processing'])
        self.assertEqual(self.request('/api/ledger', {'slug': 'demo', 'type': 'topup', 'amount': 'NaN'}, user='finance-test')[0], 400)
        self.assertEqual(self.request('/api/plan/save', {'id': 'invalid-plan', 'price': 'Infinity'})[0], 400)

    def test_invoice_adjustment_payment_roles_and_manual_renewal_idempotency(self):
        plan = self.m.plans()[0]
        ai.atomic_json(self.base / 'sites/demo/billing.json', {'plan_id': plan['id'], 'expires': '2027-01-01',
                                                            'status': 'active', 'domain': {'registrar': 'Keep'}})
        invoice = self.m.make_invoice('demo', 'Demo', 'example.test', plan)
        body = {'no': invoice['no'], 'version': 0, 'subtotal': '200', 'gst': '18',
                'due_date': '2026-01-01', 'reason': 'Updated scope'}
        self.assertEqual(self.request('/api/invoice/adjust', body, user='ops-test')[0], 403)
        code, result = self.request('/api/invoice/adjust', body, user='finance-test')
        self.assertEqual(code, 200, result)
        self.assertEqual(result['item']['total'], 218)
        self.assertEqual(self.request('/api/invoice/adjust', body)[0], 409)
        pay = {'no': invoice['no'], 'version': 1}
        self.assertEqual(self.request('/api/invoice/pay', pay, user='ops-test')[0], 403)
        self.assertEqual(self.request('/api/invoice/pay', pay, user='finance-test')[0], 200)
        self.assertEqual(self.request('/api/invoice/pay', pay, user='finance-test')[0], 200)
        self.assertEqual(len(self.m.ledger()), 1)
        self.assertEqual(self.request('/api/invoice/adjust', dict(body, version=2))[0], 409)
        code, renewal = self.request('/api/renew', {'slug': 'demo', 'years': 2}, user='finance-test')
        self.assertEqual(code, 200, renewal)
        self.assertEqual(renewal['expires'], '2029-01-01')
        self.assertEqual(self.request('/api/renew', {'slug': 'demo', 'years': 2})[1]['invoice'], renewal['invoice'])
        self.assertEqual(self.request('/api/invoice/pay', {'no': renewal['invoice']}, user='finance-test')[0], 200)
        self.assertEqual(self.m.read_billing('demo')['expires'], '2029-01-01')
        self.assertEqual(self.m.read_billing('demo')['domain']['registrar'], 'Keep')
        item = next(i for i in self.m.invoices() if i['no'] == renewal['invoice'])
        self.assertEqual(item['subtotal'], float(plan['price'])*2)
        self.assertTrue(item['renewal_applied'])
        self.assertEqual(self.request('/api/renew', {'slug': 'demo', 'years': 1.5})[0], 400)

    def test_enquiries_cross_site_followup_conflicts_and_permissions(self):
        for slug in ('other', 'archived', 'broken'):
            site = self.base / 'sites' / slug
            site.mkdir()
            ai.atomic_json(site / 'meta.json', {'company': slug})
        ai.atomic_json(self.base / 'sites/archived/archive.json', {'archived': True})
        def read(site, page=1, lead_id=None):
            if site.name == 'broken':
                raise self.m.kf_leads.LeadReadError('read failure')
            return {'items': [{'id': 7, 'title': 'Contact', 'date': '2026-11-01', 'msg': 'Original'}],
                    'total': 1, 'has_more': False, 'checked_at': 1}
        with patch.object(self.m.kf_leads, 'read_page', side_effect=read):
            self.assertEqual(self.request('/api/leads', user='finance-test')[0], 403)
            code, data = self.request('/api/leads', user='ops-test')
            self.assertEqual(code, 200)
            self.assertEqual({x['slug'] for x in data['items']}, {'demo', 'other'})
            self.assertEqual(next(x for x in data['sources'] if x['slug'] == 'broken')['error'], 'read_failed')
            self.assertEqual(len(self.request('/api/leads?archived=1')[1]['items']), 3)
            self.assertEqual(self.request('/api/leads/broken')[0], 503)
            for query in ('page=0', 'page=x', 'slug=missing'):
                self.assertEqual(self.request('/api/leads?'+query)[0], 400)
            body = {'slug': 'demo', 'id': 7, 'status': 'contacted', 'note': 'Call tomorrow', 'version': 0}
            self.assertEqual(self.request('/api/leads/followup', body, user='finance-test')[0], 403)
            self.assertEqual(self.request('/api/leads/followup', body, user='ops-test')[0], 200)
            self.assertEqual(self.request('/api/leads/followup', body)[0], 409)
            rows = self.request('/api/leads')[1]['items']
            self.assertEqual(next(x for x in rows if x['slug'] == 'demo')['followup']['status'], 'contacted')
            self.assertEqual(next(x for x in rows if x['slug'] == 'other')['followup']['version'], 0)
            body.update(version=1, status='won', note='Converted')
            self.assertEqual(self.request('/api/leads/followup', body)[0], 200)
            history = self.m.kf_leads.Followups(self.base, 'demo').all()['7']['history']
            self.assertEqual([h['by'] for h in history], ['ops-test', 'admin'])
            self.assertNotIn('Call tomorrow', self.m.AUDIT_F.read_text())

    def test_registered_domain_links_to_new_site_without_duplicate_or_lost_accounts(self):
        body={'domain':'future.sg','registrar':'Existing registrar'}
        code,data=self.request('/api/domain/records',body);self.assertEqual(code,200)
        ident=data['item']['slug']
        self.assertEqual(self.request('/api/domain/accounts',{'slug':ident,'provider':'Existing account','password':'secret'})[0],200)
        target=self.base/'sites/future-site';target.mkdir()
        ai.atomic_json(target/'meta.json',{'domain':'future.sg','company':'New site'})
        rows=[v for v in self.request('/api/domains')[1]['items'] if v['domain']=='future.sg']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['slug'],ident)
        self.assertEqual(rows[0]['site_slug'],'future-site');self.assertEqual(rows[0]['manage']['registrar'],'Existing registrar')
        update=dict(body,id=ident,version=rows[0]['version'],registrar='Updated registrar')
        self.assertEqual(self.request('/api/domain/records',update)[0],200)
        self.assertEqual(self.m.read_domain('future-site')['registrar'],'Updated registrar')
        self.assertEqual(self.request('/api/domain/accounts')[1]['items'][0]['slug'],ident)

    def test_domain_registry_crud_binding_accounts_and_concurrency(self):
        body=dict(domain='independent.sg',company='Independent',registrar='Name.com',expires='2027-01-01',owner='client',auto_renew=False,note='Registry only')
        self.assertEqual(self.request('/api/domain/records',body,user='finance-test')[0],403)
        for bad in [dict(body,domain='https://bad.sg'),dict(body,expires='2027-02-30'),dict(body,owner='unknown')]:
            self.assertEqual(self.request('/api/domain/records',bad)[0],400)
        code,data=self.request('/api/domain/records',body,user='ops-test');self.assertEqual(code,200,data)
        item=data['item'];ident=item['slug'];self.assertFalse(item['site_slug'])
        self.assertEqual(self.request('/api/domain/records',body)[0],400)
        changed=dict(body,id=ident,version=item['version'],registrar='Updated')
        code,data=self.request('/api/domain/records',changed);self.assertEqual(code,200)
        self.assertEqual(self.request('/api/domain/records',changed)[0],409)
        item=data['item'];account=dict(slug=ident,provider='Registrar',username='user',password='vault-test-password')
        code,data=self.request('/api/domain/accounts',account);self.assertEqual(code,200,data)
        account=data['item']
        deletion=dict(action='delete',id=ident,version=item['version'])
        self.assertEqual(self.request('/api/domain/records',deletion)[0],400)
        self.assertEqual(self.request('/api/domain/accounts',dict(action='delete',id=account['id'],version=account['version']))[0],200)
        self.assertEqual(self.request('/api/domain/records',deletion)[0],200)
        self.assertNotIn(ident,[i['slug'] for i in self.request('/api/domains')[1]['items']])
        linked=next(i for i in self.request('/api/domains')[1]['items'] if i['slug']=='demo')
        before=(self.base/'sites/demo/meta.json').read_bytes()
        self.assertEqual(self.request('/api/domain/records',dict(body,id='demo',version=linked['version']))[0],400)
        self.assertEqual(self.request('/api/domain/records',dict(action='delete',id='demo',version=linked['version']))[0],200)
        self.assertNotIn('demo',[i['slug'] for i in self.request('/api/domains')[1]['items']])
        code,data=self.request('/api/domain/records',dict(body,domain=linked['domain']))
        self.assertEqual(code,200,data);self.assertEqual(data['item']['site_slug'],'demo')
        self.assertEqual((self.base/'sites/demo/meta.json').read_bytes(),before)
        self.assertEqual(self.m.read_domain('demo')['registrar'],'Name.com')
        self.assertEqual(self.request('/api/domain/records',dict(action='delete',id='demo',version=linked['version']))[0],409)

    def test_health_cache_force_refresh_and_failed_suspend_preserves_state(self):
        with patch.object(self.m, 'docker_state', return_value=[]), patch.object(self.m, 'http_status', side_effect=[200, 503]) as probe:
            self.assertEqual(self.request('/api/state')[1]['sites'][0]['http'], 200)
            self.assertEqual(self.request('/api/state')[1]['sites'][0]['http'], 200)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(self.request('/api/state?refresh=1')[1]['sites'][0]['http'], 503)
            self.assertEqual(probe.call_count, 2)
        path = self.base / 'sites/demo/billing.json'
        ai.atomic_json(path, {'status': 'active', 'expires': '2027-01-01'})
        before = path.read_bytes()
        with patch.object(self.m.subprocess, 'run') as command:
            command.return_value.returncode = 1
            code, result = self.request('/api/suspend', {'slug': 'demo', 'action': 'stop'})
        self.assertEqual(code, 500)
        self.assertEqual(result['status'], 'active')
        self.assertEqual(path.read_bytes(), before)

    def test_operations_permissions_acknowledgement_and_action_visibility(self):
        store = self.m.ai_store()
        job = store.create_job('demo', store.resolve('mock')[0], 'ops-test', 'existing')
        store.update_job(job['id'], status='failed', message='private job content')
        actions = self.m.automation_store().actions
        item = actions.prepare(user='admin', slug='demo', tool='site.context', arguments={},
                               mode='read', summary='private operation', snapshot={})
        with actions.locked():
            item['state'] = 'failed'
            actions.save(item, 'test')
        self.assertEqual(self.request('/api/operations/overview', user='finance-test')[0], 403)
        code, data = self.request('/api/operations/overview', user='ops-test')
        self.assertEqual(code, 200, data)
        task = next(x for x in data['items'] if x['kind'] == 'generation')
        self.assertFalse(any(x['kind'] == 'action' for x in data['items']))
        self.assertNotIn('private', json.dumps(data))
        admin = self.request('/api/operations/overview')[1]['items']
        self.assertTrue(any(x['reference'] == item['id'] for x in admin))
        body = {'id': task['id'], 'revision': task['revision']}
        self.assertEqual(self.request('/api/operations/ack', body, user='finance-test')[0], 403)
        self.assertEqual(self.request('/api/operations/ack', dict(body, revision='stale'), user='ops-test')[0], 409)
        self.assertEqual(self.request('/api/operations/ack', body, user='ops-test')[0], 200)
        self.assertFalse(any(x['id'] == task['id'] for x in self.request('/api/operations/overview', user='ops-test')[1]['items']))
        self.assertTrue(any(x['id'] == task['id'] for x in self.request('/api/operations/overview')[1]['items']))
        acknowledged = self.request('/api/operations/overview?ack=1', user='ops-test')[1]['items']
        self.assertTrue(next(x for x in acknowledged if x['id'] == task['id'])['acknowledged'])
        self.assertEqual(self.request('/api/operations/ack', dict(body, action='restore'), user='ops-test')[0], 200)
        self.assertTrue(any(x['id'] == task['id'] for x in self.request('/api/operations/overview', user='ops-test')[1]['items']))

    def test_site_archive_restore_permissions_and_data_preservation(self):
        site=self.base/'sites/demo'
        before={p.name:p.read_bytes() for p in site.iterdir() if p.is_file()}
        body={'slug':'demo','archived':True,'version':0}
        with patch.object(self.m,'reserve_site') as reserve:
            self.assertEqual(self.request('/api/create',{'slug':'new-site'})[0],410)
            reserve.assert_not_called()
        self.assertEqual(self.request('/api/site/archive',body,user=None)[0],401)
        self.assertEqual(self.request('/api/site/archive',body,user='finance-test')[0],403)
        for invalid in [dict(body,slug='../demo'),dict(body,slug='missing'),dict(body,archived='true'),dict(body,version=True)]:
            self.assertEqual(self.request('/api/site/archive',invalid)[0],400)
        with patch.object(self.m.subprocess,'run') as run:
            code,result=self.request('/api/site/archive',body,user='ops-test')
            self.assertEqual(code,200,result);run.assert_not_called()
        self.assertTrue(result['archived']);self.assertEqual(result['archived_by'],'ops-test')
        self.assertEqual(json.loads((site/'archive.json').read_text())['archive_version'],1)
        self.assertEqual({p.name:p.read_bytes() for p in site.iterdir() if p.is_file() and p.name!='archive.json'},before)
        self.assertEqual(self.request('/api/site/archive',body)[0],409)
        with patch.object(self.m,'docker_state',return_value=[]),patch.object(self.m,'http_status',return_value=200):
            row=next(x for x in self.m.site_list() if x['slug']=='demo')
            self.assertTrue(row['archived']);self.assertEqual(row['http'],200)
        code,result=self.request('/api/site/archive',dict(body,archived=False,version=1))
        self.assertEqual(code,200);self.assertFalse(result['archived']);self.assertEqual(result['archive_version'],2)
        self.assertIn('site_restore',(self.base/'console/audit.log').read_text())

    def wait_job(self, jid):
        for _ in range(100):
            job = next(j for j in self.m.ai_store().jobs() if j['id']==jid)
            if job['status'] not in ai.ACTIVE: return job
            time.sleep(.02)
        self.fail('Job did not terminate')

    def test_preview_assets_and_form_placeholder(self):
        spec = copy.deepcopy(self.original)
        spec['pages'][0]['sections'] = [
            {'type':'band','src':'/wp-content/uploads/kampong/photo.webp','alt':'Photo'},
            {'type':'form','title':'Contact'}]
        ai.atomic_json(self.base/'sites/demo/site-draft.json', spec)
        page = self.m.preview_html('demo', 'home', base='/s/test', asset='/sa/test', public=True)
        self.assertIn('/sa/test/uploads/kampong/photo.webp', page)
        self.assertNotIn('/wp-content/uploads/', page)
        self.assertNotIn('[kf_contact_form', page)
        self.assertIn('Form preview only', page)
        self.assertNotIn('127.0.0.1:18085', page)

    def test_local_style_preview_permissions_and_publish_tokens(self):
        status, library = self.request('/api/ai/styles')
        self.assertEqual(status, 200)
        self.assertEqual(len(library['templates']), 28)
        item = library['templates'][0]
        status, result = self.request('/api/ai/styles/preview', item, user='ops-test')
        self.assertEqual(status, 200, result)
        self.assertIn('default-src &#39;none&#39;', result['html'])
        self.assertIn('data:image/svg+xml;base64,', result['html'])
        self.assertIn('--kf-heading-size:88px', result['html'])
        status, form = self.request('/api/ai/styles/preview', dict(item, blueprint=['form','cards','stats','band','rich']), user='ops-test')
        self.assertEqual(status, 200)
        self.assertNotIn('[kf_contact_form', form['html'])
        self.assertNotIn('区块缺少字段', form['html'])
        self.assertIn('Preview only', form['html'])
        self.assertEqual(self.m.sanitize_design(item['tokens']), item['tokens'])
        self.assertEqual(self.request('/api/ai/styles/preview', item, user='finance-test')[0], 403)
        malformed = dict(item, tokens=dict(item['tokens'], advanced={'hero':'</style><script>'}))
        self.assertEqual(self.request('/api/ai/styles/preview', malformed)[0], 400)
        self.assertEqual(self.request('/api/design', dict(malformed['tokens'], slug='demo'))[0], 400)
        self.assertEqual(self.request('/api/ai/styles', dict(item, name='Forbidden'), user='ops-test')[0], 403)
        self.assertEqual(self.request('/api/ai/styles')[1]['templates'][0], item)

    def test_reference_styles_permissions_generation_preview_and_publish(self):
        import kf_styles
        analysis = kf_styles.extract('<title>Reference</title><style>body{color:#345678}</style>', [], 'https://example.com/', [])
        with patch.object(kf_styles, 'analyze', return_value=analysis):
            self.assertEqual(self.request('/api/ai/styles/analyze', {'url':'https://example.com'}, user='ops-test')[0], 200)
            self.assertEqual(self.request('/api/ai/styles/analyze', {'url':'https://example.com'}, user='finance-test')[0], 403)
        body = dict(analysis, name='Reference style')
        self.assertEqual(self.request('/api/ai/styles', body, user='ops-test')[0], 403)
        status, saved = self.request('/api/ai/styles', body)
        self.assertEqual(status, 200, saved)
        item = saved['item']
        self.assertEqual(self.request('/api/ai/styles', dict(item, version=0))[0], 409)
        status, data = self.request('/api/ai/build', dict(slug='demo', brief='Consulting', style_template_id=item['id']))
        self.assertEqual(status, 202, data)
        job = self.wait_job(data['job']['id'])
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual(job['style']['version'], 1)
        self.assertEqual(self.m.read_draft('demo')['design'], item['tokens'])
        self.assertFalse((self.base/'sites/demo/design.json').exists())
        status, preview = self.request('/preview/demo/home')
        self.assertEqual(status,200)
        self.assertIn('--kf-primary:#345678',preview.replace(' ',''))
        self.assertEqual(self.request('/api/ai/styles', dict(item, action='delete'))[0],200)
        self.assertEqual(self.m.read_draft('demo')['ai']['style']['name'], item['name'])
        with patch.object(self.m,'apply_design',return_value=False), patch.object(self.m.Handler,'_render_check') as render:
            self.assertEqual(self.request('/api/publish',{'slug':'demo'})[0],500)
            render.assert_not_called()
        with patch.object(self.m,'apply_design',return_value=True) as apply, patch.object(self.m.Handler,'_render_check',return_value={'ok':True}):
            self.assertEqual(self.request('/api/publish',{'slug':'demo'})[0],200)
            apply.assert_called_once_with('demo',item['tokens'])
        self.assertEqual(self.m.read_spec('demo')['design'],item['tokens'])
        self.assertFalse(self.m.is_dirty('demo'))

    def test_reference_support_install_failure_does_not_save_design(self):
        import kf_styles
        from types import SimpleNamespace
        tokens = kf_styles.normalize_tokens({})
        with patch.object(self.m.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run:
            self.assertFalse(self.m.apply_design('demo', tokens))
            self.assertEqual(run.call_count, 1)
        self.assertFalse((self.base/'sites/demo/design.json').exists())
        with patch.object(self.m.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(self.m.apply_design('demo', tokens))
            self.assertEqual(run.call_count, 2)
        self.assertEqual(json.loads((self.base/'sites/demo/design.json').read_text()), tokens)

    def test_wordpress_entry_uses_browser_session_and_hides_keys(self):
        import kf_sso
        import re
        store = kf_sso.SSOStore(self.base)
        store.configure('https://mvp.example.com','demo','https://site.example.com')
        status, data = self.request('/api/wordpress/sites')
        self.assertEqual(status,200)
        self.assertTrue(data['sites']['demo']['enabled'])
        self.assertNotIn('secret',json.dumps(data))
        self.assertFalse(self.request('/api/wordpress/sites',user='finance-test')[1]['sites']['demo']['enabled'])
        challenge=kf_sso.digest('a'*64)
        path='/wordpress/authorize?site=demo&challenge='+challenge
        self.assertEqual(self.request(path,user='finance-test')[0],403)
        status,page=self.request(path)
        self.assertEqual(status,200)
        self.assertIn('https://site.example.com/?kf_mvp_sso=finish',page)
        self.assertRegex(page,r'name="ticket" value="[a-f0-9]{64}"')
        self.assertEqual(self.request('/api/wordpress/callback',{'site':'demo'},user=None)[0],403)
        for url in ['//evil.example','/\\evil.example','/ok\r\nLocation:evil','/\t/evil.example']:
            self.assertEqual(self.m.safe_next(url),'/')
        self.assertEqual(self.m.safe_next('/wordpress/authorize?site=demo'),'/wordpress/authorize?site=demo')

    def test_workflow_http_build_preview_confirm_and_complete(self):
        import kf_builtin_tools
        with patch.object(self.m,'render_check',return_value={'ok':True}) as render, patch.object(kf_builtin_tools,'https_check',return_value={'ok':True,'certificate_valid':True}):
            status,data=self.request('/api/automation/workflow/create',{'slug':'demo','brief':'Build a useful website','context_options':['client']})
            self.assertEqual(status,200);ident=data['item']['id']
            self.assertEqual(self.request('/api/automation/workflow/control',{'id':ident,'action':'start'})[0],200)
            deadline=time.time()+6
            while time.time()<deadline:
                item=self.request('/api/automation/workflows')[1]['items'][0]
                if item['state'] in ('waiting','failed'):break
                time.sleep(.05)
            self.assertEqual(item['state'],'waiting',item)
            action_id=next(s['action_id'] for s in item['steps'] if s['state']=='waiting')
            action=self.request('/api/automation/action/'+action_id)[1]['item']
            self.assertEqual(action['tool'],'site.publish');self.assertTrue(action['snapshot']['pages'])
            render.assert_not_called()
            self.assertEqual(self.request('/api/automation/execute',{'id':action_id,'digest':action['digest'],'confirmed':True})[0],200)
            deadline=time.time()+4
            while time.time()<deadline:
                item=self.request('/api/automation/workflows')[1]['items'][0]
                if item['state'] in ('completed','failed'):break
                time.sleep(.05)
            self.assertEqual(item['state'],'completed',item);self.assertTrue(render.called)
            draft=json.loads((self.base/'sites/demo/site-draft.json').read_text())
            self.assertIn('context_sources',draft['ai']);self.assertNotIn('data',draft['ai']['context_sources'][0])

    def test_automation_scopes_review_and_sender_idempotency(self):
        import kf_builtin_tools
        self.assertEqual(self.request('/api/automation/config',user='finance-test')[0],403)
        status,data=self.request('/api/automation/prepare',{'slug':'demo','tool':'site.context','arguments':{'selected':['client']}})
        self.assertEqual(status,200);item=data['item']
        status,data=self.request('/api/automation/execute',{'id':item['id'],'digest':item['digest']})
        self.assertEqual(status,200);self.assertEqual(data['item']['state'],'succeeded')
        self.assertEqual(self.request('/api/automation/execute',{'id':item['id'],'digest':item['digest']},user='ops-test')[0],403)
        mail={'slug':'demo','tool':'mail.send','arguments':{'to':'client@example.test','subject':'Review','body':'Approved content'}}
        status,data=self.request('/api/automation/prepare',mail);self.assertEqual(status,200);item=data['item']
        self.assertEqual(self.request('/api/automation/execute',{'id':item['id'],'digest':item['digest']})[0],403)
        with patch.object(kf_builtin_tools,'send',return_value={'state':'accepted','delivered':None}) as send:
            payload={'id':item['id'],'digest':item['digest'],'confirmed':True}
            self.assertEqual(self.request('/api/automation/execute',payload)[1]['item']['state'],'succeeded')
            self.assertEqual(self.request('/api/automation/execute',payload)[1]['item']['state'],'succeeded')
            self.assertEqual(send.call_count,1)
        self.assertNotIn('Approved content',(self.base/'console/audit.log').read_text())

    def test_provider_account_permissions_and_redaction(self):
        body={'id':'name-account','name':'Name.com','provider':'namecom','enabled':True,'sites':['demo'],'capabilities':['dns'],'values':{'username':'api-user','token':'private-provider-token'}}
        self.assertEqual(self.request('/api/automation/providers',user=None)[0],401)
        for user in ('ops-test','finance-test'):
            self.assertEqual(self.request('/api/automation/providers',user=user)[0],403)
            self.assertEqual(self.request('/api/automation/providers',body,user=user)[0],403)
        status,data=self.request('/api/automation/providers',body);self.assertEqual(status,200,data)
        for path in ('/api/automation/providers','/api/automation/config'):
            status,data=self.request(path);self.assertEqual(status,200);self.assertNotIn('private-provider-token',json.dumps(data));self.assertNotIn('gAAAA',json.dumps(data))
        self.assertNotIn('private-provider-token',(self.base/'console/audit.log').read_text())
        self.assertEqual(self.request('/api/automation/providers',dict(body,version=0))[0],409)
        self.assertEqual(self.request('/api/automation/providers',{'action':'delete','id':'name-account','version':1})[0],200)

    def test_provider_connection_test_is_admin_only_and_versioned(self):
        import kf_sg_providers
        body={'id':'sg-test','name':'cPanel','provider':'cpanel','enabled':True,'sites':['demo'],'capabilities':['dns'],'values':{'endpoint':'https://panel.example.com:2083','username':'demo','token':'private-token'}}
        self.assertEqual(self.request('/api/automation/providers',body)[0],200)
        with patch.object(kf_sg_providers,'probe',return_value={'provider':'cpanel','ok':True,'message':'Read-only probe'}) as probe:
            for user in ('ops-test','finance-test'):
                self.assertEqual(self.request('/api/automation/providers/test',{'id':'sg-test','version':1},user=user)[0],403)
            self.assertEqual(self.request('/api/automation/providers/test',{'id':'sg-test','version':0})[0],409)
            probe.assert_not_called()
            status,data=self.request('/api/automation/providers/test',{'id':'sg-test','version':1});self.assertEqual(status,200);self.assertTrue(data['result']['ok'])
            self.assertEqual(probe.call_count,1)
        self.assertNotIn('private-token',(self.base/'console/audit.log').read_text())

    def test_mcp_admin_permissions_and_credential_redaction(self):
        import kf_mcp
        body={'id':'fixture','name':'Fixture','url':'https://example.com/mcp','token':'test-mcp-token','enabled':True}
        self.assertEqual(self.request('/api/mcp/servers',user=None)[0],401)
        for user in ('ops-test','finance-test'):
            self.assertEqual(self.request('/api/mcp/servers',user=user)[0],403)
            self.assertEqual(self.request('/api/mcp/servers',body,user=user)[0],403)
            self.assertEqual(self.request('/api/mcp/test',{'id':'fixture','version':1},user=user)[0],403)
        status,data=self.request('/api/mcp/servers',body);self.assertEqual(status,200)
        self.assertTrue(data['item']['has_token']);self.assertNotIn(body['token'],json.dumps(data))
        status,data=self.request('/api/mcp/servers');self.assertEqual(status,200);self.assertNotIn('secret',data['items'][0])
        with patch.object(kf_mcp,'discover',return_value={'tools':[],'resources':[],'prompts':[]}):
            self.assertEqual(self.request('/api/mcp/test',{'id':'fixture','version':1})[0],200)
        self.assertEqual(self.request('/api/mcp/servers',dict(body,version=0))[0],409)
        self.assertEqual(self.request('/api/mcp/servers',{'action':'delete','id':'fixture','version':1})[0],200)
        self.assertNotIn(body['token'],(self.base/'console/audit.log').read_text())

    def test_domain_vault_requires_fresh_totp_and_never_lists_password(self):
        import kf_domain_vault
        self.assertEqual(self.request('/api/domain/accounts',user='finance-test')[0],403)
        body={'slug':'demo','provider':'Example Registrar','category':'registrar','url':'https://registrar.example/dashboard',
              'username':'operator@example.test','password':'vault-secret-not-for-logs','configuration':'NS: ns1.example.test'}
        self.assertEqual(self.request('/api/domain/accounts',body,user='finance-test')[0],403)
        status,data=self.request('/api/domain/accounts',body)
        self.assertEqual(status,200,data);item=data['item'];ident=item['id']
        for path in ['/api/domain/accounts','/api/domains','/api/state']:
            status,listing=self.request(path)
            self.assertEqual(status,200)
            self.assertNotIn(body['password'],json.dumps(listing))
            self.assertNotIn('gAAAA',json.dumps(listing))
        self.assertTrue(item['has_password']);self.assertNotIn('password',item)
        reveal={'id':ident,'code':'123456'}
        self.assertEqual(self.request('/api/domain/accounts/reveal',reveal)[0],403)
        users=self.m.load_users();users['admin']['mfa_secret']='JBSWY3DPEHPK3PXP';self.m._write(self.m.USERS_F,users)
        self.assertEqual(self.request('/api/domain/accounts/reveal',dict(reveal,code='abcd-1234'))[0],403)
        reveal['code']=self.m._totp(users['admin']['mfa_secret'],int(time.time()//30))
        status,data=self.request('/api/domain/accounts/reveal',reveal)
        self.assertEqual(status,200,data);self.assertEqual(data['password'],body['password']);self.assertEqual(data['expires_in'],30)
        self.assertEqual(self.request('/api/domain/accounts/reveal',reveal)[0],403)
        self.assertNotIn(body['password'],self.m.AUDIT_F.read_text())
        self.assertNotIn(reveal['code'],self.m.AUDIT_F.read_text())
        self.assertNotIn(body['password'],kf_domain_vault.DomainVault(self.base).path.read_text())
        self.assertEqual(self.request('/api/domain/accounts',dict(body,id=ident,version=0,password=''))[0],409)
        self.assertEqual(self.request('/api/domain/accounts',dict(body,id=ident,version=1,password='',username='edited'))[0],200)
        self.assertTrue(self.request('/api/domain/accounts')[1]['items'][0]['has_password'])
        self.assertEqual(self.request('/api/domain/accounts',{'action':'delete','id':ident,'version':2})[0],200)
        self.assertEqual(self.request('/api/domain/accounts')[1]['items'],[])

    def test_pdf_font_fallback(self):
        inv = {'no':'TEST-001','company':'测试客户','domain':'example.test','plan_name':'Demo',
               'plan_specs':'测试服务','subtotal':100,'gst':0,'total':100,'status':'unpaid',
               'issued_at':'2026-11-05','paid_at':''}
        self.assertTrue(self.m.invoice_pdf(inv).startswith(b'%PDF'))
        (self.base/'sites/demo/handover.md').write_text('# Test\n## 网站\n- 演示信息\n')
        self.assertTrue(self.m.handover_pdf('demo').startswith(b'%PDF'))

    def test_showcase_preset_text_contrast(self):
        def luminance(value):
            rgb = [int(value[i:i+2], 16)/255 for i in (1,3,5)]
            linear = [v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in rgb]
            return sum(a*b for a,b in zip(linear, (0.2126,0.7152,0.0722)))
        for name in ('nursery','robotics','wellness'):
            palette = self.m.presets()[name]['palette']
            for text, background in [(palette['primary'],'#ffffff'),(palette['ink'],palette['bg']),
                                     (palette['muted'],palette['bg']),('#d6e1dc',palette['deep'])]:
                a,b = sorted((luminance(text),luminance(background)))
                self.assertGreaterEqual((b+0.05)/(a+0.05),4.5,(name,text,background))

    def test_client_profile_crud_versions_validation_and_retained_finance(self):
        m=self.m
        row=self.request('/api/clients',user='finance-test')[1]['items'][0]
        self.assertFalse(row['registered'])
        body=dict(action='create',slug='demo',version=row['version'],company='Customer profile',contact='A client',email='client@example.test',address='1 Test Road',notes='Long note '*40,annual_fee=1200,scope=['托管'],service_start='2026-01-01',service_end='2027-01-01')
        self.assertEqual(self.request('/api/clients/save',body,user='finance-test')[0],200)
        self.assertEqual(self.request('/api/clients/save',body,user='ops-test')[0],409)
        row=self.request('/api/clients')[1]['items'][0]
        self.assertTrue(row['registered']);self.assertEqual(row['client']['company'],'Customer profile')
        self.assertNotIn('_version',row['client']);self.assertEqual(len(row['client']['notes']),len(body['notes'].strip()))
        update=dict(body,action='save',version=row['version'])
        self.assertEqual(self.request('/api/clients/save',dict(update,service_end='2025-01-01'))[0],400)
        self.assertEqual(self.request('/api/clients/save',dict(update,agreement_date='2026-02-30'))[0],400)
        self.assertEqual(self.request('/api/clients/save',dict(update,annual_fee='nan'))[0],400)
        self.assertEqual(self.request('/api/clients/save',dict(update,email='invalid'))[0],400)
        self.assertEqual(self.request('/api/clients/save',dict(update,owner='missing-user'))[0],400)
        self.assertEqual(self.request('/api/clients/save',dict(update,contact='Changed'),user='ops-test')[0],200)
        self.assertEqual(self.request('/api/clients/save',update)[0],409)
        row=self.request('/api/clients')[1]['items'][0]
        m.add_ledger('demo','topup',500,'Service','Retained financial entry','admin')
        invoice=m.make_invoice('demo','Demo','example.test',dict(m.plans()[0],price=100))
        before_ledger=m.ledger();before_invoices=m.invoices();before_meta=m.load_meta('demo')
        delete=dict(action='delete',slug='demo',version=row['version'],confirmed=True)
        self.assertEqual(self.request('/api/clients/save',dict(delete,confirmed=False))[0],409)
        self.assertEqual(self.request('/api/clients/save',delete,user='finance-test')[0],200)
        self.assertFalse(self.request('/api/clients')[1]['items'][0]['registered'])
        self.assertEqual(m.ledger(),before_ledger);self.assertEqual(m.invoices(),before_invoices);self.assertEqual(m.load_meta('demo'),before_meta)
        empty=self.request('/api/clients')[1]['items'][0]
        self.assertEqual(self.request('/api/clients/save',dict(body,version=empty['version']))[0],200)
        self.assertEqual(self.request('/api/clients/save',delete)[0],409)

    def test_page_crud_versions_delete_guards_and_recovery(self):
        m = self.m
        endpoint = '/api/spec/page'
        data = self.request('/api/spec/demo')[1]
        body = dict(action='create',slug='demo',page='guide',title='Guide',draft_version=data['draft_version'])
        self.assertEqual(self.request(endpoint,body,user='finance-test')[0],403)
        status, created = self.request(endpoint,body,user='ops-test')
        self.assertEqual(status,200)
        self.assertEqual(self.request(endpoint,body)[0],409)
        self.assertNotIn('guide',[p['slug'] for p in m.read_spec('demo')['pages']])
        sections = copy.deepcopy(self.original['pages'][0]['sections'])
        update = dict(slug='demo',page='guide',title='New guide',sections=sections,version=created['version'])
        with patch.object(m.Handler,'_render_check',return_value={'ok':True,'length':1000}):
            self.assertEqual(self.request('/api/spec',update,user='ops-test')[0],200)
            self.assertEqual(self.request('/api/spec',update,user='ops-test')[0],409)
        data = self.request('/api/spec/demo')[1]
        deletion = dict(action='delete',slug='demo',page='guide',version=data['versions']['guide'],confirmed=True)
        self.assertEqual(self.request(endpoint,dict(deletion,confirmed=False))[0],400)
        self.assertEqual(self.request(endpoint,dict(deletion,page='home',version=data['versions']['home']))[0],400)
        linked = m.read_draft('demo');linked['pages'][0]['sections'].append({'type':'cta','cta':{'href':'/guide/','label':'Guide'}})
        m.kf_ai.atomic_json(m.draft_path('demo'),linked)
        self.assertEqual(self.request(endpoint,deletion)[0],409)
        linked['pages'][0]['sections'].pop();m.kf_ai.atomic_json(m.draft_path('demo'),linked)
        self.assertEqual(self.request(endpoint,deletion,user='ops-test')[0],200)
        self.assertNotIn('guide',[p['slug'] for p in m.read_draft('demo')['pages']])
        # A published-page deletion snapshots both live and draft files. Recovery
        # refuses intervening draft edits and restores the exact previous files.
        live=m.read_spec('demo');live['pages'].append({'slug':'guide','title':'Live guide','sections':sections})
        m.kf_ai.atomic_json(m.spec_path('demo'),live);m.kf_ai.atomic_json(m.draft_path('demo'),live)
        deletion['version']=m.kf_design_profiles.fingerprint(live['pages'][-1])
        status,result=self.request(endpoint,deletion,user='ops-test');self.assertEqual(status,200)
        history=self.request('/api/publications/demo')[1]['items'][0]
        self.assertEqual(history['operation'],'delete_page')
        self.assertNotIn('guide',[p['slug'] for p in m.read_spec('demo')['pages']])
        after=m.read_draft('demo');changed=copy.deepcopy(after);changed['pages'][0]['title']='Later edit'
        m.kf_ai.atomic_json(m.draft_path('demo'),changed)
        restore=dict(slug='demo',id=result['publication_id'],version=history['version'],confirmed=True)
        self.assertEqual(self.request('/api/publish/restore',restore)[0],409)
        m.kf_ai.atomic_json(m.draft_path('demo'),after)
        self.assertEqual(self.request('/api/publish/restore',restore)[0],200)
        self.assertEqual(m.read_draft('demo'),live)
        self.assertEqual(m.read_spec('demo'),live)
        draft=copy.deepcopy(live);draft['pages']=[p for p in draft['pages'] if p['slug']!='guide']
        m.kf_ai.atomic_json(m.draft_path('demo'),draft)
        current=self.request('/api/spec/demo')[1]
        self.assertIn('guide',current['versions'])
        imported=dict(action='import',slug='demo',page='guide',version=current['versions']['guide'],draft_version=current['draft_version'])
        self.assertEqual(self.request(endpoint,dict(imported,version='stale'))[0],409)
        self.assertEqual(self.request(endpoint,imported,user='ops-test')[0],200)
        self.assertEqual(m.read_draft('demo'),live)

    def test_design_profile_crud_conflicts_and_application(self):
        m = self.m
        endpoint = '/api/design/profiles'
        builtin = self.request(endpoint,user='ops-test')[1]['items'][0]
        body = dict(name='Test design',description='<script>plain text</script>',tokens=builtin['tokens'])
        self.assertEqual(self.request(endpoint,body,user='finance-test')[0],403)
        self.assertEqual(self.request(endpoint,dict(body,id=builtin['id'],version=0))[0],400)
        status, result = self.request(endpoint,body,user='ops-test')
        self.assertEqual(status,200)
        item = result['item']
        self.assertEqual(item['version'],1)
        self.assertFalse((self.base/'sites/demo/design.json').exists())
        status, data = self.request(endpoint,dict(body,id=item['id'],version=1,name='Updated'),user='ops-test')
        self.assertEqual(status,200)
        self.assertEqual(data['item']['version'],2)
        self.assertEqual(self.request(endpoint,dict(body,id=item['id'],version=1))[0],409)
        bad = copy.deepcopy(body); bad['tokens']['palette']['ink'] = bad['tokens']['palette']['bg']
        self.assertEqual(self.request(endpoint,bad)[0],400)
        self.assertEqual(self.request(endpoint,dict(body,tokens=[]))[0],400)
        current = self.request('/api/design/demo',user='ops-test')[1]
        apply = dict(slug='demo',profile_id=item['id'],profile_version=1,expected_design=current['version'])
        with patch.object(m.subprocess,'run') as run:
            self.assertEqual(self.request('/api/design',apply,user='ops-test')[0],409)
            self.assertFalse(run.called)
            apply['profile_version']=2
            run.return_value.returncode=1
            self.assertEqual(self.request('/api/design',apply,user='ops-test')[0],500)
            self.assertFalse((self.base/'sites/demo/design.json').exists())
            run.return_value.returncode=0
            self.assertEqual(self.request('/api/design',apply,user='ops-test')[0],200)
            self.assertTrue((self.base/'sites/demo/design.json').exists())
            run.reset_mock()
            self.assertEqual(self.request('/api/design',apply,user='ops-test')[0],409)
            self.assertFalse(run.called)
        applied = m.site_design('demo')
        self.assertEqual(self.request(endpoint,dict(action='delete',id=item['id'],version=1))[0],409)
        self.assertEqual(self.request(endpoint,dict(action='delete',id=item['id'],version=2),user='ops-test')[0],200)
        self.assertEqual(m.site_design('demo'),applied)
        self.assertNotIn(item['id'],[x['id'] for x in self.request(endpoint)[1]['items']])
        self.assertEqual(self.request('/api/design',dict(apply,expected_design=m.kf_design_profiles.fingerprint(applied)))[0],409)

    def test_media_metadata_versions_references_and_scope(self):
        m = self.m
        directory = self.base/'sites/demo/html/wp-content/uploads/kampong'
        directory.mkdir(parents=True)
        (directory/'photo.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        item = self.request('/api/media/demo',user='ops-test')[1]['items'][0]
        self.assertEqual(item['preview_url'], '/pa/demo/uploads/kampong/photo.png')
        body = dict(slug='demo',name='photo.png',version=item['version'],title='New title',alt='Descriptive alternative',caption='<script>text only</script>')
        self.assertEqual(self.request('/api/media/update',body,user='finance-test')[0],403)
        status, result = self.request('/api/media/update',body,user='ops-test')
        self.assertEqual(status,200)
        self.assertNotEqual(result['item']['version'],item['version'])
        self.assertEqual(result['item']['url'],item['url'])
        self.assertEqual(self.request('/api/media/update',body,user='ops-test')[0],409)
        self.assertEqual(self.request('/api/media/delete',body,user='ops-test')[0],409)
        self.assertEqual(m.media_list('demo')[0]['title'],'New title')
        draft = copy.deepcopy(self.original)
        (directory/'photo-400.png').write_bytes(b'variant')
        (directory/'photo-other.png').write_bytes(b'other image')
        draft['pages'][0]['sections'] = [{'type':'band','src':item['url'].replace('.png','-400.png'),'alt':'Photo'}]
        m.kf_ai.atomic_json(m.draft_path('demo'),draft)
        current = next(x for x in m.media_list('demo') if x['name']=='photo.png')
        self.assertTrue(current['used_by'])
        self.assertTrue(current['thumbnail_url'].endswith('/photo-400.png'))
        deletion = dict(slug='demo',name='photo.png',version=current['version'])
        self.assertEqual(self.request('/api/media/delete',deletion,user='ops-test')[0],409)
        m.kf_ai.atomic_json(m.draft_path('demo'),self.original)
        (directory/'escape.png').symlink_to(self.base/'console/admin.pass')
        self.assertNotIn('escape.png',[x['name'] for x in m.media_list('demo')])
        self.assertEqual(self.request('/api/media/update',dict(body,name='../escape.png'))[0],404)
        self.assertEqual(self.request('/api/media/delete',deletion,user='ops-test')[0],200)
        self.assertFalse((directory/'photo.png').exists())
        self.assertFalse((directory/'photo-400.png').exists())
        self.assertTrue((directory/'photo-other.png').exists())
        self.assertEqual(json.loads((self.base/'sites/demo/media-metadata.json').read_text()),{})

    def test_upload_unique_names_and_permission_error(self):
        import io
        from PIL import Image
        buf = io.BytesIO(); Image.new('RGB', (32, 32), 'red').save(buf, format='PNG')
        body = b'--testboundary\r\nContent-Disposition: form-data; name="file"; filename="photo.png"\r\nContent-Type: image/png\r\n\r\n' + buf.getvalue() + b'\r\n--testboundary--\r\n'
        def upload():
            req = urllib.request.Request('http://127.0.0.1:%d/api/upload?slug=demo' % self.server.server_port,
                data=body, headers={'Content-Type':'multipart/form-data; boundary=testboundary', 'Cookie':self.cookies['admin'], 'X-KF-CSRF':self.m.csrf_token(self.cookies['admin'])})
            try: response = urllib.request.urlopen(req)
            except urllib.error.HTTPError as e: response = e
            with response:
                return response.status, json.load(response)
        with patch.object(self.m.time, 'time', return_value=time.time()):
            status, first = upload(); self.assertEqual(status, 200)
            status, second = upload(); self.assertEqual(status, 200)
        self.assertNotEqual(first['name'], second['name'])
        with patch.object(Path, 'mkdir', side_effect=PermissionError('test')):
            status, error = upload()
        self.assertEqual(status, 500)
        self.assertIn('error', error)

    def test_prompt_permissions_preview_and_job_snapshot(self):
        status, library = self.request('/api/ai/prompts', user='ops-test')
        self.assertEqual(status, 200)
        self.assertFalse(library['can_manage'])
        self.assertEqual(self.request('/api/ai/prompts', user='finance-test')[0], 403)
        self.assertEqual(self.request('/api/ai/prompts', {}, user='ops-test')[0], 403)
        selection = {'revision':library['revision'], 'template_id':'company', 'variables':{'services':'Design consulting'}}
        status, preview = self.request('/api/ai/prompts/preview', {'selection':selection}, user='ops-test')
        self.assertEqual(status, 200, preview)
        self.assertIn('Design consulting', preview['preview'])
        status, data = self.request('/api/ai/build', dict(slug='demo',mode='existing',profile_id='mock',language='en',prompt_selection=selection), user='ops-test')
        self.assertEqual(status, 202, data)
        job = self.wait_job(data['job']['id'])
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual(job['prompt']['template']['version'], 1)
        self.assertEqual(job['prompt']['preview'], preview['preview'])
        self.assertEqual(self.m.read_draft('demo')['ai']['prompt']['template']['id'], 'company')
        selection['revision'] = -1
        self.assertEqual(self.request('/api/ai/prompts/preview', {'selection':selection})[0], 409)
        for filename in ('appearance.js','locale.js'):
            self.assertEqual(self.request('/'+filename, user=None)[0], 200)

    def test_recovery_login_consumes_code_once(self):
        import urllib.parse
        m = self.m
        users = m.load_users()
        users['admin']['mfa_secret'] = 'JBSWY3DPEHPK3PXP'
        users['admin']['recovery'] = m.hash_recovery(['abcd-1234'], users['admin']['salt'])
        m._write(m.USERS_F, users)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        data = urllib.parse.urlencode({'user':'admin', 'pw':'Test-Password-123', 'code':'abcd-1234'}).encode()
        url = 'http://127.0.0.1:%d/login' % self.server.server_port
        with self.assertRaises(urllib.error.HTTPError) as redirect:
            opener.open(urllib.request.Request(url, data=data), timeout=10)
        self.assertEqual(redirect.exception.code, 303)
        redirect.exception.close()
        self.assertEqual(m.load_users()['admin']['recovery'], [])
        with opener.open(urllib.request.Request(url, data=data), timeout=10) as response:
            self.assertIn('两步验证码不正确', response.read().decode())

    def test_prompt_writing_context_revision_and_variable_guards(self):
        cfg = dict(id='writing', name='Writing', protocol='openai_chat', model='test', base_url='https://example.test/v1', api_key='private-key')
        self.assertEqual(self.request('/api/ai/config', cfg)[0], 200)
        library = self.request('/api/ai/prompts')[1]
        template = library['templates'][0]
        body = dict(scope='prompts', profile_id='writing', text='Serve {{audience}} with {{services}}.', limit=2400,
                    prompt=dict(kind='templates', revision=library['revision'], module_ids=template['module_ids']),
                    context=dict(field='promptEditBody', name=template['name'], category=template['category'], defaults='{"audience":"Teams"}', language='en', instruction='Make acceptance criteria explicit.'))
        valid = 'Guide {{audience}} through {{services}} with verifiable acceptance criteria.'
        with patch.object(self.m.kf_ai, 'complete', return_value=valid) as complete:
            self.assertEqual(self.request('/api/ai/assist', body)[1]['text'], valid)
            sent = json.loads(complete.call_args.args[3])['context']
            modules = json.loads(sent['modules'])
            self.assertEqual(modules[0]['body'], next(m['body'] for m in library['modules'] if m['id']==template['module_ids'][0]))
            self.assertEqual(sent['prompt_kind'], 'templates')
            self.assertEqual(json.loads(sent['defaults'])['audience'], 'Teams')
            count = complete.call_count
            self.assertEqual(self.request('/api/ai/assist', dict(body, prompt=dict(body['prompt'], revision=0)))[0], 409)
            self.assertEqual(self.request('/api/ai/assist', dict(body, context=dict(body['context'], defaults='not json')))[0], 400)
            self.assertEqual(complete.call_count, count)
            complete.return_value = 'Missing original variables'
            self.assertEqual(self.request('/api/ai/assist', body)[0], 400)
            complete.return_value = valid + ' {{unsupported}}'
            self.assertEqual(self.request('/api/ai/assist', body)[0], 400)
            complete.return_value = 'A concise purpose description.'
            self.assertEqual(self.request('/api/ai/assist', dict(body, context=dict(body['context'], field='promptEditDescription'), limit=300))[0], 200)
        self.assertEqual(self.request('/api/ai/prompts')[1]['revision'], library['revision'])

    def test_writing_field_contracts_and_scope_isolation(self):
        cfg=dict(id='writing',name='Writing',protocol='openai_chat',model='test',base_url='https://example.test/v1',api_key='private-key')
        self.request('/api/ai/config',cfg)
        for field,(scope,contract) in self.m.kf_ai.WRITING_FIELDS.items():
            with self.subTest(field=field),patch.object(self.m.kf_ai,'complete',return_value='Scoped suggestion') as complete:
                body=dict(scope=scope,profile_id='writing',text='',context={'field':field,'name':'Current item','industry':'Healthcare','company':'Unrelated builder','summary':'Style description','operation_id':'mail.send'},limit=300)
                self.assertEqual(self.request('/api/ai/assist',body)[0],200)
                self.assertIn(contract,complete.call_args.args[2])
                context=json.loads(complete.call_args.args[3])['context']
                if scope in ('styles','prompts'):self.assertNotIn('company',context)
                if scope!='styles':self.assertNotIn('summary',context)
        with patch.object(self.m.kf_ai,'complete') as complete:
            self.assertEqual(self.request('/api/ai/assist',dict(scope='build',profile_id='writing',text='',context={'field':'styleSummary'}))[0],400)
            self.assertEqual(self.request('/api/ai/assist',dict(scope='automation',profile_id='writing',text='',context={'field':'auto-subject','operation_id':'dns.change'}))[0],400)
            self.assertEqual(self.request('/api/ai/assist',dict(scope='styles',profile_id='writing',text='',context={'field':'styleSummary'}),user='ops-test')[0],403)
            complete.assert_not_called()

    def test_writing_assistance_permissions_context_and_limits(self):
        cfg = dict(id='writing', name='Writing', protocol='openai_chat', model='test', base_url='https://example.test/v1', api_key='private-key')
        self.assertEqual(self.request('/api/ai/config', cfg)[0], 200)
        body = dict(scope='build', profile_id='writing', text='Existing', context={'company':'Demo','language':'en'}, limit=100)
        with patch.object(self.m.kf_ai, 'complete', return_value='Suggested text') as complete:
            status, data = self.request('/api/ai/assist', body, user='ops-test')
            self.assertEqual((status, data['text']), (200, 'Suggested text'))
            self.assertFalse(complete.call_args.args[0]['json_mode'])
            self.assertIn('Demo', complete.call_args.args[3])
            self.assertNotIn('private-key', complete.call_args.args[3])
            self.assertEqual(self.request('/api/ai/assist', body, user='finance-test')[0], 403)
            self.assertEqual(self.request('/api/ai/assist', dict(body,scope='prompts'), user='ops-test')[0], 403)
            self.assertEqual(self.request('/api/ai/assist', dict(body,scope='prompts'))[0], 200)
            self.assertEqual(self.request('/api/ai/assist', dict(body,context={'password':'secret'}))[0], 400)
            self.assertEqual(self.request('/api/ai/assist', dict(body,limit=0))[0], 400)
            self.assertEqual(self.request('/api/ai/assist', dict(body,profile_id='mock'))[0], 400)
            complete.return_value = 'x'*101
            self.assertEqual(self.request('/api/ai/assist', body)[0], 400)

    def test_permissions_and_secret_redaction(self):
        self.assertEqual(self.request('/api/ai/config', user=None)[0], 401)
        self.assertEqual(self.request('/api/ai/config', user='finance-test')[0], 403)
        cfg = dict(id='test', name='Test', protocol='openai_chat', model='test', base_url='https://example.test/v1', api_key='secret-test')
        self.assertEqual(self.request('/api/ai/config',cfg,user='ops-test')[0], 403)
        self.assertEqual(self.request('/api/ai/config',cfg)[0], 200)
        status, data = self.request('/api/ai/config', user='ops-test')
        self.assertEqual(status,200); self.assertNotIn('secret-test',json.dumps(data))
        self.assertNotIn('base_url',data['profiles'][1]); self.assertFalse(data['can_configure'])
        self.assertEqual(self.request('/api/ai/test',{'profile_id':'test'},user='ops-test')[0],403)

    def test_generate_preview_save_publish_handoff(self):
        body = dict(slug='demo',mode='existing',brief='设计咨询；空间规划',profile_id='mock',language='zh')
        status, data = self.request('/api/ai/build',body,user='ops-test')
        self.assertEqual(status,202, data)
        job = self.wait_job(data['job']['id']); self.assertEqual(job['status'],'completed', job)
        self.assertTrue(job['simulated'])
        draft = self.m.read_draft('demo')
        self.assertIn('设计咨询',json.dumps(draft,ensure_ascii=False))
        self.assertEqual(self.m.read_spec('demo'),self.original)
        self.assertTrue((self.base/'sites/demo/.backups'/('ai-'+job['id']+'.json')).exists())
        status, preview = self.request('/preview/demo/home')
        self.assertEqual(status,200); self.assertIn('设计咨询',preview)
        self.assertEqual(self.request('/api/ai/build',body)[0],409)
        with patch.object(self.m.Handler,'_render_check',return_value={'ok':True}):
            status, result = self.request('/api/publish',{'slug':'demo'})
        self.assertEqual(status,200,result); self.assertEqual(result['pages'],2)
        self.assertEqual(self.m.read_spec('demo')['pages'],draft['pages'])
        self.assertFalse(self.m.is_dirty('demo'))

    def test_publication_history_restore_permissions_and_draft_preservation(self):
        draft = ai.mock_spec('Changed', 'New copy', PAGES, 'zh')
        ai.atomic_json(self.base/'sites/demo/site-draft.json', draft)
        with patch.object(self.m.Handler, '_render_check', return_value={'ok': True}):
            code, result = self.request('/api/publish', {'slug': 'demo'}, user='ops-test')
        self.assertEqual(code, 200, result)
        ident = result['publication_id']
        self.assertEqual(result['publication_state'], 'published')
        self.assertEqual(self.request('/api/publications/demo', user='finance-test')[0], 403)
        code, data = self.request('/api/publications/demo', user='ops-test')
        self.assertEqual(code, 200)
        item = data['items'][0]
        self.assertEqual(item['user'], 'ops-test')
        self.assertNotIn('before', item)
        self.assertNotIn('after', item)
        body = dict(slug='demo', id=ident, version=item['version'], confirmed=True)
        self.assertEqual(self.request('/api/publish/restore', body, user='finance-test')[0], 403)
        self.assertEqual(self.request('/api/publish/restore', dict(body, confirmed=False))[0], 400)
        self.assertEqual(self.request('/api/publish/restore', dict(body, version=0))[0], 409)
        code, restored = self.request('/api/publish/restore', body, user='ops-test')
        self.assertEqual(code, 200, restored)
        self.assertEqual(self.m.read_spec('demo'), self.original)
        self.assertEqual(self.m.read_draft('demo'), draft)
        self.assertTrue(restored['dirty'])
        self.assertEqual(self.request('/api/publications/demo')[1]['items'][0]['state'], 'restored')

    def test_publication_transport_failure_is_visible_as_interrupted(self):
        with patch.object(self.m.Handler, '_render_check', side_effect=OSError('transport lost')):
            code, result = self.request('/api/publish', {'slug': 'demo'})
        self.assertEqual(code, 409, result)
        self.assertEqual(self.request('/api/publications/demo')[1]['items'][0]['state'], 'interrupted')
        self.assertEqual(self.m.read_spec('demo'), self.original)

    def test_partial_publish_tracks_pages_that_reached_wordpress(self):
        draft=ai.mock_spec('Changed', 'New copy', PAGES, 'zh')
        ai.atomic_json(self.base/'sites/demo/site-draft.json',draft)
        with patch.object(self.m.Handler,'_render_check',side_effect=[{'ok':True},{'ok':False,'errors':['write failed']}]):
            status,result=self.request('/api/publish',{'slug':'demo'})
        self.assertEqual(status,400)
        self.assertEqual(result['pages'],1)
        self.assertTrue(result['dirty'])
        live=self.m.read_spec('demo')
        self.assertEqual(live['pages'][0],draft['pages'][0])
        self.assertEqual(live['pages'][1],self.original['pages'][1])

    def test_generation_blocks_edits_and_duplicates(self):
        started, release = threading.Event(), threading.Event()
        original = ai.generate
        def slow(*a,**k):
            started.set(); release.wait(5); return original(*a,**k)
        with patch.object(ai,'generate',side_effect=slow):
            body=dict(slug='demo',brief='Test',profile_id='mock')
            status, data=self.request('/api/ai/build',body);self.assertEqual(status,202)
            self.assertTrue(started.wait(2))
            self.assertEqual(self.request('/api/ai/build',body)[0],400)
            self.assertEqual(self.request('/api/publish',{'slug':'demo'})[0],409)
            self.assertEqual(self.request('/api/spec',{'slug':'demo','page':'home','sections':[]})[0],409)
            release.set(); self.assertEqual(self.wait_job(data['job']['id'])['status'],'completed')

    def test_failed_generation_leaves_draft_and_live_unchanged(self):
        with patch.object(ai,'generate',side_effect=ai.AIError('模型没有返回有效 JSON')):
            status,data=self.request('/api/ai/build',dict(slug='demo',brief='Test',profile_id='mock'))
            self.assertEqual(status,202);job=self.wait_job(data['job']['id'])
            self.assertEqual(job['status'],'failed')
        self.assertEqual(self.m.read_draft('demo'),self.original)
        self.assertEqual(self.m.read_spec('demo'),self.original)

    def test_new_site_uses_template_pages_without_changing_provisioned_live_pages(self):
        import kf_template, kf_styles
        store=kf_styles.StyleStore(self.base)
        template=store.public(True)['templates'][0]
        template=store.change(dict(template,pages=[
            {'slug':'home','title':'Welcome','blueprint':['hero','cards','cta']},
            {'slug':'portfolio','title':'Our work','blueprint':['hero','gallery','cta']}]))
        def provision(company,domain,slug,port,name,price,industry,plan_id):
            site=self.base/'sites'/slug;site.mkdir()
            ai.atomic_json(site/'meta.json',dict(company=company,domain=domain,port=port))
            ai.atomic_json(site/'site-spec.json',{'pages':kf_template.build_spec(industry,company,domain)})
        with patch.object(self.m,'provision',side_effect=provision):
            status,data=self.request('/api/ai/build',dict(mode='new',slug='portfolio-site',company='Studio',
                domain='portfolio.example.test',plan_id='starter',brief='Design portfolio',language='en',
                profile_id='mock',style_template_id=template['id']))
            self.assertEqual(status,202,data)
            job=self.wait_job(data['job']['id']);self.assertEqual(job['status'],'completed',job)
        draft=self.m.read_draft('portfolio-site')
        self.assertEqual([p['slug'] for p in draft['pages']],['home','portfolio'])
        self.assertEqual(draft['ai']['style']['pages'],template['pages'])
        self.assertNotIn('portfolio',[p['slug'] for p in self.m.read_spec('portfolio-site')['pages']])
        self.assertTrue(list((self.base/'sites'/'portfolio-site'/'.backups').glob('ai-*.json')))
        with patch.object(self.m,'apply_design',return_value=True),patch.object(self.m.ks(),'sync_template_navigation',return_value=False):
            code,result=self.m.publish_site({'slug':'portfolio-site'},lambda *a,**kw:{'ok':True})
            self.assertEqual(code,500);self.assertTrue(self.m.is_dirty('portfolio-site'))
        with patch.object(self.m,'apply_design',return_value=True),patch.object(self.m.ks(),'sync_template_navigation',return_value=True) as navigation:
            code,result=self.m.publish_site({'slug':'portfolio-site'},lambda *a,**kw:{'ok':True})
            self.assertEqual(code,200,result);self.assertFalse(result['dirty'])
            self.assertEqual(navigation.call_args.args[1],draft['pages'])
            self.assertEqual(self.m.read_spec('portfolio-site'),draft)


    def test_new_site_pipeline_and_invoice(self):
        import kf_template
        def provision(company, domain, slug, port, name, price, industry, plan_id):
            site=self.base/'sites'/slug;site.mkdir()
            ai.atomic_json(site/'meta.json',dict(company=company,domain=domain,port=port))
            ai.atomic_json(site/'site-spec.json',{'pages':kf_template.build_spec(industry,company,domain)})
        with patch.object(self.m,'provision',side_effect=provision):
            status,data=self.request('/api/ai/build',dict(mode='new',slug='new-site',company='New Company',
                domain='new.example.test',plan_id='starter',industry='tech',brief='New site requirements',language='en'))
            self.assertEqual(status,202,data)
            job=self.wait_job(data['job']['id']);self.assertEqual(job['status'],'completed',job)
            self.assertEqual(job['pages'],4);self.assertTrue(job['invoice'])
            self.assertEqual(len(self.m.invoices()),1)
            self.assertNotIn('new-site',self.m._SITE_RESERVATIONS)
            self.assertTrue(self.m.is_dirty('new-site'))


if __name__ == '__main__':
    unittest.main()
