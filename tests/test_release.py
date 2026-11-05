import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('release', Path(__file__).resolve().parents[1] / 'tools/kf_release.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, base, name, content):
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def test_package_uses_commit_and_excludes_runtime(self):
        repo = self.root / 'repo'
        repo.mkdir()
        for name in ['console/kf_console.py', 'core/kf_ai.py', 'console/ai.js', 'requirements.txt', 'constraints.txt']:
            self.write(repo, name, '')
        self.write(repo, 'console/users.json', '{"secret":"never ship"}')
        self.write(repo, 'sites/demo/data.json', '{}')
        self.write(repo, 'templates/basic.json', '{}')
        def git(*args):
            return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL)
        git('init'); git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
        self.write(repo, 'console/kf_console.py', 'uncommitted invalid python !')
        archive = self.root / 'release.tgz'
        manifest = r.package(repo, 'HEAD', archive)
        self.assertNotIn('console/users.json', manifest['files'])
        self.assertNotIn('sites/demo/data.json', manifest['files'])
        self.assertIn('templates/basic.json', manifest['files'])
        stage = self.root / 'stage'
        r.unpack(archive, stage, manifest['revision'])
        self.assertEqual((stage / 'console/kf_console.py').read_text(), '')
        with self.assertRaises(r.ReleaseError):
            r.unpack(archive, stage, '0' * 40)

    def test_invalid_archives(self):
        for path, link, wrong_digest in [('../escape.py', False, False), ('core/x.py', True, False), ('core/x.py', False, True)]:
            with self.subTest(path=path, link=link):
                archive = self.root / 'bad.tgz'
                data = b'pass\n'
                manifest = {'revision': 'a' * 40, 'files': {path: '0' * 64 if wrong_digest else r.digest(data)}}
                with tarfile.open(archive, 'w:gz') as tar:
                    for name, content in [(path, data), ('release.json', json.dumps(manifest).encode())]:
                        info = tarfile.TarInfo(name); info.size = len(content)
                        if link and name == path:
                            info.type = tarfile.SYMTYPE; info.linkname = '/tmp/escape'
                        tar.addfile(info, io.BytesIO(content))
                with self.assertRaises(r.ReleaseError):
                    r.unpack(archive, self.root / 'stage')

    def fixture(self):
        base, stage = self.root / 'live', self.root / 'stage'
        self.write(base, 'console/admin.pass', 'fixture only')
        self.write(base, 'console/users.json', 'original runtime data')
        self.write(base, 'core/app.py', 'old code')
        self.write(stage, 'core/app.py', 'new code')
        self.write(stage, 'core/new.py', 'new file')
        manifest = {'revision': 'a' * 40, 'files': {'core/app.py': '', 'core/new.py': ''}}
        return base, stage, manifest

    def test_success_preserves_data(self):
        base, stage, manifest = self.fixture()
        actions = []
        backup = r.apply(stage, base, manifest, control=actions.append, check=lambda: None)
        self.assertEqual(actions, ['stop', 'start'])
        self.assertEqual((base / 'core/app.py').read_text(), 'new code')
        self.assertEqual((base / 'console/users.json').read_text(), 'original runtime data')
        self.assertFalse((backup / 'console/users.json').exists())
        self.assertEqual(json.loads((base / '.release.json').read_text())['revision'], 'a' * 40)

    def test_failed_health_rolls_back_only_code(self):
        base, stage, manifest = self.fixture()
        calls = []
        def check():
            calls.append(1)
            if len(calls) == 1:
                self.write(base, 'console/users.json', 'updated while deploying')
                raise RuntimeError('bad release')
        with patch.object(r, 'wait_healthy', side_effect=lambda fn: fn()):
            with self.assertRaisesRegex(r.ReleaseError, 'previous code restored'):
                r.apply(stage, base, manifest, control=lambda action: None, check=check)
        self.assertEqual((base / 'core/app.py').read_text(), 'old code')
        self.assertFalse((base / 'core/new.py').exists())
        self.assertEqual((base / 'console/users.json').read_text(), 'updated while deploying')

    def test_automation_guard_and_active_workflows_block_release(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
        from kf_tool_runtime import release_guard
        from kf_ai import AIError
        base,stage,manifest=self.fixture()
        self.write(base,'console/workflows/fixture.json','{"state":"running"}')
        with self.assertRaisesRegex(r.ReleaseError,'automation'):
            r.apply(stage,base,manifest)
        self.write(base,'console/workflows/fixture.json','{"state":"paused"}')
        with release_guard(base):
            with self.assertRaises(r.ReleaseError):
                with r.deployment_lock(base):pass
        with r.deployment_lock(base):
            with self.assertRaises(AIError):
                with release_guard(base):pass

    def test_active_jobs_and_lock_block_deployment(self):
        base, stage, manifest = self.fixture()
        self.write(base, 'console/ai-jobs.json', '[{"status":"generating"}]')
        with self.assertRaisesRegex(r.ReleaseError, 'active AI'):
            r.apply(stage, base, manifest)
        with r.deployment_lock(base):
            with self.assertRaisesRegex(r.ReleaseError, 'Another deployment'):
                with r.deployment_lock(base):
                    pass
        self.assertFalse(r.allowed(''))
        self.assertFalse(r.allowed('console/users.json'))


if __name__ == '__main__':
    unittest.main()
