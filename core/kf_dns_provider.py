"""Authority-aware, site-scoped DNS changes with reviewable before/after records."""
import copy
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from kf_ai import AIError,NoRedirect,atomic_json,read_json,text
from kf_domain_vault import DomainVault,VaultConflict
from kf_tool_runtime import fingerprint,ActionConflict
from kf_health import domain_name,authority,query,authoritative_query
from kf_providers import ProviderStore
import kf_cloud_dns


def cloudflare(token,zone,method='GET',suffix='',body=None):
    if not re.fullmatch('[a-f0-9]{32}',zone):raise AIError('Cloudflare Zone ID 无效')
    if not re.fullmatch(r'(?:/dns_records(?:/[a-f0-9]{32})?(?:\?page=\d+&per_page=100)?)?',suffix):raise AIError('DNS API 路径无效')
    req=urllib.request.Request('https://api.cloudflare.com/client/v4/zones/'+zone+suffix,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=method)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=15) as r:
            raw=r.read(1024*1024+1)
            if len(raw)>1024*1024:raise AIError('DNS 服务商响应过大')
            result=json.loads(raw)
        if not result.get('success'):raise AIError('DNS 服务商拒绝操作，请检查 Zone ID、权限与记录配置')
        return result
    except (OSError,ValueError,urllib.error.HTTPError) as exc:
        if isinstance(exc,AIError):raise
        raise AIError('DNS 服务商请求失败，请核实服务商状态；写操作不会自动重试') from None


def normalize_record(value,domain):
    if not isinstance(value,dict):raise AIError('DNS 记录必须是对象')
    kind=text(value.get('type','A'),'记录类型',8,True).upper();name=text(value.get('name','@'),'记录名',253,True).lower().rstrip('.')
    if name=='@':name=domain
    elif name!=domain and not name.endswith('.'+domain):name=name+'.'+domain
    # TXT/DKIM/SRV owner names may contain underscores; only the selected site subtree is writable.
    if not re.fullmatch(r'(?:\*\.)?[a-z0-9_-]+(?:\.[a-z0-9_-]+)+',name) or not (name==domain or name.endswith('.'+domain)):raise AIError('记录名称超出本站点域名范围')
    content=text(value.get('content',value.get('value','')),'记录值',4000,True)
    if kind not in ('A','AAAA','CNAME','MX','TXT','NS','SRV'):raise AIError('不支持此记录类型')
    try:ttl=int(value.get('ttl',300))
    except (TypeError,ValueError):raise AIError('TTL 无效') from None
    if ttl!=1 and not 60<=ttl<=86400:raise AIError('TTL 必须是 60–86400 秒，或 1（自动）')
    try:
        if kind in ('A','AAAA'):
            addr=ipaddress.ip_address(content)
            if addr.version!=(4 if kind=='A' else 6):raise ValueError()
            content=str(addr)
        elif kind in ('CNAME','NS','MX'):content=domain if content=='@' else domain_name(content)
        elif kind=='SRV':
            priority,weight,port,target=content.split()
            if any(not 0<=int(x)<=65535 for x in (priority,weight,port)):raise ValueError()
            content='%d %d %d %s'%(int(priority),int(weight),int(port),domain_name(target))
    except (ValueError,TypeError):raise AIError('DNS 记录值格式无效') from None
    result={'name':name,'type':kind,'content':content,'ttl':ttl,'proxied':value.get('proxied') is True}
    if result['proxied'] and kind not in ('A','AAAA','CNAME'):raise AIError('只有 A、AAAA、CNAME 可启用代理')
    if kind=='MX':
        try:priority=int(value.get('priority',10))
        except (ValueError,TypeError):raise AIError('MX 优先级无效') from None
        if not 0<=priority<=65535:raise AIError('MX 优先级无效')
        result['priority']=priority
    return result


