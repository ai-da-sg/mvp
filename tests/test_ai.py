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
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base/'console').mkdir(); (self.base/'sites'/'demo').mkdir(parents=True)
        (self.base/'core').symlink_to(ROOT/'core', target_is_directory=True)
        (self.base/'console'/'admin.pass').write_text('Test-Password-123')
        (self.base/'console'/'ai.js').symlink_to(ROOT/'console'/'ai.js')
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
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), m.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.env.stop(); self.tmp.cleanup()

    def request(self, path, data=None, user='admin'):
        headers = {'Content-Type':'application/json'}
        if user: headers['Cookie'] = self.cookies[user]
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (self.server.server_port,path),
                                     data=json.dumps(data).encode() if data is not None else None, headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e: r = e
        raw = r.read()
        try: body = json.loads(raw)
        except ValueError: body = raw.decode()
        return r.status, body

    def wait_job(self, jid):
        for _ in range(100):
            job = next(j for j in self.m.ai_store().jobs() if j['id']==jid)
            if job['status'] not in ai.ACTIVE: return job
            time.sleep(.02)
        self.fail('Job did not terminate')

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
