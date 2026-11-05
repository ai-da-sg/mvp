"""Persistent, parameter-bound execution tickets shared by UI and AI workflows.

Only the executor owns side effects. A ticket entering `running` is never retried
implicitly: process loss or an ambiguous provider response requires reconciliation.
"""
import copy
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
import fcntl
import threading
from pathlib import Path
from kf_ai import AIError, atomic_json, read_json, text

_LOCK=threading.RLock()
ACTIVE={'running'}
MODES={'read','draft','confirm','totp'}


def fingerprint(value):
    try:encoded=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    except (TypeError,ValueError):raise AIError('操作参数必须是有效 JSON，不能包含非有限数值') from None
    return hashlib.sha256(encoded).hexdigest()


@contextmanager
def release_guard(base):
    path=Path(base)/'console'/'deploy.lock';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:raise AIError('系统正在更新，请完成后重试；操作尚未执行') from None
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


class ActionConflict(AIError):pass
class ActionDenied(AIError):pass
class UncertainResult(AIError):pass


class ActionStore:
    def __init__(self,base):
        self.root=Path(base)/'console'/'actions'
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)

    @contextmanager
    def locked(self):
        with _LOCK,(self.root/'.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock,fcntl.LOCK_UN)

    def path(self,ident):
        if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident):raise AIError('操作 ID 无效')
        return self.root/(ident+'.json')

    def get(self,ident,user=None):
        item=read_json(self.path(ident),None)
        if not item:raise AIError('操作不存在')
        if user is not None and item['user']!=user:raise ActionDenied('不能访问其他账号的操作')
        return item

    def list(self,user,admin=False):
        with self.locked():
            items=[]
            for path in sorted(self.root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
                item=read_json(path,{})
                if admin or item.get('user')==user:
                    items.append({k:item.get(k) for k in ('id','user','slug','tool','mode','state','created','updated','summary','error','elapsed_ms','workflow_id')})
                if len(items)>=200:break
            return items

    def prepare(self,*,user,slug,tool,arguments,mode,summary,snapshot,request_key='',workflow_id=''):
        if mode not in MODES:raise AIError('执行规则无效')
        if not isinstance(arguments,dict):raise AIError('工具参数必须是对象')
        if len(json.dumps(arguments,ensure_ascii=False))>40000:raise AIError('工具参数超过限制')
        text(user,'用户',100,True);text(slug,'站点',40,True);text(tool,'工具',200,True)
        text(request_key,'请求标识',100);text(summary,'操作说明',1000,True)
        payload={'slug':slug,'tool':tool,'arguments':arguments,'mode':mode,'snapshot':snapshot}
        digest=fingerprint(payload)
        with self.locked():
            if request_key:
                for path in self.root.glob('*.json'):
                    old=read_json(path,{})
                    if old.get('user')==user and old.get('request_key')==request_key:
                        if old['digest']!=digest:raise ActionConflict('同一请求标识不能用于不同参数')
                        return old
            item={**copy.deepcopy(payload),'id':uuid.uuid4().hex,'user':user,'summary':summary,
                  'digest':digest,'request_key':request_key,'workflow_id':workflow_id,'state':'prepared',
                  'created':time.time(),'updated':time.time(),'expires':time.time()+1800,'events':[]}
            self.save(item,'prepared');return item

    def save(self,item,event):
        item['updated']=time.time();item.setdefault('events',[]).append({'event':event,'at':item['updated']})
        atomic_json(self.path(item['id']),item)

    def execute(self,ident,user,*,digest,confirmed=False,code='',authorize,verify_totp,executor):
        with self.locked():
            item=self.get(ident,user)
            if digest!=item['digest']:raise ActionConflict('操作内容已变，请重新查看并确认')
            # Recheck role, scope, schema, provider settings and live business snapshot even on a completed ticket.
            authorize(item)
            if item['state']=='succeeded':return item
            if item['state']!='prepared':raise ActionConflict('操作已执行或结果待核实，请查看记录，不能重复提交')
            if time.time()>item['expires']:raise ActionConflict('确认已过期，请重新生成操作方案')
            if item['mode'] in ('confirm','totp') and confirmed is not True:raise ActionDenied('请先核对具体变更并确认执行')
            if item['mode']=='totp':verify_totp(user,code)
            item['state']='running';item['started']=time.time();self.save(item,'started')
        try:
            result=executor(copy.deepcopy(item))
            # Bound persistent results. Executor must redact secrets before returning.
            if len(json.dumps(result,ensure_ascii=False))>256000:raise UncertainResult('结果超过保存限制，请核实外部状态')
        except Exception as exc:
            with self.locked():
                current=self.get(ident)
                current['state']='failed' if item['mode'] in ('read','draft') else 'uncertain'
                current['error']=str(exc)[:1000] if isinstance(exc,AIError) else '执行失败，请检查记录及外部服务状态'
                current['elapsed_ms']=int((time.time()-item['started'])*1000)
                self.save(current,current['state']);return current
        with self.locked():
            current=self.get(ident);current['state']='succeeded';current['result']=result
            current['elapsed_ms']=int((time.time()-item['started'])*1000);self.save(current,'succeeded');return current

    def cancel(self,ident,user):
        with self.locked():
            item=self.get(ident,user)
            if item['state']!='prepared':raise ActionConflict('只有待执行操作可以取消')
            item['state']='cancelled';self.save(item,'cancelled');return item

    def reconcile(self,ident,user,outcome,note,*,admin=False):
        """Human resolution never re-executes an ambiguous operation."""
        if not admin:raise ActionDenied('只有管理员可核实不确定的操作结果')
        if outcome not in ('succeeded','failed'):raise AIError('核实结果无效')
        note=text(note,'核实依据',1000,True)
        with self.locked():
            item=self.get(ident)
            if item['state'] not in ('uncertain','interrupted'):raise ActionConflict('该操作不需要核实')
            item.update(state=outcome,reconciled_by=user,reconciliation=note)
            self.save(item,'reconciled');return item

    def recover_interrupted(self):
        # Call exactly once during process startup, before accepting new requests.
        with self.locked():
            for path in self.root.glob('*.json'):
                item=read_json(path,{})
                if item.get('state')=='running':
                    item['state']='interrupted';item['error']='服务中断；请核实执行结果后继续，系统不会自动重放操作'
                    self.save(item,'interrupted')
