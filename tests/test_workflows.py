import sys
import tempfile
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from kf_automation import Automation
from kf_workflows import Workflows
from kf_tool_runtime import ActionConflict

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.calls=[];self.https=True
        self.results={'site.generate':{'job':{'id':'generated'}},'site.publish':{'pages':2},'dns.change':{'applied':True},'dns.verify':{'ok':True},
                      'mail.draft':{'to':'client@example.test','subject':'Delivery','body':'Website is live'},'mail.send':{'state':'accepted'}}
        registry={}
        for name in ('site.generate','site.publish','dns.change','dns.verify','site.https','mail.draft','mail.send'):
            def prepare(args,ctx,user,n=name):return {'arguments':args,'snapshot':{},'summary':n,'mode':'totp' if n=='dns.change' else 'confirm' if n in ('site.publish','mail.send') else 'draft' if n in ('site.generate','mail.draft') else 'read'}
            def execute(item,ctx,n=name):
                self.calls.append(n)
                return {'ok':self.https} if n=='site.https' else self.results[n]
            registry[name]={'purpose':'build','prepare':prepare,'authorize':lambda item,ctx:None,'execute':execute}
        self.auto=Automation(self.tmp.name,lambda slug:{'slug':slug,'domain':'example.test'},lambda *args:None,lambda *args:None,registry)
        self.flow=Workflows(self.tmp.name,self.auto,lambda:[{'id':'generated','status':'completed'}])
    def tearDown(self):
        for t in self.flow.threads.values():t.join(5)
        self.tmp.cleanup()
    def wait(self,ident,state):
        for _ in range(100):
            item=self.flow.get(ident)
            if item['state']==state:return item
            time.sleep(.02)
        self.fail('Expected '+state+', got '+str(self.flow.get(ident)))
    def approve(self,item):
        step=next(s for s in item['steps'] if s['state']!='completed');action=self.auto.actions.get(step['action_id'])
        self.auto.execute('operator',{'id':action['id'],'digest':action['digest'],'confirmed':True,'code':'123456'})
        # The HTTP controller resumes after a successful confirmation; emulate that boundary here.
        self.flow.control(item['id'],'operator','resume')
    def test_complete_delivery_requires_each_write_approval(self):
        item=self.flow.create('operator',{'slug':'demo','brief':'Build a site','recipient':'client@example.test','dns_changes':[{'operation':'add','record':{'name':'www','type':'A','content':'93.184.216.34'}}]})
        self.flow.control(item['id'],'operator','start');item=self.wait(item['id'],'waiting')
        self.assertEqual(self.calls,['site.generate']);self.approve(item)
        item=self.wait(item['id'],'waiting');self.assertEqual(self.calls,['site.generate','site.publish']);self.approve(item)
        item=self.wait(item['id'],'waiting');self.assertNotIn('mail.send',self.calls)
        ticket=self.flow.amend(item['id'],'operator',{'to':'reviewed@example.test','subject':'Revised','body':'Reviewed delivery'})
        self.assertEqual(ticket['arguments']['to'],'reviewed@example.test');self.approve(self.flow.get(item['id']))
        item=self.wait(item['id'],'completed');self.assertEqual(self.calls.count('site.publish'),1);self.assertEqual(self.calls.count('mail.send'),1)
        self.flow.control(item['id'],'operator','resume');self.assertEqual(self.calls.count('mail.send'),1)
    def test_https_retry_does_not_republish(self):
        self.https=False;item=self.flow.create('operator',{'slug':'demo','brief':'Build'})
        self.flow.control(item['id'],'operator','start');self.approve(self.wait(item['id'],'waiting'))
        self.wait(item['id'],'failed');self.https=True;self.flow.control(item['id'],'operator','retry')
        self.wait(item['id'],'completed');self.assertEqual(self.calls.count('site.publish'),1);self.assertEqual(self.calls.count('site.https'),2)
    def test_pause_and_restart_do_not_auto_replay(self):
        item=self.flow.create('operator',{'slug':'demo','brief':'Build'})
        item['state']='running';self.flow.save(item)
        restarted=Workflows(self.tmp.name,self.auto,self.flow.jobs)
        self.assertEqual(restarted.get(item['id'])['state'],'paused');self.assertEqual(self.calls,[])
        restarted.control(item['id'],'operator','pause');self.assertEqual(restarted.get(item['id'])['state'],'paused')
