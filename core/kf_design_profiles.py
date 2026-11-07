"""Versioned visual design recipes, independent of live site application."""
import copy
import fcntl
import hashlib
import json
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from kf_ai import AIError, atomic_json, read_json, text
from kf_styles import normalize_tokens

_LOCK = threading.RLock()


class DesignConflict(AIError):
    pass


def fingerprint(tokens):
    return hashlib.sha256(json.dumps(tokens, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class DesignProfiles:
    def __init__(self, base, presets):
        self.path = Path(base) / 'console/design-profiles.json'
        self.defaults = presets

    @contextmanager
    def lock(self):
        with _LOCK, self.path.with_suffix('.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def public(self):
        stored = read_json(self.path, {'items': []})
        builtins = [{'id': 'builtin:'+key, 'name': key, 'description': '', 'version': 0,
                     'builtin': True, 'tokens': copy.deepcopy(value)} for key, value in self.defaults.items()]
        return {'items': builtins + stored['items']}

    def resolve(self, ident, version):
        item = next((x for x in self.public()['items'] if x['id'] == ident), None)
        if not item or type(version) is not int or item['version'] != version:
            raise DesignConflict('Design changed; refresh and review again')
        return copy.deepcopy(item)

    def change(self, body):
        with self.lock():
            data = read_json(self.path, {'items': []})
            ident = body.get('id')
            old = None
            if ident:
                if not isinstance(ident, str) or ident.startswith('builtin:'):
                    raise AIError('Built-in designs are read-only; create a copy')
                old = next((x for x in data['items'] if x['id'] == ident), None)
                if not old or type(body.get('version')) is not int or body['version'] != old['version']:
                    raise DesignConflict('Design changed; refresh before editing')
            action = body.get('action', 'save')
            if action == 'delete':
                if not old:
                    raise AIError('Choose a saved design')
                data['items'].remove(old)
                atomic_json(self.path, data)
                return {'id': ident, 'deleted': True}
            if action != 'save':
                raise AIError('Unknown design action')
            if not old and len(data['items']) >= 200:
                raise AIError('Design library is full (200 profiles)')
            raw = body.get('tokens', {})
            tokens = normalize_tokens(raw)
            if raw.get('preset') != 'reference':
                tokens['preset'] = 'custom'
            item = {'id': ident or 'design-'+uuid.uuid4().hex[:16],
                    'version': old['version']+1 if old else 1, 'builtin': False,
                    'name': text(body.get('name'), 'Design name', 120, True),
                    'description': text(body.get('description', ''), 'Description', 1000), 'tokens': tokens}
            data['items'] = [x for x in data['items'] if x['id'] != ident] + [item]
            atomic_json(self.path, data)
            return copy.deepcopy(item)
