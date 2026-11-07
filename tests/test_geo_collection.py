import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from kf_ai import AIError, atomic_json
from kf_geo import GeoStore
from kf_geo_collector import Collector
from kf_geo_search import collect, parse, request, SearchFailure
from kf_tool_runtime import ActionConflict


def response(provider='openai_search',answer='Demo provides workshops.'):
    citation={'type':'url_citation','url':'https://example.com/services','title':'Services','start_index':0,'end_index':4}
    if provider=='openai_search':
        return {'id':'response-1','status':'completed','model':'test-model','usage':{'total_tokens':30},'output':[
            {'type':'web_search_call','status':'completed','action':{'type':'search','sources':[{'url':'https://retrieved.example.com/'}]}},
            {'type':'message','role':'assistant','content':[{'type':'output_text','text':answer,'annotations':[citation]}]}]}
    return {'id':'interaction-1','status':'completed','model':'test-model','usage':{},'steps':[
        {'type':'google_search_call','arguments':{'queries':['workshops']}},
        {'type':'google_search_result','call_id':'search-1','result':[{'search_suggestions':'<div>Search suggestions</div>'}]},
        {'type':'model_output','content':[{'type':'text','text':answer,'annotations':[citation]}]}]}


class AdapterTests(unittest.TestCase):
    def test_search_evidence_is_distinct_from_citations(self):
        for provider in ('openai_search','gemini_search'):
            data=response(provider);result=parse(provider,data)
            self.assertEqual(result['status'],'success')
            self.assertEqual(result['citations'],['https://example.com/services'])
            self.assertEqual(len(result['search_calls']),1)
            data['status']='incomplete'
            self.assertEqual(parse(provider,data)['status'],'failed')
        data=response();data['output']=data['output'][1:]
        self.assertEqual(parse('openai_search',data)['status'],'no_search')

    def test_payload_is_neutral_and_secrets_are_headers_only(self):
        captured=[]
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(response()).encode()
        class Opener:
            def open(self,req,timeout):captured.append(req);return Reply()
        with patch('urllib.request.build_opener',return_value=Opener()):
            for provider in ('openai_search','gemini_search'):
                request(provider,{'api_key':'private-test-key','model':'test-model','max_tokens':'2048'},
                    {'text':'Which workshops are available?','language':'en','market':'SG','brand':'Secret Brand','facts':['Private facts']})
        for req in captured:
            body=req.data.decode()
            for forbidden in ('Secret Brand','Private facts','private-test-key'):self.assertNotIn(forbidden,body)
            self.assertIn('Which workshops',body)
        self.assertEqual(json.loads(captured[0].data)['tools'][0]['user_location']['country'],'SG')

    def test_invalid_upstream_schema_is_retained_without_success(self):
        payload={'status':'completed','output':[{'type':'message','role':'assistant','content':[None]}]}
        result,raw=collect('openai_search',{}, {},transport=lambda *args:payload)
        self.assertEqual(result['status'],'failed');self.assertEqual(raw,payload)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        site=self.base/'sites/demo';site.mkdir(parents=True);(site/'meta.json').write_text('{}')
        self.calls=[];self.allowed=True
        def authorize(user,slug):
            if not self.allowed or slug!='demo':raise AIError('Site access revoked')
        def transport(provider,config,question):
            self.calls.append(copy.deepcopy(question));return response(provider)
        self.collector=Collector(self.base,authorize,transport)
        self.store=GeoStore(self.base,'demo')
        self.store.save_profile({'revision':0,'profile':{'brand':'Demo','language':'en','market':'SG','sector':'general'}},'ops')
        self.q=self.store.save_item('questions',{'revision':1,'item':{'text':'Which workshops are available?','language':'en','market':'SG','intent':'category'}},'ops')['questions'][0]
        self.account=self.collector.providers.save({'id':'search-test','name':'Search','provider':'openai_search','enabled':True,'sites':['demo'],'capabilities':['geo'],
            'values':{'api_key':'test-secret','model':'test-model','daily_limit':'40','max_tokens':'2048'}},'admin')
        self.collector.probe('search-test',1,'admin')
        self.plan=self.collector.save_plan({'slug':'demo','name':'Daily baseline','question_ids':[self.q['id']],'account_ids':['search-test'],'repeats':2,'interval_hours':24,'enabled':True},'ops')

    def tearDown(self):self.tmp.cleanup()

    def run_plan(self,key='test-run'):
        return self.collector.start(self.plan['id'],'ops',self.plan['version'],key,background=False)

    def test_durable_samples_quota_idempotency_and_no_secret_leak(self):
        item=self.run_plan();self.assertEqual(item['state'],'succeeded')
        self.assertEqual(item['result']['status'],'completed')
        observations=self.store.read()['observations'];self.assertEqual(len(observations),2)
        self.assertTrue(observations[0]['brand_mentioned']);self.assertIsNone(observations[0]['facts_accurate'])
        self.assertEqual(self.store.response(observations[0]['id'])['id'],'response-1')
        self.assertEqual(self.collector.config('demo')['accounts'][0]['requests_today'],3)
        self.run_plan();self.assertEqual(len(self.calls),3)
        self.assertNotIn('test-secret',json.dumps(self.collector.config('demo')))

    def test_quota_failure_and_corruption_fail_closed(self):
        with self.collector.locked():
            data=self.collector.read();key=next(iter(data['quota']));data['quota'][key]=40;atomic_json(self.collector.path,data)
        run=self.run_plan();self.assertEqual(run['result']['status'],'partial');self.assertEqual(len(self.calls),1)
        self.collector.path.write_text('{invalid')
        with self.assertRaises(AIError):self.collector.reserve(self.account)
        self.assertEqual(self.collector.path.read_text(),'{invalid')

    def test_changed_questions_connections_and_authorization_stop_requests(self):
        self.store.save_item('questions',{'revision':2,'item':dict(self.q,text='Changed')},'ops')
        with self.assertRaises(ActionConflict):self.run_plan()
        self.allowed=False
        with self.assertRaises(AIError):self.run_plan()
        self.assertEqual(len(self.calls),1)

    def test_pause_cancels_between_samples(self):
        def transport(*args):
            self.collector.change_plan({'id':self.plan['id'],'version':self.plan['version'],'action':'pause'},'ops')
            return response()
        self.collector.transport=transport
        run=self.run_plan();self.assertEqual(run['result']['status'],'cancelled')
        self.assertEqual(len(self.store.read()['observations']),1)

    def test_scheduler_claims_once_and_recovery_does_not_replay(self):
        with self.collector.locked():
            data=self.collector.read();data['plans'][0]['next_run']=1;atomic_json(self.collector.path,data)
        with patch.object(self.collector,'start') as start:
            self.collector.tick();self.collector.tick();self.assertEqual(start.call_count,1)
        run=self.collector.actions.prepare(user='ops',slug='demo',tool='geo.collect',arguments={},mode='read',summary='Interrupted',snapshot=self.collector.snapshot(self.plan),request_key='interrupted')
        run['state']='running';self.collector.actions.save(run,'started')
        self.collector.actions.recover_interrupted()
        self.assertEqual(self.collector.actions.get(run['id'])['state'],'interrupted')
        self.assertEqual(len(self.calls),1)

    def test_active_run_blocks_duplicate_spend(self):
        run=self.collector.actions.prepare(user='ops',slug='demo',tool='geo.collect',arguments={},mode='read',summary='Queued',snapshot=self.collector.snapshot(self.plan),request_key='queued')
        with self.assertRaises(ActionConflict):self.run_plan()
        self.assertEqual(self.run_plan('queued')['id'],run['id'])
        self.assertEqual(len(self.calls),1)


