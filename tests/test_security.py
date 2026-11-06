"""Security boundaries exercised against a temporary console, never production."""
import base64
import concurrent.futures
import http.client
import json
from pathlib import Path
import time
import unittest
from urllib.parse import urlencode
from unittest.mock import patch
import test_ai
import kf_sections


class SecurityTests(unittest.TestCase):
    setUp = test_ai.ConsoleTests.setUp
    tearDown = test_ai.ConsoleTests.tearDown
    request = test_ai.ConsoleTests.request

    def raw(self, path, body=None, cookie=None, headers=None):
        headers = dict(headers or {})
        if cookie: headers['Cookie'] = cookie
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        conn.request('POST' if body is not None else 'GET', path, body, headers)
        response = conn.getresponse(); data = response.read()
        result = (response.status, data, dict(response.getheaders()))
        conn.close(); return result

    def login(self, code='', password='Test-Password-123'):
        return self.raw('/login', urlencode({'user':'admin','pw':password,'code':code}),
                        headers={'Content-Type':'application/x-www-form-urlencoded'})

    def enable_mfa(self):
        users = self.m.load_users()
        users['admin']['mfa_secret'] = 'JBSWY3DPEHPK3PXP'
        self.m._write(self.m.USERS_F, users)
        return self.m._totp(users['admin']['mfa_secret'], int(time.time()//30))

    def test_asset_paths_and_symlinks(self):
        root = self.base/'sites/demo/html'; upload = root/'wp-content/uploads'
        upload.mkdir(parents=True); (upload/'ok.png').write_bytes(b'fixture-image')
        (root/'wp-config.php').write_text('fixture-only')
        (upload/'secret.png').symlink_to(root/'wp-config.php')
        outside = self.base/'sites/demo/html-other'; outside.mkdir(); (outside/'private.png').write_bytes(b'private')
        self.m._write(self.m.SHARES_F, {'fixture-share':{'slug':'demo','active':True}})
        for base, user in [('/pa/demo/','admin'),('/sa/fixture-share/',None)]:
            for rel in ['uploads/../../wp-config.php','uploads/../../../html-other/private.png',
                        'uploads/%2e%2e/%2e%2e/wp-config.php','uploads/secret.png','uploads/ok.php',
                        'uploads/..\\..\\wp-config.php']:
                with self.subTest(base=base,rel=rel):
                    self.assertEqual(self.request(base+rel,user=user)[0],404)
            self.assertEqual(self.request(base+'uploads/ok.png',user=user)[0],200)
        self.assertEqual(self.request('/pa/demo/uploads/ok.png',user='finance-test')[0],403)

    def test_rich_sanitizer_and_attribute_boundaries(self):
        for payload in ['<svg/onload=alert(1)>','<img src=x onerror=alert(1)>',
                        '<a href="jav&#x61;script:alert(1)">x</a>',
                        '<math><mtext><table><mglyph><style><!--</style><img title="--><img src=x onerror=alert(1)>">']:
            clean = kf_sections.sanitize_rich(payload)
            self.assertNotIn('onerror', clean); self.assertNotIn('onload',clean)
            self.assertNotIn('javascript:',clean)
        self.assertIn('<strong>Safe</strong>',kf_sections.sanitize_rich('<p><strong>Safe</strong></p>'))
        bad = {'type':'rich','bg':'"><img src=x onerror=alert(1)>','html':'<p>Content</p>'}
        self.assertTrue(kf_sections.validate_sections([bad]))
        rendered = kf_sections.render_sections([bad])
        self.assertNotIn('onerror', rendered)
        status, data = self.request('/api/spec',{'slug':'demo','page':'home','sections':[bad]},user='ops-test')
        self.assertEqual(status,400,data)
        self.assertEqual(kf_sections.validate_sections([{'type':'table','headers':['A'],'rows':[['B']]}]),[])

    def test_preview_sandbox_and_no_script(self):
        for path, cookie in [('/preview/demo/home',self.cookies['admin']),('/s/fixture-share/home',None)]:
            self.m._write(self.m.SHARES_F, {'fixture-share':{'slug':'demo','active':True}})
            code, _, headers = self.raw(path,cookie=cookie)
            self.assertEqual(code,200)
            csp = headers['Content-Security-Policy']
            self.assertIn('sandbox ',csp);self.assertIn("script-src 'none'",csp)
            self.assertNotIn('allow-same-origin',csp)

    def test_csrf_requires_session_token_and_exact_origin(self):
        body=json.dumps({'action':'disable','user':'finance-test'})
        cookie=self.cookies['admin']; token=self.m.csrf_token(cookie)
        for headers in [{'Content-Type':'text/plain'}, {'Content-Type':'application/json'},
                        {'Content-Type':'application/json','X-KF-CSRF':token,'Origin':'https://sibling.example'},
                        {'Content-Type':'application/json','X-KF-CSRF':self.m.csrf_token(self.cookies['ops-test'])}]:
            self.assertEqual(self.raw('/api/users',body,cookie,headers)[0],403)
        self.assertTrue(self.m.load_users()['finance-test']['active'])
        self.assertEqual(self.raw('/api/users',body,cookie,{'Content-Type':'text/plain','X-KF-CSRF':token})[0],415)
        self.assertEqual(self.raw('/api/users',body,cookie,{'Content-Type':'application/json','X-KF-CSRF':token,
            'Origin':'http://127.0.0.1:'+str(self.server.server_port)})[0],200)
        self.assertFalse(self.m.load_users()['finance-test']['active'])

    def test_login_and_logout_csrf(self):
        self.assertEqual(self.raw('/login','user=admin',headers={'Origin':'null','Content-Type':'application/x-www-form-urlencoded'})[0],403)
        self.assertEqual(self.raw('/logout',cookie=self.cookies['admin'])[0],200)
        self.assertEqual(self.request('/api/state')[0],200,'GET logout must not revoke session')
        self.assertEqual(self.request('/logout',{})[0],200)
        self.assertEqual(self.request('/api/state')[0],401)

    def test_basic_is_disabled(self):
        for password in ('wrong','Test-Password-123'):
            auth=base64.b64encode(('admin:'+password).encode()).decode()
            self.assertEqual(self.raw('/api/state',headers={'Authorization':'Basic '+auth})[0],401)

    def test_mfa_failures_lock_and_persist(self):
        self.enable_mfa()
        with patch.object(self.m,'client_ip',return_value='198.51.100.8'):
            for _ in range(5):self.login('invalid')
        self.assertGreater(self.m.locked_for('admin'),0)
        self.assertEqual(self.m.IP_FAILS['198.51.100.8']['count'],5)
        self.m.FAILS.clear();self.m.load_fails()
        self.assertGreater(self.m.locked_for('admin'),0)
        self.assertEqual(self.login(self.enable_mfa())[0],200)

    def test_mfa_replay_persisted_and_concurrent_recovery(self):
        code=self.enable_mfa()
        self.assertEqual(self.login(code)[0],303)
        self.assertEqual(self.login(code)[0],200)
        self.assertTrue((self.base/'console/login-mfa.json').exists())
        users=self.m.load_users();users['admin']['recovery']=self.m.hash_recovery(['abcd-1234'],users['admin']['salt'])
        self.m._write(self.m.USERS_F,users)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(lambda _:self.login('abcd-1234')[0],range(2)))
        self.assertEqual(sorted(statuses),[200,303])
        self.assertEqual(self.m.load_users()['admin']['recovery'],[])

    def test_mfa_management_throttles_and_revokes(self):
        self.enable_mfa()
        for _ in range(5):self.request('/api/mfa',{'action':'disable','code':'invalid'})
        self.assertEqual(self.request('/api/mfa',{'action':'disable','code':self.enable_mfa()})[0],429)
        self.m.clear_fails('admin')
        other='kf_sid='+self.m.new_session('admin')
        self.assertEqual(self.request('/api/mfa',{'action':'disable','code':self.enable_mfa()})[0],200)
        self.assertIsNone(self.m.session_user(other))
        self.assertEqual(self.m.session_user(self.cookies['admin']),'admin')
        self.assertNotIn('recovery',self.m.load_users()['admin'])

    def test_read_permissions(self):
        for user in ('finance-test','ops-test'):
            for path in ('/api/users','/api/security','/api/audit','/api/smtp','/health/ip'):
                self.assertEqual(self.request(path,user=user)[0],403,(user,path))
        for path in ('/api/spec/demo','/api/leads/demo','/api/media/demo','/preview/demo/home'):
            self.assertEqual(self.request(path,user='finance-test')[0],403)
        for path in ('/api/state','/api/mfa','/api/clients','/api/ledger/demo'):
            self.assertEqual(self.request(path,user='finance-test')[0],200)

    def test_llm_credentials_bound_to_endpoint(self):
        store=self.m.ai_store()
        profile=dict(id='fixture',name='Test',protocol='openai_chat',base_url='https://one.example/v1',model='model',api_key='fixture-key')
        store.configure(profile)
        profile.update(base_url='https://two.example/v1',api_key='')
        with self.assertRaises(test_ai.ai.AIError):store.configure(profile)
        profile['clear_key']=True;store.configure(profile)
        self.assertEqual(store.resolve('fixture')[1],'')
        profile['base_url']='http://remote.example/v1'
        with self.assertRaises(test_ai.ai.AIError):store.configure(profile)
        profile['base_url']='http://127.0.0.1:11434/v1';store.configure(profile)

    def test_global_smtp_endpoint_change_requires_new_password(self):
        body={'provider':'smtp','host':'one.example','port':587,'tls':True,'user':'user','pass':'fixture-password'}
        self.assertEqual(self.request('/api/smtp',body)[0],200)
        body.update(host='two.example',**{'pass':''})
        self.assertEqual(self.request('/api/smtp',body)[0],400)
        self.assertEqual(self.m.settings()['smtp']['host'],'one.example')
        body['pass']='new-fixture';self.assertEqual(self.request('/api/smtp',body)[0],200)
        body['tls']=False;self.assertEqual(self.request('/api/smtp',body)[0],400)

    def test_request_limits_and_json_types(self):
        self.assertEqual(self.raw('/login',b'',headers={'Content-Length':'-1'})[0],413)
        self.assertEqual(self.raw('/login',b'',headers={'Content-Length':'999999999'})[0],413)
        cookie=self.cookies['admin'];headers={'Content-Type':'application/json','X-KF-CSRF':self.m.csrf_token(cookie)}
        self.assertEqual(self.raw('/api/users','[]',cookie,headers)[0],400)
        self.assertEqual(self.raw('/api/users','{',cookie,headers)[0],400)
