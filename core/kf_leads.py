"""WordPress enquiry reads and versioned operator follow-up records."""
import copy
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import re
import threading
import time

from kf_ai import AIError, atomic_json, read_json
from kf_tool_runtime import ActionConflict
from kf_sections import wp

STATUSES = ('new', 'contacted', 'won', 'closed')
_LOCK = threading.RLock()
_FIELDS = '''$rows=[];foreach($q->posts as $p){$rows[]=['id'=>$p->ID,
 'title'=>$p->post_title,'date'=>$p->post_date,'msg'=>$p->post_content,
 'email'=>get_post_meta($p->ID,'_kf_email',true),
 'phone'=>get_post_meta($p->ID,'_kf_phone',true),
 'sent'=>get_post_meta($p->ID,'_kf_mail_sent',true)];}
 echo wp_json_encode(['items'=>$rows,'total'=>(int)$q->found_posts]);'''


class LeadReadError(AIError):
    pass


def read_page(site, page=1, lead_id=None):
    if type(page) is not int or not 1 <= page <= 100000:
        raise AIError('Invalid enquiry page')
    if lead_id is not None and (type(lead_id) is not int or lead_id <= 0):
        raise AIError('Invalid enquiry ID')
    args = {'post_type': 'kf_lead', 'post_status': 'any', 'posts_per_page': 100,
            'paged': page, 'orderby': 'ID', 'order': 'DESC'}
    if lead_id is not None:
        # Keep a list query. `p` changes WP_Query to a single-post query and
        # applies front-end private-post visibility to the CLI's anonymous user.
        args['post__in'] = [lead_id]
    # Only generated numeric/constant query values enter PHP; no operator text.
    import base64
    payload = base64.b64encode(json.dumps(args).encode()).decode()
    code = "$q=new WP_Query(json_decode(base64_decode('" + payload + "'),true));" + _FIELDS
    try:
        result = wp(str(site), 'eval', code, timeout=45)
        if result.returncode:
            raise ValueError('WordPress query failed')
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or not isinstance(data.get('items'), list) or type(data.get('total')) is not int:
            raise ValueError('Invalid enquiry response')
        if any(not isinstance(x, dict) or type(x.get('id')) is not int or x['id'] <= 0 for x in data['items']):
            raise ValueError('Invalid enquiry identity')
        return dict(data, page=page, has_more=page * 100 < data['total'], checked_at=time.time())
    except (OSError, ValueError, TimeoutError) as exc:
        raise LeadReadError('Unable to read enquiries from this site') from None
    except Exception:
        raise LeadReadError('Unable to read enquiries from this site') from None


class Followups:
    def __init__(self, base, slug):
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,19}', slug):
            raise AIError('Invalid site')
        self.path = Path(base) / 'console' / 'lead-followups' / (slug + '.json')
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def locked(self):
        with _LOCK, self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def all(self):
        with self.locked():
            return copy.deepcopy(read_json(self.path, {}))

    @staticmethod
    def empty():
        return {'status': 'new', 'version': 0, 'history': []}

    def save(self, lead_id, status, note, version, user):
        if type(lead_id) is not int or lead_id <= 0 or status not in STATUSES or type(version) is not int or version < 0:
            raise AIError('Invalid enquiry update')
        if not isinstance(note, str) or len(note) > 2000 or '\x00' in note:
            raise AIError('Follow-up note must be at most 2000 characters')
        note = note.strip()
        with self.locked():
            data = read_json(self.path, {})
            record = data.get(str(lead_id), self.empty())
            if record['version'] != version:
                raise ActionConflict('Enquiry changed; refresh before saving')
            if status == record['status'] and not note:
                raise AIError('Add a note or change the status')
            record['history'].append({'at': time.time(), 'by': user, 'from': record['status'], 'to': status, 'note': note})
            record.update(status=status, version=version + 1)
            data[str(lead_id)] = record
            atomic_json(self.path, data)
            return copy.deepcopy(record)
