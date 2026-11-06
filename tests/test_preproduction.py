import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import kf_preproduction as gate


class PreproductionTests(unittest.TestCase):
    def test_harness_comes_from_commit_not_dirty_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            repo.mkdir()
            (repo / 'tests').mkdir()
            source = repo / 'tests/proof.py'
            source.write_text('committed')
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL)
            git('init'); git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'test')
            source.write_text('dirty')
            destination = Path(tmp) / 'stage'
            gate.copy_tests(repo, 'HEAD', destination)
            self.assertEqual((destination / 'tests/proof.py').read_text(), 'committed')

    def test_invalid_release_fails_before_running_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gate.release, 'unpack', side_effect=gate.release.ReleaseError('Revision mismatch')):
                with patch.object(gate.subprocess, 'run') as runner:
                    with self.assertRaises(gate.release.ReleaseError):
                        gate.run('invalid.tgz', 'a' * 40, '.', tmp)
                    runner.assert_not_called()
            self.assertEqual(json.loads((Path(tmp) / 'result.json').read_text())['status'], 'failed')

    def test_browser_failure_blocks_gate_and_retains_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            def browser(*args, **kwargs):
                output = kwargs['cwd'] / 'output'
                output.mkdir()
                (output / 'failure.png').write_bytes(b'fixture')
                return subprocess.CompletedProcess(args[0], 1)
            with patch.object(gate.release, 'unpack', return_value={'files': {'core/app.py': 'hash'}}), \
                 patch.object(gate.release, 'dependencies'), patch.object(gate, 'copy_tests'), \
                 patch.object(gate.subprocess, 'run', side_effect=browser):
                with self.assertRaisesRegex(gate.release.ReleaseError, 'browser tests failed'):
                    gate.run('fixture.tgz', 'a' * 40, '.', tmp)
            self.assertEqual((Path(tmp) / 'fixtures/failure.png').read_bytes(), b'fixture')
            result = json.loads((Path(tmp) / 'result.json').read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['exit_code'], 1)
