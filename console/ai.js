/* AI website generation UI. No provider keys are retained in browser storage. */
let AI_CONFIG = null;
let AI_READY = false;
let AI_POLL = null;
let AI_LOADING = false;
let AI_PUBLISHING = false;
async function aiRequest(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  if (response.status === 401) throw new Error('登录已过期，请刷新页面重新登录');
  let data;
  try { data = await response.json(); } catch (_) { throw new Error('服务响应异常，请稍后重试'); }
  if (!response.ok) throw new Error(data.error || '操作失败');
  return data;
}
function aiMessage(id, message, bad=false) {
  const el = $(id); el.textContent = message; el.className = 'msg ' + (bad ? 'bad' : 'ok');
}
function aiOptions(id, items, label) {
  const el = $(id), old = el.value;
  el.innerHTML = items.map(x => `<option value="${esc(x.id)}">${esc(label(x))}</option>`).join('');
  if (items.some(x => x.id === old)) el.value = old;
}
function aiMode() {
  const isNew = $('#aiMode').value === 'new';
  $('#aiExistingWrap').classList.toggle('hidden', isNew);
  $('#aiNewFields').classList.toggle('hidden', !isNew);
  $('#aiReplaceWrap').style.display = isNew ? 'none' : 'block';
  for (const id of ['aiCompany','aiDomain','aiSlug','aiPlan']) $('#'+id).required = isNew;
  $('#aiSite').required = !isNew;
  $('#aiGenerate').textContent = isNew ? '创建站点并生成草稿' : '生成整站草稿';
}
function aiNotice() {
  const p = (AI_CONFIG?.profiles || []).find(p => p.id === $('#aiProfile').value);
  $('#aiModeNotice').textContent = p?.protocol === 'mock'
    ? '当前为 GPT 模拟模式：按企业信息与需求生成示例草稿，不调用真实 GPT、不产生模型费用。'
    : `将调用 ${p?.name || '所选服务商'} / ${p?.model || ''} 生成内容，企业名称和建站要求会发送至该配置的接口。`;
}
function aiRenderProfiles() {
  $('#aiSettings').classList.toggle('hidden', !AI_CONFIG.can_configure);
  if (!AI_CONFIG.can_configure) return;
  $('#aiProfilesList').innerHTML = AI_CONFIG.profiles.map(p => `<div class="share-row">
    <span class="u">${esc(p.name)} · ${esc(p.model)} ${p.id===AI_CONFIG.default_profile?' · 默认':''}</span>
    <span class="hint">${p.protocol==='mock'?'模拟':esc(p.protocol)+(p.has_key?' · 已配置密钥':' · 无密钥')}</span>
    ${p.id!=='mock'?`<button type="button" data-ai-edit="${esc(p.id)}">编辑</button>`:''}
    <button type="button" data-ai-test="${esc(p.id)}">测试连接</button>
    ${p.id!==AI_CONFIG.default_profile?`<button type="button" data-ai-default="${esc(p.id)}">设为默认</button>`:''}
    ${p.id!=='mock'?`<button type="button" data-ai-delete="${esc(p.id)}">删除</button>`:''}</div>`).join('');
  $('#aiPreset').innerHTML = '<option value="">自定义配置</option>' + AI_CONFIG.presets.map((p,i)=>`<option value="${i}">${esc(p.name)}</option>`).join('');
}
async function aiLoadConfig() {
  const old = $('#aiProfile').value;
  AI_CONFIG = await aiRequest('/api/ai/config');
  aiOptions('#aiProfile', AI_CONFIG.profiles, p => p.name+' / '+p.model);
  if (!old || !AI_CONFIG.profiles.some(p=>p.id===old)) $('#aiProfile').value = AI_CONFIG.default_profile;
  aiRenderProfiles(); aiNotice();
}
function aiEditConfig(id) {
  const p = AI_CONFIG.profiles.find(p=>p.id===id);
  if (!p) return;
  const fields = {aiConfigId:'id',aiConfigName:'name',aiProtocol:'protocol',aiBaseUrl:'base_url',aiModel:'model',aiTimeout:'timeout',aiMaxTokens:'max_tokens',aiTokenParameter:'token_parameter'};
  for (const [id,key] of Object.entries(fields)) $('#'+id).value=p[key];
  $('#aiJsonMode').checked=p.json_mode; $('#aiKey').value=''; $('#aiClearKey').checked=false;
  $('#aiConfigId').readOnly=true;
  $('#aiSettings').open=true; $('#aiConfigForm').scrollIntoView({block:'center',behavior:'smooth'});
}
function aiResetConfig() {
  $('#aiConfigForm').reset(); $('#aiConfigId').readOnly=false; $('#aiKey').value='';
}
async function aiOpenEditor(slug) {
  await load();
  $('#lSlug').innerHTML='';
  window.aiEditorTarget=slug;
  document.querySelector('[data-t="layout"]').click();
}
async function aiJobs() {
  if (AI_LOADING || AI_PUBLISHING) return;
  AI_LOADING=true;
  try {
    const data=await aiRequest('/api/ai/jobs');
    const labels={queued:'排队中',generating:'生成中',provisioning:'开通站点中',saving:'保存中',completed:'草稿已就绪',failed:'失败',interrupted:'已中断'};
    const html=data.jobs.length?data.jobs.map(j=>`<div class="dom-row">
      <div class="h"><b>${esc(j.slug)}</b><span class="pill">${esc(labels[j.status]||j.status)}</span>
      <span>${esc(j.provider)} / ${esc(j.model)}</span>${j.simulated?'<span class="pill">模拟</span>':''}
      <span class="hint">${esc(new Date(j.created*1000).toLocaleString())}</span></div>
      <p style="margin:8px 0">${esc(j.message)}</p>${j.style?`<p>参考风格：${esc(j.style.name)}${j.style.version?` · v${Number(j.style.version)}`:""}（随草稿发布）</p>`:""}${j.prompt?`<details><summary>提示词：${esc(j.prompt.template.name)} · v${j.prompt.template.version}</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(j.prompt.preview)}</pre></details>`:''}
      ${j.status==='completed'?`<a href="/preview/${encodeURIComponent(j.slug)}/home" target="_blank" rel="noopener">预览草稿</a>
      <button type="button" data-ai-editor="${esc(j.slug)}">编辑页面</button>
      <button type="button" data-ai-publish="${esc(j.slug)}">发布当前草稿</button>
      <span class="hint">${Number(j.pages)} 个页面 · 预览和发布均使用该站点当前草稿</span>`:''}</div>`).join(''):'<div class="callout">还没有建站任务。填写上方要求，开始生成第一份草稿。</div>';
    setStableHtml($('#aiJobs'),html);
  } catch(e) { aiMessage('#aiBuildMsg', e.message, true); }
  finally { AI_LOADING=false; }
}
async function initAI() {
  try {
    await aiLoadConfig();
    await initPromptComposer();
    await styleLoad();
    aiOptions('#aiSite',(STATE.sites||[]).map(s=>({...s,id:s.slug})),s=>s.company+' / '+s.slug);
    aiOptions('#aiPlan',STATE.plans||[],p=>p.name+' — '+money(p.price));
    aiOptions('#aiIndustry',(STATE.industries||[]).map(([id,name])=>({id,name})),p=>p.name);
    if (!AI_READY) {
      $('#aiMode').value=STATE.sites.length?'existing':'new'; $('#aiIndustry').value='tech';
      AI_READY=true;
    }
    if(window.aiContextTarget){$('#aiMode').value='existing';$('#aiSite').value=window.aiContextTarget;window.aiContextTarget=null;}
    renderAIContext();aiMode(); await aiJobs();
    if (!AI_POLL) AI_POLL=setInterval(()=>{if(!$('#p-ai').classList.contains('hidden')) aiJobs();},3000);
  } catch(e) { aiMessage('#aiBuildMsg', e.message, true); }
}
$('#aiMode').onchange=aiMode;
$('#aiProfile').onchange=aiNotice;
$('#aiResetConfig').onclick=aiResetConfig;
$('#aiPreset').onchange=()=>{
  const preset=AI_CONFIG?.presets?.[$('#aiPreset').value]; if(!preset) return;
  $('#aiProtocol').value=preset.protocol; $('#aiBaseUrl').value=preset.base_url;
  $('#aiConfigName').value=preset.name;
};
$('#aiBuildForm').onsubmit=async e=>{
  e.preventDefault(); const button=$('#aiGenerate'); button.disabled=true;
  aiMessage('#aiBuildMsg','正在提交任务…');
  try {
    const mode=$('#aiMode').value;
    const body={mode,slug:mode==='new'?$('#aiSlug').value.trim():$('#aiSite').value,
      company:$('#aiCompany').value.trim(),domain:$('#aiDomain').value.trim(),plan_id:$('#aiPlan').value,
      industry:$('#aiIndustry').value,profile_id:$('#aiProfile').value,language:$('#aiLanguage').value,
      brief:$('#aiBrief').value.trim(),replace_draft:$('#aiReplace').checked,
      context_options:mode==='existing'?[...document.querySelectorAll('#aiContextOptions input[value]:checked')].map(e=>e.value):[],
      context_actions:mode==='existing'?(window.aiContextActions||[]):[],auto_research:mode==='existing'&&$('#aiAutoResearch').checked};
    Object.assign(body, styleSelection());
    const selection=promptSelection();
    if(selection){await previewPrompt();body.prompt_selection=selection;}
    await aiRequest('/api/ai/build',body);
    aiMessage('#aiBuildMsg','任务已提交，进度显示在下方。可以离开本页，任务会继续执行。');
    await aiJobs();
  } catch(e) { aiMessage('#aiBuildMsg', e.message, true); }
  finally { button.disabled=false; }
};
$('#aiConfigForm').onsubmit=async e=>{
  e.preventDefault(); const button=e.submitter; button.disabled=true;
  try {
    await aiRequest('/api/ai/config',{action:'save',id:$('#aiConfigId').value.trim(),name:$('#aiConfigName').value.trim(),
      protocol:$('#aiProtocol').value,base_url:$('#aiBaseUrl').value.trim(),model:$('#aiModel').value.trim(),
      api_key:$('#aiKey').value,clear_key:$('#aiClearKey').checked,timeout:Number($('#aiTimeout').value),
      max_tokens:Number($('#aiMaxTokens').value),token_parameter:$('#aiTokenParameter').value,json_mode:$('#aiJsonMode').checked});
    $('#aiKey').value=''; $('#aiClearKey').checked=false;
    await aiLoadConfig(); aiMessage('#aiConfigMsg','配置已保存，可点击“测试连接”验证。');
  } catch(e) { aiMessage('#aiConfigMsg',e.message,true); }
  finally { button.disabled=false; }
};
$('#aiProfilesList').onclick=async e=>{
  const button=e.target.closest('button'); if(!button) return;
  if(button.dataset.aiEdit){aiEditConfig(button.dataset.aiEdit);return;}
  button.disabled=true;
  try {
    if(button.dataset.aiTest){
      aiMessage('#aiConfigMsg','正在测试接口…');
      const d=await aiRequest('/api/ai/test',{profile_id:button.dataset.aiTest});
      aiMessage('#aiConfigMsg',d.message);
    } else {
      const id=button.dataset.aiDefault||button.dataset.aiDelete;
      if(button.dataset.aiDelete&&!confirm('删除这个模型配置和保存的密钥？'))return;
      await aiRequest('/api/ai/config',{action:button.dataset.aiDefault?'default':'delete',id});
      await aiLoadConfig(); aiMessage('#aiConfigMsg','配置已更新');
    }
  } catch(e) { aiMessage('#aiConfigMsg',e.message,true); }
  finally { button.disabled=false; }
};
$('#aiJobs').onclick=async e=>{
  const button=e.target.closest('button'); if(!button) return;
  button.disabled=true;
  try {
    if(button.dataset.aiEditor) await aiOpenEditor(button.dataset.aiEditor);
    else if(button.dataset.aiPublish) {
      if(!confirm('将该站点当前草稿发布到线上？请先完成预览检查。')) return;
      AI_PUBLISHING=true;
      aiMessage('#aiBuildMsg','正在发布页面…');
      const d=await aiRequest('/api/publish',{slug:button.dataset.aiPublish});
      aiMessage('#aiBuildMsg',`已发布 ${d.pages} 个页面`);
    }
  } catch(e) { aiMessage('#aiBuildMsg',e.message,true); }
  finally { button.disabled=false; AI_PUBLISHING=false; }
};

