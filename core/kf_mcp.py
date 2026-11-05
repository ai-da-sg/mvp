"""Admin-managed remote MCP connections. Discovery only; never executes tools."""
import copy
import http.client
import json
import re
import socket
import ssl
import time
import threading
from urllib.parse import urlsplit
from kf_ai import AIError, atomic_json, read_json, text
from kf_domain_vault import DomainVault, VaultConflict
from kf_styles import public_url, public_addresses

VERSIONS = ('2025-06-18', '2025-03-26')
_TEST_SLOTS = threading.BoundedSemaphore(2)


def endpoint(value):
    try: p = urlsplit(text(value, 'MCP 地址', 2000, True))
    except ValueError: raise AIError('MCP 地址无效') from None
    if p.scheme != 'https' or p.query or p.fragment:
        raise AIError('MCP 地址必须是公开 HTTPS 地址，不含查询参数或片段；凭据请填入 Token')
    return public_url(value)


def rpc(url, token, message, session, version, deadline):
    """Pinned public IP, verified TLS, no redirects, bounded JSON/SSE response."""
    p = urlsplit(endpoint(url)); addresses = public_addresses(p.hostname, 443)
    remaining = deadline - time.monotonic()
    if remaining <= 0: raise AIError('MCP 连接测试超时')
    conn = http.client.HTTPConnection(p.hostname, 443, timeout=min(10, remaining))
    try:
        conn.sock = socket.create_connection((addresses[0], 443), timeout=min(10, remaining))
        conn.sock = ssl.create_default_context().wrap_socket(conn.sock, server_hostname=p.hostname)
        headers = {'Content-Type':'application/json', 'Accept':'application/json, text/event-stream', 'Accept-Encoding':'identity'}
        if token: headers['Authorization'] = 'Bearer ' + token
        if session: headers['Mcp-Session-Id'] = session
        if version: headers['MCP-Protocol-Version'] = version
        conn.request('POST', p.path or '/', json.dumps(message).encode(), headers)
        r = conn.getresponse()
        if r.status not in (200, 202): raise AIError('MCP 返回 HTTP %d，请检查地址、凭据和服务状态' % r.status)
        sid = r.getheader('Mcp-Session-Id', session)
        if sid and (len(sid)>256 or not all(33<=ord(c)<=126 for c in sid)): raise AIError('MCP 会话标识无效')
        if 'id' not in message:
            if r.status != 202: raise AIError('MCP 未接受初始化通知')
            return {}, sid
        kind = r.getheader('Content-Type', '').split(';')[0].strip().lower()
        if kind not in ('application/json','text/event-stream'): raise AIError('MCP 响应类型不受支持')
        if r.getheader('Content-Encoding','identity') not in ('','identity'): raise AIError('MCP 响应压缩不受支持')
        buf = b''; total = 0
        while True:
            remaining = deadline-time.monotonic()
            if remaining<=0: raise AIError('MCP 连接测试超时')
            # The socket can move to HTTPResponse after Connection: close.
            if conn.sock: conn.sock.settimeout(min(10,remaining))
            chunk = r.read1(16384); total += len(chunk)
            if total>1024*1024: raise AIError('MCP 响应超过 1MB 限制')
            buf += chunk
            candidates=[]
            if kind=='text/event-stream':
                buf=buf.replace(b'\r\n',b'\n')
                while b'\n\n' in buf:
                    event,buf=buf.split(b'\n\n',1)
                    data=b'\n'.join(line[5:].lstrip(b' ') for line in event.split(b'\n') if line.startswith(b'data:'))
                    if data:candidates.append(json.loads(data))
            elif not chunk:candidates=[json.loads(buf)]
            for result in candidates:
                if not isinstance(result,dict):raise AIError('MCP 响应格式无效')
                if result.get('id')!=message['id']:continue
                if result.get('jsonrpc')!='2.0' or 'error' in result:raise AIError('MCP 请求失败：'+message['method'])
                if not isinstance(result.get('result'),dict):raise AIError('MCP 返回结果无效')
                return result['result'],sid
            if not chunk:raise AIError('MCP 未返回匹配的请求结果')
    except (OSError,http.client.HTTPException,ValueError) as exc:
        if isinstance(exc,AIError):raise
        raise AIError('MCP 连接或响应解析失败，请检查服务地址、证书与网络') from None
    finally:conn.close()


