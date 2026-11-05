"""Fixed-provider API transports. No user-controlled endpoints; no automatic write retry."""
import base64
import datetime
import hashlib
import hmac
import json
import re
import threading
import time
import urllib.request
import urllib.parse
import uuid
from kf_ai import AIError,NoRedirect
from kf_tool_runtime import fingerprint

_TOKEN_CACHE={};_LOCK=threading.Lock()

def request(url,method='GET',body=None,headers=None,form=False):
    data=urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode() if body is not None else None
    if body is None:data=None
    hdr={'Content-Type':'application/x-www-form-urlencoded' if form else 'application/json',**(headers or {})}
    req=urllib.request.Request(url,data=data,headers=hdr,method=method)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as response:
            raw=response.read(2097153)
            if len(raw)>2097152:raise AIError('供应商响应超过 2 MiB，请缩小管理范围')
            return json.loads(raw) if raw else {}
    except Exception as exc:
        if isinstance(exc,AIError):raise
        # Never include provider exception text, request bodies, URLs containing signatures, or credentials.
        raise AIError('供应商 API 请求失败，请核对权限、区域及配置；写操作不会自动重试') from None

def aws_session(c):
    import boto3
    options={'region_name':c.get('region','ap-southeast-1')}
    if c.get('auth','keys')=='keys':options.update(aws_access_key_id=c['access_key'],aws_secret_access_key=c['secret_key'],aws_session_token=c.get('session_token') or None)
    return boto3.Session(**options)

def aws_client(c,service):
    from botocore.config import Config
    return aws_session(c).client(service,config=Config(retries={'total_max_attempts':1},connect_timeout=8,read_timeout=20,ignore_configured_endpoint_urls=True))

def aws_call(c,service,operation,**kwargs):
    try:return getattr(aws_client(c,service),operation)(**kwargs)
    except Exception:raise AIError('AWS API 请求失败，请检查 IAM、区域及资源配置；写操作不会自动重试') from None

def bearer(provider,c):
    key=fingerprint([provider,c]);now=time.time()
    with _LOCK:
        cached=_TOKEN_CACHE.get(key)
        if cached and cached[1]>now+60:return cached[0]
    if provider=='azure':
        response=request('https://login.microsoftonline.com/'+c['tenant_id']+'/oauth2/v2.0/token','POST',
            {'grant_type':'client_credentials','client_id':c['client_id'],'client_secret':c['client_secret'],'scope':'https://management.azure.com/.default'},form=True)
    elif provider=='gcp':
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        data=json.loads(c['service_account'])
        encode=lambda b:base64.urlsafe_b64encode(b).rstrip(b'=')
        token=encode(json.dumps({'alg':'RS256','typ':'JWT'}).encode())+b'.'+encode(json.dumps({'iss':data['client_email'],'scope':'https://www.googleapis.com/auth/cloud-platform','aud':'https://oauth2.googleapis.com/token','iat':int(now),'exp':int(now)+3600}).encode())
        try:
            keyobj=serialization.load_pem_private_key(data['private_key'].encode(),password=None)
            token+=b'.'+encode(keyobj.sign(token,padding.PKCS1v15(),hashes.SHA256()))
        except Exception:raise AIError('Google 服务账号私钥无效') from None
        response=request('https://oauth2.googleapis.com/token','POST',{'grant_type':'urn:ietf:params:oauth:grant-type:jwt-bearer','assertion':token.decode()},form=True)
    else:raise AIError('OAuth 服务商不支持')
    token=response.get('access_token','')
    if not isinstance(token,str) or not token:raise AIError('供应商未返回访问令牌')
    with _LOCK:
        if len(_TOKEN_CACHE)>=100:_TOKEN_CACHE.clear()
        _TOKEN_CACHE[key]=(token,now+min(int(response.get('expires_in',300)),3600))
    return token

def rest(provider,c,path,method='GET',body=None,headers=None):
    host={'azure':'https://management.azure.com','gcp':'https://dns.googleapis.com'}[provider]
    if not path.startswith('/') or path.startswith('//') or '..' in path:raise AIError('API 路径无效')
    return request(host+path,method,body,{'Authorization':'Bearer '+bearer(provider,c),**(headers or {})})

