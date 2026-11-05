"""Singapore provider transports with fixed operations and sanitized inventory output."""
import base64
import http.client
import json
import re
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from kf_ai import AIError, NoRedirect
from kf_cloud_api import request, quote
from kf_styles import public_addresses
from kf_tool_runtime import fingerprint

_CACHE = {}
_LOCK = threading.Lock()
_LIMIT = 2 * 1024 * 1024


def webnic(c, path, method='GET', body=None):
    if not path.startswith('/dns/v2/'):raise AIError('WebNIC API 路径不支持')
    host = 'https://oteapi.webnic.cc' if c['environment']=='ote' else 'https://api.webnic.cc'
    key = fingerprint(['webnic', c]);now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached[1] > now + 60:token = cached[0]
        else:
            result = request(host+'/reseller/v2/api-user/token','POST',{'username':c['username'],'password':c['password']})
            if str(result.get('code'))!='1000':raise AIError('WebNIC 认证失败，请检查 API 凭据、环境及 IP 白名单')
            data = result.get('data',{});token = data.get('access_token')
            if not isinstance(token,str) or not token or any(ord(x)<33 or ord(x)>126 for x in token):raise AIError('WebNIC 未返回有效访问令牌')
            if len(_CACHE)>=100:_CACHE.clear()
            _CACHE[key] = (token, now+min(int(data.get('expires_in',3600)),3600))
    result = request(host+path,method,body,{'Authorization':'Bearer '+token})
    if str(result.get('code'))!='1000':raise AIError('WebNIC 拒绝操作，请检查 DNS 服务、权限及 IP 白名单；写操作不自动重试')
    data=result.get('data')
    if isinstance(data,dict) and data.get('saved') is False:raise AIError('WebNIC 未保存记录，请核实状态')
    return data


def cpanel_endpoint(value):
    try:
        p = urllib.parse.urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/') or p.port not in (None,443,2083):raise ValueError()
        if any(ord(x)<33 or ord(x)>126 for x in value) or '\\' in value:raise ValueError()
        host=p.hostname
        if not re.fullmatch(r'[A-Za-z0-9.-]+',host) or '.' not in host:raise ValueError()
        return host,p.port or 443
    except ValueError:raise AIError('cPanel 地址须为公开 HTTPS 主机，端口仅支持 2083 / 443，不含路径或登录信息') from None


def cpanel(c, module, function, params=None):
    if (module,function) not in (('DNS','parse_zone'),('DNS','mass_edit_zone'),('DomainInfo','list_domains')):raise AIError('cPanel 操作不支持')
    host,port=cpanel_endpoint(c['endpoint'])
    # Resolve and pin immediately before sending credentials; no redirects, cookies or retries.
    addresses=public_addresses(host,port)
    deadline=time.monotonic()+30
    conn=http.client.HTTPConnection(host,port,timeout=20)
    try:
        conn.sock=socket.create_connection((addresses[0],port),timeout=8)
        conn.sock=ssl.create_default_context().wrap_socket(conn.sock,server_hostname=host)
        conn.sock.settimeout(20)
        query=urllib.parse.urlencode(params or {})
        path='/execute/'+module+'/'+function
        headers={'Authorization':'cpanel '+c['username']+':'+c['token'],'Accept':'application/json','Accept-Encoding':'identity'}
        # UAPI accepts form POST as well as the documented URL query form.
        if function=='mass_edit_zone':
            headers['Content-Type']='application/x-www-form-urlencoded';conn.request('POST',path,query.encode(),headers)
        else:conn.request('GET',path+('?' + query if query else ''),headers=headers)
        response=conn.getresponse()
        if response.status!=200 or response.getheader('Content-Encoding','identity') not in ('','identity'):raise AIError('cPanel 请求失败，请检查地址、Token 和套餐权限')
        chunks=[];size=0
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise AIError('cPanel 响应超时')
            if conn.sock:conn.sock.settimeout(min(20,remaining))
            chunk=response.read1(16384);size+=len(chunk)
            if size>_LIMIT:raise AIError('cPanel 响应超过管理上限')
            if not chunk:break
            chunks.append(chunk)
        raw=b''.join(chunks)
        result=json.loads(raw).get('result',{})
        if result.get('status')!=1 or result.get('errors'):raise AIError('cPanel 拒绝操作，请检查权限或 DNS 区域版本并重新预览')
        return result.get('data')
    except AIError:raise
    except Exception:raise AIError('cPanel 连接或响应异常；操作不会自动重试，请核实结果') from None
    finally:conn.close()


def readyspace(c,path):
    if path not in ('/domain','/service'):raise AIError('ReadySpace 当前仅支持域名和服务清单查询')
    if c['auth']=='bearer':headers={'Authorization':'Bearer '+c['token']}
    else:headers={'Authorization':'Basic '+base64.b64encode((c['username']+':'+c['password']).encode()).decode()}
    data=request('https://cloud.readyspace.com.sg/api'+path,headers=headers)
    if not isinstance(data,dict) or data.get('error') or data.get('errors') or data.get('success') is False:raise AIError('ReadySpace 查询失败，请检查账号权限和认证状态')
    return data


SOAP='http://www.w3.org/2003/05/soap-envelope'

