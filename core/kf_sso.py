"""MVP-issued, browser-bound WordPress sessions with online revocation."""
import copy
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit
from kf_ai import atomic_json, read_json, AIError

_LOCK = threading.RLock()
HEX = re.compile(r'^[a-f0-9]{64}$')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def public_origin(value):
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.port not in (None,443):
        raise AIError('统一登录必须配置有效的 HTTPS 地址')
    if any(c.isspace() or c in '<>"\\' for c in value): raise AIError('统一登录地址无效')
    return value.rstrip('/')


def identity_version(user):
    return digest(json.dumps({k:user.get(k) for k in ('hash','salt','active','role','mfa_secret')},sort_keys=True))


class SSOStore:
    def __init__(self, base):
        self.root = Path(base)/'console'
        self.config_path = self.root/'wordpress-sso.json'
        self.state_path = self.root/'wordpress-sso-state.json'

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True,exist_ok=True)
        with _LOCK, (self.root/'.wordpress-sso.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(lock,fcntl.LOCK_UN)

    def config(self):
        return read_json(self.config_path, {'console_url':'','sites':{}})

    def configure(self, console_url, slug, site_url):
        console_url,site_url=public_origin(console_url),public_origin(site_url)
        if not re.fullmatch('[a-z][a-z0-9-]{1,19}',slug): raise AIError('站点标识无效')
        with self.locked():
            cfg=self.config()
            if cfg['console_url'] and cfg['console_url']!=console_url: raise AIError('统一入口地址已配置，不能在添加站点时更换')
            cfg['console_url']=console_url
            old=cfg['sites'].get(slug,{})
            site={'url':site_url,'secret':old.get('secret') or secrets.token_hex(32),'enabled':True}
            cfg['sites'][slug]=site;atomic_json(self.config_path,cfg)
            return dict(site,slug=slug,console_url=console_url)

    def site(self,slug):
        cfg=self.config();site=cfg['sites'].get(slug)
        if not site or not site.get('enabled'): raise AIError('此站点尚未接入统一登录')
        return dict(site,console_url=cfg['console_url'])

    def _state(self):
        now=time.time();s=read_json(self.state_path,{'tickets':{},'grants':{},'nonces':{}})
        for group in s:
            s[group]={k:v for k,v in s[group].items() if v['exp']>now}
        return s

    @staticmethod
    def authorized(sid,sessions,users,allowed):
        session=sessions.get(sid)
        if not session or session.get('exp',0)<=time.time(): raise AIError('MVP 登录已失效')
        user=users.get(session['user'],{})
        if not user.get('active') or user.get('role') not in ('admin','ops') or not allowed(user['role']):
            raise AIError('当前账号没有 WordPress 管理权限')
        return session,user

    def issue(self,slug,challenge,sid,sessions,users,allowed):
        if not isinstance(challenge,str) or not HEX.fullmatch(challenge): raise AIError('浏览器登录校验无效，请从 MVP 重新进入')
        self.site(slug)
        with self.locked():
            session,user=self.authorized(sid,sessions,users,allowed)
            state=self._state()
            if len(state['tickets'])>=500: raise AIError('登录请求过多，请稍后重试')
            token=secrets.token_hex(32)
            state['tickets'][digest(token)]={'site':slug,'challenge':challenge,'sid':sid,'exp':time.time()+60,
                'user_version':identity_version(user)}
            atomic_json(self.state_path,state)
            return token

    def callback(self,raw,headers,sessions,users,allowed):
        try:
            data=json.loads(raw)
            slug=data['site'];site=self.site(slug)
            timestamp=headers.get('X-MVP-Time','');nonce=headers.get('X-MVP-Nonce','');signature=headers.get('X-MVP-Signature','')
            if not HEX.fullmatch(nonce) or abs(time.time()-int(timestamp))>60: raise ValueError()
            expected=hmac.new(site['secret'].encode(),timestamp.encode()+b'\n'+nonce.encode()+b'\n'+raw,hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected,signature): raise ValueError()
        except (ValueError,KeyError,TypeError,AIError): raise AIError('站点请求验证失败') from None
        with self.locked():
            state=self._state();nonce_key=slug+':'+nonce
            if nonce_key in state['nonces']: raise AIError('重复请求已拒绝')
            if len(state['nonces'])>=10000: raise AIError('请求过多')
            state['nonces'][nonce_key]={'exp':time.time()+120}
            # Persist the nonce even for denied requests.
            atomic_json(self.state_path,state)
            action=data.get('action')
            if action=='consume':
                token=data.get('ticket','');verifier=data.get('verifier','')
                if not isinstance(token,str) or not HEX.fullmatch(token) or not isinstance(verifier,str) or not HEX.fullmatch(verifier): raise AIError('登录凭证无效')
                ticket=state['tickets'].get(digest(token))
                if not ticket or ticket['site']!=slug or not hmac.compare_digest(ticket['challenge'],digest(verifier)): raise AIError('登录凭证已过期、已使用或不属于此浏览器')
                session,user=self.authorized(ticket['sid'],sessions,users,allowed)
                if identity_version(user)!=ticket['user_version']: raise AIError('账号权限已变化，请重新登录')
                del state['tickets'][digest(token)]
                grant=secrets.token_hex(32)
                state['grants'][digest(grant)]={'site':slug,'sid':ticket['sid'],'user_version':identity_version(user),'exp':min(session['exp'],time.time()+12*3600)}
                atomic_json(self.state_path,state)
                return {'ok':True,'grant':grant,'expires':int(state['grants'][digest(grant)]['exp']),
                    'user':session['user'],'name':user.get('name',session['user']),'role':'administrator' if user['role']=='admin' else 'editor'}
            if action=='check':
                grant=data.get('grant','')
                if not isinstance(grant,str) or not HEX.fullmatch(grant): raise AIError('登录已失效')
                entry=state['grants'].get(digest(grant))
                if not entry or entry['site']!=slug: raise AIError('登录已失效')
                session,user=self.authorized(entry['sid'],sessions,users,allowed)
                if entry['user_version']!=identity_version(user): raise AIError('账号权限已变化，请重新登录')
                return {'ok':True,'user':session['user'],'role':'administrator' if user['role']=='admin' else 'editor'}
            raise AIError('未知统一登录操作')