class CollectionHTTPTests(unittest.TestCase):
    def setUp(self):
        from test_ai import ConsoleTests
        self.fixture=ConsoleTests();self.fixture.setUp();self.request=self.fixture.request
        self.fixture.m.geo_collector().transport=lambda provider,config,question:response(provider)

    def tearDown(self):self.fixture.tearDown()

    def test_connection_permissions_scopes_verification_and_secrets(self):
        endpoint='/api/geo/collection/'
        self.assertEqual(self.request(endpoint+'config',user='ops-test')[0],403)
        self.assertEqual(self.request(endpoint+'config?slug=demo',user='finance-test')[0],403)
        self.assertEqual(self.request(endpoint+'config?slug=demo',user='ops-test')[0],200)
        body={'id':'http-search','name':'Search','provider':'openai_search','enabled':True,'sites':['demo'],'capabilities':['geo'],
              'values':{'api_key':'http-private-key','model':'test-model','daily_limit':'40','max_tokens':'2048'}}
        self.assertEqual(self.request(endpoint+'connection',body,user='ops-test')[0],403)
        status,result=self.request(endpoint+'connection',body)
        self.assertEqual(status,200,result);self.assertNotIn('http-private-key',json.dumps(result))
        self.assertEqual(self.request(endpoint+'test',{'id':'http-search','version':1},user='ops-test')[0],403)
        status,result=self.request(endpoint+'test',{'id':'http-search','version':1})
        self.assertEqual(status,200,result);self.assertEqual(result['verification']['status'],'verified')
        self.assertEqual(self.request(endpoint+'test',{'id':'http-search','version':0})[0],409)
        self.assertEqual(self.request(endpoint+'connection',dict(body,version=1,values={'api_key':'','daily_limit':'50'}))[0],200)
        result=self.request(endpoint+'config?slug=demo',user='ops-test')[1]
        self.assertEqual(result['accounts'][0]['verification']['status'],'unverified')
        self.assertNotIn('http-private-key',json.dumps(result))
        atomic_json(self.fixture.base/'sites/demo/archive.json',{'archived':True})
        self.assertEqual(self.request(endpoint+'config?slug=demo',user='ops-test')[0],400)


if __name__=='__main__':unittest.main()
