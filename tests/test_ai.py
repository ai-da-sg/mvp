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
        (self.base/'theme').symlink_to(ROOT/'theme', target_is_directory=True)
        (self.base/'console'/'admin.pass').write_text('Test-Password-123')
        for filename in ('ai.js','prompts.js','appearance.js','locale.js','domains.js','mcp.js','automation.js'):
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

    def test_upload_unique_names_and_permission_error(self):
        import io
        from PIL import Image
        buf = io.BytesIO(); Image.new('RGB', (32, 32), 'red').save(buf, format='PNG')
        body = b'--testboundary\r\nContent-Disposition: form-data; name="file"; filename="photo.png"\r\nContent-Type: image/png\r\n\r\n' + buf.getvalue() + b'\r\n--testboundary--\r\n'
        def upload():
            req = urllib.request.Request('http://127.0.0.1:%d/api/upload?slug=demo' % self.server.server_port,
                data=body, headers={'Content-Type':'multipart/form-data; boundary=testboundary', 'Cookie':self.cookies['admin']})
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