def aliyun(c,action,params,service='alidns'):
    if service not in ('alidns','ecs'):raise AIError('阿里云服务无效')
    encode=lambda s:urllib.parse.quote(str(s),safe='~')
    values={'Format':'JSON','Version':'2015-01-09' if service=='alidns' else '2014-05-26','AccessKeyId':c['access_key'],
            'SignatureMethod':'HMAC-SHA1','SignatureVersion':'1.0','SignatureNonce':uuid.uuid4().hex,
            'Timestamp':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),'Action':action,**params}
    if c.get('session_token'):values['SecurityToken']=c['session_token']
    canonical='&'.join(encode(k)+'='+encode(v) for k,v in sorted(values.items()))
    sign=hmac.new((c['secret_key']+'&').encode(),('POST&%2F&'+encode(canonical)).encode(),hashlib.sha1).digest()
    values['Signature']=base64.b64encode(sign).decode()
    result=request('https://'+service+'.aliyuncs.com/','POST',values,form=True)
    if result.get('Code'):raise AIError('阿里云拒绝操作，请检查权限、线路和记录配置')
    return result

def tencent(c,action,params,service='dnspod'):
    if service not in ('dnspod','cvm'):raise AIError('腾讯云服务无效')
    host=service+'.tencentcloudapi.com';now=int(time.time());date=time.strftime('%Y-%m-%d',time.gmtime(now))
    body=json.dumps(params);content_type='application/json';signed='content-type;host'
    canonical='POST\n/\n\ncontent-type:'+content_type+'\nhost:'+host+'\n\n'+signed+'\n'+hashlib.sha256(body.encode()).hexdigest()
    scope=date+'/'+service+'/tc3_request';string='TC3-HMAC-SHA256\n'+str(now)+'\n'+scope+'\n'+hashlib.sha256(canonical.encode()).hexdigest()
    digest=lambda k,v:hmac.new(k,v.encode(),hashlib.sha256).digest()
    key=digest(digest(digest(('TC3'+c['secret_key']).encode(),date),service),'tc3_request')
    signature=hmac.new(key,string.encode(),hashlib.sha256).hexdigest()
    headers={'Authorization':'TC3-HMAC-SHA256 Credential='+c['access_key']+'/'+scope+', SignedHeaders='+signed+', Signature='+signature,
             'X-TC-Action':action,'X-TC-Version':'2021-03-23' if service=='dnspod' else '2017-03-12','X-TC-Timestamp':str(now),'X-TC-Region':c.get('region','')}
    if c.get('session_token'):headers['X-TC-Token']=c['session_token']
    result=request('https://'+host+'/','POST',params,headers).get('Response',{})
    if result.get('Error'):raise AIError('腾讯云拒绝操作，请检查权限、线路和记录配置')
    return result

def quote(value):return urllib.parse.quote(str(value),safe='')

