#!/usr/bin/env python3
"""Source syntax checks without importing the live console or touching its data."""
import ast
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--skip-php', action='store_true', help='Local checks only; CI requires PHP')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=root).decode().splitlines()
with tempfile.TemporaryDirectory() as tmp:
    for name in files:
        path = root / name
        if not path.is_file():
            continue
        if path.suffix == '.py':
            tree = ast.parse(path.read_bytes(), filename=name)
            compile(tree, name, 'exec')
            if name == 'core/kf_leads.py' and not args.skip_php:
                snippet = next(ast.literal_eval(stmt.value) for stmt in tree.body
                               if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_FIELDS' for t in stmt.targets))
                target = Path(tmp) / 'leads.php'
                target.write_text('<?php\n' + snippet)
                subprocess.run(['php', '-l', str(target)], check=True)
            if name == 'core/kf_publication_wp.py' and not args.skip_php:
                snippets = {target.id: ast.literal_eval(stmt.value)
                            for stmt in tree.body if isinstance(stmt, ast.Assign)
                            for target in stmt.targets if isinstance(target, ast.Name)
                            and target.id in ('PHP_CAPTURE', 'PHP_RESTORE')}
                target = Path(tmp) / 'publication.php'
                target.write_text('<?php\n' + snippets['PHP_CAPTURE'] + '\n' + snippets['PHP_RESTORE'])
                subprocess.run(['php', '-l', str(target)], check=True)
            if name == 'console/kf_console.py':
                for stmt in tree.body:
                    if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PAGE' for t in stmt.targets):
                        html = ast.literal_eval(stmt.value)
                        for i, script in enumerate(re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)):
                            target = Path(tmp) / ('inline-%d.js' % i)
                            target.write_text(script)
                            subprocess.run(['node', '--check', str(target)], check=True)
        elif path.suffix == '.sh':
            subprocess.run(['bash', '-n', str(path)], check=True)
        elif path.suffix == '.js':
            subprocess.run(['node', '--check', str(path)], check=True)
        elif path.suffix == '.php' and not args.skip_php:
            subprocess.run(['php', '-l', str(path)], check=True)
print('Source syntax checks passed' + (' (PHP skipped)' if args.skip_php else ' including PHP'))
