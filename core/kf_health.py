"""Read-only public DNS, email authentication and HTTPS diagnostics."""
import http.client
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
import dns.exception
import dns.resolver
from kf_ai import AIError
from kf_styles import public_addresses


def domain_name(value):
    if not isinstance(value,str) or len(value)>253:raise AIError('域名无效')
    try:value=value.strip().rstrip('.').encode('idna').decode().lower()
    except UnicodeError:raise AIError('域名无效') from None
    if '.' not in value or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',p) for p in value.split('.')):raise AIError('请输入有效域名')
    return value


def query(name,kind):
    resolver=dns.resolver.Resolver();resolver.timeout=2;resolver.lifetime=5
    try:
        answer=resolver.resolve(name,kind,tcp=True,raise_on_no_answer=False)
        values=[]
        for rr in answer:
            values.append(b''.join(rr.strings).decode('utf-8',errors='replace') if kind=='TXT' else rr.to_text())
        return {'state':'ok' if values else 'missing','values':values}
    except (dns.resolver.NXDOMAIN,dns.resolver.NoAnswer):return {'state':'missing','values':[]}
    except (dns.exception.DNSException,OSError):return {'state':'unknown','values':[]}


def authority(domain,lookup=query):
    domain=domain_name(domain);parts=domain.split('.')
    for i in range(len(parts)-1):
        zone='.'.join(parts[i:]);result=lookup(zone,'NS')
        if result['state']=='unknown':return {'state':'unknown','zone':zone,'nameservers':[],'provider':'unknown'}
        if result['values']:
            names=sorted({v.lower().rstrip('.') for v in result['values']})
            provider='cloudflare' if all(n.endswith('.ns.cloudflare.com') for n in names) else 'external'
            return {'state':'ok','zone':zone,'nameservers':names,'provider':provider}
    return {'state':'missing','zone':domain,'nameservers':[],'provider':'unknown'}


def diagnose(domain,selectors=None,lookup=query):
    domain=domain_name(domain);selectors=selectors or []
    if not isinstance(selectors,list) or len(selectors)>5 or any(not isinstance(s,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,63}',s) for s in selectors):raise AIError('DKIM 选择器最多 5 项，只能包含字母数字、短横线与下划线')
    requests=[(domain,'A'),(domain,'AAAA'),(domain,'MX'),(domain,'TXT'),('_dmarc.'+domain,'TXT')]+[(s+'._domainkey.'+domain,'TXT') for s in selectors]
    with ThreadPoolExecutor(max_workers=6) as pool:results=dict(zip(requests,pool.map(lambda x:lookup(*x),requests)))
    auth=authority(domain,lookup);checks=[]
    def add(name,state,detail):checks.append({'name':name,'status':state,'detail':detail})
    add('权威 DNS','ok' if auth['state']=='ok' else 'warn','、'.join(auth['nameservers']) or '无法确定权威服务商；不会执行 DNS 写入')
    ips=results[(domain,'A')]['values']+results[(domain,'AAAA')]['values']
    add('网站解析','ok' if ips else 'warn','、'.join(ips) or '未查到 A/AAAA；查询失败与无记录需进一步区分')
    mx=results[(domain,'MX')];add('邮件 MX','ok' if mx['values'] else 'warn','、'.join(mx['values']) or ('查询失败，状态未知' if mx['state']=='unknown' else '没有 MX 记录；未使用企业邮箱时可忽略'))
    txt=results[(domain,'TXT')];spf=[v for v in txt['values'] if v.lower().startswith('v=spf1')]
    state='ok' if len(spf)==1 else 'warn'
    if len(spf)>1 or any(re.search(r'(?:^|\s)\+?all(?:\s|$)',v) for v in spf):state='fail'
    add('SPF',state,'；'.join(spf) or ('查询失败，状态未知' if txt['state']=='unknown' else '未配置 SPF'))
    dmarc_result=results[('_dmarc.'+domain,'TXT')];dmarc=[v for v in dmarc_result['values'] if v.lower().startswith('v=dmarc1')]
    valid=len(dmarc)==1 and bool(re.search(r'(?:^|;)\s*p=(none|quarantine|reject)\s*(?:;|$)',dmarc[0],re.I))
    add('DMARC','ok' if valid else 'warn','；'.join(dmarc) or ('查询失败，状态未知' if dmarc_result['state']=='unknown' else '当前域名未配置 DMARC；组织域继承需另行核对'))
    if not selectors:add('DKIM','warn','请填写邮件服务商提供的选择器；不能根据缺省名称判断 DKIM 缺失')
    for selector in selectors:
        r=results[(selector+'._domainkey.'+domain,'TXT')];valid=any(re.search(r'(?:^|;)\s*p=\s*[^;\s]+',v) for v in r['values'])
        add('DKIM / '+selector,'ok' if valid else 'warn','；'.join(r['values'])[:2000] or ('查询失败，状态未知' if r['state']=='unknown' else '未查到该选择器公钥'))
    return {'domain':domain,'authority':auth,'records':{kind:results[(domain,kind)] for kind in ('A','AAAA','MX','TXT')},'checks':checks,
            'note':'此检查确认公开记录存在及基本配置，不等同于真实邮件签名、SPF 链路或投递验证。','checked_at':int(time.time())}


def https_check(domain):
    domain=domain_name(domain);conn=http.client.HTTPConnection(domain,443,timeout=8)
    try:
        addresses=public_addresses(domain,443)
        conn.sock=socket.create_connection((addresses[0],443),timeout=8)
        conn.sock=ssl.create_default_context().wrap_socket(conn.sock,server_hostname=domain)
        cert=conn.sock.getpeercert();expires=ssl.cert_time_to_seconds(cert['notAfter'])
        conn.request('HEAD','/',headers={'User-Agent':'MVP-Health/1.0'});response=conn.getresponse()
        return {'ok':200<=response.status<400,'status':response.status,'certificate_valid':True,'certificate_days':int((expires-time.time())/86400)}
    except Exception:return {'ok':False,'certificate_valid':False,'error':'HTTPS 连接、证书或响应检查失败；请检查公开解析与证书'}
    finally:conn.close()


def authoritative_query(domain,name,kind):
    """Ask a public authority directly; do not confuse recursive cache with propagation."""
    import dns.message
    import dns.query
    import dns.flags
    import dns.rcode
    auth=authority(domain)
    if auth['state']!='ok':return {'state':'unknown','values':[]}
    for ns in auth['nameservers'][:2]:
        try:
            ip=public_addresses(ns,53)[0]
            request=dns.message.make_query(name,kind);request.flags&=~dns.flags.RD
            response=dns.query.tcp(request,ip,timeout=5)
            if not response.flags&dns.flags.AA:continue
            if response.rcode() not in (dns.rcode.NOERROR,dns.rcode.NXDOMAIN):continue
            values=[]
            for rrset in response.answer:
                if rrset.rdtype!=dns.rdatatype.from_text(kind):continue
                for rr in rrset:values.append(b''.join(rr.strings).decode('utf-8',errors='replace') if kind=='TXT' else rr.to_text())
            return {'state':'ok' if values else 'missing','values':values,'nameserver':ns}
        except Exception:continue
    return {'state':'unknown','values':[]}
