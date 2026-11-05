"""Admin-managed remote MCP connections. Discovery only; never executes tools."""
import copy
import http.client
import json
import re
import socket
import ssl
import time
import threading
import subprocess
import sys
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
                record={'name':str(entry.get('name',''))[:200], 'description':str(entry.get('description',''))[:1000]}
                for key in ('inputSchema','outputSchema','uri','mimeType','arguments'):
                    if key in entry:
                        if len(json.dumps(entry[key]))>24000:raise AIError('MCP 能力定义过大')
                        record[key]=entry[key]
                out[kind].append(record)
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
                  'policy':policy_config(body.get('policy',old.get('policy',{}) if old else {})),
                  'secret':secret,'version':old['version']+1 if old else 1,'updated':int(time.time()),'updated_by':user}
            atomic_json(self.path,[i for i in items if i['id']!=ident]+[item]);return self.public_item(item)

    def resolve_call(self,ident,slug,purpose,kind,name,arguments,context,expected_version=None):
        with self.locked():
            items=read_json(self.path,[]);item=next((copy.deepcopy(i) for i in items if i['id']==ident),None)
            if not item or not item['enabled']:raise AIError('MCP 服务不存在或已停用')
            if expected_version is not None and item['version']!=expected_version:raise VaultConflict('MCP 配置已改变，请重新生成操作')
            policy=policy_config(item.get('policy',{}))
            if slug not in policy['sites'] or purpose not in policy['purposes']:raise AIError('MCP 服务未授权用于此站点或功能')
            if kind not in ('tools','resources','prompts'):raise AIError('MCP 能力类型无效')
            if not isinstance(arguments,dict):raise AIError('工具参数须为对象')
            arguments=copy.deepcopy(arguments);mode='read'
            if kind=='tools':
                rule=next((r for r in policy['tools'] if r['name']==name),None)
                if not rule:raise AIError('工具不在管理员白名单中')
                mode=rule['mode']
                for key,value in rule['bindings'].items():
                    value={'$site':slug,'$domain':context['domain']}.get(value,value)
                    if key in arguments and arguments[key]!=value:raise AIError('参数超出管理员绑定的站点范围：'+key)
                    arguments[key]=value
            elif name not in policy[kind]:raise AIError('资源或提示词不在管理员白名单中')
            if kind=='resources' and arguments:raise AIError('资源读取不能附加工具参数')
            if kind=='prompts' and any(not isinstance(k,str) or not isinstance(v,str) for k,v in arguments.items()):raise AIError('提示词参数须为文本')
            reject_argument_secrets(arguments)
            token=''
            if item.get('secret'):
                try:
                    payload=json.loads(self.cipher(items).decrypt(item['secret'].encode()))
                    if payload['id']!=ident or payload['url']!=item['url']:raise ValueError()
                    token=payload['token']
                except Exception:raise AIError('MCP 凭据无法解密，请检查密钥备份') from None
            return item,token,arguments,mode

    def call(self,request,context):
        item,token,args,mode=self.resolve_call(request['server'],request['slug'],request['purpose'],request['kind'],
            request['name'],request['arguments'],context,request['server_version'])
        with self.locked():
            path=self.root/'mcp-usage.json';usage=read_json(path,{})
            now=time.time();recent=[v for v in usage.get(item['id'],[]) if v>now-3600]
            if len(recent)>=item['policy']['calls_per_hour']:raise AIError('MCP 服务已达到每小时调用上限')
            usage[item['id']]=recent+[now];atomic_json(path,usage)
        if not _TEST_SLOTS.acquire(blocking=False):raise AIError('MCP 连接繁忙，请稍后重试')
        try:result=invoke(item,token,request['kind'],request['name'],args,request.get('schema'))
        finally:_TEST_SLOTS.release()
        def redact(v):
            if isinstance(v,str):return v.replace(token,'[REDACTED]') if token else v
            if isinstance(v,list):return [redact(x) for x in v]
            if isinstance(v,dict):return {k:redact(x) for k,x in v.items()}
            return v
        return redact(result)

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


