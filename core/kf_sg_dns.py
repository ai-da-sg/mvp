"""WebNIC RRsets and cPanel zone edits; no zone creation or delegation changes."""
import base64
import copy
import json
import shlex
from urllib.parse import urlencode
from kf_ai import AIError
from kf_cloud_api import quote
from kf_sg_providers import webnic,cpanel


def list_records(provider,c,zone):
    from kf_cloud_dns import record,fqdn,TYPES
    result=[]
    if provider=='webnic':
        if c['environment']!='production':raise AIError('WebNIC OTE 仅用于连接测试，不能绑定公网 DNS 执行')
        data=webnic(c,'/dns/v2/zone/'+quote(zone)+'/records')
        if not isinstance(data,dict) or data.get('sourceFrom') not in ('basic','subscription'):raise AIError('WebNIC 未返回已知 DNS 服务类型')
        records=data.get('records')
        if not isinstance(records,list) or len(records)>1000:raise AIError('WebNIC 记录清单无效或超过管理上限')
        ns=webnic(c,'/dns/v2/zone/'+data['sourceFrom']+'/record/nameservers')
        if not isinstance(ns,list) or not ns or any(not isinstance(n,str) for n in ns):raise AIError('WebNIC 未返回权威服务器列表')
        for source in records:
            raw=copy.deepcopy(source);raw['_source']=data['sourceFrom'];kind=raw['type'];values=raw.get('rdatas',[])
            blocked=kind not in ('A','AAAA','CNAME','MX','TXT','SRV') or not values or any(v.get('attributes') for v in values)
            for index,v in enumerate(values or [{'value':'[不支持的记录集]'}]):
                value=v['value']
                if kind=='TXT' and not value.startswith('"'):value=json.dumps(value,ensure_ascii=False)
                result.append(record(fqdn(raw.get('name') or '@',zone),kind,value,raw.get('ttl',3600),raw,index,blocked=blocked))
    elif provider=='cpanel':
        rows=cpanel(c,'DNS','parse_zone',{'zone':zone})
        if not isinstance(rows,list) or len(rows)>5000:raise AIError('cPanel 区域内容无效或超过管理上限')
        serial=None;ns=[];decoded=[]
        for raw in rows:
            if raw.get('type')!='record':continue
            try:
                decode=lambda v:base64.b64decode(v,validate=True).decode('utf-8')
                name=fqdn(decode(raw['dname_b64']),zone).lower();values=[decode(v) for v in raw['data_b64']]
            except (ValueError,UnicodeError,KeyError,TypeError):raise AIError('cPanel 区域包含无法安全解析的记录，请在后台管理') from None
            kind=raw['record_type']
            if kind=='SOA' and name.rstrip('.')==zone:
                try:serial=int(values[2])
                except (IndexError,ValueError):raise AIError('cPanel SOA 版本无效') from None
            if kind=='NS' and name.rstrip('.')==zone:ns.extend(values)
            decoded.append((raw,name,kind,values))
        if serial is None or not ns:raise AIError('cPanel 区域缺少 SOA 版本或根 NS，禁止修改')
        for raw,name,kind,values in decoded:
            if kind=='SOA':continue
            blocked=kind not in TYPES or not values
            if kind=='TXT':value=' '.join(json.dumps(v,ensure_ascii=False) for v in values)
            else:value=' '.join(values) or '[不支持的记录]'
            saved={**raw,'_serial':serial}
            result.append(record(name,kind,value,raw['ttl'],saved,0,str(raw['line_index']),blocked))
    else:raise AIError('DNS 供应商不支持')
    return zone,sorted({n.rstrip('.').lower() for n in ns}),result


def apply(provider,c,zone,old,new,records):
    from kf_cloud_dns import relative,encode_value
    if provider=='cpanel':
        serial=c.get('_zone_revision')
        if serial is None:raise AIError('cPanel 缺少已核验的区域版本，请重新预览')
        params={'zone':zone,'serial':serial}
        if new:
            kind=new['type']
            data=shlex.split(encode_value(new)) if kind=='TXT' else encode_value(new).split() if kind in ('MX','SRV') else [encode_value(new)]
            payload={'dname':new['name']+'.','ttl':new['ttl'],'record_type':kind,'data':data}
            if old:payload['line_index']=int(old['id'])
            params['edit' if old else 'add']=json.dumps(payload,ensure_ascii=False)
        else:params['remove']=int(old['id'])
        result=cpanel(c,'DNS','mass_edit_zone',params)
        if not isinstance(result,dict) or not isinstance(result.get('new_serial'),int):raise AIError('cPanel 未返回新区域版本，请核实状态，勿重复执行')
        return str(result['new_serial'])
    if provider=='webnic':
        if c['environment']!='production':raise AIError('测试环境禁止公网 DNS 变更')
        target=new or old;peers=[r for r in records if (r['name'],r['type'])==(target['name'],target['type'])]
        # Preserve the exact provider data of peers, including TXT quoting and attributes.
        values=[copy.deepcopy(r['_raw']['rdatas'][r['_index']]) for r in peers if not old or r['id']!=old['id']]
        if new:values.append({'value':encode_value(new)})
        path='/dns/v2/zone/'+quote(zone)+'/record';name=relative(target['name'],zone)
        if values:
            body={'name':name,'type':target['type'],'ttl':target['ttl'],'rdatas':values}
            if peers and 'remarks' in peers[0]['_raw']:body['remarks']=peers[0]['_raw']['remarks']
            webnic(c,path,'POST',body)
        else:webnic(c,path+'?'+urlencode({'name':name,'type':target['type']}),'DELETE')
        return ''
    raise AIError('DNS 供应商不支持')
