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
    $('#aiJobs').innerHTML=data.jobs.length?data.jobs.map(j=>`<div class="dom-row">
      <div class="h"><b>${esc(j.slug)}</b><span class="pill">${esc(labels[j.status]||j.status)}</span>
      <span>${esc(j.provider)} / ${esc(j.model)}</span>${j.simulated?'<span class="pill">模拟</span>':''}
      <span class="hint">${esc(new Date(j.created*1000).toLocaleString())}</span></div>
      <p style="margin:8px 0">${esc(j.message)}</p>
      ${j.status==='completed'?`<a href="/preview/${encodeURIComponent(j.slug)}/home" target="_blank" rel="noopener">预览草稿</a>
      <button type="button" data-ai-editor="${esc(j.slug)}">编辑页面</button>
      <button type="button" data-ai-publish="${esc(j.slug)}">发布当前草稿</button>
      <span class="hint">${Number(j.pages)} 个页面 · 预览和发布均使用该站点当前草稿</span>`:''}</div>`).join(''):'<div class="callout">还没有建站任务。填写上方要求，开始生成第一份草稿。</div>';
  } catch(e) { aiMessage('#aiBuildMsg', e.message, true); }
  finally { AI_LOADING=false; }
}
async function initAI() {
  try {
    await aiLoadConfig();
    aiOptions('#aiSite',(STATE.sites||[]).map(s=>({...s,id:s.slug})),s=>s.company+' / '+s.slug);
    aiOptions('#aiPlan',STATE.plans||[],p=>p.name+' — '+money(p.price));
    aiOptions('#aiIndustry',(STATE.industries||[]).map(([id,name])=>({id,name})),p=>p.name);
    if (!AI_READY) {
      $('#aiMode').value=STATE.sites.length?'existing':'new'; $('#aiIndustry').value='tech';
      AI_READY=true;
    }
    aiMode(); await aiJobs();
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
      brief:$('#aiBrief').value.trim(),replace_draft:$('#aiReplace').checked};
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
