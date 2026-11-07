import copy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import kf_geo as geo
from kf_ai import AIError


class GeoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        for slug in ('demo', 'other'):
            folder = self.base / 'sites' / slug
            folder.mkdir(parents=True)
            (folder / 'meta.json').write_text('{}')
        self.store = geo.GeoStore(self.base, 'demo')

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, kind, item):
        return self.store.save_item(kind, {'revision': self.store.read()['revision'], 'item': item}, 'ops')

    def question(self):
        return self.save('questions', dict(text='Which service fits?', language='en', market='SG', intent='category'))['questions'][0]

    def fact(self):
        return self.save('facts', dict(translations={'en':'Offers workshops', 'zh':'提供工作坊'}, source_url='https://example.com/services',
            verified_on=date.today().isoformat(), expires_on='', approved=True))['facts'][0]

    def observation(self, q, **overrides):
        return dict(question_id=q['id'], platform='Engine', mode='Search', environment='SG; signed out', batch='baseline',
                    observed_at=datetime.now(timezone.utc).isoformat(), channel='manual_search', status='success',
                    answer='A useful answer', citations=['https://example.com/services'], brand_mentioned=True, **overrides)

    def test_isolation_conflict_and_symlinks(self):
        self.fact()
        self.assertEqual(geo.GeoStore(self.base, 'other').read()['facts'], [])
        with self.assertRaises(geo.GeoConflict):
            self.store.save_profile({'revision':0,'profile':{'brand':'Demo','language':'en','market':'SG','sector':'general'}}, 'ops')
        for slug in ('../demo', 'missing', None):
            with self.assertRaises(AIError): geo.GeoStore(self.base, slug)
        (self.base/'sites/link').symlink_to(self.base/'sites/demo',target_is_directory=True)
        with self.assertRaises(AIError): geo.GeoStore(self.base, 'link')
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_registered_same_slug_alias_reuses_workspace_and_publication_history(self):
        from kf_publications import PublicationStore
        other_base=self.base/'shared-install'
        (other_base/'sites').mkdir(parents=True)
        (other_base/'sites/demo').symlink_to(self.base/'sites/demo',target_is_directory=True)
        self.fact()
        shared=geo.GeoStore(other_base,'demo')
        self.assertEqual(shared.read(),self.store.read())
        self.assertEqual(PublicationStore(other_base,'demo').root,PublicationStore(self.base,'demo').root)
        (other_base/'sites/other').symlink_to(self.base/'sites/demo',target_is_directory=True)
        with self.assertRaises(AIError):geo.GeoStore(other_base,'other')

    def test_observations_keep_question_versions_and_exclude_failures(self):
        q=self.question()
        success=self.observation(q)
        failed=dict(success,status='failed',answer='',citations=[],brand_mentioned=None,error='Timeout')
        sim=dict(success,channel='simulation',batch='simulated')
        data=self.store.observe({'revision':1,'items':[success,failed,sim]},'ops')
        self.save('questions',dict(q,text='New question'))
        self.assertEqual(self.store.read()['observations'][0]['question']['version'],1)
        groups=geo.metrics(data,'example.com')
        self.assertEqual(len(groups),2)
        first=groups[0]
        self.assertEqual((first['total'],first['success'],first['failed']), (2,1,1))
        self.assertEqual(first['mention_rate'],1)
        self.assertEqual(first['citation_rate'],1)
        self.assertIsNone(first['accuracy_rate'])
        first['question_versions']=[(q['id'],1)]

    def test_failed_only_is_not_zero_visibility_and_atomic_import(self):
        q=self.question()
        failed=dict(self.observation(q),status='failed',answer='',citations=[],error='Unavailable')
        data=self.store.observe({'revision':1,'items':[failed]},'ops')
        self.assertIsNone(geo.metrics(data,'example.com')[0]['mention_rate'])
        with self.assertRaises(AIError):
            self.store.observe({'revision':2,'items':[self.observation(q),dict(self.observation(q),question_id='other-site-id')]},'ops')
        self.assertEqual(len(self.store.read()['observations']),1)
        for bad in [dict(self.observation(q),observed_at='2020-01-01'),dict(self.observation(q),channel={}),dict(failed,answer='Not a failure')]:
            with self.assertRaises(AIError):self.store.observe({'revision':2,'items':[bad]},'ops')
        with self.assertRaises(AIError):self.store.observe({'revision':2,'items':[failed]},'ops')
        self.assertEqual(self.store.read()['revision'],2)

    def test_content_requires_current_approved_language_fact_and_real_model(self):
        f=self.fact();data=self.store.read();profile={'protocol':'openai_chat','id':'real','model':'model'}
        response=json.dumps(dict(title='Workshops',text='Offers workshops',fact_ids=[f['id']],rationale='Answers the question'))
        with patch.object(geo,'complete',return_value=response) as complete:
            result=geo.assist(data,'content','en','',profile,'secret')
            self.assertEqual(result['facts'][0]['id'],f['id'])
            self.assertNotIn('secret',json.dumps(result))
            self.assertIn('untrusted',complete.call_args.args[2])
        for change in ({'approved':False},{'expires_on':'2020-01-01'},{'translations':{'en':'','zh':'资料'}}):
            invalid=copy.deepcopy(data);invalid['facts'][0].update(change)
            with self.assertRaises(AIError):geo.assist(invalid,'content','en','',profile,'')
        with self.assertRaises(AIError):geo.assist(data,'content','en','',{'protocol':'mock'},'')
        with patch.object(geo,'complete',return_value=response.replace(f['id'],'invented')):
            with self.assertRaises(AIError):geo.assist(data,'content','en','',profile,'')

    def test_diagnostic_scope_and_honest_limits(self):
        html='<html><head><title>Demo</title><meta name="robots" content="noindex"><script>hidden</script></head><body><h1>Demo</h1>'+('Useful public content. '*30)+'</body></html>'
        report=geo.diagnose('https://example.com/','example.com',fetch=lambda u,d:(html,u,200,{'content-type':'text/html'}))
        checks={c['code']:c['status'] for c in report['checks']}
        self.assertEqual(checks['meta_noindex'],'warning')
        self.assertEqual(checks['search_index'],'not_checked')
        self.assertEqual(checks['visible_text'],'pass')
        with self.assertRaises(AIError):geo.diagnose('https://other.com/','example.com')
        with self.assertRaises(AIError):geo.diagnose('https://example.com/','example.com',fetch=lambda u,d:(html,'https://other.com/',200,{'content-type':'text/html'}))

    def test_diagnostic_robots_and_headers_and_private_network_rejection(self):
        def fetch(u,d):
            if u.endswith('/robots.txt'):
                return 'User-agent: OAI-SearchBot\nDisallow: /\nSitemap: https://example.com/map.xml',u,200,{'content-type':'text/plain'}
            if u.endswith('/map.xml'):
                return '<urlset><url><loc>https://example.com/</loc></url></urlset>',u,200,{'content-type':'application/xml'}
            return '<h1>Public page</h1>',u,200,{'content-type':'text/html','x-robots-tag':'noindex'}
        report=geo.diagnose('https://example.com/','example.com',fetch=fetch)
        checks={c['code']:c for c in report['checks']}
        self.assertEqual(checks['response_index_headers']['status'],'warning')
        self.assertFalse(checks['robots_txt']['agents']['OAI-SearchBot'])
        self.assertTrue(checks['robots_txt']['agents']['Googlebot'])
        self.assertEqual(checks['sitemap']['status'],'pass')
        with self.assertRaises(AIError):geo.fetch_document('http://127.0.0.1/',999999999)


