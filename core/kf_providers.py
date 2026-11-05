"""Provider accounts with encrypted, binding-aware credentials and explicit site scopes."""
import copy
import json
import re
import time
from kf_ai import AIError,atomic_json,read_json,text
from kf_domain_vault import DomainVault,VaultConflict

# Field schemas drive both server validation and the administrator form.
def field(key,label,secret=False,required=True,default=''):
    return {'key':key,'label':label,'secret':secret,'required':required,'default':default}
CATALOG={
 'cloudflare':{'name':'Cloudflare','capabilities':['dns','cloud','mcp'],'fields':[field('token','API Token',True)]},
 'aws':{'name':'AWS','capabilities':['dns','cloud','mail','mcp'],'fields':[field('region','区域',default='ap-southeast-1'),field('auth','认证：keys 或 role',default='keys'),field('access_key','Access Key ID',True,False),field('secret_key','Secret Access Key',True,False),field('session_token','Session Token（临时凭据）',True,False),field('sender','SES 发件人',False,False)]},
 'azure':{'name':'Microsoft Azure','capabilities':['dns','cloud'],'fields':[field('tenant_id','Tenant ID'),field('client_id','Client ID'),field('subscription_id','Subscription ID'),field('resource_group','Resource Group'),field('client_secret','Client Secret',True)]},
 'gcp':{'name':'Google Cloud','capabilities':['dns','cloud'],'fields':[field('project_id','Project ID'),field('service_account','Service Account JSON',True)]},
 'aliyun':{'name':'阿里云','capabilities':['dns','cloud'],'fields':[field('region','区域',default='cn-hangzhou'),field('access_key','AccessKey ID',True),field('secret_key','AccessKey Secret',True),field('session_token','STS Token',True,False)]},
 'tencent':{'name':'腾讯云','capabilities':['dns','cloud'],'fields':[field('region','区域',default='ap-singapore'),field('access_key','SecretId',True),field('secret_key','SecretKey',True),field('session_token','临时 Token',True,False)]},
 'smtp':{'name':'通用 SMTP（企业邮箱 / 邮件服务商）','capabilities':['mail'],'fields':[field('host','SMTP 主机'),field('port','TLS 端口：465 或 587',default='587'),field('user','SMTP 用户名',True),field('password','SMTP 密码 / 应用密码',True),field('sender','发件人')]},
}
CATALOG['namecom']={'name':'Name.com','capabilities':['dns'],'fields':[field('username','API 用户名',True),field('token','API Token',True)],'note':'Core API：DNS 查询与变更；域名必须使用 Name.com 权威 DNS。不包含注册、续费和转移。'}
CATALOG['cldy']={'name':'CLDY（新加坡）','capabilities':['mail'],'fields':copy.deepcopy(CATALOG['smtp']['fields']),'note':'通过 SMTP 发送邮件。主机、端口和邮箱凭据以 CLDY 开通信息为准；DNS / 主机管理请使用 CLDY 或 cPanel 后台。尚未接入 CLDY 管理 API。'}
for ident,label in [('resend','Resend'),('sendgrid','SendGrid'),('postmark','Postmark'),('brevo','Brevo')]:
    CATALOG[ident]={'name':label,'capabilities':['mail'],'fields':[field('api_key','API Key / Server Token',True),field('sender','发件人')]}
CATALOG['mailgun']={'name':'Mailgun','capabilities':['mail'],'fields':[field('api_key','API Key',True),field('domain','发送域名'),field('region','API 区域：us 或 eu',default='us'),field('sender','发件人')]}