class DNSProviders(DomainVault):
    def __init__(self,base,local_dns):
        super().__init__(base);self.path=self.root/'dns-providers.json';self.key_path=self.root/'dns-provider.key';self.local=local_dns
    @staticmethod
    def public_item(item):return {**{k:v for k,v in item.items() if k!='secret'},'has_token':bool(item.get('secret'))}
    def configure(self,body,context):
        slug=context['slug'];provider=body.get('provider')
        if provider not in ('local','cloudflare','disabled')+kf_cloud_dns.PROVIDERS:raise AIError('DNS 服务商无效')
        zone=text(body.get('zone_id',''),'DNS 区域',253)
        account_id=text(body.get('account_id',''),'供应商账号',40)
        if provider in kf_cloud_dns.PROVIDERS:
            kf_cloud_dns.zone_key(provider,zone)
            if not account_id:raise AIError('请选择已保存的供应商账号')
        if account_id:
            account,credentials=ProviderStore(self.root.parent).resolve(account_id,slug,'dns')
            if account['provider']!=provider:raise AIError('账号供应商与 DNS 配置不一致')
        if provider=='cloudflare' and not re.fullmatch('[a-f0-9]{32}',zone):raise AIError('Cloudflare Zone ID 须为 32 位十六进制字符串')
        token=body.get('token','')
        if not isinstance(token,str) or len(token)>4096 or any(not 33<=ord(c)<=126 for c in token):raise AIError('API Token 无效')
        with self.locked():
            items=read_json(self.path,[]);old=next((i for i in items if i['slug']==slug),None)
            if old and body.get('version')!=old['version']:raise VaultConflict('DNS 服务商配置已改变，请刷新')
            secret=old.get('secret','') if old else ''
            binding={'slug':slug,'domain':context['domain'],'provider':provider,'zone_id':zone,**({'account_id':account_id} if account_id else {})}
            if old and any(old.get(k)!=v for k,v in binding.items()):secret=''
            if body.get('clear_token'):secret=''
            if token:secret=self.cipher(items).encrypt(json.dumps({**binding,'token':token}).encode()).decode()
            if provider=='cloudflare' and not secret and not account_id:raise AIError('请填写仅授权对应 DNS Zone 的 API Token')
            item={**binding,'secret':secret,'version':old['version']+1 if old else 1}
            atomic_json(self.path,[i for i in items if i['slug']!=slug]+[item]);return self.public_item(item)
    def resolve(self,context):
        with self.locked():
            items=read_json(self.path,[]);item=next((copy.deepcopy(i) for i in items if i['slug']==context['slug']),None)
            if not item or item['provider']=='disabled':raise AIError('尚未为此站点配置 DNS 执行服务商，请先配置并检查公网委托')
            if item['domain']!=context['domain']:raise AIError('站点域名已改变，请重新配置 DNS 服务商')
            token=''
            if item.get('account_id'):
                account,credentials=ProviderStore(self.root.parent).resolve(item['account_id'],context['slug'],'dns')
                if account['provider']!=item['provider']:raise AIError('供应商账号类型已改变')
                item['account_version']=account['version']
                return item,credentials['token'] if item['provider']=='cloudflare' else credentials
            if item.get('secret'):
                try:
                    payload=json.loads(self.cipher(items).decrypt(item['secret'].encode()))
                    if any(payload.get(k)!=item[k] for k in ('slug','domain','provider','zone_id')):raise ValueError()
                    token=payload['token']
                except Exception:raise AIError('DNS 凭据无法解密，请检查密钥备份') from None
            return item,token
    def records(self,context):
        item,token=self.resolve(context);domain=context['domain'];auth=authority(domain)
        if auth['state']!='ok':raise AIError('无法确认公网权威 DNS，禁止修改')
        if item['provider']=='cloudflare':
            zone=cloudflare(token,item['zone_id'])['result'];zone_domain=domain_name(zone.get('name',''))
            if not (domain==zone_domain or domain.endswith('.'+zone_domain)):raise AIError('Cloudflare Zone 与站点域名不匹配')
            expected=sorted(n.lower().rstrip('.') for n in zone.get('name_servers',[]))
            if auth['zone']!=zone_domain or expected!=auth['nameservers']:raise AIError('公网 DNS 未委托给此 Cloudflare Zone，禁止写入错误服务商')
            result=[]
            for page in range(1,11):
                data=cloudflare(token,item['zone_id'],suffix='/dns_records?page=%d&per_page=100'%page)
                for r in data['result']:
                    if r['name']==domain or r['name'].endswith('.'+domain):result.append(r)
                if page>=data.get('result_info',{}).get('total_pages',1):break
            else:raise AIError('DNS Zone 记录超过管理范围，请使用服务商后台')
            return item,result,auth
        if item['provider'] in kf_cloud_dns.PROVIDERS:
            zone_domain,expected,result=kf_cloud_dns.list_records(item['provider'],token,item['zone_id'])
            if not (domain==zone_domain or domain.endswith('.'+zone_domain)):raise AIError('DNS 区域与站点域名不匹配')
            if not expected or auth['zone']!=zone_domain or expected!=auth['nameservers']:raise AIError('公网未委托给所选区域的权威服务器，禁止写入')
            return item,sorted([r for r in result if r['name']==domain or r['name'].endswith('.'+domain)],key=lambda r:r['id']),auth
        zone=self.local.load_zones().get(context['slug'])
        if not zone or zone['domain']!=domain:raise AIError('本机尚未启用匹配的 DNS 区域')
        expected=sorted({r['value'].rstrip('.').lower() for r in zone['records'] if r['type']=='NS' and r['name']=='@'})
        if auth['zone']!=domain or expected!=auth['nameservers']:raise AIError('公网 DNS 未委托给本机区域；本机改动不会生效，已阻止写入')
        return item,local_records(zone),auth
    def plan(self,args,context):
        item,records,auth=self.records(context);operation=args.get('operation','add')
        if operation not in ('add','update','delete'):raise AIError('DNS 操作无效')
        old=None
        if operation!='add':
            old=next((r for r in records if r['id']==str(args.get('record_id',''))),None)
            if not old:raise AIError('原记录不存在，请刷新')
            if old['type'] in ('SOA','NS') and old['name']==auth['zone']:raise AIError('权威区域根 NS/SOA 请在服务商后台管理，不能通过此操作修改')
        new=None if operation=='delete' else normalize_record(args.get('record',{}),context['domain'])
        if new and new['type']=='NS' and new['name']==auth['zone']:raise AIError('区域根 NS 须在服务商后台管理')
        if new and item['provider']=='local' and new['proxied']:raise AIError('本机 DNS 不支持代理')
        if operation=='add' and len(records)>=200:raise AIError('单个站点最多管理 200 条 DNS 记录')
        if new:
            others=[r for r in records if not old or r['id']!=old['id']]
            same=[r for r in others if r['name']==new['name']]
            if same and (new['type']=='CNAME' or any(r['type']=='CNAME' for r in same)):raise AIError('CNAME 不能与同名记录共存，请先核对现有记录')
            if any(r['type']==new['type'] and r['content']==new['content'] for r in same):raise AIError('相同 DNS 记录已存在')
        if item['provider'] in kf_cloud_dns.PROVIDERS:kf_cloud_dns.validate_change(item['provider'],old,new,records)
        high=any(r and (r['type'] in ('MX','NS') or r['name']==context['domain']) for r in (old,new))
        return {'arguments':{'operation':operation,'before':old,'after':new},'mode':'totp' if high else 'confirm',
            'summary':'DNS '+operation+' / '+(new or old)['name'],'snapshot':{'provider_version':item['version'],'account_version':item.get('account_version'),'records':fingerprint(records),'authority':auth}}
    def apply(self,ticket,context):
        item,records,auth=self.records(context);args=ticket['arguments'];snapshot=ticket['snapshot']
        if item['version']!=snapshot['provider_version'] or item.get('account_version')!=snapshot.get('account_version') or fingerprint(records)!=snapshot['records'] or auth!=snapshot['authority']:raise ActionConflict('DNS 配置、记录或委托已改变，请重新生成变更单')
        op=args['operation'];old=args['before'];new=args['after']
        if item['provider']=='cloudflare':
            _,token=self.resolve(context);suffix='/dns_records'+('/'+old['id'] if old else '')
            payload=copy.deepcopy(new)
            if payload and payload['type']=='SRV':
                priority,weight,port,target=payload.pop('content').split();payload['data']={'priority':int(priority),'weight':int(weight),'port':int(port),'target':target}
            result=cloudflare(token,item['zone_id'],{'add':'POST','update':'PATCH','delete':'DELETE'}[op],suffix,payload)['result']
            record_id=result.get('id')
        elif item['provider'] in kf_cloud_dns.PROVIDERS:
            _,credentials=self.resolve(context)
            record_id=kf_cloud_dns.apply(item['provider'],credentials,item['zone_id'],old,new,records)
        else:
            def change(zones):
                zone=zones[context['slug']]
                if fingerprint(local_records(zone))!=snapshot['records']:raise ActionConflict('本机 DNS 记录已改变，请重新生成变更单')
                if old:zone['records'].pop(int(old['id']))
                if new:
                    name='@' if new['name']==context['domain'] else new['name'][:-(len(context['domain'])+1)]
                    value=('%s %s'%(new['priority'],new['content'])) if new['type']=='MX' else new['content']
                    zone['records'].append({'name':name,'type':new['type'],'value':value,'ttl':300 if new['ttl']==1 else new['ttl']})
            self.local.update_zones(change);record_id=None
        target=new or old;observed=query(target['name'],target['type'])
        return {'applied':True,'provider':item['provider'],'record_id':record_id,'before':old,'after':new,
                'public_observation':observed,'verification':'已提交服务商；公网缓存可能尚未更新，请运行解析检查确认'}

    def verify(self,ticket,context):
        item,records,auth=self.records(context);args=ticket['arguments'];new=args['after'];old=args['before'];target=new or old
        if item['version']!=ticket['snapshot']['provider_version'] or item.get('account_version')!=ticket['snapshot'].get('account_version'):raise ActionConflict('DNS 服务商配置已改变，请人工核对')
        def equal(r):
            content=r.get('content','')
            expected=target['content']
            if target['type'] in ('CNAME','NS','MX'):content=content.rstrip('.').lower();expected=expected.rstrip('.').lower()
            return r['name'].rstrip('.').lower()==target['name'] and r['type']==target['type'] and content==expected and (target['type']!='MX' or r.get('priority')==target.get('priority'))
        provider_match=any(equal(r) for r in records)
        if not new:provider_match=not provider_match
        observed=authoritative_query(context['domain'],target['name'],target['type'])
        expected=target['content']
        if target['type']=='MX':expected=str(target.get('priority',10))+' '+expected
        normalize=lambda v:v if target['type']=='TXT' else v.rstrip('.').lower()
        values=[normalize(v) for v in observed['values']]
        public_match=normalize(expected) in values
        if new and new.get('proxied') and target['type'] in ('A','AAAA','CNAME'):
            # Cloudflare may flatten/proxy records; provider state proves the configured origin.
            proxied=authoritative_query(context['domain'],target['name'],'A')
            public_match=bool(proxied['values']);observed=proxied
        if not new:public_match=normalize(expected) not in values
        verified=provider_match and observed['state']!='unknown' and public_match
        return {'ok':verified,'provider_matches':provider_match,'authoritative_observation':observed,
                'message':'服务商配置与权威 DNS 已核对；递归缓存仍可能按 TTL 延迟更新' if verified else '解析尚未通过验证；请检查配置或等待服务商同步后重试验证，不要重复提交写操作'}



def local_records(zone):
    domain=zone['domain']
    result=[]
    for index,r in enumerate(zone['records']):
        if r['type']=='SOA':continue
        value=r['value'];priority=None
        if r['type']=='MX':priority,value=value.split(None,1)
        name=domain if r['name']=='@' else r['name'].rstrip('.') if r['name'].endswith('.') else r['name']+'.'+domain
        result.append({'id':str(index),'name':name,'type':r['type'],'content':value,'ttl':r['ttl'],'proxied':False,**({'priority':int(priority)} if priority is not None else {})})
    return result
