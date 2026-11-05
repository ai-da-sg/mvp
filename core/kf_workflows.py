"""Resumable site delivery workflows with explicit approval checkpoints."""
import copy
import threading
import time
import uuid
from pathlib import Path
from kf_ai import AIError,atomic_json,read_json,text
from kf_tool_runtime import ActionDenied,ActionConflict
from kf_mail import address

_LOCK=threading.RLock()

class Workflows:
    def __init__(self,base,automation,jobs):
        self.root=Path(base)/'console'/'workflows';self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.automation=automation;self.jobs=jobs;self.threads={}
        with _LOCK:
            for path in self.root.glob('*.json'):
                item=read_json(path,{})
                if item.get('state')=='running':
                    item.update(state='paused',message='服务已重启，请核实当前步骤后继续');self.save(item)
    def path(self,ident):
        self.automation.actions.path(ident) # Shared strict identifier validation.
        return self.root/(ident+'.json')
    def get(self,ident,user=None):
        item=read_json(self.path(ident),None)
        if not item:raise AIError('交付任务不存在')
        if user is not None and user!=item['user']:raise ActionDenied('不能操作其他账号的交付任务')
        return item
    def save(self,item):item['updated']=time.time();atomic_json(self.path(item['id']),item)
    def list(self,user,admin=False):
        with _LOCK:
            items=[read_json(p,{}) for p in self.root.glob('*.json')]
            return sorted([i for i in items if admin or i.get('user')==user],key=lambda i:i.get('created',0),reverse=True)[:100]
    def create(self,user,body):
        slug=text(body.get('slug',''),'站点',40,True);self.automation.authorize(user,slug,'build')
        brief=text(body.get('brief',''),'建站要求',6000,True);profile=text(body.get('profile_id',''),'模型',40)
        changes=body.get('dns_changes',[])
        if not isinstance(changes,list) or len(changes)>5 or any(not isinstance(c,dict) for c in changes):raise AIError('每个流程最多配置 5 项 DNS 变更')
        recipient=body.get('recipient','')
        if recipient:recipient=address(recipient);self.automation.authorize(user,slug,'mail')
        if changes:self.automation.authorize(user,slug,'dns')
        build={'brief':brief,'profile_id':profile,'replace_draft':body.get('replace_draft') is True,
               'auto_research':body.get('auto_research') is True,'language':body.get('language','zh'),'context_options':body.get('context_options',[]),'context_actions':body.get('context_actions',[])}
        if body.get('prompt_selection') is not None:build['prompt_selection']=body['prompt_selection']
        if body.get('style_template_id'):build['style_template_id']=body['style_template_id']
        if body.get('reference_style') is not None:build['reference_style']=body['reference_style']
        steps=[{'tool':'site.generate','label':'生成网站草稿','arguments':build},{'tool':'site.publish','label':'预览并确认发布','arguments':{}}]
        for i,c in enumerate(changes):
            steps.extend([{'tool':'dns.change','label':'确认 DNS 变更 %d'%(i+1),'arguments':copy.deepcopy(c)},
                          {'tool':'dns.verify','label':'验证权威 DNS 生效 %d'%(i+1),'arguments':{}}])
        steps.append({'tool':'site.https','label':'验证 HTTPS 与证书','arguments':{}})
        if recipient:
            steps.extend([{'tool':'mail.draft','label':'生成交付邮件草稿','arguments':{'to':recipient,'profile_id':profile,'brief':text(body.get('mail_brief','网站已完成发布，请根据真实站点信息起草交付通知。'),'邮件要求',6000,True)}},
                          {'tool':'mail.send','label':'核对并确认发送交付邮件','arguments':{}}])
        item={'id':uuid.uuid4().hex,'user':user,'slug':slug,'state':'ready','created':time.time(),'message':'交付流程已创建，等待开始',
              'steps':[{**s,'state':'pending','attempt':0,'action_id':None} for s in steps]}
        with _LOCK:self.save(item)
        return item
    def control(self,ident,user,action):
        with _LOCK:
            item=self.get(ident,user)
            if action=='pause':
                if item['state']=='completed':raise ActionConflict('已完成的流程不能暂停')
                item.update(state='paused',message='已暂停；当前已开始的操作会完成并记录结果');self.save(item);return item
            if action not in ('start','resume','retry'):raise AIError('流程操作无效')
            if item['state']=='completed':return item
            thread=self.threads.get(ident)
            if thread and thread.is_alive():
                if item['state']=='running':return item
                raise ActionConflict('当前操作仍在收尾，请稍后继续')
            if action=='retry':
                step=next((s for s in item['steps'] if s['state']!='completed'),None)
                if step and step.get('action_id'):
                    ticket=self.automation.actions.get(step['action_id'],user)
                    if ticket['state'] in ('uncertain','interrupted','running'):raise ActionConflict('请先核实该操作的外部结果，不能直接重试')
                    if ticket['state']=='prepared':raise ActionConflict('操作仍待确认，请先执行或取消')
                    if ticket['state']=='succeeded' and step['tool'] not in ('site.generate','site.https','dns.verify'):
                        raise ActionConflict('操作已成功，请继续流程，不能重复执行')
                    step.setdefault('previous_actions',[]).append(step['action_id'])
                    step.update(action_id=None,state='pending',attempt=step['attempt']+1)
            if sum(t.is_alive() for t in self.threads.values())>=3:raise AIError('已有三个交付流程运行，请稍后继续')
            self.automation.authorize(user,item['slug'],'build')
            item.update(state='running',message='正在继续交付流程');self.save(item)
            thread=threading.Thread(target=self.run,args=(ident,),daemon=True);self.threads[ident]=thread;thread.start()
            return item
    def amend(self,ident,user,arguments):
        if not isinstance(arguments,dict):raise AIError('参数必须是对象')
        with _LOCK:
            item=self.get(ident,user)
            thread=self.threads.get(ident)
            if thread and thread.is_alive():raise ActionConflict('当前操作仍在收尾，请稍后修改')
            if item['state'] not in ('waiting','failed','paused'):raise ActionConflict('请先暂停流程或等待确认')
            index=next((i for i,s in enumerate(item['steps']) if s['state']!='completed'),None)
            if index is None:raise ActionConflict('流程已完成')
            step=item['steps'][index]
            if step['tool'] not in ('mail.send','dns.change','site.publish','site.generate','mail.draft'):raise AIError('此步骤不能修改参数')
            if step['action_id']:
                ticket=self.automation.actions.get(step['action_id'],user)
                if ticket['state']=='prepared':self.automation.actions.cancel(ticket['id'],user)
                elif ticket['state']=='succeeded' and step['tool']=='site.generate':
                    job=next((j for j in self.jobs() if j['id']==ticket.get('result',{}).get('job',{}).get('id')),None)
                    if not job or job['status'] not in ('failed','interrupted'):raise ActionConflict('建站仍在运行或已完成，不能改写此步骤')
                elif ticket['state'] not in ('failed','cancelled'):raise ActionConflict('该操作已执行，不能改写确认内容')
            if not isinstance(arguments,dict):raise AIError('参数必须是对象')
            # Validate the new preview now; this also creates a new immutable confirmation ticket.
            ticket=self.automation.prepare_builtin(user,{'slug':item['slug'],'tool':step['tool'],'arguments':arguments,'workflow_id':ident})
            if step['action_id']:step.setdefault('previous_actions',[]).append(step['action_id'])
            step.update(arguments=copy.deepcopy(arguments),action_id=ticket['id'],attempt=step['attempt']+1,state='waiting')
            item.update(state='waiting',message='参数已更新，请重新预览并确认');self.save(item)
            return ticket

    def run(self,ident):
        try:
            while True:
                with _LOCK:
                    item=self.get(ident)
                    if item['state']!='running':return
                    index=next((i for i,s in enumerate(item['steps']) if s['state']!='completed'),None)
                    if index is None:item.update(state='completed',message='交付流程已完成');self.save(item);return
                    step=item['steps'][index];user=item['user'];slug=item['slug']
                if not step['action_id']:
                    args=copy.deepcopy(step['arguments'])
                    if step['tool']=='dns.verify':args={'change_action':item['steps'][index-1]['action_id']}
                    if step['tool']=='mail.send' and not args:
                        previous=self.automation.actions.get(item['steps'][index-1]['action_id'],user)
                        args={k:previous['result'].get(k,'') for k in ('to','subject','body')}
                    ticket=self.automation.prepare_builtin(user,{'slug':slug,'tool':step['tool'],'arguments':args,
                        'request_key':'workflow:'+ident+':'+str(index)+':'+str(step['attempt']),'workflow_id':ident})
                    with _LOCK:
                        latest=self.get(ident);latest['steps'][index]['action_id']=ticket['id'];self.save(latest)
                        if latest['state']!='running':return
                else:ticket=self.automation.actions.get(step['action_id'],user)
                if ticket['state']=='prepared':
                    if ticket['mode'] in ('confirm','totp'):
                        self.set_step(ident,index,'waiting','waiting','请预览并确认当前操作');return
                    ticket=self.automation.execute(user,{'id':ticket['id'],'digest':ticket['digest']})
                if ticket['state']!='succeeded':
                    self.set_step(ident,index,'failed','failed',ticket.get('error','请核实当前操作结果'));return
                if step['tool']=='site.generate':
                    jid=ticket.get('result',{}).get('job',{}).get('id');job=next((j for j in self.jobs() if j['id']==jid),None)
                    if not job:self.set_step(ident,index,'failed','failed','建站任务记录不存在，请人工核对');return
                    if job['status'] in ('queued','generating','saving','provisioning'):
                        self.set_step(ident,index,'running','running','等待建站草稿完成');time.sleep(2);continue
                    if job['status']!='completed':self.set_step(ident,index,'failed','failed',job.get('message','草稿生成失败'));return
                if step['tool'] in ('site.https','dns.verify') and not ticket.get('result',{}).get('ok'):
                    self.set_step(ident,index,'failed','failed','解析或 HTTPS 尚未通过，请检查 DNS/证书后重试验证；已完成的写操作不会重复执行');return
                self.set_step(ident,index,'completed','running',step['label']+'已完成')
        except Exception as exc:
            with _LOCK:
                item=self.get(ident)
                if item['state']=='running':
                    item.update(state='failed',message=str(exc)[:1000] if isinstance(exc,AIError) else '流程执行失败，请检查当前步骤记录');self.save(item)
    def set_step(self,ident,index,state,workflow_state,message):
        with _LOCK:
            item=self.get(ident);item['steps'][index]['state']=state
            if item['state']=='running':item.update(state=workflow_state,message=message)
            if workflow_state in ('waiting','failed') and self.threads.get(ident) is threading.current_thread():self.threads.pop(ident,None)
            self.save(item)
