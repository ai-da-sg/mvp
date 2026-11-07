#!/usr/bin/env python3
"""Deploy pinned GEOInflow beside MVP; never shares MVP databases or login secrets."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess

REVISION = '13c32ecc6eb76b9e6d68a0a92d973ea859e8700b'
IMAGE = 'mvp-geoinflow:' + REVISION[:7]


def private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle: handle.write(value)


def compose_config():
    env = {'DATABASE_URL': 'postgresql://inflow:${POSTGRES_PASSWORD}@db:5432/inflow',
           'APP_SECRET': '${APP_SECRET}', 'TWO_FACTOR_ENCRYPTION_KEY': '${TWO_FACTOR_ENCRYPTION_KEY}',
           'LIEKAN_LOG_CREDENTIALS_KEY': '${LIEKAN_LOG_CREDENTIALS_KEY}',
           'LIEKAN_ANALYTICS_REDIS_URL': 'redis://cache:6379', 'LIEKAN_PUBLIC_URL': '${LIEKAN_PUBLIC_URL}',
           'DISABLE_TELEMETRY': '1', 'NEXT_TELEMETRY_DISABLED': '1', 'CLIENT_IP_HEADER': 'x-mvp-client-ip',
           'NODE_OPTIONS': '--max-old-space-size=512', 'LIEKAN_AI_ENABLED': 'false', 'MCP_ENABLED': '0'}
    # The MVP integration starts with real site data; the bundled demonstration stays in the image.
    start = 'export PATH="/app/node_modules/.bin:$$PATH"; node scripts/liekan-schema-check.mjs --migrations-only --allow-pending && node scripts/check-db.js && node scripts/liekan-schema-check.mjs && node scripts/liekan-migrate.mjs && node scripts/liekan-queue-bootstrap.mjs && node scripts/update-tracker.js && exec node server.js'
    common = {'image': IMAGE, 'restart': 'unless-stopped', 'environment': env, 'logging': {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '3'}}}
    return {'name': 'mvp-geoinflow', 'services': {
        'db': {'image': 'postgres:16-alpine', 'restart': 'unless-stopped', 'mem_limit': '512m',
               'environment': {'POSTGRES_DB': 'inflow', 'POSTGRES_USER': 'inflow', 'POSTGRES_PASSWORD': '${POSTGRES_PASSWORD}'},
               'volumes': ['inflow-data:/var/lib/postgresql/data'],
               'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U inflow -d inflow'], 'interval': '5s', 'retries': 20}},
        'cache': {'image': 'redis:7.4-alpine', 'restart': 'unless-stopped', 'mem_limit': '192m',
                  'command': ['redis-server', '--maxmemory', '128mb', '--maxmemory-policy', 'allkeys-lru', '--save', '', '--appendonly', 'no']},
        'app': {**common, 'ports': ['127.0.0.1:3002:3000'], 'mem_limit': '768m', 'command': ['sh', '-ec', start],
                'depends_on': {'db': {'condition': 'service_healthy'}, 'cache': {'condition': 'service_started'}},
                'healthcheck': {'test': ['CMD', 'node', '-e', "fetch('http://127.0.0.1:3000/api/heartbeat').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"], 'interval': '15s', 'retries': 10, 'start_period': '10m'}},
        'log-worker': {**common, 'mem_limit': '512m', 'command': ['node', 'dist/liekan-worker.mjs'], 'depends_on': {'app': {'condition': 'service_healthy'}}},
        'analytics-worker': {**common, 'mem_limit': '512m', 'cpus': 0.5, 'command': ['node', 'dist/liekan-analytics-worker.mjs'], 'depends_on': {'app': {'condition': 'service_healthy'}}},
    }, 'volumes': {'inflow-data': {}}}


def docker(*args):
    subprocess.run(['sg', 'docker', '-c', shlex.join(['docker', *args])], check=True)


def build_image(source, root):
    import re
    memory=Path('/proc/meminfo').read_text()
    available=int(re.search(r'MemAvailable:\s+(\d+)',memory)[1])*1024
    if available<6*1024**3: raise SystemExit('Build on CI or a host with 6 GiB available memory; load its verified image here')
    source=Path(source).resolve()
    revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if revision!=REVISION: raise SystemExit('Checkout must match the pinned upstream revision')
    if subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True).strip():
        raise SystemExit('Build requires an unchanged upstream checkout')
    content=(source/'Dockerfile.liekan').read_text()
    recipe=root/'Dockerfile';recipe.write_text(content)
    check=subprocess.run(['sg','docker','-c','docker buildx inspect mvp-geoinflow-build'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if check.returncode:
        docker('buildx','create','--name','mvp-geoinflow-build','--driver','docker-container','--driver-opt','memory=6g,memory-swap=6g,cpu-period=100000,cpu-quota=200000')
    docker('buildx','build','--builder','mvp-geoinflow-build','--load','--build-arg','LIEKAN_REVISION='+REVISION,'--build-arg','SKIP_BUILD_GEO=1','-f',str(recipe),'-t',IMAGE,str(source))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('prepare', 'build', 'start', 'status', 'stop'))
    p.add_argument('--directory', default=str(Path.home()/'.local/share/mvp-geoinflow'))
    p.add_argument('--source', default=str(Path.home()/'geoinflow'))
    p.add_argument('--public-url', default='')
    a = p.parse_args(); root = Path(a.directory).resolve(); root.mkdir(parents=True, exist_ok=True, mode=0o700)
    compose = root/'compose.json'
    if a.action == 'build':
        build_image(a.source,root)
    elif a.action == 'prepare':
        import base64
        if not (root/'.env').exists():
            if compose.exists(): raise SystemExit('Existing configuration has lost its credentials; restore the original .env')
            probe=subprocess.run(['sg','docker','-c','docker volume inspect mvp-geoinflow_inflow-data'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if probe.returncode==0: raise SystemExit('Existing data volume found; restore its original configuration')
            if probe.returncode!=1: raise SystemExit('Cannot determine whether an existing data volume is present')
            values = {'POSTGRES_PASSWORD': secrets.token_urlsafe(36), 'APP_SECRET': secrets.token_urlsafe(48),
                      'TWO_FACTOR_ENCRYPTION_KEY': secrets.token_hex(32),
                      'LIEKAN_LOG_CREDENTIALS_KEY': base64.b64encode(secrets.token_bytes(32)).decode(), 'LIEKAN_PUBLIC_URL': a.public_url}
            private(root/'.env', '\n'.join(k+'='+v for k,v in values.items())+'\n')
        if compose.exists():
            if json.loads(compose.read_text()) != compose_config(): raise SystemExit('Existing deployment differs; review before changing it')
        else: private(compose, json.dumps(compose_config(), indent=2)+'\n')
        print('Private deployment configuration prepared; no services changed')
    elif not compose.exists() or not (root/'.env').exists():
        raise SystemExit('Prepare the deployment first; never replace missing existing credentials')
    else:
        command = {'start': ['up', '-d'], 'status': ['ps'], 'stop': ['stop']}[a.action]
        docker('compose', '--project-directory', str(root), '--env-file', str(root/'.env'), '-f', str(compose), *command)


if __name__ == '__main__': main()