// Reference analyses are explicit selections; saved templates are immutable job snapshots.
let STYLE_LIBRARY={templates:[],can_manage:false}, STYLE_ANALYSIS=null, STYLE_EDIT=null;
const STYLE_LABELS={primary:'主色',primaryDark:'深主色',accent:'强调色',bg:'页面背景',surface:'卡片背景',ink:'正文',muted:'次要文字',deep:'深色背景'};
async function styleLoad(){
 const previous=$('#aiStyleTemplate').value;
 STYLE_LIBRARY=await aiRequest('/api/ai/styles');
 STYLE_LIBRARY.templates=STYLE_LIBRARY.templates||[];
 $('#aiStyleTemplate').innerHTML='<option value="">保持站点当前风格</option>'+(STYLE_ANALYSIS?'<option value="@analysis">刚分析的参考风格</option>':'')+STYLE_LIBRARY.templates.filter(t=>t.enabled).map(t=>`<option value="${esc(t.id)}">${esc(t.name)} · v${Number(t.version)}</option>`).join('');
 if([...$('#aiStyleTemplate').options].some(o=>o.value===previous))$('#aiStyleTemplate').value=previous;
 $('#aiStyleSaveAnalysis').classList.toggle('hidden',!STYLE_LIBRARY.can_manage);
 styleRender();
}
function styleRender(){
 const q=$('#styleSearch').value.trim().toLowerCase();
 const items=STYLE_LIBRARY.templates.filter(t=>(t.name+' '+t.category).toLowerCase().includes(q));
 $('#styleLibrary').innerHTML=items.length?items.map(t=>`<div class="share-row"><span class="u">${esc(t.name)} · ${esc(t.category)} · v${Number(t.version)}${t.enabled?'':' · 已停用'}</span><button type="button" data-style-use="${esc(t.id)}" ${t.enabled?'':'disabled'}>使用</button>${STYLE_LIBRARY.can_manage?`<button type="button" data-style-edit="${esc(t.id)}">编辑</button><button type="button" data-style-copy="${esc(t.id)}">复制</button><button type="button" data-style-delete="${esc(t.id)}">删除</button>`:''}</div>`).join(''):'<p class="hint">尚无匹配模板。分析参考网站后可保存为模板。</p>';
}
function styleShow(item){
 $('#aiStyleResult').classList.toggle('hidden',!item);
 if(!item)return;
 $('#aiStyleSummary').textContent=item.summary;
 $('#aiStyleWarnings').textContent=(item.warnings||[]).join(' ');
 $('#aiStyleEvidence').textContent=item.evidence?JSON.stringify(item.evidence,null,2):'已保存模板 · '+(item.source_url||'自定义');
 $('#aiStyleSwatches').innerHTML=Object.entries(item.tokens.palette).map(([k,v])=>`<span><span style="display:inline-block;width:20px;height:20px;border:1px solid #777;background:${/^#[0-9a-f]{6}$/i.test(v)?v:'#ffffff'}"></span> ${esc(STYLE_LABELS[k]||k)} ${esc(v)}</span>`).join('');
 $('#aiStyleSaveAnalysis').classList.toggle('hidden',!STYLE_LIBRARY.can_manage||$('#aiStyleTemplate').value!=='@analysis');
}
function styleSelection(){
 if($('#aiAnalyzeStyle').disabled)throw new Error('请等待参考风格分析完成');
 const id=$('#aiStyleTemplate').value;
 if(id==='@analysis'){
  if(!STYLE_ANALYSIS)throw new Error('请先分析参考网站');
  if($('#aiReferenceUrl').value.trim()!==STYLE_ANALYSIS.requested_url)throw new Error('参考网址已修改，请重新分析后生成');
  return {reference_style:STYLE_ANALYSIS};
 }
 return id?{style_template_id:id}:{};
}
$('#aiAnalyzeStyle').onclick=async()=>{
 const button=$('#aiAnalyzeStyle');button.disabled=true;
 const url=$('#aiReferenceUrl').value.trim();
 aiMessage('#aiStyleMsg','正在读取参考网站和样式…');
 try{
  const result=await aiRequest('/api/ai/styles/analyze',{url});
  STYLE_ANALYSIS={...result,requested_url:url};
  await styleLoad();$('#aiStyleTemplate').value='@analysis';styleShow(STYLE_ANALYSIS);
  aiMessage('#aiStyleMsg','分析完成，已选择本次参考风格。可直接生成，也可先编辑保存为模板。');
 }catch(e){aiMessage('#aiStyleMsg',e.message,true);}
 finally{button.disabled=false;}
};
$('#aiStyleTemplate').onchange=()=>styleShow($('#aiStyleTemplate').value==='@analysis'?STYLE_ANALYSIS:STYLE_LIBRARY.templates.find(t=>t.id===$('#aiStyleTemplate').value));
$('#aiStyleManage').onclick=()=>{$('#styleManager').open=true;$('#styleManager').scrollIntoView({block:'start'});};
function styleEdit(item){
 STYLE_EDIT=JSON.parse(JSON.stringify(item));
 for(const [id,key] of Object.entries({styleName:'name',styleCategory:'category',styleSource:'source_url',styleSummary:'summary',styleGuidance:'guidance'}))$('#'+id).value=item[key]||'';
 $('#styleEnabled').checked=item.enabled!==false;
 $('#styleHeading').value=item.tokens.type.heading;$('#styleRadius').value=parseInt(item.tokens.shape.radius);$('#stylePad').value=parseInt(item.tokens.layout.pad);
 $('#styleColors').innerHTML=Object.entries(STYLE_LABELS).map(([key,label])=>`<div class="field"><label for="styleColor-${key}">${label}</label><input type="color" id="styleColor-${key}" value="${esc(item.tokens.palette[key])}"></div>`).join('');
 $('#styleEditForm').classList.remove('hidden');$('#styleManager').open=true;$('#styleEditForm').scrollIntoView({block:'start'});
}
$('#aiStyleSaveAnalysis').onclick=()=>{if(STYLE_ANALYSIS)styleEdit({...STYLE_ANALYSIS,name:(STYLE_ANALYSIS.title||'参考网站').slice(0,70)+' 风格'});};
$('#styleCancel').onclick=()=>{$('#styleEditForm').classList.add('hidden');STYLE_EDIT=null;};
$('#styleSearch').oninput=styleRender;
$('#styleRefresh').onclick=async()=>{try{await styleLoad();aiMessage('#styleManageMsg','模板已刷新');}catch(e){aiMessage('#styleManageMsg',e.message,true);}};
$('#styleLibrary').onclick=async e=>{
 const button=e.target.closest('button');if(!button)return;
 const id=button.dataset.styleUse||button.dataset.styleEdit||button.dataset.styleCopy||button.dataset.styleDelete;
 const item=STYLE_LIBRARY.templates.find(t=>t.id===id);if(!item)return;
 if(button.dataset.styleUse){$('#aiStyleTemplate').value=id;styleShow(item);aiMessage('#aiStyleMsg','已选择 '+item.name);$('#aiStyleTemplate').scrollIntoView({block:'center'});return;}
 if(button.dataset.styleEdit){styleEdit(item);return;}
 if(button.dataset.styleDelete&&!confirm('删除此风格模板？已生成的网站和任务快照会保留。'))return;
 button.disabled=true;
 try{await aiRequest('/api/ai/styles',{action:button.dataset.styleCopy?'duplicate':'delete',id,version:item.version});await styleLoad();styleShow(null);aiMessage('#styleManageMsg','模板已更新');}
 catch(e){aiMessage('#styleManageMsg',e.message,true);}finally{button.disabled=false;}
};
$('#styleEditForm').onsubmit=async e=>{
 e.preventDefault();const button=e.submitter;button.disabled=true;
 try{
  const body=JSON.parse(JSON.stringify(STYLE_EDIT));
  for(const [id,key] of Object.entries({styleName:'name',styleCategory:'category',styleSource:'source_url',styleSummary:'summary',styleGuidance:'guidance'}))body[key]=$('#'+id).value.trim();
  body.enabled=$('#styleEnabled').checked;body.action='save';
  for(const key of Object.keys(STYLE_LABELS))body.tokens.palette[key]=$('#styleColor-'+key).value;
  body.tokens.type.heading=$('#styleHeading').value;body.tokens.shape.radius=$('#styleRadius').value+'px';body.tokens.layout.pad=$('#stylePad').value+'px';
  const data=await aiRequest('/api/ai/styles',body);await styleLoad();
  $('#aiStyleTemplate').value=data.item.enabled?data.item.id:'';styleShow(data.item.enabled?data.item:null);
  $('#styleEditForm').classList.add('hidden');STYLE_EDIT=null;aiMessage('#styleManageMsg','风格模板已保存，可用于后续建站');
 }catch(e){aiMessage('#styleManageMsg',e.message,true);}finally{button.disabled=false;}
};

function renderAIContext(){
 const entries=window.aiContextActions||[];
 $('#aiContextList').innerHTML=entries.map(id=>`<p><span data-user-content>${esc(window.aiContextLabels?.[id]||id)}</span> <button type="button" class="ghost" data-context-remove="${esc(id)}">移除</button></p>`).join('')||'<p class="hint">尚未选择 MCP 资料；可先在运营助手运行已授权的只读工具或资源读取。</p>';
}
$('#aiContextList').onclick=e=>{const b=e.target.closest('[data-context-remove]');if(!b)return;window.aiContextActions=(window.aiContextActions||[]).filter(id=>id!==b.dataset.contextRemove);renderAIContext();};
$('#aiChooseContext').onclick=()=>navigateTo('automation');