def inventory(provider,c):
    """A bounded, read-only view of the configured account scope. No lifecycle actions."""
    if provider=='aws':
        data=aws_call(c,'ec2','describe_instances',MaxResults=100);items=[i for r in data.get('Reservations',[]) for i in r.get('Instances',[])]
        result=[{'id':i['InstanceId'],'name':next((t['Value'] for t in i.get('Tags',[]) if t['Key']=='Name'),''),'state':i.get('State',{}).get('Name'),'type':i.get('InstanceType'),'zone':i.get('Placement',{}).get('AvailabilityZone')} for i in items]
        more=bool(data.get('NextToken'))
    elif provider=='azure':
        data=rest(provider,c,'/subscriptions/'+quote(c['subscription_id'])+'/resourceGroups/'+quote(c['resource_group'])+'/providers/Microsoft.Compute/virtualMachines?api-version=2024-07-01')
        result=[{'id':i['id'],'name':i['name'],'state':i.get('properties',{}).get('provisioningState'),'type':i.get('properties',{}).get('hardwareProfile',{}).get('vmSize'),'zone':i.get('location')} for i in data.get('value',[])[:100]];more=bool(data.get('nextLink')) or len(data.get('value',[]))>100
    elif provider=='gcp':
        data=request('https://compute.googleapis.com/compute/v1/projects/'+quote(c['project_id'])+'/aggregated/instances?maxResults=100',headers={'Authorization':'Bearer '+bearer(provider,c)})
        result=[{'id':i['id'],'name':i['name'],'state':i.get('status'),'type':i.get('machineType','').split('/')[-1],'zone':i.get('zone','').split('/')[-1]} for g in data.get('items',{}).values() for i in g.get('instances',[])];more=bool(data.get('nextPageToken'))
    elif provider=='aliyun':
        data=aliyun(c,'DescribeInstances',{'RegionId':c['region'],'PageSize':100},'ecs');result=[{'id':i['InstanceId'],'name':i.get('InstanceName'),'state':i.get('Status'),'type':i.get('InstanceType'),'zone':i.get('ZoneId')} for i in data.get('Instances',{}).get('Instance',[])];more=data.get('TotalCount',0)>100
    elif provider=='tencent':
        data=tencent(c,'DescribeInstances',{'Limit':100},'cvm');result=[{'id':i['InstanceId'],'name':i.get('InstanceName'),'state':i.get('InstanceState'),'type':i.get('InstanceType'),'zone':i.get('Placement',{}).get('Zone')} for i in data.get('InstanceSet',[])];more=data.get('TotalCount',0)>100
    elif provider=='cloudflare':
        data=request('https://api.cloudflare.com/client/v4/zones?per_page=50',headers={'Authorization':'Bearer '+c['token']})
        if not data.get('success'):raise AIError('Cloudflare 拒绝区域查询')
        result=[{'id':i['id'],'name':i['name'],'state':i.get('status'),'type':'DNS Zone'} for i in data.get('result',[])];more=data.get('result_info',{}).get('total_pages',1)>1
    else:raise AIError('此服务商不提供云资源清单')
    return {'provider':provider,'items':result,'truncated':more,'note':'只读清单，范围由账号权限和配置的区域/资源组/项目决定；不代表应用或网站健康状态。'}

class MCPAuth:
    """Ephemeral signer; never serialized into MCP configs or operation tickets."""
    def __init__(self,provider,credentials,version):self.provider=provider;self.credentials=credentials;self.version=version;self._signing_secrets=[]
    def headers(self,url,data,headers):
        if self.provider=='cloudflare':
            if urllib.parse.urlsplit(url).hostname!='mcp.cloudflare.com':raise AIError('Cloudflare 凭据只能用于官方 MCP')
            return {**headers,'Authorization':'Bearer '+self.credentials['token']}
        match=re.fullmatch(r'https://aws-mcp\.([a-z0-9-]+)\.api\.aws/mcp',url)
        if not match:raise AIError('AWS 签名只能用于官方 AWS MCP 地址')
        try:
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
            credentials=aws_session(self.credentials).get_credentials()
            if credentials is None:raise ValueError()
            frozen=credentials.get_frozen_credentials();self._signing_secrets=[v for v in (frozen.access_key,frozen.secret_key,frozen.token) if v]
            request=AWSRequest(method='POST',url=url,data=data,headers=headers)
            SigV4Auth(frozen,'aws-mcp',match[1]).add_auth(request)
            return dict(request.headers)
        except Exception:raise AIError('AWS MCP 凭据获取或签名失败') from None
    def redact(self,value):
        for secret in self._signing_secrets:value=value.replace(secret,'[REDACTED]')
        for key in ('token','access_key','secret_key','session_token'):
            if self.credentials.get(key):value=value.replace(self.credentials[key],'[REDACTED]')
        return value


def namecom(c,path,method='GET',body=None):
    if not path.startswith('/domains/') or '..' in path or '#' in path:raise AIError('Name.com API 路径无效')
    auth=base64.b64encode((c['username']+':'+c['token']).encode()).decode()
    return request('https://api.name.com/core/v1'+path,method,body,{'Authorization':'Basic '+auth})
