#!/usr/bin/env python3
"""Code-only releases for an existing installation; never package or roll back tenant data."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
from importlib.metadata import version
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import ssl
import subprocess
import tarfile
import tempfile
import time
import urllib.request


class ReleaseError(RuntimeError):
    pass


def allowed(path):
    p = PurePosixPath(path)
    if not p.parts or p.is_absolute() or '..' in p.parts or str(p) != path:
        return False
    if path in ('requirements.txt', 'constraints.txt', 'VERSION'):
        return True
    if len(p.parts) == 2 and p.parts[0] in ('console', 'core'):
        return p.suffix in ('.py', '.js')
    if p.parts[0] == 'tools' and len(p.parts) in (2, 3):
        return p.suffix in ('.py', '.sh', '.js')
    if len(p.parts) == 3 and p.parts[:2] == ('theme', 'kampong'):
        return p.suffix in ('.php', '.css')
    return len(p.parts) == 2 and p.parts[0] == 'templates' and p.suffix == '.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package(root, revision, output):
    root, output = Path(root), Path(output)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args])
    revision = git('rev-parse', '--verify', revision + '^{commit}').decode().strip()
    names = git('ls-tree', '-rz', '--name-only', revision).decode().split('\0')
    files = {}
    for name in sorted(n for n in names if n and allowed(n)):
        files[name] = git('show', revision + ':' + name)
    for needed in ('console/kf_console.py', 'core/kf_ai.py', 'console/ai.js', 'requirements.txt', 'constraints.txt'):
        if needed not in files:
            raise ReleaseError('Release is missing ' + needed)
    manifest = {'revision': revision, 'files': {name: digest(data) for name, data in files.items()}}
    files['release.json'] = json.dumps(manifest, sort_keys=True).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.mode = 0o755 if name.endswith('.sh') else 0o644
            archive.addfile(entry, io.BytesIO(data))
    output.with_suffix(output.suffix + '.sha256').write_text(digest(output.read_bytes()) + '  ' + output.name + '\n')
    return manifest


def unpack(archive, destination, expected_revision=None):
    destination = Path(destination)
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)) or 'release.json' not in names:
            raise ReleaseError('Missing manifest or duplicate archive paths')
        if len(names) > 300 or sum(m.size for m in members) > 30 * 1024 * 1024:
            raise ReleaseError('Release exceeds size limit')
        for member in members:
            if not member.isfile() or member.size > 5 * 1024 * 1024:
                raise ReleaseError('Release contains a link, directory or oversized file')
            if member.name != 'release.json' and not allowed(member.name):
                raise ReleaseError('Release contains a non-code path: ' + member.name)
        manifest = json.loads(tar.extractfile('release.json').read())
        revision = manifest.get('revision', '')
        if not re.fullmatch('[0-9a-f]{40}', revision):
            raise ReleaseError('Invalid revision')
        if expected_revision and revision != expected_revision:
            raise ReleaseError('Release revision does not match the tested commit')
        if set(manifest['files']) != set(names) - {'release.json'}:
            raise ReleaseError('Manifest and archive disagree')
        for name, expected in manifest['files'].items():
            data = tar.extractfile(name).read()
            if digest(data) != expected:
                raise ReleaseError('Checksum mismatch: ' + name)
            if name.endswith('.py'):
                compile(data, name, 'exec')
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755 if name.endswith('.sh') else 0o644)
        return manifest


def service(action):
    subprocess.run(['systemctl', '--user', action, 'kf-console', 'kf-dns'], check=True, timeout=60)


def dependencies(stage):
    # Do not silently upgrade a shared virtualenv: dependency rollback must be planned separately.
    for line in (stage / 'constraints.txt').read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        name, wanted = line.split('==', 1)
        if version(name) != wanted:
            raise ReleaseError('Runtime dependency mismatch: %s; prepare the tested virtualenv before deploying' % name)
    import reportlab, PIL, dns, qrcode, cryptography, jsonschema, boto3, botocore, nh3  # noqa: F401: importing catches runtime/version incompatibilities


def health(base, console_port=18090, dns_port=5354, https_port=18444):
    import dns.message
    import dns.query
    import dns.rcode
    subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'kf-console', 'kf-dns', 'kf-proxy'], check=True)
    with urllib.request.urlopen('http://127.0.0.1:%d/login' % console_port, timeout=5) as r:
        if r.status != 200:
            raise ReleaseError('Console login failed')
    # Trust this installation's certificate, including its self-signed deployment certificate.
    ctx = ssl.create_default_context(cafile=str(base / 'console/tls/cert.pem'))
    ctx.check_hostname = False  # Local loopback probe; the certificate itself is still verified.
    with urllib.request.urlopen('https://127.0.0.1:%d/login' % https_port, context=ctx, timeout=5) as r:
        if r.status != 200:
            raise ReleaseError('HTTPS proxy failed')
    q = dns.message.make_query('kf-release-health.invalid', 'A')
    if dns.query.udp(q, '127.0.0.1', port=dns_port, timeout=3).rcode() != dns.rcode.REFUSED:
        raise ReleaseError('Authoritative DNS health check failed')


def wait_healthy(check, attempts=10):
    error = None
    for attempt in range(attempts):
        try:
            check()
            return
        except Exception as e:
            error = e
            if attempt + 1 < attempts:
                time.sleep(1)
    raise ReleaseError('Health check failed: ' + str(error))


def target_path(base, relative):
    path = base / relative
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != base and base in p.parents):
        raise ReleaseError('Refusing symlink destination: ' + relative)
    if base not in path.resolve().parents:
        raise ReleaseError('Destination escapes installation')
    return path


def copy_atomic(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.release-', dir=destination.parent)
    os.close(fd)
    try:
        shutil.copy2(source, tmp)
        os.replace(tmp, destination)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def deployment_lock(base):
    with (base / 'console/deploy.lock').open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReleaseError('Another deployment is running')
        yield


def apply(stage, base, manifest, control=service, check=None):
    """The rollback set contains only the exact code paths in this release."""
    base = Path(base).resolve()
    if any(not allowed(name) for name in manifest['files']):
        raise ReleaseError('Refusing non-code deployment path')
    if not (base / 'console/admin.pass').is_file():
        raise ReleaseError('Target is not an initialized installation')
    check = check or (lambda: health(base))
    with deployment_lock(base):
        jobs_file = base / 'console/ai-jobs.json'
        jobs = json.loads(jobs_file.read_text()) if jobs_file.exists() else []
        if any(j.get('status') in ('queued', 'generating', 'provisioning', 'saving') for j in jobs):
            raise ReleaseError('Wait for active AI builds to finish before deploying')
        for folder in ('actions','workflows'):
            for path in (base/'console'/folder).glob('*.json'):
                if json.loads(path.read_text()).get('state')=='running':
                    raise ReleaseError('Wait for active automation operations/workflows to finish or pause before deploying')
        names = list(manifest['files']) + ['.release.json']
        targets = {name: target_path(base, name) for name in names}
        backup = base / '.code-backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + manifest['revision'][:12])
        backup.mkdir(parents=True, mode=0o700)
        existed = {}
        for name, dest in targets.items():
            existed[name] = dest.exists()
            if dest.exists():
                if not dest.is_file():
                    raise ReleaseError('Destination is not a regular file: ' + name)
                saved = backup / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, saved)
        (backup / 'rollback.json').write_text(json.dumps(existed, indent=2))
        try:
            control('stop')
            for name in manifest['files']:
                copy_atomic(stage / name, targets[name])
            control('start')
            wait_healthy(check)
            release = stage / '.release.json'
            release.write_text(json.dumps(manifest, indent=2))
            copy_atomic(release, targets['.release.json'])
            return backup
        except BaseException as original:
            try:
                control('stop')
                for name, dest in targets.items():
                    if existed[name]:
                        copy_atomic(backup / name, dest)
                    elif dest.exists():
                        dest.unlink()
                control('start')
                wait_healthy(check)
            except BaseException as rollback_error:
                raise ReleaseError('Deployment and rollback failed; recover code from %s: %s' % (backup, rollback_error)) from original
            raise ReleaseError('Deployment failed; previous code restored. Backup: ' + str(backup)) from original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('package')
    build.add_argument('--root', default='.')
    build.add_argument('--revision', default='HEAD')
    build.add_argument('--output', required=True)
    deploy = sub.add_parser('deploy')
    deploy.add_argument('archive')
    deploy.add_argument('--base', required=True)
    deploy.add_argument('--expected-revision', required=True)
    deploy.add_argument('--console-port', type=int, default=18090)
    deploy.add_argument('--dns-port', type=int, default=5354)
    deploy.add_argument('--https-port', type=int, default=18444)
    deploy.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if args.command == 'package':
        manifest = package(args.root, args.revision, args.output)
        print('Packaged %d code files from %s' % (len(manifest['files']), manifest['revision']))
        return
    def interrupted(signum, frame):
        raise ReleaseError('Deployment interrupted by signal %d' % signum)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    with tempfile.TemporaryDirectory(prefix='kf-release-') as directory:
        stage = Path(directory)
        manifest = unpack(args.archive, stage, args.expected_revision)
        dependencies(stage)
        if args.check_only:
            print('Release checks passed; installation was not modified')
            return
        base = Path(args.base)
        backup = apply(stage, base, manifest, check=lambda: health(base, args.console_port, args.dns_port, args.https_port))
        print('Deployed %s; code backup: %s' % (manifest['revision'], backup))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(str(error))
