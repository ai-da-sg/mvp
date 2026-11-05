/* Reviewed operations use immutable server tickets; browser state never authorizes execution. */
let AUTO_CONFIG={tools:[],dns_providers:[]},AUTO_SERVERS=[],AUTO_ITEM=null,AUTO_RECORDS=[];
window.aiContextActions=window.aiContextActions||[];
const AUTO_LABELS={'cloud.inspect':'查询云资源清单','site.context':'读取建站资料','site.generate':'生成网站草稿','site.publish':'发布网站页面','dns.inspect':'检查域名与邮件解析','dns.change':'修改 DNS 记录','dns.verify':'验证已提交的 DNS 变更','mail.inspect':'检查邮件域名配置','mail.draft':'生成邮件草稿','mail.send':'发送邮件','mail.status':'查询邮件投递状态','maintenance.inspect':'运行运营健康检查','site.https':'检查 HTTPS 与证书'};
const AUTO_STATES={prepared:'待执行',running:'执行中',succeeded:'已完成',failed:'失败',uncertain:'结果待核实',interrupted:'中断待核实',cancelled:'已取消'};
function autoField(name,label,type='text',value='',required=false){return `<div class="field"><label for="auto-${name}">${esc(label)}</label><input id="auto-${name}" name="${name}" type="${type}" value="${esc(value)}" ${required?'required':''}></div>`;}
function autoText(name,label,value='',required=false){return `<div class="fld"><label for="auto-${name}">${esc(label)}</label><textarea id="auto-${name}" name="${name}" rows="5" ${required?'required':''}>${esc(value)}</textarea></div>`;}
async function loadAutomation(){
 const controls=['autoSite','autoPurpose','autoSource','autoTool','autoPrepare'].map(id=>document.getElementById(id));controls.forEach(e=>e.disabled=true);
 try{
 const previous=window.autoPendingAction?.slug||$('#autoSite').value;$('#autoSite').innerHTML=(STATE.sites||[]).map(s=>`<option value="${esc(s.slug)}">${esc(s.company)} / ${esc(s.domain)}</option>`).join('');if(previous)$('#autoSite').value=previous;
 AUTO_CONFIG=await aiRequest('/api/automation/config');$('#autoDNSConfig').hidden=!AUTO_CONFIG.can_configure;$('#autoMailConfig').hidden=!AUTO_CONFIG.can_configure;
 await autoSources();await autoHistory();await autoWorkflows();
 if(window.autoPendingAction){const item=window.autoPendingAction;window.autoPendingAction=null;showAutoReview(item);}
 if(!AUTO_POLL)AUTO_POLL=setInterval(()=>{if(!$('#p-automation').classList.contains('hidden'))autoWorkflows().catch(e=>aiMessage('#workflowMsg',e.message,true));},5000);
 }finally{controls.forEach(e=>e.disabled=false);}
}
async function autoSources(){
 $('#autoReview').classList.add('hidden');AUTO_ITEM=null;
 const slug=$('#autoSite').value;if(!slug){$('#autoFields').innerHTML='<p>请先创建站点。</p>';return;}
 const d=await aiRequest('/api/automation/available',{slug,purpose:$('#autoPurpose').value});AUTO_SERVERS=d.items||[];
 $('#autoSource').innerHTML='<option value="builtin">MVP 内置业务</option>'+AUTO_SERVERS.map(s=>`<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');autoTools();
 const config=(AUTO_CONFIG.dns_providers||[]).find(x=>x.slug===slug);$('#autoDNSProvider').value=config?.provider||'disabled';$('#autoDNSZone').value=config?.zone_id||'';$('#autoDNSToken').value='';$('#autoDNSClear').checked=false;autoDNSAccounts(config?.account_id||'');
 $('#autoMailAccount').innerHTML='<option value="">系统默认发送配置</option>'+(AUTO_CONFIG.provider_accounts||[]).filter(a=>a.sites.includes(slug)&&a.capabilities.includes('mail')).map(a=>`<option value="${esc(a.id)}">${esc(a.name+' / '+a.provider)}</option>`).join('');$('#autoMailAccount').value=AUTO_CONFIG.mail_bindings?.[slug]?.account_id||'';
}
function autoTools(){
 const source=$('#autoSource').value,purpose=$('#autoPurpose').value;
 if(source==='builtin')$('#autoTool').innerHTML=AUTO_CONFIG.tools.filter(t=>t.purpose===purpose).map(t=>`<option value="${esc(t.name)}">${esc(AUTO_LABELS[t.name]||t.name)}</option>`).join('');
 else{
  const p=AUTO_SERVERS.find(x=>x.id===source)?.policy||{};
  const entries=[...(p.tools||[]).map(t=>['tools',t.name]),...(p.resources||[]).map(n=>['resources',n]),...(p.prompts||[]).map(n=>['prompts',n])];
  $('#autoTool').innerHTML=entries.map(([k,n])=>`<option value="${esc(JSON.stringify([k,n]))}">${esc(({tools:'工具',resources:'资源',prompts:'提示词'})[k]+': '+n)}</option>`).join('');
 }
 autoFields();
}
async function autoFields(){
 const name=$('#autoTool').value;let html='';
 if($('#autoSource').value!=='builtin'){
  html=autoText('arguments','工具或提示词参数（JSON 对象；资源读取留空）','{}')+'<p class="hint">固定参数由管理员的绑定规则补入。服务端会验证参数、站点范围及执行规则。</p>';
 }else if(name==='cloud.inspect'){html='<div class="field"><label for="auto-account_id">供应商账号（已授权当前站点）</label><select id="auto-account_id" name="account_id" required><option value="">请选择</option>'+(AUTO_CONFIG.provider_accounts||[]).filter(a=>a.sites.includes($('#autoSite').value)&&a.capabilities.includes('cloud')).map(a=>`<option value="${esc(a.id)}">${esc(a.name+' / '+a.provider)}</option>`).join('')+'</select></div><p class="hint">查询账号授权区域/资源组/项目的资源清单，不修改云资源。</p>';}else if(['dns.inspect','mail.inspect','maintenance.inspect'].includes(name))html=autoField('selectors','DKIM 选择器（可选，逗号分隔）');
 else if(name==='site.context')html='<fieldset><legend>选择建站资料</legend>'+[['client','客户资料'],['brand','品牌与风格'],['pages','现有页面'],['media','素材目录']].map(([v,t])=>`<label><input name="selected" type="checkbox" value="${v}" checked>${t}</label>`).join('')+'</fieldset>';
 else if(name==='dns.verify')html=autoField('change_action','已完成的 DNS 操作 ID','text','',true);
 else if(name==='mail.status')html=autoField('send_action','已完成的邮件发送操作 ID','text','',true);
 else if(name==='site.publish')html=autoField('page','页面标识（留空发布全部页面）');
 else if(name==='site.generate')html=autoText('brief','建站要求','',true)+autoField('profile_id','模型配置 ID（留空使用默认模型）')+'<label><input type="checkbox" name="replace_draft">允许替换未发布草稿（旧草稿会备份）</label>';
 else if(name==='mail.draft')html=autoField('to','收件人','email')+autoText('brief','邮件要求','',true)+autoField('profile_id','模型配置 ID（留空使用默认模型）');
 else if(name==='mail.send')html=autoField('to','收件人','email','',true)+autoField('subject','主题','text','',true)+autoText('body','正文','',true);
 else if(name==='dns.change')html='<div class="formrow"><div class="field"><label for="auto-operation">操作</label><select id="auto-operation" name="operation"><option value="add">新增</option><option value="update">修改</option><option value="delete">删除</option></select></div><div class="field"><label for="auto-record_id">现有记录（修改或删除时选择）</label><select id="auto-record_id" name="record_id"><option value="">加载中…</option></select></div></div><div class="formrow">'+autoField('name','记录名','text','@')+'<div class="field"><label for="auto-type">类型</label><select name="type" id="auto-type">'+['A','AAAA','CNAME','TXT','MX','NS','SRV'].map(t=>`<option>${t}</option>`).join('')+'</select></div>'+autoField('content','记录值')+autoField('ttl','TTL（秒，1 为自动）','number','300')+autoField('priority','MX 优先级','number','10')+'</div><label><input type="checkbox" name="proxied">Cloudflare 代理</label>';
 $('#autoFields').innerHTML=html;
 if(name==='dns.change'&&$('#autoSource').value==='builtin'){
  try{const d=await aiRequest('/api/automation/dns-records',{slug:$('#autoSite').value});AUTO_RECORDS=d.records;
   if(!$('#auto-record_id'))return;$('#auto-record_id').innerHTML='<option value="">请选择原记录</option>'+d.records.map(r=>`<option value="${esc(r.id)}">${esc(r.name+' '+r.type+' '+r.content)}</option>`).join('');
   $('#auto-record_id').onchange=()=>{const r=AUTO_RECORDS.find(x=>x.id==$('#auto-record_id').value);if(r){for(const k of ['name','type','content','ttl','priority'])if($('#auto-'+k))$('#auto-'+k).value=r[k]??'';$('#autoForm [name=proxied]').checked=!!r.proxied;}};
  }catch(e){aiMessage('#autoMsg',e.message,true);if($('#auto-record_id'))$('#auto-record_id').innerHTML='<option value="">尚未获取记录</option>';}
 }
}
$('#autoSite').onchange=()=>autoSources().catch(e=>aiMessage('#autoMsg',e.message,true));
$('#autoPurpose').onchange=$('#autoSite').onchange;$('#autoSource').onchange=autoTools;$('#autoTool').onchange=autoFields;
$('#autoRefresh').onclick=()=>loadAutomation().catch(e=>aiMessage('#autoMsg',e.message,true));
$('#autoForm').onsubmit=async e=>{
 e.preventDefault();$('#autoPrepare').disabled=true;
 try{
  const fd=new FormData(e.target),args=Object.fromEntries(fd),body={slug:$('#autoSite').value,purpose:$('#autoPurpose').value,request_key:crypto.randomUUID?.()||String(Date.now())+'-'+Math.random()};
  if($('#autoSource').value!=='builtin'){const [kind,name]=JSON.parse($('#autoTool').value);Object.assign(body,{server:$('#autoSource').value,kind,name,arguments:JSON.parse(args.arguments||'{}')});}
  else{
   body.tool=$('#autoTool').value;
   if(args.selectors!==undefined)args.selectors=args.selectors.split(',').map(s=>s.trim()).filter(Boolean);
   if(body.tool==='site.context')args.selected=fd.getAll('selected');
   if(body.tool==='site.generate')args.replace_draft=fd.has('replace_draft');
   body.arguments=body.tool==='dns.change'?{operation:args.operation,record_id:args.record_id,record:{name:args.name,type:args.type,content:args.content,ttl:Number(args.ttl),priority:Number(args.priority),proxied:fd.has('proxied')}}:args;
  }
  const d=await aiRequest('/api/automation/prepare',body);showAutoReview(d.item);aiMessage('#autoMsg','操作预览已生成，请核对内容。');await autoHistory();
 }catch(err){aiMessage('#autoMsg',err.message,true);}finally{$('#autoPrepare').disabled=false;}
};
function showAutoReview(item){
 AUTO_ITEM=item;const needs=['confirm','totp'].includes(item.mode);const prepared=item.state==='prepared';
 $('#autoReview').innerHTML=`<h3>${esc(item.summary)}</h3><p>状态：${esc(AUTO_STATES[item.state]||item.state)} · ${esc(item.slug)}</p>${autoReadablePreview(item)}<details><summary>完整执行参数 / 修改前后</summary><pre data-user-content style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(item.arguments,null,2))}</pre></details>${item.error?`<p class="msg bad">${esc(item.error)}</p>`:''}${item.result?autoReadableResult(item.result):''}
 ${prepared?`<form id="autoConfirmForm">${needs?'<label><input id="autoConfirmed" type="checkbox" required>我已核对上述目标与具体内容，确认执行此操作</label>':''}${item.mode==='totp'?autoField('code','当前账号的 6 位 TOTP','text','',true):''}<button type="submit">${needs?'确认并执行':'执行查询 / 生成草稿'}</button><button id="autoCancel" type="button" class="ghost">取消此操作</button><div id="autoConfirmMsg" class="msg" role="status"></div></form>`:''}
 ${canAmendWorkflow(item)?'<details><summary>修改此步骤参数（重新确认）</summary><form id="autoAmend">'+autoText('amend','新的操作参数（JSON 对象）',JSON.stringify(item.tool==='dns.change'?{operation:item.arguments.operation,record_id:item.arguments.before?.id,record:item.arguments.after}:item.arguments,null,2),true)+'<button type="submit">更新操作预览</button></form></details>':''}
 ${item.state==='succeeded'&&item.mode==='read'&&item.arguments.purpose==='build'?'<button id="autoUseContext" type="button">用于 AI 建站资料</button>':''}
 ${item.state==='succeeded'&&item.tool==='mail.send'?'<button id="autoMailStatus" type="button">查询投递状态</button>':''}
 ${item.state==='succeeded'&&item.tool==='mail.draft'?'<button id="autoUseMail" type="button">编辑并预览发送</button>':''}
 ${item.state==='succeeded'&&item.tool==='site.generate'?'<a href="#ai" id="autoViewBuild">查看建站任务与预览</a>':''}
 ${['uncertain','interrupted'].includes(item.state)&&AUTO_CONFIG.can_configure?'<form id="autoReconcile"><label for="autoOutcome">人工核实结果</label><select id="autoOutcome"><option value="succeeded">外部服务已完成</option><option value="failed">已确认未完成</option></select>'+autoText('note','核实依据（例如服务商记录编号）','',true)+'<button type="submit">记录核实结果</button></form>':''}`;
 $('#autoReview').classList.remove('hidden');
 if($('#autoAmend'))$('#autoAmend').onsubmit=async e=>{e.preventDefault();try{const d=await aiRequest('/api/automation/workflow/amend',{id:item.workflow_id,arguments:JSON.parse($('#auto-amend').value)});showAutoReview(d.item);await autoWorkflows();}catch(err){aiMessage('#autoMsg',err.message,true);}};
 if($('#auto-code')){$('#auto-code').pattern='[0-9]{6}';$('#auto-code').maxLength=6;$('#auto-code').inputMode='numeric';$('#auto-code').autocomplete='one-time-code';}
 if($('#autoConfirmForm'))$('#autoConfirmForm').onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;try{const d=await aiRequest('/api/automation/execute',{id:item.id,digest:item.digest,confirmed:!!$('#autoConfirmed')?.checked,code:$('#auto-code')?.value||''});showAutoReview(d.item);await autoHistory();}catch(err){aiMessage('#autoConfirmMsg',err.message,true);e.submitter.disabled=false;}finally{if($('#auto-code'))$('#auto-code').value='';}};
 if($('#autoCancel'))$('#autoCancel').onclick=async()=>{try{const d=await aiRequest('/api/automation/cancel',{id:item.id});showAutoReview(d.item);await autoHistory();}catch(e){aiMessage('#autoConfirmMsg',e.message,true);}};
 if($('#autoUseContext'))$('#autoUseContext').onclick=()=>{window.aiContextActions=[...new Set([...window.aiContextActions,item.id])].slice(-8);window.aiContextTarget=item.slug;window.aiContextLabels=window.aiContextLabels||{};window.aiContextLabels[item.id]=item.summary;navigateTo('ai');if(window.renderAIContext)renderAIContext();};
 if($('#autoMailStatus'))$('#autoMailStatus').onclick=async()=>{try{const d=await aiRequest('/api/automation/prepare',{slug:item.slug,tool:'mail.status',arguments:{send_action:item.id}});showAutoReview(d.item);}catch(err){aiMessage('#autoMsg',err.message,true);}};
 if($('#autoUseMail'))$('#autoUseMail').onclick=()=>{$('#autoPurpose').value='mail';$('#autoSource').value='builtin';autoTools();$('#autoTool').value='mail.send';autoFields();for(const key of ['to','subject','body'])$('#auto-'+key).value=item.result[key]||'';$('#autoReview').classList.add('hidden');};
 if($('#autoViewBuild'))$('#autoViewBuild').onclick=e=>{e.preventDefault();navigateTo('ai');};
 if($('#autoReconcile'))$('#autoReconcile').onsubmit=async e=>{e.preventDefault();try{const d=await aiRequest('/api/automation/reconcile',{id:item.id,outcome:$('#autoOutcome').value,note:$('#auto-note').value});showAutoReview(d.item);await autoHistory();}catch(err){aiMessage('#autoMsg',err.message,true);}};
}
async function autoHistory(){const d=await aiRequest('/api/automation/actions');$('#autoActions').innerHTML=(d.items||[]).map(x=>`<article class="dom-row"><div class="h"><strong>${esc(x.summary)}</strong><span>${esc(AUTO_STATES[x.state]||x.state)}</span><button type="button" data-auto-detail="${esc(x.id)}">查看</button></div><p class="hint">${esc(x.user)} · ${esc(x.slug)} · ${esc(new Date(x.created*1000).toLocaleString())}${x.elapsed_ms!=null?' · '+x.elapsed_ms+' ms':''}</p></article>`).join('')||'<p class="hint">暂无操作记录。</p>';}
$('#autoActions').onclick=async e=>{const b=e.target.closest('[data-auto-detail]');if(!b)return;try{const d=await aiRequest('/api/automation/action/'+b.dataset.autoDetail);showAutoReview(d.item);}catch(err){aiMessage('#autoMsg',err.message,true);}};
$('#autoDNSForm').onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;const slug=$('#autoSite').value,current=AUTO_CONFIG.dns_providers.find(x=>x.slug===slug);try{await aiRequest('/api/automation/dns-provider',{slug,version:current?.version,provider:$('#autoDNSProvider').value,zone_id:$('#autoDNSZone').value,account_id:$('#autoDNSAccount').value,token:$('#autoDNSToken').value,clear_token:$('#autoDNSClear').checked});$('#autoDNSToken').value='';await loadAutomation();aiMessage('#autoDNSMsg','DNS 执行配置已保存');}catch(err){aiMessage('#autoDNSMsg',err.message,true);}finally{e.submitter.disabled=false;}};
new MutationObserver(()=>{if($('#p-automation').classList.contains('hidden')){if($('#auto-code'))$('#auto-code').value='';$('#autoDNSToken').value='';}}).observe($('#p-automation'),{attributes:true,attributeFilter:['class']});
let AUTO_WORKFLOWS=[],AUTO_POLL=null;
async function autoWorkflows(){
 const d=await aiRequest('/api/automation/workflows');AUTO_WORKFLOWS=d.items||[];
 const states={ready:'待开始',running:'运行中',waiting:'等待确认',failed:'需要处理',paused:'已暂停',completed:'已完成'};
 $('#autoWorkflows').innerHTML=AUTO_WORKFLOWS.map(w=>`<article class="dom-row"><div class="h"><strong>${esc(w.slug)} · ${esc(states[w.state]||w.state)}</strong>${w.state!=='completed'?`<button type="button" data-workflow-control="${esc(w.id)}" data-command="${w.state==='running'?'pause':'resume'}">${w.state==='running'?'暂停':'开始 / 继续'}</button>${w.state==='failed'?`<button type="button" data-workflow-control="${esc(w.id)}" data-command="retry">重试当前步骤</button>`:''}`:''}</div><p>${esc(w.message)}</p><ol>${w.steps.map(s=>`<li>${esc(s.label)} · ${esc(({pending:'待处理',waiting:'待确认',running:'处理中',completed:'已完成',failed:'需要处理'})[s.state]||s.state)} ${s.action_id?`<button type="button" class="ghost" data-workflow-action="${esc(s.action_id)}">查看 / 确认</button>`:''}</li>`).join('')}</ol></article>`).join('')||'<p class="hint">暂无交付流程。</p>';
}
$('#workflowForm').onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;try{const body={slug:$('#autoSite').value,brief:$('#workflowBrief').value,profile_id:$('#workflowProfile').value,recipient:$('#workflowRecipient').value,replace_draft:$('#workflowReplace').checked,dns_changes:JSON.parse($('#workflowDNS').value||'[]')};
 if($('#workflowInherit').checked){
  if($('#aiMode').value!=='existing'||$('#aiSite').value!==body.slug)throw Error('请先在 AI 建站页选择同一已有站点及所需资料');
  body.profile_id=body.profile_id||$('#aiProfile').value;body.language=$('#aiLanguage').value;
  const selection=promptSelection();if(selection)body.prompt_selection=selection;Object.assign(body,styleSelection());
  body.context_options=[...document.querySelectorAll('#aiContextOptions input[value]:checked')].map(e=>e.value);body.context_actions=window.aiContextActions||[];body.auto_research=$('#aiAutoResearch').checked;
 }
 await aiRequest('/api/automation/workflow/create',body);await autoWorkflows();aiMessage('#workflowMsg','交付流程已创建，点击“开始 / 继续”执行。');}catch(err){aiMessage('#workflowMsg',err.message,true);}finally{e.submitter.disabled=false;}};
$('#autoWorkflows').onclick=async e=>{const b=e.target.closest('button');if(!b)return;b.disabled=true;try{if(b.dataset.workflowControl){await aiRequest('/api/automation/workflow/control',{id:b.dataset.workflowControl,action:b.dataset.command});await autoWorkflows();}else if(b.dataset.workflowAction){const d=await aiRequest('/api/automation/action/'+b.dataset.workflowAction);showAutoReview(d.item);$('#autoReview').scrollIntoView({block:'start'});}}catch(err){aiMessage('#workflowMsg',err.message,true);}finally{b.disabled=false;}};

function openAutoAction(item){window.autoPendingAction=item;navigateTo('automation');}
function autoReadablePreview(item){
 const a=item.arguments;
 if(item.tool==='site.publish')return '<p>请逐页查看草稿预览；确认后将发布所列页面。</p><ul>'+(item.snapshot?.pages||[{slug:'home',title:'网站预览'}]).map(p=>`<li><a href="/preview/${encodeURIComponent(item.slug)}/${encodeURIComponent(p.slug)}" target="_blank" rel="noopener">${esc(p.title)}</a></li>`).join('')+'</ul>';
 if(item.tool==='mail.send')return `<p>发件人：${esc(a.from||'已配置发件人')}<br>收件人：${esc(a.to)}<br>主题：${esc(a.subject)}</p><pre data-user-content style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(a.body)}</pre>`;
 if(item.tool==='dns.change')return '<div class="formrow">'+[['before','修改前'],['after','修改后']].map(([key,title])=>`<div class="field"><strong>${title}</strong><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${a[key]?esc(a[key].name+' '+a[key].type+' '+a[key].content+'\nTTL: '+a[key].ttl):'无记录'}</pre></div>`).join('')+'</div>';
 return '';
}
function autoReadableResult(result){
 if(result.checks)return result.checks.map(c=>`<p><strong>${esc(c.name)}</strong> · ${esc(({ok:'正常',warn:'需检查',fail:'异常'})[c.status]||c.status)}<br><span data-user-content>${esc(c.detail)}</span></p>`).join('')+(result.note?`<p class="hint">${esc(result.note)}</p>`:'')+`<details><summary>完整检查结果</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(result,null,2))}</pre></details>`;
 if(result.state==='accepted')return '<p class="msg ok">邮件服务商已接受发送请求。最终送达状态尚未确认，可凭消息编号在服务商后台核实。</p>'+`<pre style="white-space:pre-wrap">${esc(JSON.stringify(result,null,2))}</pre>`;
 return `<details open><summary>执行结果</summary><pre data-user-content style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(result,null,2))}</pre></details>`;
}

function canAmendWorkflow(item){
 if(!item.workflow_id||['running','uncertain','interrupted'].includes(item.state))return false;
 const workflow=AUTO_WORKFLOWS.find(w=>w.id===item.workflow_id);
 const step=workflow?.steps.find(s=>s.state!=='completed');
 return !!(step?.action_id===item.id&&['waiting','failed','paused'].includes(workflow.state));
}

function autoDNSAccounts(selected=''){
 const p=$('#autoDNSProvider').value,slug=$('#autoSite').value;
 $('#autoDNSAccount').innerHTML='<option value="">'+(p==='cloudflare'?'使用下方独立 Token':p==='local'||p==='disabled'?'无需账号':'请选择已保存的账号')+'</option>'+(AUTO_CONFIG.provider_accounts||[]).filter(a=>a.provider===p&&a.sites.includes(slug)&&a.capabilities.includes('dns')).map(a=>`<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('');$('#autoDNSAccount').value=selected;
 $('#autoDNSToken').disabled=p!=='cloudflare'||!!$('#autoDNSAccount').value;
 if($('#autoDNSToken').disabled)$('#autoDNSToken').value='';
}
$('#autoDNSProvider').onchange=()=>autoDNSAccounts();$('#autoDNSAccount').onchange=()=>{const id=$('#autoDNSAccount').value;autoDNSAccounts(id);};
$('#autoMailForm').onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;try{const slug=$('#autoSite').value;await aiRequest('/api/automation/mail-binding',{slug,account_id:$('#autoMailAccount').value,version:AUTO_CONFIG.mail_bindings?.[slug]?.version||0});await loadAutomation();aiMessage('#autoMailMsg','邮件账号绑定已保存');}catch(err){aiMessage('#autoMailMsg',err.message,true);}finally{e.submitter.disabled=false;}};
