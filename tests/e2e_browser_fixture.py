"""Real application HTTP server with disposable account/data files; no mocked handlers."""
import json
from pathlib import Path
import sys
from test_ai import ConsoleTests

fixture = ConsoleTests()
fixture.setUp()
m = fixture.m
try:
    (m.CONSOLE / 'providers.js').symlink_to(Path(__file__).resolve().parents[1] / 'console/providers.js')
    users = m.load_users()
    users['mfa-test'] = dict(users['ops-test'], mfa_secret='JBSWY3DPEHPK3PXP')
    m._write(m.USERS_F, users)
    # Deliberately provide no preauthenticated cookie: tests must log in through the UI.
    print(json.dumps({'origin': 'http://127.0.0.1:' + str(fixture.server.server_port),
                      'password': 'Test-Password-123'}), flush=True)
    sys.stdin.readline()
finally:
    fixture.tearDown()
