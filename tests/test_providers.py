import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from kf_ai import AIError
from kf_providers import ProviderStore,bind_mail,mail_config,CATALOG
import kf_cloud_dns as dns
import kf_cloud_api as api

class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=ProviderStore(self.tmp.name)
    def account(self,provider='namecom',values=None,caps=None):
        return self.store.save({'id':'test-account','provider':provider,'name':'Test','sites':['demo'],'capabilities':caps or ['dns'],'enabled':True,'values':values or {'username':'test-user','token':'private-token'}},'admin')
    def test_encryption_scope_and_revocation(self):
        item=self.account();self.assertNotIn('private-token',json.dumps(item));self.assertNotIn('private-token',self.store.path.read_text())
        self.assertEqual(self.store.resolve(item['id'],'demo','dns')[1]['token'],'private-token')
        for slug,cap in [('other','dns'),('demo','mail')]:
            with self.assertRaises(AIError):self.store.resolve(item['id'],slug,cap)
        self.store.save({'action':'delete','id':item['id'],'version':item['version']},'admin')
        with self.assertRaises(AIError):self.store.resolve(item['id'],'demo','dns')
    def test_cldy_mail_binding_and_endpoint_change(self):
        values={'host':'mail.example.com','port':'465','user':'me@example.com','password':'private-pass','sender':'me@example.com'}
        item=self.account('cldy',values,['mail']);bind_mail(self.tmp.name,{'slug':'demo','account_id':item['id']})
        c=mail_config(self.tmp.name,'demo',lambda:{});self.assertEqual((c['provider'],c['port'],c['pass']),('smtp',465,'private-pass'))
        edit={**item,'values':{'host':'new.example.com'}}
        with self.assertRaisesRegex(AIError,'重新填写密码'):self.store.save(edit,'admin')
        edit['values']['password']='replacement';self.store.save(edit,'admin')
        self.assertEqual(mail_config(self.tmp.name,'demo',lambda:{})['host'],'new.example.com')
        self.assertEqual(CATALOG['cldy']['capabilities'],['mail'])
    def test_name_api_fixed_host_basic_auth(self):
        with patch.object(api,'request',return_value={}) as req:
            api.namecom({'username':'user','token':'token'},'/domains/example.com/records','POST',{'type':'A'})
        self.assertEqual(req.call_args.args[0],'https://api.name.com/core/v1/domains/example.com/records')
        self.assertEqual(req.call_args.args[3],{'Authorization':'Basic dXNlcjp0b2tlbg=='})
        with self.assertRaises(AIError):api.namecom({},'https://evil.example/')
    def name_records(self):
        return [{'id':1,'host':'','type':'MX','answer':'mail.example.com','priority':10,'ttl':300},
                {'id':2,'host':'_sip._tcp','type':'SRV','answer':'5 5060 sip.example.com','priority':20,'ttl':300},
                {'id':3,'host':'','type':'TXT','answer':'v=spf1 -all','ttl':300},
                {'id':4,'host':'www','type':'ANAME','answer':'example.com','ttl':300}]
    def test_name_records_roundtrip(self):
        with patch.object(dns,'namecom',side_effect=[{'domainName':'example.com','nameservers':['ns1.name.com']},{'records':self.name_records()}]):
            domain,ns,records=dns.list_records('namecom',{},'example.com')
        self.assertEqual(domain,'example.com');self.assertEqual(records[0]['name'],domain);self.assertEqual(records[0]['priority'],10)
        self.assertEqual(records[1]['content'],'20 5 5060 sip.example.com');self.assertEqual(records[2]['content'],'v=spf1 -all')
        with patch.object(dns,'namecom',return_value={'id':2}) as req:
            dns.apply('namecom',{},domain,records[1],records[1],records)
            self.assertEqual(req.call_args.args[2],'PUT');self.assertEqual(req.call_args.args[3]['priority'],20);self.assertEqual(req.call_args.args[3]['answer'],'5 5060 sip.example.com')
            dns.apply('namecom',{},domain,records[0],None,records);self.assertEqual(req.call_args.args[2],'DELETE')
        with self.assertRaises(AIError):dns.validate_change('namecom',records[3],None,records)
        with self.assertRaises(AIError):dns.validate_change('namecom',None,{**records[0],'ttl':60},records)
    def test_name_external_dns_and_incomplete_zone_rejected(self):
        with patch.object(dns,'namecom',return_value={'domainName':'example.com','nameservers':['ns.cloudflare.com']}) as req:
            with self.assertRaises(AIError):dns.list_records('namecom',{},'example.com')
            self.assertEqual(req.call_count,1)
        with patch.object(dns,'namecom',side_effect=[{'domainName':'example.com','nameservers':['ns1.name.com']},{'records':[],'nextPage':2}]):
            with self.assertRaises(AIError):dns.list_records('namecom',{},'example.com')
    def test_aws_recordset_preserves_peers_atomically(self):
        raw={'Name':'example.com.','Type':'A','TTL':300,'ResourceRecords':[{'Value':'1.1.1.1'},{'Value':'2.2.2.2'}]}
        records=[dns.record('example.com','A',v,300,raw,i) for i,v in enumerate(['1.1.1.1','2.2.2.2'])]
        with patch.object(dns,'aws_call',return_value={}) as req:
            dns.apply('aws',{},'Z123',records[0],{**records[0],'content':'3.3.3.3'},records)
        changes=req.call_args.kwargs['ChangeBatch']['Changes'];self.assertEqual(changes[0],{'Action':'DELETE','ResourceRecordSet':raw})
        self.assertEqual(changes[1]['ResourceRecordSet']['ResourceRecords'],[{'Value':'2.2.2.2'},{'Value':'3.3.3.3'}])
    def test_gcp_exact_old_set_and_azure_etag(self):
        raw={'name':'example.com.','type':'TXT','ttl':300,'rrdatas':['"hello" " world"'],'kind':'dns#resourceRecordSet'}
        record=dns.record('example.com','TXT',raw['rrdatas'][0],300,raw,0)
        with patch.object(dns,'rest',return_value={}) as req:
            dns.apply('gcp',{'project_id':'project'},'zone',record,None,[record])
            self.assertEqual(req.call_args.args[4]['deletions'][0]['rrdatas'],raw['rrdatas']);self.assertNotIn('kind',req.call_args.args[4]['deletions'][0])
        raw={'type':'Microsoft.Network/dnsZones/A','name':'@','etag':'v1','properties':{'TTL':300,'ARecords':[{'ipv4Address':'1.1.1.1'}]}}
        record=dns.record('example.com','A','1.1.1.1',300,raw,0)
        with patch.object(dns,'rest',return_value={}) as req:
            dns.apply('azure',{'subscription_id':'sub','resource_group':'rg'},'example.com',record,None,[record])
            self.assertEqual(req.call_args.kwargs['headers'],{'If-Match':'v1'})
    def test_recordset_unsupported_and_ttl_conflict(self):
        raw={'name':'example.com.','type':'MX','ttl':300,'routingPolicy':{}}
        with patch.object(dns,'rest',side_effect=[{'dnsName':'example.com.','nameServers':['ns.example.com']},{'rrsets':[raw]}]):
            _,_,records=dns.list_records('gcp',{'project_id':'project'},'zone')
        self.assertTrue(records[0]['_blocked'])
        with self.assertRaises(AIError):dns.validate_change('gcp',records[0],None,records)
        r={'id':'one','name':'example.com','type':'A','ttl':300,'proxied':False}
        with self.assertRaises(AIError):dns.validate_change('aws',None,{**r,'ttl':600},[r])

    def test_aliyun_and_tencent_record_contracts(self):
        r={'id':'123','name':'mail.example.com','type':'MX','content':'mx.example.com','priority':20,'ttl':600,'proxied':False}
        for provider in ('aliyun','tencent'):
            with self.subTest(provider=provider),patch.object(dns,provider,return_value={'RecordId':123}) as req:
                self.assertEqual(dns.apply(provider,{},'example.com',None,r,[]),'123')
                params=req.call_args.args[2];self.assertEqual(params['TTL'],600)
                self.assertEqual(params['Priority' if provider=='aliyun' else 'MX'],20)
                dns.apply(provider,{},'example.com',r,None,[r]);self.assertIn('Delete',req.call_args.args[1])
    def test_ses_single_attempt_and_accepted_not_delivered(self):
        import kf_mail
        with patch.object(api,'aws_call',return_value={'MessageId':'message-1'}) as req:
            receipt=kf_mail.send('to@example.com','Subject','Body',{'provider':'ses','from':'from@example.com'})
            self.assertEqual(req.call_count,1);self.assertIsNone(receipt['delivered']);self.assertEqual(receipt['provider_id'],'message-1')
        with patch.object(api,'aws_call',side_effect=AIError('timeout')) as req:
            with self.assertRaises(AIError):kf_mail.send('to@example.com','Subject','Body',{'provider':'ses','from':'from@example.com'})
            self.assertEqual(req.call_count,1)
    def test_mcp_credentials_stay_on_official_endpoints(self):
        signer=api.MCPAuth('cloudflare',{'token':'secret'},1)
        with self.assertRaises(AIError):signer.headers('https://example.com/mcp',b'{}',{})
        self.assertEqual(signer.headers('https://mcp.cloudflare.com/mcp',b'{}',{})['Authorization'],'Bearer secret')
        signer=api.MCPAuth('aws',{'auth':'keys','region':'ap-southeast-1','access_key':'AKIDEXAMPLE','secret_key':'test-secret'},2)
        with self.assertRaises(AIError):signer.headers('https://example.com/mcp',b'{}',{})
        headers=signer.headers('https://aws-mcp.ap-southeast-1.api.aws/mcp',b'{}',{'Content-Type':'application/json'})
        self.assertIn('/ap-southeast-1/aws-mcp/aws4_request',headers['Authorization'])

if __name__=='__main__':unittest.main()
