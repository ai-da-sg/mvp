"""Domain provider accounts; passwords leave the vault only after fresh TOTP verification."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
from urllib.parse import urlsplit
from cryptography.fernet import Fernet, InvalidToken
from kf_ai import AIError, atomic_json, read_json, text

_LOCK = threading.RLock()
_HELD_LOCKS = threading.local()

class VaultConflict(AIError): pass
class VaultDenied(AIError): pass
class VaultLimited(AIError): pass


class DomainVault:
    def __init__(self, base):
        self.root=Path(base)/'console'
        self.path=self.root/'domain-accounts.json'
        self.key_path=self.root/'domain-vault.key'
        self.auth_path=self.root/'domain-vault-auth.json'

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True,exist_ok=True)
        # DNS/MCP stores resolve provider credentials inside an existing vault transaction.
        # flock on a second descriptor is not reentrant, even in the same thread.
        key=str(self.root.resolve())
        with _LOCK:
            held=getattr(_HELD_LOCKS,'roots',set())
            if key in held:
                yield
                return
            with (self.root/'.domain-vault.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                _HELD_LOCKS.roots=held|{key}
                try:yield
                finally:
                    _HELD_LOCKS.roots=held
                    fcntl.flock(lock,fcntl.LOCK_UN)

    def cipher(self, items):
        if not self.key_path.exists():
            if any(i.get('secret') for i in items):
                raise AIError('密码加密密钥缺失，请恢复服务器备份；现有数据未更改')
            fd=os.open(str(self.key_path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as file:
                file.write(Fernet.generate_key());file.flush();os.fsync(file.fileno())
        try: return Fernet(self.key_path.read_bytes())
        except (ValueError,OSError): raise AIError('密码加密密钥不可用，请检查服务器备份') from None

    @staticmethod
    def public_item(item):
        return {**{k:v for k,v in item.items() if k!='secret'},'has_password':bool(item.get('secret'))}

    def public(self):
        with self.locked():return [self.public_item(i) for i in read_json(self.path,[])]

    def change(self,body,user):
        with self.locked():
            items=read_json(self.path,[])
            ident=text(body.get('id',''),'记录 ID',40)
            old=next((i for i in items if i['id']==ident),None)
            if ident and not old: raise AIError('管理账号不存在，请刷新')
            if old and body.get('version')!=old['version']: raise VaultConflict('资料已被其他操作更新，请刷新后重试')
            if body.get('action')=='delete':
                if not old: raise AIError('管理账号不存在')
                atomic_json(self.path,[i for i in items if i['id']!=ident]);return self.public_item(old)
            if body.get('action','save')!='save':raise AIError('未知账号操作')
            slug=text(body.get('slug',''),'站点',20,True)
            if not re.fullmatch(r'[a-z][a-z0-9-]{1,19}',slug):raise AIError('站点标识无效')
            if old and old['slug']!=slug:raise AIError('已有账号不能移动到其他域名，请新建记录')
            if not old and len(items)>=500:raise AIError('最多保存 500 个管理账号')
            url=text(body.get('url',''),'管理后台地址',2000)
            if url:
                try:
                    parts=urlsplit(url)
                    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or any(ord(c)<=32 or c in '\\<>"' for c in url):raise ValueError()
                    parts.port
                except ValueError:raise AIError('后台地址必须是 HTTPS 网址，不能包含登录凭据') from None
            category=body.get('category','registrar')
            if category not in ('registrar','dns','hosting','other'):raise AIError('机构类型无效')
            ident=ident or uuid.uuid4().hex
            item={'id':ident,'slug':slug,'provider':text(body.get('provider',''),'管理机构',120,True),
                'category':category,'url':url,'username':text(body.get('username',''),'用户名',300),
                'configuration':text(body.get('configuration',''),'配置信息',12000),
                'version':old['version']+1 if old else 1,'updated':int(time.time()),'updated_by':user,
                'secret':old.get('secret','') if old else ''}
            password=body.get('password','')
            if not isinstance(password,str) or len(password)>4096:raise AIError('密码必须是最多 4096 字符的文本')
            if body.get('clear_password') is True and password:raise AIError('不能同时设置和清除密码')
            if body.get('clear_password') is True:item['secret']=''
            elif password:
                payload=json.dumps({'id':ident,'slug':slug,'password':password},ensure_ascii=False).encode()
                item['secret']=self.cipher(items).encrypt(payload).decode()
            atomic_json(self.path,[i for i in items if i['id']!=ident]+[item])
            return self.public_item(item)

    def reveal(self,ident,user,code,verify_counter):
        """Rate limiting and successful TOTP consumption persist across server restarts."""
        with self.locked():
            now=time.time();auth=read_json(self.auth_path,{})
            state=auth.get(user,{'failures':[],'last_counter':-1,'blocked_until':0})
            if state.get('blocked_until',0)>now:raise VaultLimited('验证失败次数过多，请 5 分钟后再试')
            items=read_json(self.path,[]);item=next((i for i in items if i['id']==ident),None)
            if not item or not item.get('secret'):raise AIError('此账号未保存密码')
            counter=verify_counter(code) if isinstance(code,str) and re.fullmatch(r'[0-9]{6}',code) else None
            if counter is None or counter<=state.get('last_counter',-1):
                failures=[t for t in state.get('failures',[]) if t>now-300]+[now]
                state.update(failures=failures,blocked_until=now+300 if len(failures)>=5 else 0)
                auth[user]=state;atomic_json(self.auth_path,auth)
                if len(failures)>=5:raise VaultLimited('验证失败次数过多，请 5 分钟后再试')
                raise VaultDenied('TOTP 无效或已使用，请等待下一枚验证码；恢复码不能用于显示密码')
            try:
                payload=json.loads(self.cipher(items).decrypt(item['secret'].encode()))
                if payload['id']!=item['id'] or payload['slug']!=item['slug']:raise InvalidToken()
                password=payload['password']
                if not isinstance(password,str):raise InvalidToken()
            except (InvalidToken,KeyError,ValueError,TypeError):raise AIError('密码解密失败，请检查加密密钥和数据备份') from None
            state.update(failures=[],blocked_until=0,last_counter=counter)
            auth[user]=state;atomic_json(self.auth_path,auth)
            return password
