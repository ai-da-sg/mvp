import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import kf_health as health
import kf_mail as mail
import kf_dns_provider as provider
from kf_ai import AIError
from kf_tool_runtime import ActionConflict

class OperationsTests(unittest.TestCase):
    def test_health_distinguishes_missing_and_unknown(self):
        def lookup(name,kind):
            data={('example.test','NS'):['a.ns.cloudflare.com.','b.ns.cloudflare.com.'],('example.test','A'):['93.184.216.34'],
                  ('example.test','TXT'):['v=spf1 +all','v=spf1 -all'],('_dmarc.example.test','TXT'):['v=DMARC1; p=reject'],
                  ('mail._domainkey.example.test','TXT'):['v=DKIM1; p=abc']}
            if kind=='MX':return {'state':'unknown','values':[]}
            values=data.get((name,kind),[]);return {'state':'ok' if values else 'missing','values':values}
        report=health.diagnose('example.test',['mail'],lookup)
        checks={c['name']:c for c in report['checks']}
        self.assertEqual(checks['SPF']['status'],'fail');self.assertIn('未知',checks['邮件 MX']['detail'])
        self.assertEqual(checks['DKIM / mail']['status'],'ok');self.assertEqual(report['authority']['provider'],'cloudflare')
        report=health.diagnose('example.test',[],lookup);self.assertIn('选择器',next(c for c in report['checks'] if c['name']=='DKIM')['detail'])
    def test_mail_no_retry_and_header_injection(self):
        with self.assertRaises(AIError):mail.message({'to':'a@example.test\nBcc: x@evil.test','subject':'X','body':'X'})
        with self.assertRaises(AIError):mail.message({'to':'a@example.test','subject':'x\r\nBcc: y','body':'X'})
        opener=Mock();opener.open.side_effect=TimeoutError('acceptance unknown')
        with patch.object(mail.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(TimeoutError):mail.send('a@example.test','Subject','Body',{'provider':'resend','from':'sender@example.test','api_key':'secret'})
        self.assertEqual(opener.open.call_count,1)
        conn=Mock();conn.send_message.return_value={}
        with patch.object(mail.smtplib,'SMTP',return_value=conn):
            receipt=mail.send('a@example.test','Subject','Body',{'host':'smtp.example.test','from':'sender@example.test','tls':True})
        self.assertEqual(receipt['state'],'accepted');self.assertIsNone(receipt['delivered']);conn.send_message.assert_called_once();conn.starttls.assert_called_once()
    def test_delivery_status_is_provider_evidence_and_never_resends(self):
        smtp={'provider':'resend','api_key':'fixture-key'};receipt={'provider':'resend','provider_id':'message-123'}
        response=Mock();response.read.return_value=b'{"id":"message-123","last_event":"delivered","text":"private body"}'
        opener=MagicMock();opener.open.return_value.__enter__.return_value=response
        with patch.object(mail.urllib.request,'build_opener',return_value=opener):
            result=mail.delivery_status(receipt,smtp,'client@example.test')
        self.assertTrue(result['delivered']);self.assertNotIn('private body',str(result));self.assertEqual(opener.open.call_args[0][0].get_method(),'GET')
        result=mail.delivery_status({'provider':'smtp','message_id':'fixture'}, {},'client@example.test');self.assertIsNone(result['delivered'])

    def test_dns_authority_record_scope_and_optimistic_change(self):
        with tempfile.TemporaryDirectory() as base:
            local=Mock();store=provider.DNSProviders(base,local);ctx={'slug':'demo','domain':'site.example.test'}
            cfg=store.configure({'provider':'cloudflare','zone_id':'a'*32,'token':'dns-token'},ctx)
            self.assertNotIn('dns-token',store.path.read_text());self.assertTrue(cfg['has_token'])
            records=[{'id':'b'*32,'name':'site.example.test','type':'A','content':'93.184.216.34','ttl':300,'proxied':False}]
            auth={'state':'ok','zone':'example.test','nameservers':['a.ns.cloudflare.com','b.ns.cloudflare.com'],'provider':'cloudflare'}
            calls=[]
            def api(token,zone,method='GET',suffix='',body=None):
                calls.append((method,suffix,body))
                if suffix=='':return {'result':{'name':'example.test','name_servers':auth['nameservers']}}
                if method=='GET':return {'result':copy.deepcopy(records),'result_info':{'total_pages':1}}
                return {'result':{'id':'b'*32}}
            with patch.object(provider,'cloudflare',side_effect=api),patch.object(provider,'authority',return_value=auth),patch.object(provider,'query',return_value={'state':'ok','values':['93.184.216.35']}):
                plan=store.plan({'operation':'update','record_id':'b'*32,'record':{'name':'@','type':'A','content':'93.184.216.35'}},ctx)
                self.assertEqual(plan['mode'],'totp');self.assertEqual(plan['arguments']['before']['content'],'93.184.216.34')
                ticket={'arguments':plan['arguments'],'snapshot':plan['snapshot']};result=store.apply(ticket,ctx)
                self.assertTrue(result['applied']);self.assertEqual(sum(c[0]=='PATCH' for c in calls),1)
                records[0]['content']='93.184.216.35'
                with patch.object(provider,'authoritative_query',return_value={'state':'unknown','values':[]}):
                    self.assertFalse(store.verify(ticket,ctx)['ok'])
                with patch.object(provider,'authoritative_query',return_value={'state':'ok','values':['93.184.216.35']}):
                    self.assertTrue(store.verify(ticket,ctx)['ok'])
                records[0]['content']='93.184.216.36'
                with self.assertRaises(ActionConflict):store.apply(ticket,ctx)
                with patch.object(provider,'authority',return_value={**auth,'nameservers':['other.example.test']}):
                    with self.assertRaises(AIError):store.plan({'operation':'add','record':{'content':'93.184.216.34'}},ctx)
                self.assertEqual(sum(c[0]=='PATCH' for c in calls),1)
            with self.assertRaises(AIError):provider.normalize_record({'name':'@','type':'A','content':'not-an-ip'},ctx['domain'])

    def test_local_dns_txt_wire_and_atomic_updates(self):
        import kf_dns as local
        import dns.message
        with tempfile.TemporaryDirectory() as base,patch.object(local,'ZONES_F',Path(base)/'zones.json'):
            local.save_zones({'example.test':local.new_zone('example.test','93.184.216.34')})
            value='v=DKIM1; k=rsa; p='+'A'*400
            local.update_zones(lambda zones:zones['example.test']['records'].append({'name':'mail._domainkey','type':'TXT','ttl':300,'value':value}))
            result=local.answer(dns.message.make_query('mail._domainkey.example.test','TXT'))
            self.assertEqual(b''.join(result.answer[0][0].strings).decode(),value)
            detached=local.load_zones();detached.clear();self.assertIn('example.test',local.load_zones())
            self.assertEqual(local.ZONES_F.stat().st_mode&0o777,0o600)