def vodien(c,operation,domain=None):
    if operation not in ('GetDomainList','DomainInfo'):raise AIError('Vodien 当前仅支持域名查询')
    url='https://soap-test.secureapi.com.au/API-2.1' if c['environment']=='test' else 'https://soap.secureapi.com.au/API-2.1'
    root=ET.Element('{'+SOAP+'}Envelope');header=ET.SubElement(root,'{'+SOAP+'}Header')
    auth=ET.SubElement(ET.SubElement(header,'{'+url+'}Authenticate'),'AuthenticateRequest')
    ET.SubElement(auth,'ResellerID').text=c['reseller_id'];ET.SubElement(auth,'APIKey').text=c['api_key']
    op=ET.SubElement(ET.SubElement(root,'{'+SOAP+'}Body'),'{'+url+'}'+operation)
    if operation=='DomainInfo':ET.SubElement(ET.SubElement(op,'DomainInfoRequest'),'DomainName').text=domain
    req=urllib.request.Request(url,data=ET.tostring(root,encoding='utf-8',xml_declaration=True),method='POST',headers={
        'Content-Type':'application/soap+xml; charset=utf-8; action="urn:API-2.1#API-2.1Server#'+operation+'"','Accept-Encoding':'identity'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as response:
            raw=response.read(_LIMIT+1)
            if len(raw)>_LIMIT:raise AIError('Vodien 响应超过管理上限')
        raw=raw.decode('utf-8')
        if '\x00' in raw or '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():raise AIError('Vodien XML 响应包含不支持的声明')
        doc=ET.fromstring(raw)
        for e in doc.iter():e.tag=e.tag.rsplit('}',1)[-1]
        if doc.tag!='Envelope' or doc.find('./Body/Fault') is not None:raise AIError('Vodien SOAP 请求失败，请检查经销商 API 权限')
        for e in doc.iter():
            if e.tag=='Errors' and len(e) or e.tag=='Success' and e.text not in ('true','1'):raise AIError('Vodien 拒绝查询，请检查经销商 API 凭据及 IP 白名单')
        result=doc.find('./Body/'+operation+'Response')
        if result is None:raise AIError('Vodien 返回了不匹配的操作响应')
        return result
    except AIError:raise
    except Exception:raise AIError('Vodien 连接或响应异常，请检查经销商 API 配置') from None


def inventory(provider,c,domain=None):
    items=[]
    if provider=='readyspace':
        for path,key in (('/domain','domains'),('/service','services')):
            data=readyspace(c,path)
            if not isinstance(data.get(key),list):raise AIError('ReadySpace 未返回有效清单，请检查认证与权限')
            for r in data[key]:
                items.append({'id':str(r.get('id','')),'name':r.get('name') if key=='domains' else r.get('domain') or r.get('name'),
                    'type':'域名' if key=='domains' else r.get('category','服务'),'state':r.get('status',''),
                    'expires':r.get('expires') if key=='domains' else r.get('next_due')})
    elif provider=='cpanel':
        data=cpanel(c,'DomainInfo','list_domains')
        if not isinstance(data,dict) or not data.get('main_domain'):raise AIError('cPanel 未返回有效域名清单')
        for key,label in (('main_domain','主域名'),('addon_domains','附加域名'),('parked_domains','别名域名'),('sub_domains','子域名')):
            names=[data[key]] if key=='main_domain' else data.get(key,[])
            items.extend({'id':name,'name':name,'type':label,'state':'已配置'} for name in names)
    elif provider=='vodien':
        data=vodien(c,'GetDomainList');listing=data.find('.//DomainList')
        if listing is None:raise AIError('Vodien 未返回域名清单')
        for row in listing:
            name=row.findtext('DomainName')
            if not name:raise AIError('Vodien 域名清单格式无效')
            items.append({'id':name,'name':name,'type':'域名','state':row.findtext('Status','')})
        # Retrieve expiry only for the current site's exact registered domain, never transfer credentials.
        target=next((r for r in items if r['name']==domain),None)
        if target is not None:
            detail=vodien(c,'DomainInfo',domain).find('.//DomainDetails')
            if detail is None or detail.findtext('DomainName')!=domain:raise AIError('Vodien 返回的域名详情不匹配')
            target.update(expires=detail.findtext('Expiry',''),locked=detail.findtext('LockStatus',''))
    else:raise AIError('供应商资源查询不支持')
    return {'provider':provider,'items':items[:200],'truncated':len(items)>200,
        'note':'只读账号资源清单；到期日期以服务商为准。仅查询，不自动续费、购买或取消服务。'}

_PROBE_SLOTS=threading.BoundedSemaphore(2)

def probe(provider,c):
    """Explicit administrator connection check. Never calls a mutation endpoint."""
    if not _PROBE_SLOTS.acquire(blocking=False):raise AIError('已有连接测试正在进行，请稍后重试')
    try:
        if provider=='webnic':
            ns=webnic(c,'/dns/v2/zone/basic/record/nameservers')
            if not isinstance(ns,list) or not ns:raise AIError('WebNIC 未返回有效结果')
            count=len(ns)
        else:count=len(inventory(provider,c)['items'])
        return {'provider':provider,'ok':True,'count':count,'message':'只读连接测试成功；未验证 DNS 写入权限，也未修改资源。'}
    finally:_PROBE_SLOTS.release()
