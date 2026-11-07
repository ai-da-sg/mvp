"""Site-scoped GEOInflow adapter. Private credentials never reach site browsers."""
import base64
import copy
import http.client
import json
import re
import socket
import ssl
import time
import threading
import hashlib
import uuid
import subprocess
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from kf_ai import AIError, atomic_json
from kf_domain_vault import DomainVault, VaultConflict
from kf_styles import public_url, public_addresses

MANAGED_URL = 'http://127.0.0.1:3002'
RESOURCES = ('human/overview', 'human/sources', 'ai/bots', 'ai/pages', 'conversions')
UUID = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$')


_PUBLIC_LOCK = threading.Lock()
_PUBLIC_REQUESTS = {}
_PUBLIC_SLOTS = threading.BoundedSemaphore(8)

def public_admission(ip):
    now = time.monotonic(); key = hashlib.sha256(ip.encode()).hexdigest()
    with _PUBLIC_LOCK:
        expired = [k for k,v in _PUBLIC_REQUESTS.items() if now-v[0]>60]
        for k in expired: _PUBLIC_REQUESTS.pop(k,None)
        if key not in _PUBLIC_REQUESTS and len(_PUBLIC_REQUESTS)>=2000: return False
        window,count = _PUBLIC_REQUESTS.get(key,(now,0))
        if count>=240: return False
        _PUBLIC_REQUESTS[key]=(window,count+1)
        return _PUBLIC_SLOTS.acquire(blocking=False)


TRACKING_PLUGIN = r'''<?php
/* MVP managed GEOInflow integration. No credentials or visitor profiles. */
function kf_inflow_settings() {
    if (is_user_logged_in() || is_preview() || is_admin()) return [];
    $c=get_option('kf_inflow',[]);
    if (empty($c['website_id']) || empty($c['origin']) || empty($c['domain'])) return [];
    if (!preg_match('/^[a-f0-9-]{36}$/D',$c['website_id']) || wp_parse_url($c['origin'],PHP_URL_SCHEME)!=='https') return [];
    if (strtolower(wp_parse_url(home_url(),PHP_URL_HOST))!==strtolower($c['domain'])) return [];
    return $c;
}
add_action('wp_head',function(){
    $c=kf_inflow_settings();if (!$c) return;
    echo '<script defer src="'.esc_url(rtrim($c['origin'],'/').'/inflow/script.js').'" data-website-id="'.esc_attr($c['website_id']).'" data-domains="'.esc_attr($c['domain']).'" data-do-not-track="true"></script>';
},30);
add_action('wp_footer',function(){if(!kf_inflow_settings())return; ?>
<script>
document.addEventListener('submit',function(e){
 var f=e.target;if(!f.matches('.kf-form')||!f.checkValidity())return;
 var msg=f.querySelector('.kf-form-msg');if(!msg)return;
 if(f.kfInflowObserver)f.kfInflowObserver.disconnect();
 var observer=new MutationObserver(function(records){
  if(!records.some(function(r){return r.attributeName==='class';}))return;
  observer.disconnect();if(msg.classList.contains('ok')&&window.umami)window.umami.track('enquiry_submitted');
 });f.kfInflowObserver=observer;observer.observe(msg,{attributes:true,attributeFilter:['class']});
},true);
</script>
<?php });
'''


def origin(value):
    p = urlsplit(public_url(value))
    if p.scheme != 'https' or p.path != '/' or p.query:
        raise AIError('Use an HTTPS origin without a path')
    return 'https://' + p.netloc


def request(url, token, method, path, body=None, headers=None):
    """Pin public destinations; the sole private target is our fixed managed service."""
    p = urlsplit(url)
    local = url == MANAGED_URL
    address = '127.0.0.1' if local else public_addresses(p.hostname, 443)[0]
    port = 3002 if local else 443
    conn = http.client.HTTPConnection(p.hostname, port, timeout=35)
    try:
        sock = socket.create_connection((address, port), timeout=35)
        conn.sock = sock if local else ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
        h = {'Accept': 'application/json', 'Accept-Encoding': 'identity', **(headers or {})}
        if token:
            h['Authorization'] = 'Bearer ' + token
        if body is not None:
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            h['Content-Type'] = 'application/json'
        conn.request(method, path, body=body, headers=h)
        response = conn.getresponse()
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise AIError('GEOInflow response is too large')
        if response.status not in (200, 201, 202, 204):
            raise AIError('GEOInflow returned HTTP %d; check its connection and permissions' % response.status)
        return response.status, raw, response.getheader('Content-Type', '')
    except AIError:
        raise
    except (OSError, http.client.HTTPException, ValueError):
        raise AIError('GEOInflow is unavailable; retry after checking the service') from None
    finally:
        conn.close()


