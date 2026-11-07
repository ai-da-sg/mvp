import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from kf_inflow import InflowStore, MANAGED_URL
from kf_ai import AIError
from kf_domain_vault import VaultConflict

class InflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.calls=[];self.remote={}
        self.store=InflowStore(self.tmp.name,self.transport)
        self.configure()
    def tearDown(self):self.tmp.cleanup()
    def transport(self,url,key,method,path,body=None,headers=None):
        self.calls.append((url,key,method,path,body,headers))
        value={}
        if '/goals' in path:value={'data':[{'id':'11111111-1111-4111-8111-111111111111','name':'MVP enquiry submitted','parameters':{'type':'event','value':'enquiry_submitted'}}]}
        elif method=='POST' and path=='/api/websites':self.remote[body['id']]=body;value=body
        elif path.startswith('/api/websites?'):value={'data':list(self.remote.values())}
        elif path.startswith('/api/websites/'):
            value=self.remote.get(path.split('/')[-1])
            if not value:raise AIError('GEOInflow returned HTTP 404; not found')
        elif '/page-report?' in path:value={'contractVersion':2,'website':{'id':path.split('/')[4]},'states':{'logs':'not_connected'},'cards':[],'tables':{},'range':{},'secret':'private'}
        return 200,json.dumps(value).encode(),'application/json'
    def configure(self):
        self.store.save({'revision':0,'url':MANAGED_URL,'token':'umami_private_key','enabled':True},'admin')
        self.store.test(1)
    def bind(self):return self.store.bind('demo','example.test','Demo',{'revision':self.store.public()['revision']},'admin')
    def test_encrypted_credential_and_version_guard(self):
        self.assertNotIn('umami_private_key',self.store.path.read_text())
        self.assertNotIn('secret',self.store.public()['connection'])
        with self.assertRaises(VaultConflict):self.store.save({'revision':0},'admin')
        with self.assertRaises(AIError):self.store.save({'revision':2,'url':'http://169.254.169.254','token':'umami_x'},'admin')
    def test_scoped_bind_duplicate_domain_and_uncertain_retry(self):
        b=self.bind();self.assertEqual(b['status'],'ready')
        with self.assertRaises(AIError):self.store.bind('other','example.test','Other',{'revision':4,'website_id':b['website_id']},'admin')
        with self.assertRaises(AIError):self.store.binding('demo','changed.test')
        r=self.store.report('demo','example.test','human/sources',7);self.assertNotIn('secret',r)
        with self.assertRaises(AIError):self.store.report('demo','example.test','../users',7)
        with self.assertRaises(AIError):self.store.report('demo','example.test','human/sources',True)
    def test_unknown_create_result_reuses_uuid(self):
        original=self.store.transport;failed=[False]
        def transport(*args,**kwargs):
            result=original(*args,**kwargs)
            if args[2:4]==('POST','/api/websites') and not failed[0]:failed[0]=True;raise AIError('Timeout')
            return result
        self.store.transport=transport
        with self.assertRaises(AIError):self.bind()
        b=self.bind();self.assertEqual(b['status'],'ready');self.assertEqual(len(self.remote),1)
    def test_tracking_installation_failure_does_not_claim_enabled(self):
        self.bind()
        with self.assertRaises(AIError):self.store.tracking('demo','example.test','/site','https://mvp.example.test',4,True,runner=lambda *a,**k:SimpleNamespace(returncode=1,stdout=''))
        self.assertFalse(self.store.binding('demo','example.test')['tracking'])
        self.store.tracking('demo','example.test','/site','https://mvp.example.test',4,True,runner=lambda *a,**k:SimpleNamespace(returncode=0,stdout='ok'))
        with self.assertRaises(AIError):self.store.disconnect('demo',5)
        disabled=self.store.tracking('demo','changed.test','/site','https://mvp.example.test',5,False,runner=lambda *a,**k:SimpleNamespace(returncode=0,stdout='ok'))
        self.assertFalse(disabled['tracking'])
        self.assertEqual(disabled['status'],'domain_changed')
        self.store.disconnect('demo',6)
        self.assertIsNone(self.store.binding('demo','changed.test',require=False))
    def test_public_collection_cannot_forge_identity_or_cross_sites(self):
        b=self.bind()
        self.store.tracking('demo','example.test','/site','https://mvp.example.test',4,True,runner=lambda *a,**k:SimpleNamespace(returncode=0,stdout='ok'))
        body={'type':'event','payload':{'website':b['website_id'],'ip':'1.1.1.1','userAgent':'fake','data':{'password':'no'},'webdriver':True,'eventId':b['website_id'],'url':'/home','name':'enquiry_submitted'}}
        self.store.collect(body,'https://example.test',{'demo':'example.test'},'192.0.2.1','browser','cache-token')
        url,key,_,_,sent,headers=self.calls[-1]
        self.assertEqual(key,'');self.assertNotIn('ip',sent['payload']);self.assertNotIn('data',sent['payload']);self.assertTrue(sent['payload']['webdriver']);self.assertEqual(headers['X-MVP-Client-IP'],'192.0.2.1')
        for source,sites in [('https://other.test',{'demo':'example.test'}),('https://example.test',{})]:
            with self.assertRaises(AIError):self.store.collect(body,source,sites,'','')
        body['payload']['url']='https://other.test/'
        with self.assertRaises(AIError):self.store.collect(body,'https://example.test',{'demo':'example.test'},'','')
    def test_import_limits_and_corrupt_state_fail_closed(self):
        self.bind()
        with self.assertRaises(AIError):self.store.import_data('demo','example.test','logs',{'format':'json','content':'x'*256001})
        self.store.path.write_text('{')
        with self.assertRaises(AIError):self.store.public()

if __name__=='__main__':unittest.main()