CATALOG['webnic']={'name':'WebNIC','capabilities':['dns'],'fields':[field('environment','API 环境：production 或 ote',default='production'),field('username','API 用户名',True),field('password','API Secret Key',True)],'note':'经销商 DNS API v2；需开通 API 并设置服务器出口 IP 白名单。公网 DNS 绑定仅支持 production。保留同名记录集其他值；不购买域名或订阅。'}
CATALOG['cpanel']={'name':'通用 cPanel（CLDY / Oryon / HostSG 等）','capabilities':['dns','cloud'],'fields':[field('endpoint','cPanel HTTPS 地址（例如 https://panel.example.com:2083）'),field('username','cPanel 用户名',True),field('token','cPanel API Token',True)],'note':'需供应商套餐开放 cPanel API Token 和 DNS 权限。支持 DNS 变更及托管域名清单；要求有效 TLS 证书和公网地址。供应商品牌本身不保证 API 可用。'}
CATALOG['vodien']={'name':'Vodien / Dreamscape 经销商','capabilities':['cloud'],'fields':[field('environment','API 环境：production 或 test',default='production'),field('reseller_id','Reseller ID',True),field('api_key','API Key',True)],'note':'使用 Dreamscape SOAP 2.1 经销商 API 查询域名清单；当前站点恰为注册域名时查询到期信息。需经销商 API 权限，普通门户密码不可代替；暂不支持 DNS 写入、注册或续费。'}
CATALOG['readyspace']={'name':'ReadySpace Singapore','capabilities':['cloud'],'fields':[field('auth','认证方式：bearer 或 basic',default='bearer'),field('token','Bearer Token',True,False),field('username','Basic 用户名',True,False),field('password','Basic 密码',True,False)],'note':'仅查询新加坡账户的域名、服务和到期信息。优先使用完成供应商授权后的 Bearer Token；过期需更新，不自动绕过 MFA 或续费。'}

for ident in ('webnic','cpanel','vodien','readyspace'):CATALOG[ident]['can_test']=True

