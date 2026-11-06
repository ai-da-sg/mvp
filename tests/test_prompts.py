import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import kf_ai as ai
import kf_prompts as prompts


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=prompts.PromptStore(self.tmp.name)

    def test_all_presets_compose_and_variables_remain_data(self):
        for t in self.store.read()['templates']:
            selection={'revision':1,'template_id':t['id'],'variables':{'services':'Real services','facts':'Do not reinterpret {{services}}'}}
            result=self.store.compose(selection,'Customer-specific brief')
            self.assertIn('Real services',result['brief'])
            self.assertIn('Do not reinterpret {{services}}',result['preview'])
            self.assertEqual(result['template']['version'],1)
            self.assertTrue(result['modules'])
        with self.assertRaises(ai.AIError):self.store.compose({'revision':1,'template_id':'company'})
        with self.assertRaises(ai.AIError):self.store.compose({'revision':1,'template_id':'company','module_ids':['copy','copy']})
        with self.assertRaises(prompts.PromptConflict):self.store.compose({'revision':0,'template_id':'company'})

    def test_version_conflict_history_restore_and_restart(self):
        old=self.store.read()['templates'][0]
        body=dict(old,kind='templates',revision=1,body='Specific brief for {{audience}}')
        updated=self.store.change(body)
        self.assertEqual(updated['version'],2)
        with self.assertRaises(prompts.PromptConflict):self.store.change(body)
        restored=self.store.change({'action':'restore','kind':'templates','id':old['id'],'revision':2,'version':1})
        self.assertEqual(restored['version'],3)
        self.assertEqual(restored['body'],old['body'])
        self.assertEqual(prompts.PromptStore(self.tmp.name).read()['revision'],3)

    def test_invalid_module_references_and_archive_protection(self):
        with self.assertRaises(ai.AIError):self.store.change({'action':'toggle','kind':'modules','id':'quality','revision':1})
        old=self.store.read()['templates'][0]
        for update in ({'module_ids':['missing']},{'module_ids':[]},{'body':'Bad {{unknown}}'},{'defaults':{'secret':'no'}}):
            with self.subTest(update=update),self.assertRaises(ai.AIError):self.store.change(dict(old,kind='templates',revision=1,**update))
        created=self.store.change({'kind':'modules','revision':1,'id':'custom','name':'Custom','category':'copy','body':'Write for {{audience}}'})
        self.assertEqual(created['version'],1)
        self.store.change({'kind':'modules','revision':2,'id':'custom','action':'toggle'})
        self.assertNotIn('custom',[m['id'] for m in self.store.public()['modules']])

    def test_guidance_reaches_provider_with_output_constraints(self):
        from unittest.mock import patch
        pages=[{'slug':'home','title':'Home'}]
        payload=ai.mock_spec('Acme','Consulting',pages,'en')
        import json
        with patch.object(ai,'complete',return_value=json.dumps(payload)) as complete:
            ai.generate(dict(ai.MOCK,protocol='openai_chat'),'key','Acme','Real business data',pages,'en',guidance='Keep copy concise')
        system,prompt=complete.call_args.args[-2:]
        self.assertIn('HTML is allowed only inside a rich.html field',system)
        self.assertIn('without scripts, styles, embeds or events',system)
        self.assertEqual(json.loads(prompt)['design_guidance'],'Keep copy concise')
        self.assertEqual(json.loads(prompt)['brief'],'Real business data')
