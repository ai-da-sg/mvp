import copy
from datetime import datetime,timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import kf_geo_analysis as analysis
from kf_ai import AIError
import test_geo


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_geo.GeoTests();self.fixture.setUp();self.store=self.fixture.store
        self.profile={'brand':'Demo','aliases':['Demo Studio'],'owned_domains':['example.com'],'competitors':[{'name':'Other','aliases':['Other Studio'],'domains':['other.example.com']}],'market':'SG','language':'en','sector':'general'}
        self.store.save_profile({'revision':0,'profile':self.profile},'ops')
        self.q=self.fixture.question()

    def tearDown(self):self.fixture.tearDown()

    def sample(self,batch='baseline',**changes):
        item=self.fixture.observation(self.q)
        item.update(batch=batch,answer='Demo Studio and Other are available.',**changes)
        self.store.observe({'revision':self.store.read()['revision'],'items':[item]},'ops')
        return self.store.read()['observations'][-1]

    def test_entities_are_snapshotted_and_reviews_never_overwrite_evidence(self):
        original=self.sample()
        self.store.save_profile({'revision':3,'profile':dict(self.profile,aliases=['New alias'],competitors=[])},'ops')
        data=self.store.review_observation({'revision':4,'id':original['id'],'mentioned':True,'recommended':False,'accurate':None,'note':'Both listed, no recommendation'},'reviewer')
        self.assertEqual(data['observations'][0],original)
        result=analysis.overview(data,'example.com')[0]
        self.assertEqual(result['mention_events'],2)
        target=result['entities'][0];competitor=result['entities'][1]
        self.assertEqual(target['share_of_voice'],0.5)
        self.assertEqual(target['recommendation_reviews'],1)
        self.assertEqual(target['recommendations'],0)
        self.assertEqual(target['accuracy_reviews'],0)
        self.assertEqual(competitor['name'],'Other')
        self.assertEqual(original['entity_profile']['version'],1)

    def test_aliases_boundaries_and_ambiguous_entities(self):
        self.assertTrue(analysis.mentioned('Try DEMO STUDIO.', ['Demo Studio']))
        self.assertFalse(analysis.mentioned('Demographic data', ['Demo']))
        self.assertTrue(analysis.mentioned('推荐小宝石幼儿园', ['小宝石']))
        for invalid in [dict(self.profile,competitors=[{'name':'demo'}]),dict(self.profile,owned_domains=['example.com/path']),dict(self.profile,aliases='not-a-list')]:
            with self.assertRaises(AIError):analysis.clean_entities(invalid)

    def test_source_classification_requires_real_evidence(self):
        original=self.sample()
        data=self.store.review_source({'revision':3,'domain':'example.com','category':'owned','note':'Verified official domain'},'reviewer')
        source=analysis.overview(data,'example.com')[0]['sources'][0]
        self.assertEqual(source['category'],'owned');self.assertEqual(source['observation_ids'],[original['id']])
        with self.assertRaises(AIError):self.store.review_source({'revision':4,'domain':'invented.example.com','category':'independent','note':'No evidence'},'reviewer')

    def test_comparison_rejects_protocol_and_question_changes(self):
        self.sample();self.sample('retest')
        data=self.store.read();report=analysis.comparison(data,'baseline','retest')
        self.assertTrue(report['comparable']);self.assertEqual(report['rows'][0]['mention_delta'],0)
        self.assertIsNone(report['summaries'][0]['interval'])
        for location,field,value in [('record','model','another'),('question','version',2),('profile','aliases',['Changed'])]:
            changed=copy.deepcopy(data);o=changed['observations'][1]
            (o if location=='record' else o['question'] if location=='question' else o['entity_profile'])[field]=value
            self.assertFalse(analysis.comparison(changed,'baseline','retest')['comparable'])

    def test_question_cluster_summary_and_missing_samples(self):
        self.sample();self.sample('retest')
        data=self.store.read()
        for o in list(data['observations']):
            extra=copy.deepcopy(o);extra['question']['id']='a'*32;extra['id']=('b' if o['batch']=='baseline' else 'c')*32
            extra['brand_mentioned']=o['batch']=='retest';data['observations'].append(extra)
        report=analysis.comparison(data,'baseline','retest')
        summary=report['summaries'][0]
        self.assertEqual(summary['questions'],2);self.assertEqual(summary['mean_question_delta'],0.5)
        self.assertEqual(summary['interval'],[0,1])
        data['observations'][-1]['status']='failed'
        summary=analysis.comparison(data,'baseline','retest')['summaries'][0]
        self.assertEqual(summary['missing_questions'],1);self.assertIsNone(summary['mean_question_delta']);self.assertIsNone(summary['interval'])

    def test_experiment_snapshot_and_unknown_attribution(self):
        before=self.sample();after=self.sample('retest')
        stamp=datetime.fromisoformat(before['observed_at']).timestamp()
        publication={'id':'a'*32,'state':'published','created':stamp,'updated':stamp,'targets':['home']}
        body={'revision':4,'name':'Content experiment','baseline':'baseline','retest':'retest','control_questions':[],'note':'No control, descriptive comparison only'}
        data=self.store.save_experiment(body,'ops',publication)
        record=data['experiments'][0]
        self.assertTrue(record['publication_between_windows']);self.assertEqual(record['publication']['id'],publication['id'])
        self.assertEqual(record['report']['rows'][0]['mention_delta'],0)
        with self.assertRaises(AIError):self.store.save_experiment(dict(body,revision=5),'ops',dict(publication,state='failed'))
        report={'revision':5,'channel':'unknown','platform':'Unknown','start':'2026-01-01','end':'2026-01-31','visits':None,'conversions':None,'note':'No analytics export available'}
        data=self.store.save_attribution(report,'ops');self.assertIsNone(data['attribution'][0]['visits'])
        with self.assertRaises(AIError):self.store.save_attribution(dict(report,revision=6),'ops')
        with self.assertRaises(AIError):self.store.save_attribution(dict(report,revision=6,visits=-1),'ops')
        self.assertEqual(self.store.read()['experiments'][0],record)


if __name__=='__main__':unittest.main()
