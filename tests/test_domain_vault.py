import json
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from kf_domain_vault import DomainVault, VaultDenied, VaultLimited, VaultConflict
from kf_ai import AIError

class DomainVaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.vault=DomainVault(self.tmp.name)
        self.body={'slug':'demo','provider':'Example','category':'dns','url':'https://example.com','username':'operator',
                   'password':' secret with spaces <>& ','configuration':'NS: ns1.example.com'}
        self.item=self.vault.change(self.body,'admin')
    def tearDown(self):self.tmp.cleanup()
    def test_encryption_roundtrip_versions_and_missing_key(self):
        self.assertNotIn(self.body['password'],self.vault.path.read_text())
        self.assertNotIn('secret',self.item)
        self.assertTrue(self.item['has_password'])
        self.assertEqual(self.vault.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.vault.key_path.stat().st_mode & 0o777,0o600)
        restored=DomainVault(self.tmp.name)
        self.assertEqual(restored.reveal(self.item['id'],'admin','123456',lambda _:100),self.body['password'])
        with self.assertRaises(VaultDenied):restored.reveal(self.item['id'],'admin','123456',lambda _:100)
        updated=self.vault.change(dict(self.body,id=self.item['id'],version=1,password='',provider='Updated'),'admin')
        self.assertEqual(updated['version'],2)
        with self.assertRaises(VaultConflict):self.vault.change(dict(self.body,id=self.item['id'],version=1),'admin')
        self.vault.key_path.unlink()
        with self.assertRaises(AIError):self.vault.reveal(self.item['id'],'admin','123456',lambda _:101)
        self.assertFalse(self.vault.key_path.exists())
    def test_rate_limit_replay_and_concurrency(self):
        for _ in range(4):
            with self.assertRaises(VaultDenied):self.vault.reveal(self.item['id'],'admin','bad-code',lambda _:None)
        with self.assertRaises(VaultLimited):self.vault.reveal(self.item['id'],'admin','123456',lambda _:None)
        with self.assertRaises(VaultLimited):DomainVault(self.tmp.name).reveal(self.item['id'],'admin','123456',lambda _:100)
        def request(_):
            try:self.vault.reveal(self.item['id'],'other','123456',lambda _:100);return True
            except VaultDenied:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(request,range(2))),1)
        with patch('kf_domain_vault.time.time',return_value=time.time()+301):
            self.assertEqual(self.vault.reveal(self.item['id'],'admin','123456',lambda _:110),self.body['password'])
    def test_context_binding_clear_and_validation(self):
        second=self.vault.change(dict(self.body,slug='other'),'admin')
        items=json.loads(self.vault.path.read_text());items[1]['secret']=items[0]['secret'];self.vault.path.write_text(json.dumps(items))
        with self.assertRaises(AIError):self.vault.reveal(second['id'],'admin','123456',lambda _:100)
        for url in ['http://example.com','javascript:alert(1)','https://user:pass@example.com','https://example.com/\nx']:
            with self.assertRaises(AIError):self.vault.change(dict(self.body,url=url),'admin')
        with self.assertRaises(AIError):self.vault.change(dict(self.body,id=self.item['id'],version=1,slug='other'),'admin')
        cleared=self.vault.change(dict(self.body,id=self.item['id'],version=1,password='',clear_password=True),'admin')
        self.assertFalse(cleared['has_password'])
        with self.assertRaises(AIError):self.vault.reveal(cleared['id'],'admin','123456',lambda _:100)
