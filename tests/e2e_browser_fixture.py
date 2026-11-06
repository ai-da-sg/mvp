"""Real application HTTP server with disposable account/data files; no mocked handlers."""
import json
import os
from pathlib import Path
import sys
from test_ai import ConsoleTests

fixture = ConsoleTests()
fixture.setUp()
m = fixture.m
try:
    (m.CONSOLE / 'providers.js').symlink_to(Path(__file__).resolve().parents[1] / 'console/providers.js')
    if os.environ.get('KF_E2E_DOMAIN') == '1':
        # Register a domain for UI coverage; no upstream service is contacted.
        meta_path = fixture.base / 'sites/demo/meta.json'
        meta = json.loads(meta_path.read_text())
        meta['port'] = 9
        meta_path.write_text(json.dumps(meta))
    users = m.load_users()
    users['mfa-test'] = dict(users['ops-test'], mfa_secret='JBSWY3DPEHPK3PXP')
    m._write(m.USERS_F, users)
    if os.environ.get('KF_E2E_OPERATIONS') == '1':
        store = m.ai_store()
        job = store.create_job('demo', store.resolve('mock')[0], 'ops-test', 'existing')
        store.update_job(job['id'], status='failed', message='Private generation details')
    if os.environ.get('KF_E2E_PUBLICATION') == '1':
        # The fixture has no WordPress service; use its explicit in-memory
        # transport while exercising the real publication journal and HTTP UI.
        import kf_ai
        draft = json.loads(json.dumps(fixture.original))
        draft['pages'][0]['title'] = 'Publication recovery fixture'
        kf_ai.atomic_json(m.SITES / 'demo' / 'site-draft.json', draft)
        code, result = m.publish_site({'slug': 'demo'}, lambda *a, **kw: {'ok': True}, 'admin')
        assert code == 200, result
    # Deliberately provide no preauthenticated cookie: tests must log in through the UI.
    print(json.dumps({'origin': 'http://127.0.0.1:' + str(fixture.server.server_port),
                      'password': 'Test-Password-123'}), flush=True)
    sys.stdin.readline()
finally:
    fixture.tearDown()
