"""Opt-in enquiry read proof against an authorized test WordPress instance.

Creates one private test enquiry, verifies paged/id reads and separate follow-up
storage, then permanently removes only that test enquiry and verifies cleanup.
"""
import argparse
import base64
import json
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
from kf_sections import wp
from kf_leads import read_page, Followups

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--site', required=True)
parser.add_argument('--allow-test-writes', action='store_true')
args = parser.parse_args()
if not args.allow_test_writes:
    parser.error('Use --allow-test-writes only for an authorized test site')
site = str(Path(args.site).resolve())


def evaluate(code):
    result = wp(site, 'eval', code, timeout=45)
    assert result.returncode == 0, 'WordPress proof command failed'
    return json.loads(result.stdout)


title = 'enquiry-proof-' + uuid.uuid4().hex
payload = base64.b64encode(json.dumps({'post_type': 'kf_lead', 'post_status': 'private',
    'post_title': title, 'post_content': 'Authorized enquiry integration proof'}).encode()).decode()
ident = None
try:
    ident = evaluate("$id=wp_insert_post(json_decode(base64_decode('" + payload + "'),true));echo wp_json_encode($id);")
    assert type(ident) is int and ident > 0
    original = read_page(site, lead_id=ident)['items'][0]
    assert original['title'] == title
    assert any(x['id'] == ident for x in read_page(site)['items'])
    with tempfile.TemporaryDirectory() as base:
        store = Followups(base, Path(site).name)
        store.save(ident, 'contacted', 'Local proof note', 0, 'integration-test')
        assert store.all()[str(ident)]['status'] == 'contacted'
        assert read_page(site, lead_id=ident)['items'][0] == original
finally:
    if type(ident) is int and ident > 0:
        evaluate('wp_delete_post('+str(ident)+',true);echo "true";')
        assert read_page(site, lead_id=ident)['items'] == [], 'Test enquiry cleanup failed'
print(json.dumps({'wordpress_paged_and_id_reads': 'passed', 'original_message_preserved': 'passed',
                  'separate_followup_persistence': 'passed', 'test_enquiry_cleanup': 'passed'}))