def policy_config(value):
    if not isinstance(value,dict):raise AIError('MCP 使用策略必须是对象')
    purposes=value.get('purposes',[]);sites=value.get('sites',[])
    if not isinstance(purposes,list) or any(p not in ('build','dns','mail','maintenance') for p in purposes):raise AIError('MCP 用途无效')
    if not isinstance(sites,list) or len(sites)>100 or any(not isinstance(v,str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,19}',v) for v in sites):raise AIError('请选择具体站点范围')
    entries=value.get('tools',[])
    if not isinstance(entries,list) or len(entries)>100:raise AIError('工具白名单最多 100 条')
    tools=[]
    for entry in entries:
        if not isinstance(entry,dict):raise AIError('工具规则无效')
        name=text(entry.get('name',''),'工具名',200,True);mode=entry.get('mode','confirm')
        if mode not in ('read','confirm','totp'):raise AIError('工具执行规则无效')
        bindings=entry.get('bindings',{})
        if not isinstance(bindings,dict) or len(bindings)>20 or any(not isinstance(k,str) or not isinstance(v,str) or len(k)>100 or len(v)>500 for k,v in bindings.items()):raise AIError('工具固定参数无效')
        tools.append({'name':name,'mode':mode,'bindings':bindings})
    if len({x['name'] for x in tools})!=len(tools):raise AIError('工具白名单不能有重复名称')
    lists={}
    for key in ('resources','prompts'):
        values=value.get(key,[])
        if not isinstance(values,list) or len(values)>100 or any(not isinstance(v,str) or not v or len(v)>2000 for v in values):raise AIError('资源或提示词白名单无效')
        lists[key]=list(dict.fromkeys(values))
    try:limit=int(value.get('calls_per_hour',30));timeout=int(value.get('timeout',30))
    except (TypeError,ValueError):raise AIError('调用次数或超时无效') from None
    if not 1<=limit<=120 or not 5<=timeout<=45:raise AIError('调用上限 1–120 次/小时，超时 5–45 秒')
    return {'purposes':list(dict.fromkeys(purposes)),'sites':list(dict.fromkeys(sites)), 'tools':tools,**lists,'calls_per_hour':limit,'timeout':timeout}


def validate_schema(schema,arguments):
    # Validate in a bounded process: hostile regex/schema recursion must not stall the web server.
    if not isinstance(schema,dict) or len(json.dumps(schema))>24000:raise AIError('工具参数定义缺失或过大')
    if not isinstance(arguments,dict) or len(json.dumps(arguments))>40000:raise AIError('工具参数必须是有限大小的对象')
    script="""import sys,json
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import NoSuchResource
s,a=json.load(sys.stdin)
def deny(uri):raise NoSuchResource(ref=uri)
try:
 v=validator_for(s);v.check_schema(s);v(s,registry=Registry(retrieve=deny)).validate(a)
except Exception:sys.exit(2)
"""
    try:
        result=subprocess.run([sys.executable,'-c',script],input=json.dumps([schema,arguments]),text=True,
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
    except subprocess.TimeoutExpired:raise AIError('工具参数定义校验超时') from None
    if result.returncode:raise AIError('参数不符合工具定义，或定义包含不可用的外部引用')


def invoke(item,token,kind,name,arguments,schema=None):
    deadline=time.monotonic()+item.get('policy',{}).get('timeout',30)
    init,sid=rpc(item['url'],token,{'jsonrpc':'2.0','id':1,'method':'initialize','params':{
        'protocolVersion':VERSIONS[0],'capabilities':{},'clientInfo':{'name':'MVP-Automation','version':'1.0'}}},None,None,deadline)
    version=init.get('protocolVersion')
    if version not in VERSIONS:raise AIError('MCP 协议不兼容')
    if kind not in init.get('capabilities',{}):raise AIError('MCP 服务已撤销该能力')
    rpc(item['url'],token,{'jsonrpc':'2.0','method':'notifications/initialized'},sid,version,deadline)
    if kind=='tools':
        # Discover the exact current input schema before executing; a changed definition invalidates approval.
        cursor=None;found=None
        for page in range(5):
            data,_=rpc(item['url'],token,{'jsonrpc':'2.0','id':2+page,'method':'tools/list','params':{'cursor':cursor} if cursor else {}},sid,version,deadline)
            entries=data.get('tools',[])
            if not isinstance(entries,list):raise AIError('MCP 工具列表无效')
            found=next((t for t in entries if isinstance(t,dict) and t.get('name')==name),None)
            if found:break
            cursor=data.get('nextCursor')
            if not cursor:break
        if not found or found.get('inputSchema')!=schema:raise AIError('工具定义已改变，请重新生成并确认操作')
        validate_schema(schema,arguments)
        method='tools/call';params={'name':name,'arguments':arguments}
    elif kind=='resources':method='resources/read';params={'uri':name}
    elif kind=='prompts':method='prompts/get';params={'name':name,'arguments':arguments}
    else:raise AIError('MCP 能力类型无效')
    result,_=rpc(item['url'],token,{'jsonrpc':'2.0','id':20,'method':method,'params':params},sid,version,deadline)
    if result.get('isError'):raise AIError('MCP 工具执行返回错误，请检查服务端记录')
    return result


def reject_argument_secrets(value):
    if isinstance(value,dict):
        for key,child in value.items():
            if str(key).lower().replace('-','_') in ('api_key','apikey','password','access_token','refresh_token','authorization','cookie','client_secret','secret'):
                raise AIError('凭据请保存在 MCP 连接配置中，不能作为工具参数或模型资料')
            reject_argument_secrets(child)
    elif isinstance(value,list):
        for child in value:reject_argument_secrets(child)
