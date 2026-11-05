import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import kf_automation as a
from kf_ai import AIError
from kf_tool_runtime import ActionDenied
from kf_stepup import StepUp

class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.engine=a.Automation(self.tmp.name,lambda slug:{'domain':'example.test','slug':slug},lambda *args:None,lambda *args:None)
        self.policy={'sites':['demo'],'purposes':['build'],'tools':[{'name':'search','mode':'read'}],'resources':['brand://guide']}
        self.server=self.engine.mcp.change({'id':'provider','name':'Provider','url':'https://example.com/mcp','enabled':True,'policy':self.policy},'admin')
        self.catalog={'tools':[{'name':'search','description':'Search','inputSchema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query'],'additionalProperties':False}}],
                      'resources':[{'name':'Guide','uri':'brand://guide','description':'Brand guide'}],'prompts':[]}
    def tearDown(self):self.tmp.cleanup()
    def test_ai_plan_is_read_only_scoped_and_records_context_hash(self):
        plan={'calls':[{'server':'provider','kind':'tools','name':'search','arguments':{'query':'brand'}}]}
        with patch.object(a,'complete',return_value=json.dumps(plan)),patch.object(self.engine.mcp,'test',return_value=self.catalog),patch.object(self.engine.mcp,'call',return_value={'content':[{'type':'text','text':'Brand reference'}]}):
            sources=self.engine.research('operator','demo','Build a website',{'protocol':'openai_chat'},'key','job')
        self.assertEqual(len(sources),1);self.assertIn('result_digest',sources[0]);self.assertEqual(sources[0]['server_version'],1)
        self.assertNotIn('key',json.dumps(self.engine.actions.list('operator')))
        # A malicious planner cannot invoke a tool omitted from the read-only allowlist.
        plan['calls'][0]['name']='delete_everything'
        with patch.object(a,'complete',return_value=json.dumps(plan)),patch.object(self.engine.mcp,'test',return_value=self.catalog),patch.object(self.engine.mcp,'call') as call:
            with self.assertRaises(ActionDenied):self.engine.research('operator','demo','Build',{'protocol':'openai_chat'},'key','job2')
            call.assert_not_called()
    def test_context_revocation_and_prompt_argument_validation(self):
        with patch.object(self.engine.mcp,'test',return_value=self.catalog),patch.object(self.engine.mcp,'call',return_value={'contents':[{'text':'Reference'}]}):
            ticket=self.engine.prepare_mcp('operator',{'slug':'demo','server':'provider','kind':'resources','name':'brand://guide','arguments':{}})
            self.engine.execute('operator',{'id':ticket['id'],'digest':ticket['digest']})
        with self.assertRaises(ActionDenied):self.engine.context_results('other-user','demo',[ticket['id']])
        self.engine.mcp.change({'id':'provider','version':1,'name':'Provider','url':'https://example.com/mcp','enabled':False,'policy':self.policy},'admin')
        with self.assertRaises(AIError):self.engine.context_results('operator','demo',[ticket['id']])
    def test_stepup_replay_rate_limit_and_restart(self):
        gate=StepUp(self.tmp.name);gate.verify('operator','123456',lambda code:100)
        with self.assertRaises(ActionDenied):StepUp(self.tmp.name).verify('operator','123456',lambda code:100)
        for _ in range(5):
            with self.assertRaises(ActionDenied):gate.verify('bad-user','invalid',lambda code:None)
        with self.assertRaises(ActionDenied):gate.verify('bad-user','123456',lambda code:101)
        gate.verify('operator','654321',lambda code:101)