class ProviderStore(DomainVault):
    def __init__(self,base):
        super().__init__(base);self.path=self.root/'providers.json';self.key_path=self.root/'providers.key'
    @staticmethod
    def public_item(item):
        return {k:copy.deepcopy(v) for k,v in item.items() if k!='secret'}
    def save(self,body,user):
        ident=text(body.get('id',''),'账号 ID',40,True)
        if not re.fullmatch(r'[a-z][a-z0-9_-]{1,39}',ident):raise AIError('账号 ID 需要 2–40 位小写字母数字、短横线或下划线')
        with self.locked():
            items=read_json(self.path,[]);old=next((i for i in items if i['id']==ident),None)
            if old and body.get('version')!=old['version']:raise VaultConflict('供应商配置已改变，请刷新')
            if not old and body.get('version') is not None:raise VaultConflict('供应商配置已被删除')
            if body.get('action')=='delete':
                if not old:raise AIError('账号不存在')
                atomic_json(self.path,[i for i in items if i['id']!=ident]);return self.public_item(old)
            if body.get('action','save')!='save':raise AIError('操作无效')
            provider=text(body.get('provider',''),'供应商',40,True)
            if provider not in CATALOG:raise AIError('供应商不支持')
            if old and old['provider']!=provider:raise AIError('已有账号不能更换供应商，请新建账号')
            sites=body.get('sites',[]);caps=body.get('capabilities',[])
            if not isinstance(sites,list) or not sites or len(sites)>100 or any(not isinstance(s,str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,19}',s) for s in sites):raise AIError('请选择具体站点')
            if not isinstance(caps,list) or not caps or any(c not in CATALOG[provider]['capabilities'] for c in caps):raise AIError('请选择供应商实际支持的能力')
            values=body.get('values',{})
            if not isinstance(values,dict):raise AIError('配置字段必须是对象')
            fields=CATALOG[provider]['fields'];allowed={f['key'] for f in fields}
            if set(values)-allowed:raise AIError('包含未知供应商字段')
            merged={**(old.get('config',{}) if old else {})}
            if old and old.get('secret'):merged.update(self.decrypt(old,items))
            for f in fields:
                val=values.get(f['key'],merged.get(f['key'],f['default']))
                if f['secret'] and val=='':val=merged.get(f['key'],'')
                merged[f['key']]=text(val,f['label'],16000 if f['key']=='service_account' else 4096,f['required'])
            if old and provider in ('smtp','cldy') and merged.get('host')!=old['config'].get('host'):
                if not values.get('password'):raise AIError('更换 SMTP 主机需要重新填写密码，防止将旧凭据发送到新主机')
            if old and provider=='cpanel' and merged.get('endpoint')!=old['config'].get('endpoint'):
                if not values.get('token'):raise AIError('更换 cPanel 地址需要重新填写 API Token')
            if old and provider in ('webnic','vodien') and merged.get('environment')!=old['config'].get('environment'):
                if not all(values.get(f['key']) for f in fields if f['secret']):raise AIError('更换 API 环境需要重新填写该环境的全部凭据')
            validate(provider,merged)
            if 'mail' in caps and not merged.get('sender'):raise AIError('启用邮件能力需要填写发件人')
            secret={f['key']:merged[f['key']] for f in fields if f['secret']}
            config={f['key']:merged[f['key']] for f in fields if not f['secret']}
            # Credentials are bound to the full non-secret configuration, not merely the account name.
            payload={'id':ident,'provider':provider,'config':config,'credentials':secret}
            item={'id':ident,'name':text(body.get('name',''),'账号名称',100,True),'provider':provider,'sites':sorted(set(sites)),
                  'capabilities':sorted(set(caps)),'enabled':body.get('enabled') is True,'config':config,
                  'credential_fields':[k for k,v in secret.items() if v], 'version':old['version']+1 if old else 1,
                  'updated':int(time.time()),'updated_by':user,'secret':self.cipher(items).encrypt(json.dumps(payload).encode()).decode()}
            if not old and len(items)>=100:raise AIError('最多配置 100 个账号')
            atomic_json(self.path,[i for i in items if i['id']!=ident]+[item]);return self.public_item(item)
    def decrypt(self,item,items):
        try:
            payload=json.loads(self.cipher(items).decrypt(item['secret'].encode()))
            if any(payload.get(k)!=item[k] for k in ('id','provider','config')):raise ValueError()
            return payload['credentials']
        except Exception:raise AIError('供应商凭据无法解密，请检查数据和密钥备份') from None
    def resolve(self,ident,slug,capability):
        with self.locked():
            items=read_json(self.path,[]);item=next((i for i in items if i['id']==ident),None)
            if not item or not item['enabled']:raise AIError('供应商账号不存在或已停用')
            if slug not in item['sites'] or capability not in item['capabilities']:raise AIError('账号未授权用于此站点或能力')
            return self.public_item(item),{**item['config'],**self.decrypt(item,items)}
    def scoped(self,slug,capability):
        return [i for i in self.public() if i['enabled'] and slug in i['sites'] and capability in i['capabilities']]

def validate(provider,c):
    if provider=='webnic' and c['environment'] not in ('production','ote'):raise AIError('WebNIC 环境仅支持 production / ote')
    if provider=='vodien':
        if c['environment'] not in ('production','test'):raise AIError('Vodien 环境仅支持 production / test')
        if not re.fullmatch(r'[0-9]{1,20}',c['reseller_id']):raise AIError('Reseller ID 必须是数字')
    if provider=='cpanel':
        from kf_sg_providers import cpanel_endpoint
        cpanel_endpoint(c['endpoint'])
        if not re.fullmatch(r'[a-zA-Z0-9_]{1,32}',c['username']):raise AIError('cPanel 用户名格式无效')
        if not re.fullmatch(r'[!-~]{1,4096}',c['token']):raise AIError('cPanel Token 格式无效')
    if provider=='readyspace':
        if c['auth'] not in ('bearer','basic'):raise AIError('ReadySpace 认证方式仅支持 bearer / basic')
        if c['auth']=='bearer' and (not c['token'] or not re.fullmatch(r'[!-~]+',c['token'])):raise AIError('请填写有效 Bearer Token')
        if c['auth']=='basic' and (not c['username'] or not c['password'] or ':' in c['username']):raise AIError('请填写有效 Basic 用户名和密码')
    if provider=='namecom' and ':' in c['username']:raise AIError('API 用户名不能包含冒号')
    if provider=='aws':
        if c['auth'] not in ('keys','role'):raise AIError('AWS 认证方式仅支持 keys 或 role')
        if c['auth']=='keys' and not (c['access_key'] and c['secret_key']):raise AIError('请填写 AWS Key 和 Secret')
        if c['auth']=='role' and any(c.get(k) for k in ('access_key','secret_key','session_token')):raise AIError('Role 模式不能混合保存静态凭据，请新建 Role 账号')
    if provider in ('aws','aliyun','tencent') and not re.fullmatch(r'[a-z][a-z0-9-]{1,39}',c['region']):raise AIError('区域标识无效')
    if provider=='azure':
        for k in ('tenant_id','client_id','subscription_id'):
            if not re.fullmatch(r'[a-fA-F0-9-]{36}',c[k]):raise AIError('Azure ID 格式无效')
        if not re.fullmatch(r'[\w.()-]{1,90}',c['resource_group']):raise AIError('Resource Group 无效')
    if provider=='gcp':
        if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]',c['project_id']):raise AIError('Project ID 无效')
        try:
            data=json.loads(c['service_account'])
            if data.get('type')!='service_account' or not data.get('private_key') or not re.fullmatch(r'[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.iam\.gserviceaccount\.com',data.get('client_email','')):raise ValueError()
            if data.get('project_id')!=c['project_id']:raise ValueError()
        except (ValueError,TypeError,AttributeError):raise AIError('请提供匹配项目的 Service Account JSON') from None
    if provider in ('smtp','cldy'):
        if c['port'] not in ('465','587'):raise AIError('供应商 SMTP 仅支持 TLS 465 / STARTTLS 587')
        if not re.fullmatch(r'[a-zA-Z0-9.-]+',c['host']) or '.' not in c['host']:raise AIError('SMTP 主机无效')
    if provider=='mailgun':
        if c['region'] not in ('us','eu'):raise AIError('Mailgun 区域仅支持 us / eu')
        if not re.fullmatch(r'[a-zA-Z0-9.-]+',c['domain']):raise AIError('邮件域名无效')

    # (Binding helpers live below to keep account CRUD independent of business services.)

