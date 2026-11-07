/* GEO connection credentials reuse ProviderStore; runs reuse the action journal. */
const GEO_COLLECTION={config:null,plan:null,account:null,busy:false,epoch:0,poll:null};
const gcText=(zh,en)=>AdminUI.text(zh,en);
const gcButton=(action,zh,en,id='')=>`<button type="button" class="ghost" data-gc-action="${action}" data-id="${esc(id)}">${gcText(zh,en)}</button>`;
const gcSelected=id=>[...document.getElementById(id).selectedOptions].map(o=>o.value);
const gcOptions=(items,selected)=>items.map(([id,label])=>`<option value="${esc(id)}" ${selected.includes(id)?'selected':''} data-user-content>${esc(label)}</option>`).join('');
const gcMulti=(id,zh,en,items,selected)=>`<div class="field"><label for="${id}">${gcText(zh,en)}</label><select id="${id}" multiple required size="4">${gcOptions(items,selected)}</select></div>`;
const gcState=s=>({verified:['已验证','Verified'],unverified:['待验证','Unverified'],failed:['失败','Failed'],prepared:['排队中','Queued'],running:['运行中','Running'],succeeded:['已结束','Finished'],interrupted:['已中断','Interrupted'],partial:['部分完成','Partially completed'],completed:['完成','Completed'],cancelled:['已取消','Cancelled']}[s]||[s,s]);
async function gcRequest(action,body){return aiRequest('/api/geo/collection/'+action,body);}
function gcCanLeave(){
 if(GEO_COLLECTION.busy){showGlobalError(gcText('正在处理采集配置，请稍候。','Processing collection settings. Please wait.'));return false;}
 if(document.querySelector('#gcConnectionForm[data-dirty=true]')&&!confirm(gcText('放弃未保存的连接配置？','Discard unsaved connection settings?')))return false;
 return true;
}
async function initGEOSettings(){
 const epoch=++GEO_COLLECTION.epoch,node=$('#geoSettingsRoot');
 node.innerHTML=`<p role="status">${gcText('读取中…','Loading…')}</p>`;
 try{
  const config=await gcRequest('config');if(epoch!==GEO_COLLECTION.epoch)return;
  GEO_COLLECTION.config=config;GEO_COLLECTION.account=null;
  node.innerHTML=`<h2>${gcText('GEO 采集连接','GEO search connections')}</h2><div class="domain-form-actions">${gcButton('new-connection','添加连接','Add connection')}${gcButton('settings-refresh','刷新','Refresh')}</div><p class="hint">${gcText('复用供应商凭据库。保存后测试联网搜索能力，再为站点创建采集计划。','Uses the provider credential vault. Test search capability after saving, then create a site collection plan.')}</p><div class="domain-form-actions"><button type="button" class="ghost" data-inflow-action="settings">${gcText("GEOInflow 连接","GEOInflow connection")}</button></div><div id="gcAccounts"></div><div id="gcConnectionEditor"></div><p id="gcSettingsMsg" role="status"></p>`;
  AdminUI.table('gcAccounts',config.accounts,[gcText('连接','Connection'),gcText('状态','Status'),gcText('今日请求 / 上限','Today / daily cap'),gcText('操作','Actions')],a=>`<tr><td data-user-content>${esc(a.name)}<p>${esc(a.provider+' / '+a.config.model)}</p></td><td>${gcText(...gcState(a.verification.status))}${a.enabled?'':' · '+gcText('已停用','Disabled')}<p data-user-content>${esc(a.verification.error||'')}</p></td><td>${a.requests_today}/${esc(a.config.daily_limit)}</td><td>${gcButton('edit-connection','编辑','Edit',a.id)}${gcButton('test','测试搜索','Test search',a.id)}${gcButton('delete-connection','删除','Delete',a.id)}</td></tr>`);
 }catch(e){node.innerHTML=`<p role="alert">${esc(e.message)}</p>${gcButton('settings-refresh','重试','Retry')}`;}
}
async function gcEditConnection(a){
 GEO_COLLECTION.account=a;
 const profiles=(await aiRequest('/api/ai/config')).profiles.filter(p=>p.protocol==='openai_responses');
 $('#gcConnectionEditor').innerHTML=`<form id="gcConnectionForm"><h3>${gcText(a?'编辑连接':'添加连接',a?'Edit connection':'Add connection')}</h3><div class="formrow">${geoField('gcID','连接 ID','Connection ID',a?.id||'','text',`required pattern="[a-z][a-z0-9_-]{1,39}" ${a?'readonly':''}`)}${geoField('gcName','名称','Name',a?.name||'','text','required maxlength="100"')}</div>${geoSelect('gcProvider','平台','Provider',[['openai_search','OpenAI'],['gemini_search','Gemini']],a?.provider||'openai_search')}${a?'':geoSelect('gcImport','凭据来源','Credential source',[['',gcText('填写 API Key','Enter API key')],...profiles.map(p=>[p.id,p.name+' / '+p.model])])}${geoField('gcKey','API Key（编辑时留空保留）','API key (leave blank to keep)', '', 'password','autocomplete="new-password"')}${geoField('gcModel','模型','Model',a?.config.model||'gpt-6-astra','text','required maxlength="100"')}<div class="formrow">${geoField('gcLimit','每日请求上限（UTC）','Daily request cap (UTC)',a?.config.daily_limit||'40','number','required min="1" max="2000"')}${geoField('gcTokens','最大输出 Token','Maximum output tokens',a?.config.max_tokens||'4096','number','required min="256" max="16000"')}</div>${gcMulti('gcSites','授权站点','Authorized sites',STATE.sites.filter(s=>!s.archived).map(s=>[s.slug,s.company+' / '+s.domain]),a?.sites||[])}<label><input id="gcEnabled" type="checkbox" ${a?.enabled!==false?'checked':''}>${gcText('启用连接','Enable connection')}</label><p class="hint">${gcText('测试也消耗请求额度。费用由供应商计费；请求上限不等于金额上限。','Tests also consume requests. Provider billing applies; a request cap is not a monetary cap.')}</p><div class="domain-form-actions"><button type="submit">${gcText('保存','Save')}</button>${gcButton('cancel-connection','取消','Cancel')}</div><p id="gcConnectionMsg" role="status"></p></form>`;
 $('#gcProvider').disabled=!!a;
 $('#gcProvider').onchange=()=>{$('#gcModel').value=$('#gcProvider').value==='openai_search'?'gpt-6-astra':'gemini-3.8-flash';if($('#gcImport'))$('#gcImport').value='';};
 if($('#gcImport'))$('#gcImport').onchange=()=>{const p=profiles.find(p=>p.id===geoValue('gcImport'));if(p){$('#gcProvider').value='openai_search';$('#gcModel').value=p.model;}$('#gcKey').value='';$('#gcKey').disabled=!!p;};
 $('#gcConnectionForm').oninput=e=>e.currentTarget.dataset.dirty='true';
 $('#gcConnectionForm').onsubmit=async e=>{
  e.preventDefault();if(GEO_COLLECTION.busy)return;GEO_COLLECTION.busy=true;e.submitter.disabled=true;
  try{const body={id:geoValue('gcID'),version:a?.version,name:geoValue('gcName'),provider:geoValue('gcProvider'),enabled:$('#gcEnabled').checked,sites:gcSelected('gcSites'),capabilities:['geo'],values:{api_key:geoValue('gcKey'),model:geoValue('gcModel'),daily_limit:geoValue('gcLimit'),max_tokens:geoValue('gcTokens')}};
   const imported=geoValue('gcImport');if(imported)body.profile_id=imported;
   await gcRequest(imported?'import-llm':'connection',body);$('#gcKey').value='';await initGEOSettings();
  }catch(err){AdminUI.message('#gcConnectionMsg',[err.message,err.message],true);}finally{GEO_COLLECTION.busy=false;e.submitter.disabled=false;}
 };
 $('#gcName').focus();
}
async function gcLoadSite(){
 clearTimeout(GEO_COLLECTION.poll);
 const root=$('#geoCollection');if(!root)return;
 const slug=GEO.data.site.slug;
 root.innerHTML=`<p role="status">${gcText('读取采集计划…','Loading collection plans…')}</p>`;
 try{
  const [config,workspace]=await Promise.all([gcRequest('config?slug='+encodeURIComponent(slug)),aiRequest('/api/geo/workspace?slug='+encodeURIComponent(slug))]);if(!root.isConnected||GEO.data.site.slug!==slug)return;
  if(!GEO.dirty){GEO.data=workspace;geoLists();}
  GEO_COLLECTION.config=config;GEO_COLLECTION.plan=null;
  root.innerHTML=`<h4>${gcText('自动采集','Automatic collection')}</h4><div class="domain-form-actions">${gcButton('new-plan','添加计划','Add plan')}${gcButton('site-refresh','刷新进度','Refresh progress')}</div><details><summary>${gcText('采集说明','About collection')}</summary><p>${gcText('这里测量官方联网 API 的回答，不代表消费端应用排名。每次使用新请求，只发送问题、语言与市场。品牌事实库不会进入采集问题。','Measures official search API answers, not consumer-app rankings. Each fresh request sends only the question, language and market. Brand facts are excluded from measurement prompts.')}</p></details><div id="gcPlans"></div><div id="gcPlanEditor"></div><div id="gcRuns"></div><p id="gcSiteMsg" role="status"></p>`;
  AdminUI.table('gcPlans',config.plans,[gcText('计划','Plan'),gcText('调度','Schedule'),gcText('操作','Actions')],p=>`<tr><td data-user-content>${esc(p.name)}<p>${p.question_ids.length*p.account_ids.length*p.repeats} ${gcText('次请求 / 轮','requests / round')}</p></td><td>${p.enabled?new Date(p.next_run*1000).toLocaleString():gcText('手动 / 已暂停','Manual / paused')}<p data-user-content>${esc(p.last_error||'')}</p></td><td>${gcButton('run','立即采集','Run now',p.id)}${gcButton('edit-plan','编辑','Edit',p.id)}${gcButton('pause','暂停','Pause',p.id)}${gcButton('delete-plan','删除','Delete',p.id)}</td></tr>`);
  AdminUI.table('gcRuns',config.runs,[gcText('采集记录','Collection run'),gcText('状态','Status'),gcText('进度','Progress'),gcText('操作','Actions')],r=>`<tr><td data-user-content>${esc(r.summary)}<p>${new Date(r.created*1000).toLocaleString()}</p></td><td>${gcText(...gcState(r.result?.status||r.state))}<p data-user-content>${esc(r.error||'')}</p></td><td>${r.progress.length}/${r.total}</td><td>${gcButton('run-detail','详情','Details',r.id)}${['prepared','running'].includes(r.state)?'':gcButton('retry','重试未成功样本','Retry unsuccessful samples',r.id)}</td></tr>`);
  if(config.runs.some(r=>['prepared','running'].includes(r.state)))GEO_COLLECTION.poll=setTimeout(()=>{
   if(root.isConnected&&CURRENT_TAB==='geo'&&GEO.data.site.slug===slug&&!GEO.dirty&&!GEO.busy&&!GEO_COLLECTION.busy&&!$('#gcPlanForm'))gcLoadSite();
  },3000);
 }catch(e){if(root.isConnected)root.innerHTML=`<p role="alert">${esc(e.message)}</p>${gcButton('site-refresh','重试','Retry')}`;}
}
function gcEditPlan(p){
 GEO_COLLECTION.plan=p;
 const accounts=GEO_COLLECTION.config.accounts.filter(a=>a.enabled&&a.verification.status==='verified');
 $('#gcPlanEditor').innerHTML=`<form id="gcPlanForm"><h4>${gcText(p?'编辑计划':'添加计划',p?'Edit plan':'Add plan')}</h4>${geoField('gcPlanName','计划名称','Plan name',p?.name||'','text','required maxlength="80"')}${gcMulti('gcQuestions','目标问题','Target questions',GEO.data.workspace.questions.filter(q=>q.active).map(q=>[q.id,q.language+' / '+q.text]),p?.question_ids||[])}${gcMulti('gcConnections','已验证连接','Verified connections',accounts.map(a=>[a.id,a.name+' / '+a.config.model]),p?.account_ids||[])}<div class="formrow">${geoField('gcRepeats','每题每平台采样次数','Samples per question and provider',p?.repeats||1,'number','required min="1" max="40"')}${geoSelect('gcInterval','采集频率','Frequency',[[0,gcText('仅手动','Manual only')],[6,gcText('每 6 小时','Every 6 hours')],[12,gcText('每 12 小时','Every 12 hours')],[24,gcText('每天','Daily')],[168,gcText('每周','Weekly')]].map(([n,label])=>[String(n),label]),String(p?.interval_hours||0))}</div><label><input id="gcSchedule" type="checkbox" ${p?.enabled?'checked':''}>${gcText('启用定时采集','Enable scheduled collection')}</label><p id="gcEstimate" role="status"></p><div class="domain-form-actions"><button type="submit">${gcText('保存计划','Save plan')}</button>${gcButton('cancel-plan','取消','Cancel')}</div><p id="gcPlanMsg" role="status"></p></form>`;
 const estimate=()=>{$('#gcEstimate').textContent=gcText('每轮预计请求：','Estimated requests per round: ')+gcSelected('gcQuestions').length*gcSelected('gcConnections').length*Number(geoValue('gcRepeats'))+gcText('（最多 120 次，受每日额度限制）',' (maximum 120, subject to daily quota)');};estimate();
 $('#gcPlanForm').oninput=()=>{GEO.dirty=true;estimate();};
 $('#gcPlanForm').onsubmit=async e=>{e.preventDefault();if(GEO.busy)return;GEO.busy=true;e.submitter.disabled=true;try{
  await gcRequest('plan',{id:p?.id,version:p?.version,slug:GEO.data.site.slug,name:geoValue('gcPlanName'),question_ids:gcSelected('gcQuestions'),account_ids:gcSelected('gcConnections'),repeats:Number(geoValue('gcRepeats')),interval_hours:Number(geoValue('gcInterval')),enabled:$('#gcSchedule').checked});GEO.dirty=false;await gcLoadSite();
 }catch(err){AdminUI.message('#gcPlanMsg',[err.message,err.message],true);}finally{GEO.busy=false;e.submitter.disabled=false;}};
 $('#gcPlanName').focus();
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-gc-action]');if(!b||GEO_COLLECTION.busy||GEO.busy)return;
 const action=b.dataset.gcAction,id=b.dataset.id,isSite=!!b.closest('#geoCollection'),msg=isSite?'#gcSiteMsg':'#gcSettingsMsg';
 if(isSite&&GEO.dirty&&!geoCanLeave())return;
 const a=GEO_COLLECTION.config?.accounts.find(a=>a.id===id),p=GEO_COLLECTION.config?.plans.find(p=>p.id===id),r=GEO_COLLECTION.config?.runs.find(r=>r.id===id);
 b.disabled=true;
 try{
  if(action==='settings-refresh'){if(gcCanLeave())await initGEOSettings();return;}
  if(action==='new-connection'||action==='edit-connection'){if(gcCanLeave())await gcEditConnection(a);return;}
  if(action==='cancel-connection'){if(gcCanLeave())$('#gcConnectionEditor').innerHTML='';return;}
  if(action==='site-refresh'){await gcLoadSite();return;}
  if(action==='new-plan'||action==='edit-plan'){gcEditPlan(p);return;}
  if(action==='cancel-plan'){$('#gcPlanEditor').innerHTML='';return;}
  if(action==='run-detail'){AdminUI.detail(gcText('采集记录','Collection run'),`<pre data-user-content>${esc(JSON.stringify(r,null,2))}</pre>`);return;}
  if(['delete-connection','delete-plan','retry','run','test'].includes(action)&&!confirm(gcText(action.startsWith('delete')?'确认删除？':'此操作会调用供应商 API 并可能产生费用，继续？',action.startsWith('delete')?'Confirm deletion?':'This calls the provider API and may incur charges. Continue?')))return;
  GEO_COLLECTION.busy=true;if(isSite)GEO.busy=true;
  if(action==='test'){await gcRequest('test',{id,version:a.version});await initGEOSettings();}
  if(action==='delete-connection'){await gcRequest('connection',{id,version:a.version,action:'delete'});await initGEOSettings();}
  if(action==='pause'||action==='delete-plan'){await gcRequest('plan-action',{id,version:p.version,action:action==='pause'?'pause':'delete'});await gcLoadSite();}
  if(action==='run'||action==='retry'){const plan=p||GEO_COLLECTION.config.plans.find(p=>p.id===r.plan_id);if(!plan)throw Error(gcText('原计划已删除','Original plan was deleted'));await gcRequest('run',{id:plan.id,version:plan.version,request_key:crypto.randomUUID(),retry_run_id:r?.id});await gcLoadSite();}
 }catch(err){AdminUI.message(msg,[err.message,err.message],true);}finally{GEO_COLLECTION.busy=false;if(isSite)GEO.busy=false;b.disabled=false;}
});
new MutationObserver(()=>{if($('#p-geo-settings').classList.contains('hidden')){const key=$('#gcKey');if(key)key.value='';}}).observe($('#p-geo-settings'),{attributes:true,attributeFilter:['class']});
new MutationObserver(async()=>{
 if(CURRENT_TAB!=='geo-settings'||GEO_COLLECTION.busy)return;
 const form=$('#gcConnectionForm'),account=GEO_COLLECTION.account,dirty=form?.dataset.dirty;
 const values=form?[...form.querySelectorAll('input,select')].map(e=>[e.id,e.multiple?[...e.selectedOptions].map(o=>o.value):e.value,e.checked,e.disabled]):null;
 try{await initGEOSettings();if(values){await gcEditConnection(account);for(const [id,value,checked,disabled] of values){const e=document.getElementById(id);if(!e)continue;if(e.multiple)[...e.options].forEach(o=>o.selected=value.includes(o.value));else e.value=value;e.checked=checked;e.disabled=disabled;}$('#gcConnectionForm').dataset.dirty=dirty||'false';}}
 catch(e){AdminUI.message('#gcSettingsMsg',[e.message,e.message],true);}
}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
window.addEventListener('beforeunload',e=>{if(GEO_COLLECTION.busy||$('#gcConnectionForm')?.dataset.dirty==='true'){e.preventDefault();e.returnValue='';}});
