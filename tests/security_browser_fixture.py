"""Loopback-only real HTTP fixture for security browser regression tests."""
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from test_ai import ConsoleTests, ai

fixture=ConsoleTests();fixture.setUp();m=fixture.m
# Avoid Docker/network health probes: this fixture has no deployed WordPress instance.
m.site_list=lambda:[{'slug':'demo','company':'Fixture','domain':'demo.example','state':'active','http':200,'running':2,'port':0,'owner':'admin','plan':'Test','days_left':30}]
(m.CONSOLE/'providers.js').symlink_to(Path(__file__).resolve().parents[1]/'console/providers.js')
m._write(m.SHARES_F,{'fixture-share':{'slug':'demo','active':True}})
root=fixture.base/'sites/demo/html'
(root/'wp-content/themes/kampong').mkdir(parents=True)
(root/'wp-content/themes/kampong/style.css').write_text('body{color:rgb(12,34,56)}')
# Simulates previously stored data, not just newly validated edits.
draft=fixture.original
draft['pages'][0]['sections']=[{'type':'rich','html':'<p id="safe">Safe preview</p><svg/onload=window.__unsafe=1></svg><a href="jav&#x61;script:window.__unsafe=2">bad</a>'}]
ai.atomic_json(fixture.base/'sites/demo/site-draft.json',draft)
class Sibling(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(b'<p>Sibling origin fixture</p>')
sibling=ThreadingHTTPServer(('127.0.0.1',0),Sibling)
threading.Thread(target=sibling.serve_forever,daemon=True).start()
try:
    print(json.dumps({'origin':'http://127.0.0.1:'+str(fixture.server.server_port),'sibling':'http://127.0.0.1:'+str(sibling.server_port),
        'cookie':fixture.cookies['admin'].split('=',1)[1]}),flush=True)
    sys.stdin.readline()
finally:
    sibling.shutdown();sibling.server_close();fixture.tearDown()
