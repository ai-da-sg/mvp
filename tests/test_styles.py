import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import kf_styles as styles
from kf_ai import AIError

HTML = '''<html><head><title>Example studio</title><link rel="stylesheet" href="/theme.css"><style>
:root{--brand:#345678}body{background:#fafafa;font-family:Georgia,serif} .card{border-radius:24px;display:grid}
</style></head><body><div class="card"></div><h1>Studio</h1><h2>Our services</h2><img src="x"></body></html>'''

class StyleTests(unittest.TestCase):
    def test_extraction_and_persistent_template_lifecycle(self):
        result = styles.extract(HTML, ['.button{background:#345678}'], 'https://example.com/', [])
        self.assertEqual(result['tokens']['palette']['primary'], '#345678')
        self.assertEqual(result['tokens']['type']['heading'], 'serif')
        self.assertEqual(result['tokens']['shape']['radius'], '24px')
        self.assertIn('网格', result['evidence']['layouts'])
        with tempfile.TemporaryDirectory() as root:
            store = styles.StyleStore(root)
            item = store.change(dict(result, name='Studio', category='Technology'))
            snapshot = store.resolve(item['id'])
            updated = store.change(dict(item, name='Revised', enabled=False))
            self.assertEqual(updated['version'], 2)
            self.assertNotIn(item['id'], [t['id'] for t in store.public()['templates']])
            with self.assertRaises(styles.StyleConflict): store.change(item)
            with self.assertRaises(AIError): store.resolve(item['id'])
            copied = store.change(dict(updated, action='duplicate'))
            self.assertNotEqual(copied['id'], item['id'])
            self.assertEqual(copied['version'], 1)
            store.change(dict(updated, action='delete'))
            self.assertEqual(len(styles.StyleStore(root).public(True)['templates']), 29)
            self.assertEqual(snapshot['name'], 'Studio')
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)

    def test_local_catalog_delete_persistence_and_advanced_validation(self):
        with tempfile.TemporaryDirectory() as root:
            store = styles.StyleStore(root)
            originals = store.public(True)['templates']
            self.assertEqual(len(originals), 28)
            for item in originals:
                self.assertEqual(styles.normalize_tokens(item['tokens']), item['tokens'])
                self.assertIn('--kf-heading-size:', styles.advanced_css(item['tokens']))
                self.assertIn('blueprint', styles.guidance(item))
            item = originals[0]
            changed = store.change(dict(item, name='Locally edited', tags=['custom']))
            store.change(dict(originals[1], action='delete'))
            reloaded = styles.StyleStore(root)
            self.assertEqual(reloaded.resolve(changed['id'])['name'], 'Locally edited')
            self.assertNotIn(originals[1]['id'], [v['id'] for v in reloaded.public(True)['templates']])
            for bad in [{'columns':5}, {'content_width':float('inf')}, {'heading_size':True},
                        {'body_font':'url(https://evil.test)'}, {'custom_css':'body{}'}, {'hero':'<script>'}]:
                with self.subTest(bad=bad), self.assertRaises(AIError):
                    store.change(dict(changed, tokens=dict(changed['tokens'], advanced=bad)))
            for bad in [{'industry':'unknown'}, {'tags':['x'*33]}, {'blueprint':['script']}]:
                with self.subTest(bad=bad), self.assertRaises(AIError): store.change(dict(changed, **bad))

    def test_catalog_v2_migration_preserves_edits_and_deletions(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'console' / 'ai-styles.json'
            legacy = [v for v in styles.catalog() if v['introduced_version'] == 1]
            deleted = legacy.pop(1)['id']
            legacy[0].update(name='Owner edited', enabled=False, version=7)
            for item in legacy:
                item.pop('sector')
                item['tokens'] = styles.normalize_tokens(item['tokens'])
            custom = dict(legacy[0], id='custom', name='Custom recipe', enabled=True)
            styles.atomic_json(path, legacy + [custom])
            styles.atomic_json(path.with_name('ai-style-catalog.json'), {'version':1})
            store = styles.StyleStore(root)
            items = store.public(True)['templates']
            self.assertEqual(len(items), 28)  # 7 originals + 1 custom + 20 additions
            self.assertNotIn(deleted, [v['id'] for v in items])
            self.assertEqual(items[0]['name'], 'Owner edited')
            self.assertEqual(items[0]['version'], 7)
            self.assertFalse(items[0]['enabled'])
            self.assertEqual(items[0]['tokens'], legacy[0]['tokens'])
            self.assertEqual(items[0]['sector'], 'creative')
            self.assertEqual(store.resolve('custom')['sector'], 'general')
            self.assertEqual(len([v for v in items if v.get('introduced_version') == 2]), 20)
            self.assertEqual(styles.StyleStore(root).public(True)['templates'], items)
            store.change(dict(items[-1], action='delete'))
            self.assertEqual(len(styles.StyleStore(root).public(True)['templates']), 27)

    def test_industry_roundtrip_and_distinct_catalog(self):
        from kf_style_catalog_v2 import RECIPES
        self.assertEqual(len(RECIPES), 20)
        new = [v for v in styles.catalog() if v['introduced_version'] == 2]
        self.assertEqual(len({v['sector'] for v in new}), 20)
        research = json.loads((Path(__file__).resolve().parents[1] / 'docs/style-template-research.json').read_text())['templates']
        self.assertEqual({v['template_id']:v['source_url'] for v in research}, {v['id']:v['source_url'] for v in new})
        self.assertEqual(len({v['source_url'] for v in research}), 20)
        self.assertEqual(len({json.dumps(v['tokens'], sort_keys=True) for v in new}), 20)
        self.assertGreaterEqual(len({tuple(v['blueprint']) for v in new}), 15)
        with tempfile.TemporaryDirectory() as root:
            store = styles.StyleStore(root)
            item = store.change(dict(new[0], id='', sector='healthcare'))
            self.assertEqual(store.resolve(item['id'])['sector'], 'healthcare')
            duplicate = store.change(dict(item, action='duplicate'))
            self.assertEqual(duplicate['sector'], 'healthcare')
            self.assertIn('healthcare', styles.guidance(duplicate))
            for value in ['unknown', [], None, '<script>']:
                with self.subTest(value=value), self.assertRaises(AIError):
                    store.change(dict(item, sector=value))

    def test_url_and_address_boundaries(self):
        for url in ['file:///etc/passwd','https://u:p@example.com','http://example.com:3000','https://example.com/\r\nx','https://example.com\\@evil.test']:
            with self.subTest(url=url), self.assertRaises(AIError): styles.public_url(url)
        for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','100.64.0.1','192.0.2.1','224.0.0.1','ff00::1','2002:7f00:1::']:
            with self.subTest(ip=ip), patch.object(styles.socket, 'getaddrinfo', return_value=[(2,1,6,'',(ip,80))]), self.assertRaises(AIError):
                styles.public_addresses('example.com',80)
        with patch.object(styles.socket,'getaddrinfo',return_value=[(2,1,6,'',('1.1.1.1',80))]):
            self.assertEqual(styles.public_addresses('example.com',80),['1.1.1.1'])

    def test_fetch_pins_address_and_checks_redirect(self):
        response = MagicMock(status=302)
        response.getheader.side_effect=lambda key,default='': 'http://127.0.0.1/private' if key=='Location' else default
        connection=MagicMock();connection.getresponse.return_value=response
        with patch.object(styles,'public_addresses',side_effect=[['1.1.1.1'],AIError('blocked')]), patch.object(styles.socket,'create_connection') as sock, patch.object(styles.http.client,'HTTPConnection',return_value=connection):
            with self.assertRaisesRegex(AIError,'blocked'): styles.fetch_page('http://example.com',time.monotonic()+10)
            self.assertEqual(sock.call_args.args[0],('1.1.1.1',80))
            self.assertTrue(connection.close.called)

    def test_partial_css_failure_and_invalid_tokens(self):
        with patch.object(styles,'fetch_page',side_effect=[(HTML,'https://example.com/'),AIError('blocked')]):
            result=styles.analyze('https://example.com/')
            self.assertTrue(any('blocked' in w for w in result['warnings']))
            self.assertEqual(result['evidence']['stylesheets_read'],0)
        for tokens in [{'palette':[]},{'palette':{'ink':'#ffffff'}},{'layout':{'pad':'999px'}},{'shape':{'radius':'url(x)'}},{'type':{'heading':'<script>'}}]:
            with self.subTest(tokens=tokens), self.assertRaises(AIError): styles.normalize_tokens(tokens)

if __name__ == '__main__': unittest.main()
