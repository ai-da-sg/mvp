"""Persistent GEO schedules over the existing encrypted provider vault/action journal.

Paid requests reserve quota before I/O. Restarts never implicitly replay an
interrupted request. Manual retries are new runs and retain every earlier result.
"""
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
import time
import uuid

from kf_ai import AIError, atomic_json, read_json, text
from kf_geo import GeoStore
from kf_geo_analysis import identity
from kf_geo_search import PROVIDERS, collect
from kf_providers import ProviderStore
from kf_tool_runtime import ActionStore, ActionConflict, fingerprint, release_guard

_SLOTS=threading.BoundedSemaphore(2)
_LOCK=threading.RLock()


class Collector:
    def __init__(self,base,authorize,transport=None):
        self.base=Path(base);self.root=self.base/'console';self.path=self.root/'geo-collector.json'
        self.providers=ProviderStore(base);self.actions=ActionStore(base)
        self.authorize=authorize;self.transport=transport
        self.stop=threading.Event();self.worker=None

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True,exist_ok=True)
        with _LOCK,(self.root/'geo-collector.lock').open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            yield

    def read(self):
        if not self.path.exists():return {'plans':[],'verification':{},'quota':{}}
        try:
            data=json.loads(self.path.read_text())
            if not isinstance(data,dict) or not isinstance(data.get('plans'),list) or not isinstance(data.get('verification'),dict) or not isinstance(data.get('quota'),dict):raise ValueError()
            if any(type(v) is not int or v<0 for v in data['quota'].values()):raise ValueError()
            return data
        except (OSError,ValueError):
            raise AIError('Collection state unavailable; restore its backup before collecting') from None

    def config(self,slug=None):
        with self.locked():data=self.read()
        accounts=[a for a in self.providers.public() if a['provider'] in PROVIDERS and (slug is None or slug in a['sites'])]
        for a in accounts:
            v=data['verification'].get(a['id'],{})
            a['verification']=v if v.get('version')==a['version'] else {'status':'unverified'}
            a['requests_today']=data['quota'].get(datetime.now(timezone.utc).date().isoformat()+':'+a['id'],0)
        plans=[p for p in data['plans'] if slug is None or p['slug']==slug]
        runs=[]
        for item in self.actions.list('',admin=True):
            if item['tool']=='geo.collect' and (slug is None or item['slug']==slug):
                full=self.actions.get(item['id']);runs.append({**item,'progress':full.get('progress',[]),'result':full.get('result'),
                    'plan_id':full['snapshot']['plan_id'],'total':len(full['snapshot']['tasks'])})
        return {'accounts':accounts,'plans':plans,'runs':runs[:50]}

    def reserve(self,account):
        day=datetime.now(timezone.utc).date().isoformat();key=day+':'+account['id']
        with self.locked():
            data=self.read();used=data['quota'].get(key,0)
            if used>=int(account['config']['daily_limit']):raise AIError('Daily request limit reached')
            data['quota']={k:v for k,v in data['quota'].items() if k.startswith(day+':')}
            data['quota'][key]=used+1;atomic_json(self.path,data)

    def probe(self,ident,version,user):
        account=next((a for a in self.providers.public() if a['id']==ident and a['provider'] in PROVIDERS),None)
        if not account:raise AIError('Search connection not found')
        self.authorize(user,account['sites'][0])
        account,config=self.providers.resolve(ident,account['sites'][0],'geo')
        if account['version']!=version:raise ActionConflict('Connection changed; reload before testing')
        if not _SLOTS.acquire(blocking=False):raise AIError('Search workers are busy')
        try:
            with release_guard(self.base):
                self.reserve(account)
                question={'text':'What is the official website of the National Library Board of Singapore?','language':'en','market':'SG'}
                result,_=collect(account['provider'],config,question,**({'transport':self.transport} if self.transport else {}))
                verified=result['status']=='success' and bool(result['citations'])
                report={'version':version,'status':'verified' if verified else 'failed','checked_at':time.time(),
                        'search_calls':len(result['search_calls']),'citation_count':len(result['citations']),
                        'usage':result['usage'],'response_id':result['response_id'],
                        'error':'' if verified else result['error'] or 'Search returned no answer citations'}
        except AIError as exc:
            report={'version':version,'status':'failed','checked_at':time.time(),'error':str(exc)}
        finally:_SLOTS.release()
        with self.locked():
            current,_=self.providers.resolve(ident,account['sites'][0],'geo')
            if current['version']!=version:raise ActionConflict('Connection changed during test')
            data=self.read();data['verification'][ident]=report;atomic_json(self.path,data)
        return report

    def _connection(self,ident,slug,version=None):
        account,config=self.providers.resolve(ident,slug,'geo')
        if account['provider'] not in PROVIDERS:raise AIError('Unsupported search connection')
        with self.locked():v=self.read()['verification'].get(ident,{})
        if v.get('version')!=account['version'] or v.get('status')!='verified':raise AIError('Verify search capability before collecting')
        if version is not None and version!=account['version']:raise ActionConflict('Connection changed; review and save the collection plan')
        return account,config

    def save_plan(self,body,user):
        slug=body.get('slug');self.authorize(user,slug);workspace=GeoStore(self.base,slug).read()
        if not workspace['profile']['brand']:raise AIError('Save the site brand profile first')
        ids=body.get('question_ids');accounts=body.get('account_ids')
        for values,limit in ((ids,40),(accounts,4)):
            if not isinstance(values,list) or not 1<=len(values)<=limit or any(not isinstance(v,str) for v in values) or len(values)!=len(set(values)):raise AIError('Select unique questions and connections')
        questions=[q for q in workspace['questions'] if q['id'] in ids and q['active']]
        if len(questions)!=len(ids):raise AIError('Some selected questions are missing or inactive')
        repeats=body.get('repeats',1);interval=body.get('interval_hours',24)
        if type(repeats) is not int or not 1<=repeats<=40 or type(interval) is not int or interval not in (0,6,12,24,168):raise AIError('Invalid collection frequency')
        if len(ids)*len(accounts)*repeats>120:raise AIError('Limit each collection round to 120 requests')
        versions={a:self._connection(a,slug)[0]['version'] for a in accounts}
        ident=body.get('id') or uuid.uuid4().hex
        if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident):raise AIError('Invalid plan ID')
        with self.locked():
            data=self.read();old=next((p for p in data['plans'] if p['id']==ident),None)
            if old and (old['slug']!=slug or body.get('version')!=old['version']):raise ActionConflict('Collection plan changed; reload')
            if not old and body.get('id'):raise ActionConflict('Collection plan was deleted')
            if not old and len(data['plans'])>=100:raise AIError('Collection plan limit reached')
            plan={'id':ident,'slug':slug,'name':text(body.get('name',''),'Plan name',80,True),'owner':user,
                  'question_ids':ids,'question_versions':{q['id']:q['version'] for q in questions},'account_ids':accounts,
                  'account_versions':versions,'brand':workspace['profile']['brand'],'entity_identity':identity(workspace['profile']),'repeats':repeats,'interval_hours':interval,
                  'enabled':body.get('enabled') is True and interval>0,'version':(old or {}).get('version',0)+1,
                  'next_run':time.time()+interval*3600,'cancel_before':(old or {}).get('cancel_before',0),'updated':time.time()}
            data['plans']=[p for p in data['plans'] if p['id']!=ident]+[plan];atomic_json(self.path,data)
            return plan

    def change_plan(self,body,user):
        with self.locked():
            data=self.read();plan=next((p for p in data['plans'] if p['id']==body.get('id')),None)
            if not plan:raise AIError('Collection plan not found')
            self.authorize(user,plan['slug'])
            if body.get('version')!=plan['version']:raise ActionConflict('Collection plan changed; reload')
            if body.get('action')=='delete':data['plans'].remove(plan)
            elif body.get('action')=='pause':plan.update(enabled=False,cancel_before=time.time(),version=plan['version']+1)
            else:raise AIError('Unsupported plan action')
            atomic_json(self.path,data)
            return plan

    def snapshot(self,plan):
        self.authorize(plan['owner'],plan['slug'])
        data=GeoStore(self.base,plan['slug']).read()
        if data['profile']['brand']!=plan['brand']:raise ActionConflict('Brand changed; review and save the collection plan')
        if plan.get('entity_identity',identity(data['profile']))!=identity(data['profile']):raise ActionConflict('Brand aliases or competitors changed; review and save the collection plan')
        questions={q['id']:q for q in data['questions'] if q['active']}
        tasks=[]
        for ident in plan['account_ids']:
            account,_=self._connection(ident,plan['slug'],plan['account_versions'][ident])
            for qid in plan['question_ids']:
                q=questions.get(qid)
                if not q or q['version']!=plan['question_versions'][qid]:raise ActionConflict('Questions changed; review and save the collection plan')
                for repetition in range(plan['repeats']):
                    tasks.append({'account_id':ident,'account_version':account['version'],'question':copy.deepcopy(q),'repetition':repetition})
        return {'plan_id':plan['id'],'plan_version':plan['version'],'brand':plan['brand'],'entity_profile':copy.deepcopy(data['profile']),'protocol_version':'official_search_v1','tasks':tasks}

    def start(self,ident,user,version,request_key,retry=None,background=True):
        with self.locked():
            plan=next((p for p in self.read()['plans'] if p['id']==ident),None)
        if not plan:raise AIError('Collection plan not found')
        self.authorize(user,plan['slug'])
        if version!=plan['version']:raise ActionConflict('Collection plan changed; reload')
        snap=self.snapshot(plan)
        if retry:
            old=self.actions.get(retry)
            if old['tool']!='geo.collect' or old['slug']!=plan['slug'] or old['snapshot']['plan_id']!=ident or old['state'] in ('prepared','running'):raise AIError('Run is not eligible for retry')
            if old['snapshot']['plan_version']!=plan['version']:raise ActionConflict('Plan changed; start a new collection round instead of retrying')
            completed={(o['account_id'],o['question']['id'],o['repetition']) for o in GeoStore(self.base,plan['slug']).read()['observations'] if o.get('source_run_id')==retry and o['status']=='success'}
            snap['tasks']=[t for t in snap['tasks'] if (t['account_id'],t['question']['id'],t['repetition']) not in completed]
            snap['retry_of']=retry
            if not snap['tasks']:raise AIError('No unsuccessful samples to retry')
        if not _SLOTS.acquire(blocking=False):raise AIError('Search workers are busy; try again shortly')
        handed=False
        try:
            # Serialize admission across processes without holding the lock during API I/O.
            with (self.root/'geo-admission.lock').open('a') as admission:
                fcntl.flock(admission,fcntl.LOCK_EX)
                for path in self.actions.root.glob('*.json'):
                    prior=read_json(path,{})
                    if prior.get('tool')=='geo.collect' and prior.get('snapshot',{}).get('plan_id')==ident and prior.get('state') in ('prepared','running'):
                        if prior.get('request_key')==request_key and prior.get('user')==user:
                            _SLOTS.release();handed=True;return prior
                        raise ActionConflict('This collection plan already has an active run')
                item=self.actions.prepare(user=user,slug=plan['slug'],tool='geo.collect',arguments={'plan_id':ident,'retry':retry},
                    mode='read',summary=plan['name'],snapshot=snap,request_key=text(request_key,'Request key',100,True))
            if item['state']!='prepared':_SLOTS.release();handed=True;return item
            def run():
                try:
                    with release_guard(self.base):
                        self.actions.execute(item['id'],user,digest=item['digest'],authorize=lambda i:self.authorize(user,i['slug']),
                            verify_totp=lambda *_:None,executor=self.execute)
                except AIError as exc:
                    with self.actions.locked():
                        current=self.actions.get(item['id'])
                        if current['state']=='prepared':current.update(state='failed',error=str(exc));self.actions.save(current,'failed')
                finally:_SLOTS.release()
            if background:
                threading.Thread(target=run,daemon=True,name='geo-'+item['id'][:8]).start();handed=True
            else:
                handed=True;run()
            return self.actions.get(item['id'])
        except Exception:
            if not handed:_SLOTS.release()
            raise

    def execute(self,item):
        results=[];snap=item['snapshot'];store=GeoStore(self.base,item['slug'])
        for index,task in enumerate(snap['tasks']):
            self.authorize(item['user'],item['slug'])
            with self.locked():plan=next((p for p in self.read()['plans'] if p['id']==snap['plan_id']),None)
            if not plan or plan['version']!=snap['plan_version'] or plan.get('cancel_before',0)>item['created']:
                return {'status':'cancelled','samples':results,'remaining':len(snap['tasks'])-len(results)}
            ident=hashlib.sha256((item['id']+':'+str(index)).encode()).hexdigest()[:32]
            account=None;raw={}
            try:
                account,config=self._connection(task['account_id'],item['slug'],task['account_version'])
                self.reserve(account)
                result,raw=collect(account['provider'],config,task['question'],**({'transport':self.transport} if self.transport else {}))
            except AIError as exc:
                result={'status':'failed','answer':'','citations':[],'error':str(exc),'usage':{}}
            meta={'brand':snap['brand'],'platform':PROVIDERS[account['provider']][0] if account else task['account_id'],
                  'entity_profile':snap.get('entity_profile',{'brand':snap['brand']}),'protocol_version':snap.get('protocol_version','official_search_v1'),
                  'model':result.get('returned_model') or (account['config']['model'] if account else ''), 'mode':'official_api_search',
                  'environment':'fresh request; market context='+task['question']['market']+'; adapter=v1; connection='+task['account_id'],
                  'batch':item['id'],'source_run_id':item['id'],'account_id':task['account_id'],
                  'account_version':task['account_version'],'repetition':task['repetition']}
            store.record_sample(ident,task['question'],result,raw,meta,item['user'])
            results.append({'observation_id':ident,'question_id':task['question']['id'],'account_id':task['account_id'],
                            'status':result['status'],'error':result.get('error','')})
            with self.actions.locked():
                current=self.actions.get(item['id']);current['progress']=results;self.actions.save(current,'sample_saved')
        return {'status':'completed' if all(r['status']=='success' for r in results) else 'partial','samples':results}

    def tick(self):
        now=time.time()
        with self.locked():
            data=self.read();due=[]
            for plan in data['plans']:
                if plan['enabled'] and plan['next_run']<=now:
                    due.append(copy.deepcopy(plan));plan['next_run']=now+plan['interval_hours']*3600
            if due:atomic_json(self.path,data)
        for plan in due:
            try:self.start(plan['id'],plan['owner'],plan['version'],'schedule:'+plan['id']+':'+str(int(plan['next_run'])))
            except AIError as exc:
                with self.locked():
                    data=self.read();current=next((p for p in data['plans'] if p['id']==plan['id']),None)
                    if current and current['version']==plan['version']:
                        current.update(enabled=False,last_error=str(exc));atomic_json(self.path,data)

    def start_scheduler(self):
        if self.worker and self.worker.is_alive():return
        self.root.mkdir(parents=True,exist_ok=True)
        def loop():
            with (self.root/'geo-scheduler.lock').open('a') as leader:
                try:fcntl.flock(leader,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:return
                # A crash between preparing and starting a paid run must not leave
                # the plan permanently busy or cause an implicit replay.
                with self.actions.locked():
                    for path in self.actions.root.glob('*.json'):
                        item=read_json(path,{})
                        if item.get('tool')=='geo.collect' and item.get('state')=='prepared':
                            item.update(state='interrupted',error='Service restarted before collection; review and retry explicitly')
                            self.actions.save(item,'interrupted')
                while not self.stop.is_set():
                    try:self.tick()
                    except Exception:logging.getLogger(__name__).error('GEO scheduler could not process plans; check collection state and storage')
                    self.stop.wait(30)
        self.worker=threading.Thread(target=loop,daemon=True,name='geo-scheduler');self.worker.start()