def tracking_wp(site, *args, stdin=None, timeout=60):
    """Use the managed installer identity, as SSO does; retain protected MU directories."""
    from kf_sections import REG
    site = Path(site).resolve()
    return subprocess.run(['docker', 'run', '--rm', '-i', '--env-file', str(site/'wp.env'),
        '--network', 'kf-'+site.name+'_default', '-v', str(site/'html')+':/var/www/html',
        '--user', '0:0', REG, 'wp', '--allow-root', *args], input=stdin,
        capture_output=True, text=True, timeout=timeout)


class InflowStore(DomainVault):
    def __init__(self, base, transport=None):
        super().__init__(base)
        self.path = self.root / 'inflow.json'
        self.key_path = self.root / 'inflow.key'
        self.transport = transport or request

    def read(self):
        if not self.path.exists():
            return {'revision': 0, 'connection': {'url': MANAGED_URL, 'enabled': False, 'secret': ''}, 'sites': {}}
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data['revision'], int) or not isinstance(data['sites'], dict) or not isinstance(data['connection'], dict):
                raise ValueError()
            return data
        except (OSError, ValueError, KeyError, TypeError):
            raise AIError('GEOInflow configuration is unavailable; restore its backup') from None

    def public(self):
        with self.locked():
            d = self.read()
            return {'revision': d['revision'], 'connection': {k: v for k, v in d['connection'].items() if k != 'secret'},
                    'has_key': bool(d['connection'].get('secret')), 'sites': copy.deepcopy(d['sites'])}

    def check(self, data, revision):
        if type(revision) is not int or revision != data['revision']:
            raise VaultConflict('Configuration changed; reload before saving')

    def save(self, body, user):
        with self.locked():
            data = self.read(); self.check(data, body.get('revision'))
            old = data['connection']; url = body.get('url')
            if url != MANAGED_URL:
                url = origin(url)
                public_addresses(urlsplit(url).hostname, 443)
            token = body.get('token', '')
            if not isinstance(token, str) or len(token) > 4096 or (token and not re.fullmatch(r'umami_[A-Za-z0-9_-]+', token)):
                raise AIError('Enter a GEOInflow API key')
            if old['url'] != url and data['sites']:
                raise AIError('Disconnect bound sites before changing the service')
            if old['url'] != url and not token:
                raise AIError('A new service requires its own API key')
            secret = old.get('secret', '')
            if token:
                secret = self.cipher([old]).encrypt(json.dumps({'url': url, 'token': token}).encode()).decode()
            enabled = body.get('enabled') is True
            if enabled and not secret:
                raise AIError('Save an API key before enabling GEOInflow')
            data['connection'] = {'url': url, 'enabled': enabled, 'secret': secret, 'verified': False, 'updated_by': user}
            data['revision'] += 1; atomic_json(self.path, data)
        return self.public()

    def credentials(self):
        with self.locked():
            data = self.read(); c = data['connection']
            if not c.get('enabled') or not c.get('secret'):
                raise AIError('Configure and enable GEOInflow in system settings')
            try:
                key = json.loads(self.cipher([c]).decrypt(c['secret'].encode()))
                if key['url'] != c['url']: raise ValueError()
            except Exception:
                raise AIError('GEOInflow credentials cannot be decrypted') from None
            return c['url'], key['token'], data['revision']

    def api(self, method, path, body=None):
        url, token, _ = self.credentials()
        status, raw, _ = self.transport(url, token, method, path, body)
        try:
            value = json.loads(raw) if raw else {}
            if not isinstance(value, (dict, list)): raise ValueError()
            return status, value
        except (ValueError, TypeError):
            raise AIError('GEOInflow returned an invalid response') from None

    def test(self, revision):
        with self.locked(): self.check(self.read(), revision)
        _, response = self.api('GET', '/api/websites?page=1&pageSize=100&includeTeams=true')
        items = response.get('data', []) if isinstance(response, dict) else response
        if not isinstance(items, list): raise AIError('Invalid website list')
        result = [{'id': x['id'], 'name': x.get('name', ''), 'domain': x.get('domain', '')}
                  for x in items if isinstance(x, dict) and UUID.fullmatch(str(x.get('id', '')))]
        with self.locked():
            d = self.read(); self.check(d, revision)
            d['connection']['verified'] = True; d['revision'] += 1; atomic_json(self.path, d)
        return {**self.public(), 'websites': result}

    def binding(self, slug, domain, require=True):
        with self.locked(): b = copy.deepcopy(self.read()['sites'].get(slug))
        if not b or b.get('status') != 'ready':
            if require: raise AIError('Connect this site to GEOInflow first')
            return b
        if b['domain'] != domain.lower():
            if not require: return {**b, 'status': 'domain_changed'}
            raise AIError('Site domain changed; reconnect its analytics binding')
        return b

    def bind(self, slug, domain, company, body, user):
        ident = body.get('website_id', '')
        if ident and not UUID.fullmatch(ident): raise AIError('Invalid website ID')
        with self.locked():
            d = self.read(); self.check(d, body.get('revision'))
            if not d['connection'].get('verified'): raise AIError('Test the connection before binding a site')
            old = d['sites'].get(slug)
            if old and old.get('status') == 'ready': raise AIError('Disconnect the existing binding first')
            ident = ident or (old or {}).get('website_id') or str(uuid.uuid4())
            if any(x['website_id'] == ident for key, x in d['sites'].items() if key != slug):
                raise AIError('This analytics website is already bound to another site')
            d['sites'][slug] = {'website_id': ident, 'domain': domain.lower(), 'status': 'pending', 'tracking': False, 'updated_by': user}
            d['revision'] += 1; expected = d['revision']; atomic_json(self.path, d)
        # UUID is persisted before remote creation. An uncertain retry reads that same UUID.
        if not old and not body.get('website_id'):
            _, remote = self.api('POST', '/api/websites', {'id': ident, 'name': company, 'domain': domain})
        else:
            _, remote = self.api('GET', '/api/websites/' + ident)
        if not isinstance(remote, dict) or remote.get('id') != ident or str(remote.get('domain', '')).lower() != domain.lower():
            raise AIError('Analytics website domain does not match the selected MVP site')
        with self.locked():
            d = self.read(); self.check(d, expected)
            d['sites'][slug]['status'] = 'ready'; d['revision'] += 1; atomic_json(self.path, d)
        return self.binding(slug, domain)

    def report(self, slug, domain, resource, days, page=1):
        if resource not in RESOURCES or type(days) is not int or days not in (7, 30, 90): raise AIError('Invalid report range')
        if type(page) is not int or not 1 <= page <= 10000: raise AIError('Invalid report page')
        b = self.binding(slug, domain)
        end = int(time.time() * 1000)
        query = urlencode({'resource': resource, 'startAt': end - days * 86400000, 'endAt': end,
                           'timezone': 'Asia/Singapore', 'page': page, 'tp_srcBody': page, 'tp_apBody': page})
        status, data = self.api('GET', '/api/liekan/websites/' + b['website_id'] + '/page-report?' + query)
        if status == 202: return {'pending': True}
        if data.get('contractVersion') != 2 or data.get('website', {}).get('id') != b['website_id']:
            raise AIError('Unsupported or mismatched GEOInflow report')
        if (not isinstance(data.get('cards'), list) or not isinstance(data.get('tables'), dict)
                or not isinstance(data.get('states'), dict) or not isinstance(data.get('range'), dict)):
            raise AIError('Unsupported GEOInflow report structure')
        allowed_tables = {'human/overview': ('envGrid',), 'human/sources': ('srcBody',),
                          'ai/bots': ('botBody',), 'ai/pages': ('apBody', 'blindList'), 'conversions': ('goalBody',)}
        data['tables'] = {k: v for k, v in data['tables'].items() if k in allowed_tables[resource] and isinstance(v, list)}
        # Do not expose management hints, raw logs, credentials or other websites.
        return {k: data.get(k) for k in ('contractVersion', 'range', 'states', 'cards', 'charts', 'tables')} | {
            'meta': {k: data.get('meta', {}).get(k) for k in ('snapshot', 'demo', 'population', 'tablePages')}}

    def import_data(self, slug, domain, kind, body):
        b = self.binding(slug, domain)
        content = body.get('content', '')
        if not isinstance(content, str) or not content or len(content.encode()) > 256000:
            raise AIError('Upload a nonempty file smaller than 250 KB')
        formats = ('sitemap', 'csv', 'json') if kind == 'catalog' else ('combined', 'json')
        if body.get('format') not in formats: raise AIError('Unsupported import format')
        path = '/catalog' if kind == 'catalog' else '/logs/import'
        return self.api('PUT' if kind == 'catalog' else 'POST', '/api/liekan/websites/' + b['website_id'] + path,
                        {'content': content, 'format': body['format']})[1]

    def ensure_goal(self, website_id):
        path='/api/websites/'+website_id+'/goals'
        _,result=self.api('GET',path+'?search=MVP%20enquiry%20submitted&page=1&pageSize=100')
        rows=result.get('data',[]) if isinstance(result,dict) else result
        if not isinstance(rows,list): raise AIError('Invalid conversion goal response')
        found=next((x for x in rows if x.get('name')=='MVP enquiry submitted' and x.get('parameters',{}).get('type')=='event' and x.get('parameters',{}).get('value')=='enquiry_submitted'),None)
        if not found:
            _,found=self.api('POST',path,{'name':'MVP enquiry submitted','description':'Successful MVP contact form submissions','parameters':{'type':'event','value':'enquiry_submitted'}})
        if not isinstance(found,dict) or not UUID.fullmatch(str(found.get('id',''))): raise AIError('Conversion goal could not be verified')
        return found['id']

    def tracking(self, slug, domain, site, public_origin, revision, enabled, runner=None):
        runner = runner or tracking_wp
        b = self.binding(slug, domain, require=enabled)
        if not b: raise AIError('Site is not connected')
        public_origin = origin(public_origin)
        with self.locked(): self.check(self.read(), revision)
        value = {'website_id': b['website_id'], 'origin': public_origin, 'domain': domain} if enabled else {}
        encoded = base64.b64encode(json.dumps(value).encode()).decode()
        plugin = base64.b64encode(TRACKING_PLUGIN.encode()).decode()
        code = '<?php $v=json_decode(base64_decode("' + encoded + '"),true);$code=base64_decode("' + plugin + '");$dir="/var/www/html/wp-content/mu-plugins";$file=$dir."/kf-inflow.php";if(WPMU_PLUGIN_DIR!==$dir)WP_CLI::error("Unsupported plugin directory");foreach(["/var/www/html/wp-content",$dir,$file] as $p){if(is_link($p))WP_CLI::error("Refusing plugin symlink");}if(!is_dir($dir)&&!wp_mkdir_p($dir))WP_CLI::error("Plugin directory unavailable");$temp=tempnam($dir,".kf-inflow-");if(!$temp||file_put_contents($temp,$code,LOCK_EX)===false||!chmod($temp,0644)||!rename($temp,$file)||file_get_contents($file)!==$code)WP_CLI::error("Plugin installation failed");update_option("kf_inflow",$v,false);if(get_option("kf_inflow")!==$v)WP_CLI::error("Verification failed");echo "ok";'
        # Keep configuration changes serialized with WordPress installation.
        with self.locked():
            d = self.read(); self.check(d, revision)
            goal_id=self.ensure_goal(b['website_id']) if enabled else b.get('goal_id')
            result = runner(str(site), 'eval-file', '-', stdin=code, timeout=60)
            if result.returncode or result.stdout.strip() != 'ok': raise AIError('WordPress tracking configuration failed; retry after checking the site')
            d['sites'][slug]['tracking'] = bool(enabled); d['sites'][slug]['tracker_origin'] = public_origin
            d['sites'][slug]['goal_id'] = goal_id
            d['revision'] += 1; atomic_json(self.path, d)
        return self.binding(slug, domain, require=enabled)

    def disconnect(self, slug, revision):
        with self.locked():
            d = self.read(); self.check(d, revision); b = d['sites'].get(slug)
            if b and b.get('tracking'): raise AIError('Disable tracking before disconnecting this site')
            d['sites'].pop(slug, None); d['revision'] += 1; atomic_json(self.path, d)

    def allowed_origin(self, value, sites):
        try: value = origin(value)
        except (AIError, TypeError): return False
        with self.locked():
            d = self.read()
            if not d['connection'].get('enabled'): return False
            return any(b.get('status') == 'ready' and b.get('tracking') and slug in sites
                       and sites[slug] == b['domain'] and value == 'https://' + b['domain'] for slug, b in d['sites'].items())

    def collect(self, body, source, sites, ip, agent, cache=''):
        if not self.allowed_origin(source, sites): raise AIError('Tracking origin is not authorized')
        payload = body.get('payload', {})
        if body.get('type') != 'event' or not isinstance(payload, dict): raise AIError('Only pageviews and events are supported')
        host = urlsplit(source).hostname
        with self.locked():
            b = next((x for slug, x in self.read()['sites'].items() if slug in sites and x['domain'] == host
                      and x.get('tracking') and x.get('status') == 'ready' and x['website_id'] == payload.get('website')), None)
        if not b: raise AIError('Tracking site does not match the origin')
        # Public requests never establish trusted identity via payload overrides.
        allowed = ('website', 'url', 'referrer', 'title', 'screen', 'language', 'name')
        clean = {k: v for k, v in payload.items() if k in allowed and isinstance(v, str) and len(v) <= 2048}
        clean['hostname'] = host
        if payload.get('webdriver') is True: clean['webdriver'] = True
        if UUID.fullmatch(str(payload.get('eventId', ''))): clean['eventId'] = payload['eventId']
        url = clean.get('url', '/')
        if urlsplit(url).netloc and urlsplit(url).hostname != host: raise AIError('Tracking URL does not match the site')
        url, _, _ = self.credentials()
        status, raw, _ = self.transport(url, '', 'POST', '/api/send', {'type': 'event', 'payload': clean},
                                      {'Origin': source, 'User-Agent': agent[:512], 'X-MVP-Client-IP': ip, 'x-umami-website-id': b['website_id'], 'x-umami-hostname': host, 'x-umami-cache': cache[:4096]})
        return status, raw
