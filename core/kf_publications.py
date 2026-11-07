"""Private, per-site publication journal. WordPress I/O belongs to the adapter.

Hold ``locked`` across capture, writes and verification. A process crash leaves a
durable interrupted record; neither publishing nor recovery is retried implicitly.
The public history deliberately excludes website content and recovery snapshots.
"""
from contextlib import contextmanager
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from kf_ai import AIError, atomic_json
from kf_tool_runtime import fingerprint


class PublicationConflict(AIError):
    pass


class PublicationStore:
    ACTIVE = {'publishing', 'restoring'}
    FINISHED = {'published', 'partial', 'failed'}
    MAX_SNAPSHOT_BYTES = 10 * 1024 * 1024

    def __init__(self, base, slug):
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,39}', slug):
            raise AIError('站点标识无效')
        sites = Path(base).resolve() / 'sites'
        site = sites / slug
        if site.is_symlink() or not (site / 'meta.json').is_file():
            raise AIError('站点不存在')
        self.slug = slug
        self.root = site / '.publications'
        if self.root.is_symlink():
            raise AIError('发布记录目录无效')
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.root.chmod(0o700)
        self._owner = None

    @contextmanager
    def locked(self):
        if self._owner is not None:
            raise PublicationConflict('站点已有发布或恢复任务，请稍后重试')
        with (self.root / '.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PublicationConflict('站点已有发布或恢复任务，请稍后重试') from None
            self._owner = (os.getpid(), threading.get_ident())
            try:
                # The exclusive lock proves no other compliant publisher is live.
                for item in self._records():
                    if item['state'] in self.ACTIVE:
                        item['interrupted_operation'] = item['state']
                        item['state'] = 'interrupted'
                        self._save(item, 'interrupted')
                yield self
            finally:
                self._owner = None
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _require_lock(self):
        if self._owner != (os.getpid(), threading.get_ident()):
            raise RuntimeError('Publication mutation requires the site lock')

    def _path(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
            raise AIError('发布记录 ID 无效')
        path = self.root / (ident + '.json')
        if path.is_symlink():
            raise AIError('发布记录文件无效')
        return path

    def get(self, ident):
        try:
            item = json.loads(self._path(ident).read_text())
        except FileNotFoundError:
            raise AIError('发布记录不存在') from None
        except (ValueError, OSError):
            raise AIError('发布记录无法读取，请检查备份') from None
        if not isinstance(item, dict) or item.get('slug') != self.slug or item.get('id') != ident:
            raise AIError('发布记录与站点不匹配')
        return item

    def _records(self):
        return sorted((self.get(p.stem) for p in self.root.glob('*.json')),
                      key=lambda item: (item['created'], item['id']), reverse=True)

    def history(self):
        fields = ('id', 'slug', 'user', 'created', 'updated', 'state', 'version',
                  'targets', 'results', 'error', 'interrupted_operation', 'restored_by', 'operation')
        return [{**{k: copy.deepcopy(item[k]) for k in fields if k in item},
                 'can_restore': (item['state'] in self.FINISHED and 'after_digest' in item)
                    or (item['state'] == 'restore_failed' and 'recovery_after_digest' in item)}
                for item in self._records()[:50]]

    def _snapshot(self, value):
        if not isinstance(value, dict):
            raise AIError('发布快照格式无效')
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        except (ValueError, TypeError):
            raise AIError('发布快照格式无效') from None
        if len(encoded) > self.MAX_SNAPSHOT_BYTES:
            raise AIError('发布快照过大，尚未修改网站')
        return json.loads(encoded)

    def _save(self, item, event):
        self._require_lock()
        item['updated'] = time.time()
        item['version'] = item.get('version', 0) + 1
        item.setdefault('events', []).append({'event': event, 'at': item['updated']})
        atomic_json(self._path(item['id']), item)
        return copy.deepcopy(item)

    def begin(self, user, targets, before, operation=None):
        self._require_lock()
        if not isinstance(user, str) or not user.strip() or len(user) > 100:
            raise AIError('发布操作账号无效')
        if (not isinstance(targets, list) or not targets or len(targets) > 100
                or any(not isinstance(s, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', s) for s in targets)
                or len(set(targets)) != len(targets)):
            raise AIError('发布页面列表无效')
        records = self._records()
        if any(item['state'] in self.ACTIVE for item in records):
            raise PublicationConflict('站点已有发布或恢复任务，请稍后重试')
        snapshot = self._snapshot(before)
        item = {'id': uuid.uuid4().hex, 'slug': self.slug, 'user': user,
                'created': time.time(), 'state': 'publishing', 'targets': list(targets),
                'results': [], 'before': snapshot, 'before_digest': fingerprint(snapshot)}
        if operation is not None:
            if operation != 'delete_page':
                raise AIError('Unknown publication operation')
            item['operation'] = operation
        return self._save(item, 'started')

    def result(self, ident, stage, ok, error='', created_id=None):
        self._require_lock()
        item = self.get(ident)
        if item['state'] != 'publishing':
            raise PublicationConflict('发布任务已经结束')
        if stage not in item['targets'] + ['design', 'navigation', 'verification'] or not isinstance(ok, bool):
            raise AIError('发布步骤无效')
        result = {'stage': stage, 'ok': ok, 'error': str(error)[:500]}
        if created_id is not None:
            if type(created_id) is not int or created_id < 1 or stage not in item['targets']:
                raise AIError('新建页面 ID 无效')
            result['created_id'] = created_id
        item['results'].append(result)
        return self._save(item, 'step')

    def finish(self, ident, state, after, error=''):
        self._require_lock()
        item = self.get(ident)
        if item['state'] != 'publishing' or state not in self.FINISHED:
            raise PublicationConflict('发布任务状态已改变')
        item.update(state=state, after=self._snapshot(after), error=str(error)[:500])
        item['after_digest'] = fingerprint(item['after'])
        saved = self._save(item, state)
        # Retain unresolved incidents even when pruning older completed releases.
        completed = [v for v in self._records() if v['state'] in {'published', 'restored'}]
        for old in completed[50:]:
            self._path(old['id']).unlink()
        return saved

    def restore(self, ident, *, version, user, confirmed, capture, apply):
        """Restore only if the current scoped state still matches this release.

        Adapter ``apply`` must validate its payload and verify actual WordPress
        writes. Its ``capture`` result is a canonical scoped snapshot, excluding
        volatile timestamps and unrelated site content.
        """
        self._require_lock()
        item = self.get(ident)
        if confirmed is not True:
            raise AIError('请确认恢复到本次发布前的内容')
        if type(version) is not int or version != item['version']:
            raise PublicationConflict('发布记录已变化，请刷新后重试')
        if not isinstance(user, str) or not user.strip() or len(user) > 100:
            raise AIError('恢复操作账号无效')
        expected_key = 'recovery_after' if item['state'] == 'restore_failed' else 'after'
        if item['state'] not in self.FINISHED | {'restore_failed'} or expected_key + '_digest' not in item:
            raise PublicationConflict('该发布记录不能直接恢复，请先核实当前站点状态')
        current = self._snapshot(capture())
        if fingerprint(current) != item[expected_key + '_digest']:
            raise PublicationConflict('网站在发布后发生了修改，请先核实，避免覆盖新内容')
        if fingerprint(item['before']) != item['before_digest']:
            raise AIError('发布前快照校验失败，恢复未执行')
        item['state'] = 'restoring'
        self._save(item, 'restore_started')
        try:
            apply(copy.deepcopy(item['before']))
            restored = self._snapshot(capture())
            if fingerprint(restored) != item['before_digest']:
                raise AIError('恢复后的回读校验失败，请核实站点')
        except Exception:
            item['state'] = 'restore_failed'
            item['error'] = '恢复未完成，请核实站点；快照已保留'
            item.pop('recovery_after', None)
            item.pop('recovery_after_digest', None)
            try:
                item['recovery_after'] = self._snapshot(capture())
                item['recovery_after_digest'] = fingerprint(item['recovery_after'])
            except Exception:
                pass  # Unknown current state must not become an automatic retry.
            self._save(item, 'restore_failed')
            raise
        item.update(state='restored', restored_by=user, error='')
        return self._save(item, 'restored')
