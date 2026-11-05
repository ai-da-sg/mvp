import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from kf_tool_runtime import ActionStore,ActionDenied,ActionConflict
from kf_ai import AIError

class ActionTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=ActionStore(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def prepare(self,**kw):
        return self.store.prepare(**dict(user='operator',slug='demo',tool='mail.send',arguments={'to':'client@example.test'},mode='confirm',summary='Send reviewed message',snapshot={'version':1},**kw))
    def run_action(self,item,**kw):
        args=dict(digest=item['digest'],authorize=lambda x:None,verify_totp=lambda u,c:None,executor=lambda x:{'sent':True});args.update(kw)
        return self.store.execute(item['id'],'operator',**args)
    def test_confirmation_parameter_binding_and_idempotency(self):
        item=self.prepare(request_key='once');self.assertEqual(item['id'],self.prepare(request_key='once')['id'])
        with self.assertRaises(ActionDenied):self.run_action(item)
        with self.assertRaises(ActionConflict):self.run_action(item,digest='wrong',confirmed=True)
        called=[]
        def execute(x):called.append(x['id']);return {'sent':True}
        with ThreadPoolExecutor(max_workers=2) as pool:
            def run(_):
                try:return self.run_action(item,confirmed=True,executor=execute)['state']
                except ActionConflict:return 'busy'
            states=list(pool.map(run,range(2)))
        self.assertEqual(called,[item['id']]);self.assertIn('succeeded',states)
        with self.assertRaises(ActionDenied):self.store.get(item['id'],'someone-else')
    def test_uncertain_result_requires_reconciliation(self):
        item=self.prepare()
        def fail(x):raise TimeoutError('provider might have accepted')
        result=self.run_action(item,confirmed=True,executor=fail);self.assertEqual(result['state'],'uncertain')
        with self.assertRaises(ActionConflict):self.run_action(item,confirmed=True)
        with self.assertRaises(ActionDenied):self.store.reconcile(item['id'],'operator','succeeded','Checked provider')
        self.store.reconcile(item['id'],'admin','succeeded','Provider confirms message accepted',admin=True)
        self.assertEqual(self.run_action(item)['state'],'succeeded')
    def test_restart_and_authorization_revocation(self):
        item=self.prepare();item['state']='running';self.store.save(item,'started')
        self.store.recover_interrupted();self.assertEqual(self.store.get(item['id'])['state'],'interrupted')
        def deny(x):raise ActionDenied('Role removed')
        with self.assertRaises(ActionDenied):self.run_action(item,authorize=deny)
    def test_totp_and_cancellation(self):
        item=self.store.prepare(user='operator',slug='demo',tool='dns.change',arguments={},mode='totp',summary='DNS change',snapshot={})
        calls=[]
        def verify(user,code):
            if code!='123456':raise ActionDenied('Bad OTP')
            calls.append(user)
        with self.assertRaises(ActionDenied):self.run_action(item,confirmed=True,verify_totp=verify)
        self.assertEqual(self.run_action(item,confirmed=True,verify_totp=verify,code='123456')['state'],'succeeded')
        self.assertEqual(calls,['operator'])
        item=self.prepare();self.store.cancel(item['id'],'operator')
        with self.assertRaises(ActionConflict):self.run_action(item,confirmed=True)
