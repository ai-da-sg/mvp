"""DNS adapters normalize simple records while preserving provider record-set semantics."""
import copy
import json
import re
import shlex
from kf_ai import AIError
from kf_cloud_api import aws_call,rest,aliyun,tencent,quote,namecom
from kf_tool_runtime import fingerprint

PROVIDERS=('aws','azure','gcp','aliyun','tencent','namecom','webnic','cpanel')
TYPES=('A','AAAA','CNAME','MX','TXT','NS','SRV')

def zone_key(provider,zone):
    if provider in ('webnic','cpanel'):
        from kf_health import domain_name
        return domain_name(zone)
    patterns={'webnic':r'[a-z0-9.-]{3,253}','cpanel':r'[a-z0-9.-]{3,253}','namecom':r'[a-z0-9.-]{3,253}','aws':r'Z[A-Z0-9]{1,63}','azure':r'[a-z0-9.-]{3,253}','gcp':r'[a-z][a-z0-9-]{0,62}','aliyun':r'[a-z0-9.-]{3,253}','tencent':r'[a-z0-9.-]{3,253}'}
    if not isinstance(zone,str) or not re.fullmatch(patterns[provider],zone):raise AIError('DNS 区域标识无效：AWS 填 Hosted Zone ID，GCP 填 Managed Zone 名称，其他填区域域名')
    return zone

def azure_base(c,z):return '/subscriptions/'+quote(c['subscription_id'])+'/resourceGroups/'+quote(c['resource_group'])+'/providers/Microsoft.Network/dnsZones/'+quote(z)
def gcp_base(c,z):return '/dns/v1/projects/'+quote(c['project_id'])+'/managedZones/'+quote(z)
def relative(name,z):return '@' if name==z else name[:-(len(z)+1)]
def fqdn(name,z):return z if name=='@' else name.rstrip('.') if name.endswith('.') else name+'.'+z

def decode_value(kind,value):
    if kind=='TXT':
        try:return ''.join(shlex.split(value))
        except ValueError:raise AIError('TXT 记录编码无法解析') from None
    return value.rstrip('.') if kind in ('CNAME','NS','MX','SRV') else value

def encode_value(r):
    value=r['content'];kind=r['type']
    if kind=='MX':value=str(r['priority'])+' '+value.rstrip('.')+'.'
    elif kind in ('CNAME','NS'):value=value.rstrip('.')+'.'
    elif kind=='SRV':value=value.rstrip('.')+'.'
    elif kind=='TXT':
        # DNS character strings have a 255-octet wire limit; never split UTF-8 codepoints.
        chunks=[];part=''
        for char in value:
            if len((part+char).encode())>255:chunks.append(part);part=''
            part+=char
        chunks.append(part);value=' '.join(json.dumps(p,ensure_ascii=False) for p in chunks)
    return value

def record(name,kind,value,ttl,raw,index,ident=None,blocked=False):
    content=decode_value(kind,value);priority=None
    if kind=='MX' and not (blocked and value.startswith('[')):
        try:priority,content=content.split(None,1);priority=int(priority)
        except (ValueError,TypeError):raise AIError('服务商 MX 记录格式无效') from None
    out={'id':ident or fingerprint([raw,index])[:32],'name':name.rstrip('.').lower(),'type':kind,'content':content,'ttl':ttl,'proxied':False,'_raw':raw,'_index':index,'_blocked':blocked}
    if priority is not None:out['priority']=priority
    return out

def azure_values(raw):
    p=raw['properties'];kind=raw['type'].rsplit('/',1)[-1].upper()
    fields={'A':('ARecords','ipv4Address'),'AAAA':('AAAARecords','ipv6Address'),'NS':('NSRecords','nsdname')}
    if kind in fields:
        group,key=fields[kind];return [r[key] for r in p.get(group,[])]
    if kind=='CNAME':return [p['CNAMERecord']['cname']] if p.get('CNAMERecord') else []
    if kind=='MX':return [str(r['preference'])+' '+r['exchange'] for r in p.get('MXRecords',[])]
    if kind=='TXT':return [' '.join(json.dumps(v,ensure_ascii=False) for v in r['value']) for r in p.get('TXTRecords',[])]
    if kind=='SRV':return ['%s %s %s %s'%(r['priority'],r['weight'],r['port'],r['target']) for r in p.get('SRVRecords',[])]
    return []

