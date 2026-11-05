import copy
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import kf_sso as sso
from kf_ai import AIError

class SSOTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=sso.SSOStore(self.tmp.name)
        self.site=self.store.configure('https://mvp.example.com','demo','https://site.example.com')
        self.users={'admin':{'active':True,'role':'admin','hash':'secret-hash','salt':'salt','name':'Operator'}}
        self.sessions={'session':{'user':'admin','exp':time.time()+3600}}
        self.verifier=secrets.token_hex(32);self.challenge=sso.digest(self.verifier)
    def tearDown(self):self.tmp.cleanup()
    def issue(self,**changes):
        args=dict(slug='demo',challenge=self.challenge,sid='session',sessions=self.sessions,users=self.users,allowed=lambda role:True);args.update(changes)
        return self.store.issue(**args)
    def signed(self,action='consume',**fields):
        raw=json.dumps(dict(site='demo',action=action,**fields)).encode();ts=str(int(time.time()));nonce=secrets.token_hex(32)
        return raw,{'X-MVP-Time':ts,'X-MVP-Nonce':nonce,'X-MVP-Signature':hmac.new(self.site['secret'].encode(),ts.encode()+b'\n'+nonce.encode()+b'\n'+raw,hashlib.sha256).hexdigest()}
    def call(self,action='consume',**fields):
        raw,headers=self.signed(action,**fields)
        return self.store.callback(raw,headers,self.sessions,self.users,lambda role:True)
    def test_single_use_browser_binding_signature_and_replay(self):
        ticket=self.issue()
        with self.assertRaises(AIError):self.call(ticket=ticket,verifier=secrets.token_hex(32))
        raw,headers=self.signed(ticket=ticket,verifier=self.verifier)
        bad=dict(headers,**{'X-MVP-Signature':'0'*64})
        with self.assertRaises(AIError):self.store.callback(raw,bad,self.sessions,self.users,lambda role:True)
        result=self.store.callback(raw,headers,self.sessions,self.users,lambda role:True)
        self.assertEqual(result['role'],'administrator')
        for request in [(raw,headers),self.signed(ticket=ticket,verifier=self.verifier)]:
            with self.assertRaises(AIError):self.store.callback(*request,self.sessions,self.users,lambda role:True)
        self.assertTrue(self.call('check',grant=result['grant'])['ok'])
        self.assertNotIn(ticket,self.store.state_path.read_text())
        self.assertNotIn(result['grant'],self.store.state_path.read_text())
        self.assertEqual(self.store.config_path.stat().st_mode & 0o777,0o600)
    def test_revocation_expiry_role_and_account_changes(self):
        for change in ('logout','expired','disabled','password','mfa','role'):
            with self.subTest(change=change):
                original=copy.deepcopy((self.sessions,self.users))
                result=self.call(ticket=self.issue(),verifier=self.verifier)
                if change=='logout':self.sessions.clear()
                elif change=='expired':self.sessions['session']['exp']=time.time()-1
                elif change=='disabled':self.users['admin']['active']=False
                elif change=='password':self.users['admin']['hash']='changed'
                elif change=='mfa':self.users['admin']['mfa_secret']='changed'
                elif change=='role':self.users['admin']['role']='ops'
                with self.assertRaises(AIError):self.call('check',grant=result['grant'])
                self.sessions,self.users=original
        self.users['admin']['role']='finance'
        with self.assertRaises(AIError):self.issue()
        self.users['admin']['role']='ops'
        self.assertEqual(self.call(ticket=self.issue(),verifier=self.verifier)['role'],'editor')
        with self.assertRaises(AIError):self.issue(allowed=lambda role:False)
    def test_expired_ticket_and_parallel_consumption(self):
        ticket=self.issue();state=json.loads(self.store.state_path.read_text());state['tickets'][sso.digest(ticket)]['exp']=time.time()-1
        self.store.state_path.write_text(json.dumps(state))
        with self.assertRaises(AIError):self.call(ticket=ticket,verifier=self.verifier)
        ticket=self.issue()
        def consume(_):
            try:return self.call(ticket=ticket,verifier=self.verifier)['ok']
            except AIError:return False
        with ThreadPoolExecutor(max_workers=4) as pool:self.assertEqual(sum(pool.map(consume,range(4))),1)
    def test_cross_site_and_url_restrictions(self):
        for url in ['http://example.com','https://user:pass@example.com','https://example.com?x=1','https://example.com:8443','https://example.com/\n']:
            with self.assertRaises((AIError,ValueError)):sso.public_origin(url)
        ticket=self.issue();self.store.configure('https://mvp.example.com','other','https://other.example.com')
        site=self.store.site('other');raw=json.dumps({'site':'other','action':'consume','ticket':ticket,'verifier':self.verifier}).encode()
        ts=str(int(time.time()));nonce=secrets.token_hex(32)
        headers={'X-MVP-Time':ts,'X-MVP-Nonce':nonce,'X-MVP-Signature':hmac.new(site['secret'].encode(),ts.encode()+b'\n'+nonce.encode()+b'\n'+raw,hashlib.sha256).hexdigest()}
        with self.assertRaises(AIError):self.store.callback(raw,headers,self.sessions,self.users,lambda role:True)