class GeoHTTPTests(unittest.TestCase):
    def setUp(self):
        from test_ai import ConsoleTests
        self.fixture=ConsoleTests();self.fixture.setUp()
        self.request=self.fixture.request

    def tearDown(self):self.fixture.tearDown()

    def test_real_http_permissions_persistence_and_archive(self):
        self.assertEqual(self.request('/api/geo/workspace?slug=demo',user='finance-test')[0],403)
        status,body=self.request('/api/geo/workspace?slug=demo',user='ops-test')
        self.assertEqual(status,200)
        self.assertEqual(body['workspace']['revision'],0)
        self.assertTrue(body['pages'])
        payload={'slug':'demo','revision':0,'profile':{'brand':'Demo','market':'SG','language':'en','sector':'education'}}
        self.assertEqual(self.request('/api/geo/profile',payload,user='ops-test')[0],200)
        self.assertEqual(self.request('/api/geo/profile',payload,user='ops-test')[0],409)
        self.assertEqual(self.request('/api/geo/workspace?slug=missing',user='ops-test')[0],400)
        self.fixture.m.kf_ai.atomic_json(self.fixture.base/'sites/demo/archive.json',{'archived':True})
        self.assertEqual(self.request('/api/geo/workspace?slug=demo',user='ops-test')[0],400)

    def test_proposal_review_uses_existing_draft_and_blocks_stale_facts(self):
        f = self.fixture
        store=geo.GeoStore(f.base,'demo')
        fact=dict(translations={'en':'Offers workshops','zh':'提供工作坊'}, source_url='https://example.test/services',
                  verified_on=date.today().isoformat(), expires_on='', approved=True)
        data=store.save_item('facts',{'revision':0,'item':fact},'ops-test')
        fact=data['facts'][0]
        page=f.m.read_draft('demo')['pages'][0]
        proposal=dict(title='Workshops',text='Offers workshops',rationale='Answer the question',facts=[dict(fact,text='Offers workshops')],
                      language='en',page=page['slug'],page_version=f.m.kf_design_profiles.fingerprint(page),status='review')
        data=store.append('proposals',proposal,1,'ops-test')
        ident=data['proposals'][0]['id']
        payload=dict(slug='demo',revision=2,id=ident,confirmed=True,title='Workshops',text='Offers workshops <script>unsafe()</script>')
        original=f.m.read_spec('demo')
        self.assertEqual(self.request('/api/geo/draft',dict(payload,confirmed=False),user='ops-test')[0],400)
        status,result=self.request('/api/geo/draft',payload,user='ops-test')
        self.assertEqual(status,200,result)
        self.assertEqual(f.m.read_spec('demo'),original)
        current=f.m.read_draft('demo')['pages'][0]
        self.assertEqual(len(current['sections']),len(page['sections'])+1)
        self.assertNotIn('<script>',current['sections'][-1]['html'])
        self.assertEqual(self.request('/api/geo/draft',dict(payload,revision=3),user='ops-test')[0],409)
        proposal['page_version']=f.m.kf_design_profiles.fingerprint(current)
        data=store.append('proposals',proposal,3,'ops-test')
        ident=data['proposals'][-1]['id']
        data=store.save_item('facts',{'revision':4,'item':dict(fact,approved=False)},'ops-test')
        self.assertEqual(self.request('/api/geo/draft',dict(payload,id=ident,revision=5),user='ops-test')[0],409)

    def test_geo_prompt_seeding_preserves_existing_versions_and_edits(self):
        store=self.fixture.m.kf_prompts.PromptStore(self.fixture.base)
        original=store.read()
        seeded=store.geo_modules()
        self.assertEqual(len(seeded['modules']),6)
        self.assertEqual(store.geo_modules()['revision'],seeded['revision'])
        current=store.read()
        self.assertEqual(current['modules'][:len(original['modules'])],original['modules'])
        module=seeded['modules'][0]
        store.change(dict(module,kind='modules',revision=seeded['revision'],body='Operator custom guidance'))
        self.assertEqual(store.geo_modules()['modules'][0]['body'],'Operator custom guidance')


if __name__=='__main__': unittest.main()