def list_records(provider,c,zone):
    z=zone_key(provider,zone);result=[]
    if provider in ('webnic','cpanel'):
        from kf_sg_dns import list_records as sg_records
        return sg_records(provider,c,z)
    if provider=='aws':
        meta=aws_call(c,'route53','get_hosted_zone',Id=z)
        if meta['HostedZone'].get('Config',{}).get('PrivateZone'):raise AIError('仅支持公网 Hosted Zone')
        domain=meta['HostedZone']['Name'].rstrip('.');ns=meta.get('DelegationSet',{}).get('NameServers',[]);params={'HostedZoneId':z,'MaxItems':'100'};sets=[]
        for _ in range(10):
            data=aws_call(c,'route53','list_resource_record_sets',**params);sets.extend(data['ResourceRecordSets'])
            if not data.get('IsTruncated'):break
            params.update(StartRecordName=data['NextRecordName'],StartRecordType=data['NextRecordType'])
            if data.get('NextRecordIdentifier'):params['StartRecordIdentifier']=data['NextRecordIdentifier']
            else:params.pop('StartRecordIdentifier',None)
        else:raise AIError('DNS 区域超过 1000 条记录集，请在服务商后台管理')
        for raw in sets:
            if raw['Type']=='SOA':continue
            blocked=not raw.get('ResourceRecords') or bool(set(raw)-{'Name','Type','TTL','ResourceRecords'}) or raw['Type'] not in TYPES
            values=[r['Value'] for r in raw.get('ResourceRecords',[])] or ['[复杂路由/别名记录]']
            for index,value in enumerate(values):result.append(record(raw['Name'],raw['Type'],value,raw.get('TTL',300),raw,index,blocked=blocked))
    elif provider=='azure':
        base=azure_base(c,z);meta=rest(provider,c,base+'?api-version=2018-05-01');domain=meta['name'];ns=meta['properties'].get('nameServers',[])
        if meta['properties'].get('zoneType','Public')!='Public':raise AIError('仅支持公网 DNS Zone')
        data=rest(provider,c,base+'/all?api-version=2018-05-01&$top=1000')
        if data.get('nextLink'):raise AIError('DNS 区域超过单次管理上限，请在服务商后台管理')
        for raw in data.get('value',[]):
            kind=raw['type'].rsplit('/',1)[-1].upper()
            if kind=='SOA':continue
            values=azure_values(raw) or ['[复杂路由/别名记录]'];blocked=not azure_values(raw) or bool(raw['properties'].get('targetResource',{}).get('id')) or kind not in TYPES
            for index,value in enumerate(values):result.append(record(fqdn(raw['name'],domain),kind,value,raw['properties'].get('TTL',300),raw,index,blocked=blocked))
    elif provider=='gcp':
        base=gcp_base(c,z);meta=rest(provider,c,base);domain=meta['dnsName'].rstrip('.');ns=meta.get('nameServers',[])
        if meta.get('visibility','public')!='public':raise AIError('仅支持公网 Managed Zone')
        data=rest(provider,c,base+'/rrsets?maxResults=1000')
        if data.get('nextPageToken'):raise AIError('DNS 区域超过单次管理上限，请在服务商后台管理')
        for raw in data.get('rrsets',[]):
            if raw['type']=='SOA':continue
            blocked=not raw.get('rrdatas') or bool(raw.get('routingPolicy')) or raw['type'] not in TYPES
            for index,value in enumerate(raw.get('rrdatas',[]) or ['[复杂路由记录]']):result.append(record(raw['name'],raw['type'],value,raw.get('ttl',300),raw,index,blocked=blocked))
    elif provider=='aliyun':
        meta=aliyun(c,'DescribeDomainInfo',{'DomainName':z});domain=meta['DomainName'];ns=meta.get('DnsServers',{}).get('DnsServer',[])
        data=aliyun(c,'DescribeDomainRecords',{'DomainName':z,'PageSize':500})
        if data.get('TotalCount',0)>500:raise AIError('DNS 区域超过 500 条记录，请在服务商后台管理')
        for raw in data.get('DomainRecords',{}).get('Record',[]):
            value=str(raw.get('Priority',10))+' '+raw['Value'] if raw['Type']=='MX' else json.dumps(raw['Value'],ensure_ascii=False) if raw['Type']=='TXT' else raw['Value']
            blocked=raw.get('Line','default')!='default' or raw.get('Status','ENABLE')!='ENABLE' or raw['Type'] not in TYPES or raw.get('Locked') is True
            result.append(record(fqdn(raw['RR'],domain),raw['Type'],value,raw['TTL'],raw,0,str(raw['RecordId']),blocked))
    elif provider=='tencent':
        meta=tencent(c,'DescribeDomain',{'Domain':z})['DomainInfo'];domain=meta['Domain'];ns=meta.get('DnspodNsList',[])
        data=tencent(c,'DescribeRecordList',{'Domain':z,'Limit':1000})
        if data.get('RecordCountInfo',{}).get('TotalCount',0)>1000:raise AIError('DNS 区域超过 1000 条记录，请在服务商后台管理')
        for raw in data.get('RecordList',[]):
            value=str(raw.get('MX',10))+' '+raw['Value'] if raw['Type']=='MX' else json.dumps(raw['Value'],ensure_ascii=False) if raw['Type']=='TXT' else raw['Value']
            blocked=raw.get('LineId','0')!='0' or raw.get('Status','ENABLE')!='ENABLE' or raw['Type'] not in TYPES
            result.append(record(fqdn(raw['Name'],domain),raw['Type'],value,raw['TTL'],raw,0,str(raw['RecordId']),blocked))
    elif provider=='namecom':
        base='/domains/'+quote(z);meta=namecom(c,base);domain=meta['domainName'];ns=meta.get('nameservers',[])
        if not ns or any(not n.rstrip('.').lower().endswith('.name.com') for n in ns):raise AIError('域名未使用 Name.com 权威 DNS，请选择实际 DNS 供应商')
        data=namecom(c,base+'/records?perPage=1000&page=1')
        if data.get('nextPage') or data.get('totalCount',0)>1000:raise AIError('DNS 区域超过 1000 条记录，请在 Name.com 后台管理')
        for raw in data.get('records',[]):
            kind=raw['type'];value=raw.get('answer','')
            if kind in ('MX','SRV'):value=str(raw.get('priority',0))+' '+value
            elif kind=='TXT':value=json.dumps(value,ensure_ascii=False)
            result.append(record(fqdn(raw.get('host') or '@',domain),kind,value,raw['ttl'],raw,0,str(raw['id']),kind not in TYPES))
    else:raise AIError('DNS 供应商不支持')
    return domain.lower(),sorted({n.rstrip('.').lower() for n in ns}),result

