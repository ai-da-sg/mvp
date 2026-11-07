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

    def test_language_editions_and_english_composition(self):
        module=self.store.change({'kind':'modules','revision':1,'id':'english-copy','name':'English copy','category':'copy','language':'en','body':'Write for {{audience}}. Facts: {{facts}}.'})
        template=self.store.change({'kind':'templates','revision':2,'id':'english-site','name':'English site','category':'Business','language':'en','body':'Explain {{services}} for {{audience}}. Support {{goal}}.','module_ids':[module['id']]})
        result=self.store.compose({'revision':3,'template_id':template['id'],'variables':{'audience':'Teams','services':'Consulting','goal':'Enquiries'}})
        self.assertIn('Not provided; do not invent facts',result['preview'])
        self.assertIn('Business context',result['preview'])
        self.assertNotRegex(result['preview'],r'[㐀-鿿]')
        with self.assertRaises(ai.AIError):
            self.store.compose({'revision':3,'template_id':template['id'],'module_ids':['copy']})
        with self.assertRaises(ai.AIError):
            self.store.change(dict(template,kind='templates',revision=3,module_ids=['copy']))
        with self.assertRaises(ai.AIError):
            self.store.change(dict(module,kind='modules',revision=3,language='zh'))
        with self.assertRaises(ai.AIError):
            self.store.change(dict(module,kind='modules',revision=3,language='fr'))
        edited=self.store.change(dict(module,kind='modules',revision=3,body='Use {{facts}} only.'))
        self.assertEqual(edited['language'],'en')
        restored=self.store.change({'kind':'modules','id':module['id'],'action':'restore','version':1,'revision':4})
        self.assertEqual(restored['language'],'en')

    def test_complete_english_scene_fits_and_variable_expansion_is_bounded(self):
        ids=[]
        for i in range(10):
            item=self.store.change({'kind':'modules','revision':self.store.read()['revision'],'id':'english-'+str(i),'name':'English module '+str(i),'category':'copy','language':'en','body':('Use verified evidence. '*100)+'{{facts}}'})
            ids.append(item['id'])
        t=self.store.change({'kind':'templates','revision':self.store.read()['revision'],'id':'english-scene','name':'Full English scene','category':'Business','language':'en','body':'Support {{goal}}.','module_ids':ids})
        selection={'revision':self.store.read()['revision'],'template_id':t['id'],'variables':{'audience':'Teams','services':'Consulting','goal':'Enquiries','facts':'Verified'}}
        self.assertGreater(len(self.store.compose(selection)['instructions']),20000)
        m=self.store.read()['modules'][-1]
        self.store.change(dict(m,kind='modules',revision=selection['revision'],body=('{{facts}} '*200)))
        selection['revision']=self.store.read()['revision'];selection['variables']['facts']='x'*1500
        with self.assertRaises(ai.AIError):self.store.compose(selection)

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

    def test_delete_protects_all_references_and_preserves_composed_snapshots(self):
        self.store.change({'kind':'modules','revision':1,'id':'custom','name':'Custom','category':'copy','body':'Facts: {{services}}'})
        self.store.change({'kind':'templates','revision':2,'id':'custom-site','name':'Custom site','category':'custom','body':'Create a site','module_ids':['custom']})
        snapshot=self.store.compose({'revision':3,'template_id':'custom-site','variables':{'services':'Verified services','audience':'Customers','goal':'Enquiries','tone':'Professional'}})
        with self.assertRaises(ai.AIError):
            self.store.change({'action':'delete','kind':'modules','id':'custom','revision':3})
        self.store.change({'action':'toggle','kind':'templates','id':'custom-site','revision':3})
        with self.assertRaises(ai.AIError):
            self.store.change({'action':'delete','kind':'modules','id':'custom','revision':4})
        self.store.change({'action':'delete','kind':'templates','id':'custom-site','revision':4})
        with self.assertRaises(prompts.PromptConflict):
            self.store.change({'action':'delete','kind':'modules','id':'custom','revision':4})
        self.store.change({'action':'delete','kind':'modules','id':'custom','revision':5})
        restarted=prompts.PromptStore(self.tmp.name).read()
        self.assertNotIn('custom',[x['id'] for x in restarted['modules']])
        self.assertIn('Verified services',snapshot['preview'])
        self.assertEqual(snapshot['template']['id'],'custom-site')
