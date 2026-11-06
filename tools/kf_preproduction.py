#!/usr/bin/env python3
"""Exercise the exact release archive through disposable real HTTP/browser tests."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile

import kf_release as release


def copy_tests(repo, revision, destination):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args])
    entries = git('ls-tree', '-r', '-z', revision, '--', 'tests').split(b'\0')
    copied = 0
    for entry in filter(None, entries):
        metadata, raw = entry.split(b'\t', 1)
        mode, kind, sha = metadata.decode().split()
        name = raw.decode()
        path = PurePosixPath(name)
        if kind != 'blob' or mode not in ('100644', '100755') or path.is_absolute() or '..' in path.parts or path.parts[0] != 'tests':
            raise release.ReleaseError('Invalid test harness path')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git('cat-file', 'blob', sha))
        copied += 1
    if not copied:
        raise release.ReleaseError('Release revision has no test harness')


def run(archive, revision, repo, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = {'revision': revision, 'status': 'failed', 'scope': 'packaged code; disposable real HTTP and browser suite; external integrations use test fixtures'}
    try:
        with tempfile.TemporaryDirectory(prefix='kf-preproduction-') as directory:
            stage = Path(directory)
            manifest = release.unpack(archive, stage, revision)
            release.dependencies(stage)
            copy_tests(repo, revision, stage)
            env = dict(os.environ, PYTHON=sys.executable, E2E_OUTPUT=str(output / 'browser'))
            # Browser code runs outside the checkout; resolve the installed module explicitly.
            env['PLAYWRIGHT_MODULE'] = os.environ.get('PLAYWRIGHT_MODULE') or str(Path(repo).resolve() / 'tests/ui/node_modules/playwright')
            try:
                with (output / 'browser.log').open('w') as log:
                    completed = subprocess.run(['npm', 'test', '--prefix', 'tests/ui'], cwd=stage,
                                               env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900)
            finally:
                # Some legacy suites still write evidence relative to their checkout.
                if (stage / 'output').exists():
                    shutil.copytree(stage / 'output', output / 'fixtures', dirs_exist_ok=True)
            result.update(files=len(manifest['files']), exit_code=completed.returncode)
            if completed.returncode:
                raise release.ReleaseError('Packaged browser tests failed; inspect ' + str(output / 'browser.log'))
            result['status'] = 'passed'
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        (output / 'result.json').write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.archive, args.revision, args.repo, args.output), indent=2))


if __name__ == '__main__':
    main()