def validate_change(provider,old,new,records):
    if old and old.get('_blocked'):raise AIError('复杂路由、别名、停用或非默认线路记录请在服务商后台管理')
    if new:
        if provider=='webnic' and (new['ttl']<60 or new['type']=='NS'):raise AIError('WebNIC 需要 TTL 至少 60 秒，且不支持此 NS 写入')
        if provider=='namecom' and new['ttl']<300:raise AIError('Name.com TTL 最低为 300 秒')
        if new['proxied']:raise AIError('该 DNS 服务商不支持 Cloudflare 代理字段')
        if new['ttl']==1:raise AIError('此供应商需要明确 TTL，不能使用自动 TTL')
        if provider in ('aws','azure','gcp','webnic'):
            same=[r for r in records if r['name']==new['name'] and r['type']==new['type']]
            if any(r.get('_blocked') for r in same):raise AIError('同名记录集使用复杂路由，请在服务商后台管理')
            if old and (new['name'],new['type'])!=(old['name'],old['type']):raise AIError('记录集变更不能同时改名或改类型，请分别删除和新增')
            if any(r['ttl']!=new['ttl'] for r in same if not old or r['id']!=old['id']):raise AIError('同一记录集的 TTL 必须一致；请先保留原 TTL')

def apply(provider,c,zone,old,new,records):
    validate_change(provider,old,new,records);target=new or old;z=zone_key(provider,zone)
    if provider in ('webnic','cpanel'):
        from kf_sg_dns import apply as sg_apply
        return sg_apply(provider,c,z,old,new,records)
    if provider=='namecom':
        path='/domains/'+quote(z)+'/records'+('/'+quote(old['id']) if old else '')
        body=None
        if new:
            body={'host':relative(new['name'],z),'type':new['type'],'answer':new['content'],'ttl':new['ttl']}
            if new['type']=='MX':body['priority']=new['priority']
            if new['type']=='SRV':
                priority,answer=new['content'].split(None,1);body.update(priority=int(priority),answer=answer)
        data=namecom(c,path,'PUT' if old and new else 'DELETE' if old else 'POST',body)
        return str(data.get('id',''))
    if provider in ('aliyun','tencent'):
        if provider=='aliyun':
            params={'RecordId':old['id']} if old else {'DomainName':z}
            if new:params.update(RR=relative(new['name'],z),Type=new['type'],Value=new['content'],TTL=new['ttl'],Line='default',**({'Priority':new['priority']} if new['type']=='MX' else {}))
            data=aliyun(c,'UpdateDomainRecord' if old and new else 'DeleteDomainRecord' if old else 'AddDomainRecord',params)
        else:
            params={'Domain':z}
            if old:params['RecordId']=int(old['id'])
            if new:params.update(SubDomain=relative(new['name'],z),RecordType=new['type'],RecordLine='默认',Value=new['content'],TTL=new['ttl'],**({'MX':new['priority']} if new['type']=='MX' else {}))
            data=tencent(c,'ModifyRecord' if old and new else 'DeleteRecord' if old else 'CreateRecord',params)
        return str(data.get('RecordId',''))
    peers=[r for r in records if r['name']==target['name'] and r['type']==target['type']]
    before=copy.deepcopy(peers[0]['_raw']) if peers else None
    values=[encode_value(r) for r in peers if not old or r['id']!=old['id']]
    if new:values.append(encode_value(new))
    ttl=new['ttl'] if new else old['ttl']
    if provider=='aws':
        after={'Name':target['name']+'.','Type':target['type'],'TTL':ttl,'ResourceRecords':[{'Value':v} for v in values]}
        changes=([{'Action':'DELETE','ResourceRecordSet':before}] if before else [])+([{'Action':'CREATE','ResourceRecordSet':after}] if values else [])
        data=aws_call(c,'route53','change_resource_record_sets',HostedZoneId=z,ChangeBatch={'Changes':changes});return data.get('ChangeInfo',{}).get('Id','')
    if provider=='gcp':
        clean=lambda r:{k:v for k,v in r.items() if k in ('name','type','ttl','rrdatas')}
        after={'name':target['name']+'.','type':target['type'],'ttl':ttl,'rrdatas':values}
        body={'deletions':[clean(before)] if before else [],'additions':[after] if values else []}
        data=rest(provider,c,gcp_base(c,z)+'/changes','POST',body);return data.get('id','')
    if provider=='azure':
        path=azure_base(c,z)+'/'+target['type']+'/'+quote(relative(target['name'],z))+'?api-version=2018-05-01'
        if before and not before.get('etag'):raise AIError('Azure 记录集缺少并发版本标识，禁止覆盖')
        headers={'If-Match':before['etag']} if before else {'If-None-Match':'*'}
        if not values:rest(provider,c,path,'DELETE',headers=headers);return ''
        kind=target['type'];p={'TTL':ttl}
        if before and before.get('properties',{}).get('metadata'):p['metadata']=before['properties']['metadata']
        if kind in ('A','AAAA','NS'):
            group,key={'A':('ARecords','ipv4Address'),'AAAA':('AAAARecords','ipv6Address'),'NS':('NSRecords','nsdname')}[kind];p[group]=[{key:v} for v in values]
        elif kind=='CNAME':p['CNAMERecord']={'cname':values[0]}
        elif kind=='TXT':p['TXTRecords']=[{'value':shlex.split(v)} for v in values]
        elif kind=='MX':p['MXRecords']=[{'preference':int(v.split()[0]),'exchange':v.split()[1]} for v in values]
        elif kind=='SRV':p['SRVRecords']=[dict(zip(('priority','weight','port','target'),[int(v.split()[0]),int(v.split()[1]),int(v.split()[2]),v.split()[3]])) for v in values]
        rest(provider,c,path,'PUT',{'properties':p},headers);return ''
    raise AIError('DNS 供应商不支持')