def discover(item, token):
    deadline=time.monotonic()+45
    result,sid=rpc(item['url'],token,{'jsonrpc':'2.0','id':1,'method':'initialize','params':{
        'protocolVersion':VERSIONS[0], 'capabilities':{}, 'clientInfo':{'name':'MVP-MCP-Manager','version':'1.0'}}},None,None,deadline)
    version=result.get('protocolVersion')
    if version not in VERSIONS:raise AIError('MCP 协议版本不兼容（支持 2025-06-18、2025-03-26）')
    caps=result.get('capabilities',{});info=result.get('serverInfo',{})
    if not isinstance(caps,dict) or not isinstance(info,dict):raise AIError('MCP 初始化结果无效')
    rpc(item['url'],token,{'jsonrpc':'2.0','method':'notifications/initialized'},sid,version,deadline)
    out={'protocol':version,'server':str(info.get('name',''))[:120],'version':str(info.get('version',''))[:80],
         'capabilities':[k for k in ('tools','resources','prompts') if k in caps], 'tools':[], 'resources':[], 'prompts':[], 'truncated':False}
    ident=2
    for kind in out['capabilities']:
        cursor=None
        for page in range(5):
            msg={'jsonrpc':'2.0','id':ident,'method':kind+'/list','params':{}}
            if cursor:msg['params']['cursor']=cursor
            data,_=rpc(item['url'],token,msg,sid,version,deadline);ident+=1
            entries=data.get(kind)
            if not isinstance(entries,list):raise AIError('MCP 能力列表格式无效')
            for entry in entries:
                if not isinstance(entry,dict):raise AIError('MCP 能力条目格式无效')
                if len(out[kind])>=100:out['truncated']=True;break
                out[kind].append({'name':str(entry.get('name',''))[:200], 'description':str(entry.get('description',''))[:1000]})
            cursor=data.get('nextCursor')
            if cursor is not None and (not isinstance(cursor,str) or len(cursor)>2000):raise AIError('MCP 分页游标无效')
            if not cursor:break
            if page==4 or len(out[kind])>=100:out['truncated']=True;break
    return out


class MCPStore(DomainVault):
    def __init__(self,base):
        super().__init__(base)
        self.path=self.root/'mcp-servers.json';self.key_path=self.root/'mcp-vault.key'

    @staticmethod
    def public_item(item):
        return {**{k:v for k,v in item.items() if k!='secret'},'has_token':bool(item.get('secret'))}

    def change(self,body,user):
        with self.locked():
            items=read_json(self.path,[]);ident=text(body.get('id',''),'ID',40,True)
            if not re.fullmatch(r'[a-z][a-z0-9_-]{1,39}',ident):raise AIError('ID 须为 2–40 位小写字母、数字、短横线或下划线，以字母开头')
            old=next((i for i in items if i['id']==ident),None)
            if old and body.get('version')!=old['version']:raise VaultConflict('配置已更新，请刷新后重试')
            if not old and body.get('version') is not None:raise VaultConflict('配置已被删除，请刷新')
            action=body.get('action','save')
            if action=='delete':
                if not old:raise AIError('MCP 配置不存在')
                atomic_json(self.path,[i for i in items if i['id']!=ident]);return self.public_item(old)
            if action!='save':raise AIError('未知 MCP 操作')
            if not old and len(items)>=50:raise AIError('最多保存 50 个 MCP 服务')
            url=endpoint(body.get('url',''))
            token=body.get('token','')
            if not isinstance(token,str) or len(token)>4096 or any(ord(c)<33 or ord(c)>126 for c in token):raise AIError('Token 须为最多 4096 位可打印 ASCII 字符，不含空白')
            if token and body.get('clear_token'):raise AIError('不能同时设置和清除 Token')
            secret=old.get('secret','') if old else ''
            if old and old['url']!=url and secret and not token and not body.get('clear_token'):raise AIError('修改地址时请重新填写或清除 Token，避免将旧凭据发送到新服务')
            if body.get('clear_token'):secret=''
            if token:secret=self.cipher(items).encrypt(json.dumps({'id':ident,'url':url,'token':token}).encode()).decode()
            item={'id':ident,'name':text(body.get('name',''),'名称',80,True),'url':url,
                  'description':text(body.get('description',''),'说明',1000),'enabled':body.get('enabled') is True,
                  'secret':secret,'version':old['version']+1 if old else 1,'updated':int(time.time()),'updated_by':user}
            atomic_json(self.path,[i for i in items if i['id']!=ident]+[item]);return self.public_item(item)

    def test(self,ident,version):
        with self.locked():
            items=read_json(self.path,[]);item=next((copy.deepcopy(i) for i in items if i['id']==ident),None)
            if not item:raise AIError('MCP 配置不存在')
            if item['version']!=version:raise VaultConflict('配置已更新，请刷新后测试')
            if not item['enabled']:raise AIError('请先启用此 MCP 服务')
            token=''
            if item.get('secret'):
                try:
                    payload=json.loads(self.cipher(items).decrypt(item['secret'].encode()))
                    if payload['id']!=item['id'] or payload['url']!=item['url']:raise ValueError()
                    token=payload['token']
                except Exception:raise AIError('MCP 凭据无法解密，请检查密钥备份或重新保存 Token') from None
        # Do not store server-provided data; it may echo secrets. Redact before returning.
        if not _TEST_SLOTS.acquire(blocking=False):raise AIError('已有两个 MCP 测试进行中，请稍后重试')
        try:result=discover(item,token)
        finally:_TEST_SLOTS.release()
        def redact(value):
            if isinstance(value,str):return value.replace(token,'[REDACTED]') if token else value
            if isinstance(value,list):return [redact(v) for v in value]
            if isinstance(value,dict):return {k:redact(v) for k,v in value.items()}
            return value
        return redact(result)