def bind_mail(base,body):
    store=ProviderStore(base);slug=text(body.get('slug',''),'站点',40,True);account_id=text(body.get('account_id',''),'邮件账号',40)
    if account_id:store.resolve(account_id,slug,'mail')
    path=store.root/'provider-bindings.json'
    with store.locked():
        items=read_json(path,{});old=items.get(slug,{'version':0})
        if body.get('version',0)!=old['version']:raise VaultConflict('邮件绑定已改变，请刷新')
        item={'account_id':account_id,'version':old['version']+1};items[slug]=item;atomic_json(path,items)
        return item

def mail_config(base,slug,fallback):
    store=ProviderStore(base);binding=read_json(store.root/'provider-bindings.json',{}).get(slug,{})
    ident=binding.get('account_id')
    if not ident:return fallback()
    item,c=store.resolve(ident,slug,'mail');provider=item['provider']
    result={**c,'provider':'ses' if provider=='aws' else 'smtp' if provider=='cldy' else provider,'from':c.get('sender',''),
            '_account_id':ident,'_account_version':item['version'],'_binding_version':binding['version']}
    if provider in ('smtp','cldy'):result.update(port=int(c['port']),tls=True,**{'pass':c['password']})
    return result


def test_account(base,body):
    from kf_sg_providers import probe
    store=ProviderStore(base)
    item=next((i for i in store.public() if i['id']==body.get('id')),None)
    if not item or not CATALOG[item['provider']].get('can_test'):raise AIError('此供应商不支持独立连接测试')
    item,c=store.resolve(item['id'],item['sites'][0],item['capabilities'][0])
    if item['version']!=body.get('version'):raise VaultConflict('账号已改变，请刷新后测试')
    result=probe(item['provider'],c)
    current,_=store.resolve(item['id'],item['sites'][0],item['capabilities'][0])
    if current['version']!=item['version']:raise VaultConflict('测试期间账号已改变，请重新测试')
    return result
