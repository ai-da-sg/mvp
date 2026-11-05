import json
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import kf_mcp as m
from kf_ai import AIError
from kf_domain_vault import VaultConflict


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=m.MCPStore(self.tmp.name)
        self.body={'id':'example','name':'Example','url':'https://example.com/mcp','enabled':True,'token':'private-test-token'}
    def tearDown(self):self.tmp.cleanup()
    def test_vault_lifecycle_and_endpoint_binding(self):
        item=self.store.change(self.body,'admin');self.assertTrue(item['has_token'])
        self.assertNotIn('private-test-token',self.store.path.read_text());self.assertNotIn('secret',item)
        for f in (self.store.path,self.store.key_path):self.assertEqual(f.stat().st_mode&0o777,0o600)
        body=dict(self.body,version=1,token='');item=self.store.change(body,'admin');self.assertEqual(item['version'],2)
        with self.assertRaises(VaultConflict):self.store.change(body,'admin')
        with self.assertRaises(AIError):self.store.change(dict(body,version=2,url='https://other.example/mcp'),'admin')
        with patch.object(m,'discover',return_value={'tools':[{'name':'private-test-token'}]}) as call:
            result=self.store.test('example',2);self.assertEqual(result['tools'][0]['name'],'[REDACTED]');self.assertEqual(call.call_args[0][1],'private-test-token')
        item=self.store.change(dict(body,version=2,enabled=False),'admin')
        with self.assertRaises(AIError):self.store.test('example',3)
        self.store.change({'action':'delete','id':'example','version':3},'admin');self.assertEqual(self.store.public(),[])
    def test_validation_and_network_boundaries(self):
        for url in ('http://example.com/mcp','https://example.com:8443/mcp','https://example.com/mcp?token=x','https://u:p@example.com/mcp','https://[bad'):
            with self.assertRaises(AIError):self.store.change(dict(self.body,url=url),'admin')
        with self.assertRaises(AIError):self.store.change(dict(self.body,token='bad\nheader'),'admin')
        item=self.store.change(dict(self.body,url='https://127.0.0.1/mcp'),'admin')
        with self.assertRaises(AIError):self.store.test(item['id'],item['version'])
        self.store.key_path.unlink()
        with self.assertRaises(AIError):self.store.test(item['id'],item['version'])
        self.assertFalse(self.store.key_path.exists())
    def test_http_handshake_json_sse_pagination_and_redirect_rejection(self):
        calls=[];mode=['json']
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                b=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((b,dict(self.headers)))
                if mode[0]=='redirect':
                    self.send_response(302);self.send_header('Location','https://evil.example/');self.end_headers();return
                if b['method']=='notifications/initialized':self.send_response(202);self.end_headers();return
                if b['method']=='initialize':r={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'Fixture','version':'1'}}
                else:r={'tools':[{'name':'search','description':'Read-only discovery'}],**({'nextCursor':'page2'} if not b['params'].get('cursor') else {})}
                data=json.dumps({'jsonrpc':'2.0','id':b['id'],'result':r}).encode()
                if mode[0]=='sse':data=b'event: message\r\ndata: '+data+b'\r\n\r\n'
                self.send_response(200);self.send_header('Content-Type','text/event-stream' if mode[0]=='sse' else 'application/json');self.send_header('Mcp-Session-Id','fixture-session');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        connect=socket.create_connection
        ctx=Mock();ctx.wrap_socket.side_effect=lambda sock,**kwargs:sock
        try:
            with patch.object(m,'public_addresses',return_value=['127.0.0.1']),patch.object(m.socket,'create_connection',side_effect=lambda addr,**kw:connect(('127.0.0.1',server.server_port),**kw)),patch.object(m.ssl,'create_default_context',return_value=ctx):
                for fmt in ('json','sse'):
                    mode[0]=fmt;calls.clear();out=m.discover(self.body,'private-test-token')
                    self.assertEqual(len(out['tools']),2);self.assertEqual([b['method'] for b,h in calls],['initialize','notifications/initialized','tools/list','tools/list'])
                    self.assertEqual(calls[2][1]['MCP-Protocol-Version'],'2025-06-18');self.assertEqual(calls[2][1]['Mcp-Session-Id'],'fixture-session')
                    self.assertEqual(calls[0][1]['Authorization'],'Bearer private-test-token')
                calls.clear();mode[0]='redirect'
                with self.assertRaises(AIError):m.discover(self.body,'private-test-token')
                self.assertEqual(len(calls),1)
        finally:server.shutdown();server.server_close()
