import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from kf_ai import AIError
from kf_tool_runtime import ActionConflict
from kf_providers import ProviderStore,test_account
from kf_dns_provider import DNSProviders
import kf_cloud_dns as dns
import kf_sg_dns as sdns
import kf_sg_providers as sg

class SingaporeProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=ProviderStore(self.tmp.name);sg._CACHE.clear()
        self.cpanel={'endpoint':'https://panel.example.com:2083','username':'demo','token':'private-token'}
        self.webnic={'environment':'production','username':'api-demo','password':'private-secret'}
    def account(self,provider,values,caps):
        return self.store.save({'id':'sg-account','name':'SG','provider':provider,'enabled':True,'sites':['demo'],'capabilities':caps,'values':values},'admin')
    def test_credentials_endpoint_binding_and_environment(self):
        item=self.account('cpanel',self.cpanel,['dns','cloud'])
        self.assertNotIn('private-token',self.store.path.read_text())
        with self.assertRaises(AIError):self.store.save({**item,'values':{'endpoint':'https://other.example.com:2083'}},'admin')
        saved=self.store.save({**item,'values':{'endpoint':'https://other.example.com:2083','token':'replacement'}},'admin')
        self.assertEqual(saved['version'],2)
        for url in ['http://panel.example.com:2083','https://user:pass@example.com','https://panel.example.com/path','https://panel.example.com:8080','https://panel.example.com/#x']:
            with self.subTest(url=url),self.assertRaises(AIError):sg.cpanel_endpoint(url)
    def test_webnic_rotation_and_ote_dns_binding(self):
        item=self.account('webnic',self.webnic,['dns'])
        with self.assertRaises(AIError):self.store.save({**item,'values':{'environment':'ote'}},'admin')
        self.store.save({**item,'values':{**self.webnic,'environment':'ote'}},'admin')
        with self.assertRaises(AIError):DNSProviders(self.tmp.name,Mock()).configure({'provider':'webnic','zone_id':'example.com','account_id':item['id']},{'slug':'demo','domain':'example.com'})
    def test_webnic_token_cache_and_provider_error_no_retry(self):
        responses=[{'code':'1000','data':{'access_token':'opaque-token','expires_in':3600}},{'code':'1000','data':['ns1.web.cc']},{'code':'1000','data':[]},{'code':'2400','message':'private-secret'}]
        with patch.object(sg,'request',side_effect=responses) as request:
            sg.webnic(self.webnic,'/dns/v2/zone/basic/record/nameservers')
            sg.webnic(self.webnic,'/dns/v2/zone/basic/record/nameservers')
            with self.assertRaises(AIError) as err:sg.webnic(self.webnic,'/dns/v2/zone/example.com/record','POST',{})
            self.assertNotIn('private-secret',str(err.exception));self.assertEqual(request.call_count,4)
            self.assertEqual(request.call_args_list[0].args[0],'https://api.webnic.cc/reseller/v2/api-user/token')
            self.assertEqual(request.call_args_list[1].args[3],{'Authorization':'Bearer opaque-token'})
    def cpanel_rows(self,serial=10):
        encode=lambda s:base64.b64encode(s.encode()).decode()
        def row(index,name,kind,values):return {'type':'record','line_index':index,'dname_b64':encode(name),'record_type':kind,'ttl':300,'data_b64':[encode(v) for v in values]}
        return [row(0,'example.com.','SOA',['ns1.example.com.','hostmaster.example.com.',str(serial),'3600','600','604800','300']),row(2,'example.com.','NS',['ns1.example.com.']),row(5,'www','A',['1.1.1.1']),row(7,'example.com.','TXT',['hello ','world'])]
    def test_cpanel_parse_and_serial_edit(self):
        with patch.object(sdns,'cpanel',return_value=self.cpanel_rows()):zone,ns,records=dns.list_records('cpanel',self.cpanel,'example.com')
        self.assertEqual(ns,['ns1.example.com']);self.assertEqual(records[-1]['content'],'hello world')
        old=records[1];new={**old,'content':'2.2.2.2'}
        with patch.object(sdns,'cpanel',return_value={'new_serial':11}) as call:
            self.assertEqual(dns.apply('cpanel',{**self.cpanel,'_zone_revision':10},zone,old,new,records),'11')
        params=call.call_args.args[3];self.assertEqual(params['serial'],10);payload=json.loads(params['edit']);self.assertEqual(payload['line_index'],5);self.assertEqual(payload['dname'],'www.example.com.');self.assertEqual(payload['data'],['2.2.2.2'])
    def test_cpanel_long_txt_split_and_delete(self):
        new={'name':'test.example.com','type':'TXT','content':'界'*200,'ttl':300,'proxied':False}
        with patch.object(sdns,'cpanel',return_value={'new_serial':11}) as call:
            dns.apply('cpanel',{'_zone_revision':10},'example.com',None,new,[])
            data=json.loads(call.call_args.args[3]['add'])['data'];self.assertEqual(''.join(data),new['content']);self.assertTrue(all(len(x.encode())<=255 for x in data))
            dns.apply('cpanel',{'_zone_revision':10},'example.com',{**new,'id':'7'},None,[]);self.assertEqual(call.call_args.args[3]['remove'],7)
        with self.assertRaises(AIError):dns.apply('cpanel',{},'example.com',None,new,[])
    def test_cpanel_bad_encoding_and_serial_fail_closed(self):
        for rows in [self.cpanel_rows()[1:],[{**self.cpanel_rows()[0],'dname_b64':'bad-base64'}]]:
            with patch.object(sdns,'cpanel',return_value=rows),self.assertRaises(AIError):dns.list_records('cpanel',{},'example.com')
    def test_cpanel_blocks_private_address_before_credentials_sent(self):
        with patch.object(sg.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',2083))]),patch.object(sg.socket,'create_connection') as connect:
            with self.assertRaises(AIError):sg.cpanel(self.cpanel,'DomainInfo','list_domains')
            connect.assert_not_called()
    def test_cpanel_pins_tls_host_and_rejects_redirect(self):
        conn=Mock();response=Mock();response.status=200;response.getheader.return_value='identity';response.read1.side_effect=[b'{"result":{"status":1,"data":{"main_domain":"example.com"}}}',b''];conn.getresponse.return_value=response
        tls=Mock();tls.wrap_socket.return_value=Mock()
        with patch.object(sg,'public_addresses',return_value=['93.184.216.34']),patch.object(sg.http.client,'HTTPConnection',return_value=conn),patch.object(sg.socket,'create_connection') as connect,patch.object(sg.ssl,'create_default_context',return_value=tls):
            self.assertEqual(sg.cpanel(self.cpanel,'DomainInfo','list_domains')['main_domain'],'example.com')
            self.assertEqual(connect.call_args.args[0],('93.184.216.34',2083));self.assertEqual(tls.wrap_socket.call_args.kwargs['server_hostname'],'panel.example.com')
            response.status=302
            with self.assertRaises(AIError):sg.cpanel(self.cpanel,'DomainInfo','list_domains')
            self.assertEqual(conn.request.call_count,2)
    def test_cpanel_post_form_and_failure_not_retried(self):
        conn=Mock();response=Mock();response.status=200;response.getheader.return_value='identity';response.read1.side_effect=[b'{"result":{"status":0,"errors":["private-token"]}}',b''];conn.getresponse.return_value=response
        with patch.object(sg,'public_addresses',return_value=['93.184.216.34']),patch.object(sg.http.client,'HTTPConnection',return_value=conn),patch.object(sg.socket,'create_connection'),patch.object(sg.ssl,'create_default_context'):
            with self.assertRaises(AIError) as err:sg.cpanel(self.cpanel,'DNS','mass_edit_zone',{'zone':'example.com','serial':10,'remove':7})
            self.assertNotIn('private-token',str(err.exception));self.assertEqual(conn.request.call_count,1);self.assertEqual(conn.request.call_args.args[0],'POST');self.assertIn(b'serial=10',conn.request.call_args.args[2])
    def test_cpanel_changed_root_serial_invalidates_subdomain_plan(self):
        account=self.account('cpanel',self.cpanel,['dns']);store=DNSProviders(self.tmp.name,Mock());ctx={'slug':'demo','domain':'new.example.com'}
        store.configure({'provider':'cpanel','zone_id':'example.com','account_id':account['id']},ctx)
        auth={'state':'ok','zone':'example.com','nameservers':['ns1.example.com'],'provider':'unknown'}
        args={'operation':'add','record':{'name':'www','type':'A','content':'1.1.1.1','ttl':300}}
        with patch('kf_dns_provider.authority',return_value=auth),patch.object(sdns,'cpanel',return_value=self.cpanel_rows()):ticket=store.plan(args,ctx)
        self.assertEqual(ticket['snapshot']['zone_revision'],10)
        with patch('kf_dns_provider.authority',return_value=auth),patch.object(sdns,'cpanel',return_value=self.cpanel_rows(11)) as call:
            with self.assertRaises(ActionConflict):store.apply(ticket,ctx)
            self.assertEqual(call.call_count,1)
    def test_webnic_preserves_rrset_and_rejects_complex_metadata(self):
        raw={'name':'@','type':'MX','ttl':300,'rdatas':[{'value':'10 first.example.com','attributes':{}},{'value':'20 second.example.com','attributes':{}}]}
        with patch.object(sdns,'webnic',side_effect=[{'sourceFrom':'basic','records':[raw]},['ns1.web.cc']]):zone,ns,records=dns.list_records('webnic',self.webnic,'example.com')
        with patch.object(sdns,'webnic',return_value={}) as call:
            dns.apply('webnic',self.webnic,zone,records[0],None,records)
            body=call.call_args.args[3];self.assertEqual(body['rdatas'],[raw['rdatas'][1]]);self.assertEqual(call.call_args.args[2],'POST')
            dns.apply('webnic',self.webnic,zone,records[1],None,[records[1]]);self.assertEqual(call.call_args.args[2],'DELETE');self.assertIn('name=%40',call.call_args.args[1])
        with self.assertRaises(AIError):dns.validate_change('webnic',records[0],{**records[0],'ttl':600},records)
        raw['rdatas'][0]['attributes']={'region':'sg'}
        with patch.object(sdns,'webnic',side_effect=[{'sourceFrom':'subscription','records':[raw]},['premium1.web.cc']]):_,_,records=dns.list_records('webnic',self.webnic,'example.com')
        with self.assertRaises(AIError):dns.validate_change('webnic',records[1],None,records)
    def test_webnic_malformed_service_and_zone_rejected(self):
        with patch.object(sdns,'webnic',return_value={'sourceFrom':'unknown','records':[]}):
            with self.assertRaises(AIError):dns.list_records('webnic',self.webnic,'example.com')
        for zone in ('../example.com','example..com','-example.com'):
            with self.assertRaises(AIError):dns.zone_key('webnic',zone)
    def soap(self,operation,inner):return ('<s:Envelope xmlns:s="'+sg.SOAP+'"><s:Body><'+operation+'Response><APIResponse>'+inner+'</APIResponse></'+operation+'Response></s:Body></s:Envelope>').encode()
    def test_vodien_soap_allowlist_and_secret_redaction(self):
        response=Mock();response.read.return_value=self.soap('GetDomainList','<DomainList><item><DomainName>example.com</DomainName><Status>Registered</Status></item></DomainList>')
        opener=MagicMock();opener.open.return_value.__enter__.return_value=response
        c={'environment':'production','reseller_id':'123','api_key':'private-api-key'}
        with patch.object(sg.urllib.request,'build_opener',return_value=opener):
            result=sg.inventory('vodien',c)
        self.assertEqual(result['items'][0]['name'],'example.com');self.assertNotIn('private-api-key',json.dumps(result))
        req=opener.open.call_args.args[0];self.assertEqual(req.full_url,'https://soap.secureapi.com.au/API-2.1');self.assertIn(b'GetDomainList',req.data);self.assertIn(b'<ResellerID>123</ResellerID>',req.data)
        with self.assertRaises(AIError):sg.vodien(c,'DomainDelete','example.com')
    def test_vodien_fault_and_xml_entities_rejected(self):
        c={'environment':'test','reseller_id':'123','api_key':'private-api-key'}
        for body in [b'<!DOCTYPE foo [<!ENTITY x "expanded">]><foo>&x;</foo>',self.soap('GetDomainList','<Errors><item>private-api-key</item></Errors>'),self.soap('DomainInfo','<DomainList/>')]:
            response=Mock();response.read.return_value=body;opener=MagicMock();opener.open.return_value.__enter__.return_value=response
            with patch.object(sg.urllib.request,'build_opener',return_value=opener),self.assertRaises(AIError) as err:sg.vodien(c,'GetDomainList')
            self.assertNotIn('private-api-key',str(err.exception));self.assertEqual(opener.open.call_count,1)
    def test_vodien_domain_details_never_expose_transfer_key(self):
        import xml.etree.ElementTree as ET
        listing=ET.fromstring('<x><DomainList><item><DomainName>example.com</DomainName><Status>Registered</Status></item></DomainList></x>')
        detail=ET.fromstring('<x><DomainDetails><DomainName>example.com</DomainName><Expiry>2027-01-01</Expiry><AuthKey>transfer-secret</AuthKey><LockStatus>Locked</LockStatus></DomainDetails></x>')
        with patch.object(sg,'vodien',side_effect=[listing,detail]):result=sg.inventory('vodien',{},'example.com')
        self.assertEqual(result['items'][0]['expires'],'2027-01-01');self.assertNotIn('transfer-secret',json.dumps(result))
    def test_readyspace_inventory_projects_only_safe_fields(self):
        responses=[{'domains':[{'id':1,'name':'example.com','expires':'2027-01-01','password':'private'}]},{'services':[{'id':2,'domain':'example.com','category':'Hosting','next_due':'2026-12-01','password':'private','username':'private'}]}]
        with patch.object(sg,'request',side_effect=responses) as call:result=sg.inventory('readyspace',{'auth':'bearer','token':'private-token'})
        self.assertEqual(result['items'][0]['expires'],'2027-01-01');self.assertEqual(result['items'][1]['expires'],'2026-12-01');self.assertNotIn('private',json.dumps(result));self.assertEqual(call.call_count,2)
        self.assertEqual(call.call_args.kwargs['headers'],{'Authorization':'Bearer private-token'})
        with self.assertRaises(AIError):sg.readyspace({},'/service/2/cancel')
    def test_probe_scope_version_and_failure(self):
        item=self.account('cpanel',self.cpanel,['dns'])
        with patch.object(sg,'probe',return_value={'ok':True}) as probe:
            with self.assertRaises(AIError):test_account(self.tmp.name,{'id':item['id'],'version':0})
            probe.assert_not_called();self.assertTrue(test_account(self.tmp.name,{'id':item['id'],'version':1})['ok'])
        self.store.save({**item,'enabled':False,'values':{}},'admin')
        with self.assertRaises(AIError):test_account(self.tmp.name,{'id':item['id'],'version':2})

if __name__=='__main__':unittest.main()
