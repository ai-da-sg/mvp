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
function aiMessage(id, message, bad=false, localized=false) {
  if(!localized&&typeof AdminUI!=='undefined')AdminUI.messages.delete(id);
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
  if(typeof Workspace!=='undefined'&&CURRENT_TAB==='ai')Workspace.sync();
}
function aiNotice() {
  const p = (AI_CONFIG?.profiles || []).find(p => p.id === $('#aiProfile').value);
  $('#aiModeNotice').textContent = p?.protocol === 'mock'
    ? '模拟模式：不调用模型，不产生费用。'
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
    const html=data.jobs.length?data.jobs.map(j=>`<div class="dom-row" data-operation-reference="${esc(j.id)}">
      <div class="h"><b>${esc(j.slug)}</b><span class="pill">${esc(labels[j.status]||j.status)}</span>
      <span>${esc(j.provider)} / ${esc(j.model)}</span>${j.simulated?'<span class="pill">模拟</span>':''}
      <span class="hint">${esc(new Date(j.created*1000).toLocaleString())}</span></div>
      <p style="margin:8px 0">${esc(j.message)}</p>${j.style?`<p>参考风格：${esc(j.style.name)}${j.style.version?` · v${Number(j.style.version)}`:""}（随草稿发布）</p>`:""}${j.prompt?`<details><summary>提示词：${esc(j.prompt.template.name)} · v${j.prompt.template.version}</summary><ol>${j.prompt.modules.map(m=>`<li data-user-content>${esc(m.name)} · v${Number(m.version)}</li>`).join('')}</ol><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(j.prompt.preview)}</pre></details>`:''}
      ${j.status==='completed'?`<a href="/preview/${encodeURIComponent(j.slug)}/home" target="_blank" rel="noopener">预览草稿</a>
      <button type="button" data-inflow-site="${esc(j.slug)}">流量与抓取分析</button><button type="button" data-ai-editor="${esc(j.slug)}">编辑页面</button>
      <button type="button" data-ai-publish="${esc(j.slug)}">发布当前草稿</button>
      <span class="hint">${Number(j.pages)} 个页面 · 预览和发布均使用该站点当前草稿</span>`:''}</div>`).join(''):'<div class="callout">暂无任务。填写需求后生成草稿。</div>';
    setStableHtml($('#aiJobs'),html);focusOperationTarget('generation','#aiJobs [data-operation-reference]');
  } catch(e) { aiMessage('#aiBuildMsg', e.message, true); }
  finally { AI_LOADING=false; }
}
async function initAI() {
  $('#aiMode').disabled=true;
  try {
    await aiLoadConfig();
    await initPromptComposer();
    await styleLoad();
    SiteContext.fill($('#aiSite'),window.aiContextTarget);
    aiOptions('#aiPlan',STATE.plans||[],p=>p.name+' — '+money(p.price));
    aiOptions('#aiIndustry',(STATE.industries||[]).map(([id,name])=>({id,name})),p=>p.name);
    if (!AI_READY) {
      $('#aiMode').value=$('#aiSite').value?'existing':'new'; $('#aiIndustry').value='tech';
      AI_READY=true;
    }
    if(window.aiContextTarget){$('#aiMode').value='existing';$('#aiSite').value=window.aiContextTarget;window.aiContextTarget=null;}
    renderAIContext();aiMode();buildReconcile();$('#aiMode').disabled=false;buildRender(); await aiJobs();
    if (!AI_POLL) AI_POLL=setInterval(()=>{if(!document.hidden&&!$('#p-ai').classList.contains('hidden')) aiJobs();},3000);
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
  e.preventDefault(); if(!buildCanSubmit())return; const button=$('#aiGenerate'); button.disabled=true;
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
 const oldIndustry=$('#styleIndustry').value;
 $('#styleIndustry').innerHTML=(STYLE_LIBRARY.industries||['tech','restaurant','preschool','law','trading','littlegems']).map(v=>`<option value="${esc(v)}">${esc((STATE.industries||[]).find(([id])=>id===v)?.[1]||v)}</option>`).join('');
 if(oldIndustry)$('#styleIndustry').value=oldIndustry;
 for(const id of ['styleSector','styleSectorFilter','aiStyleSector']){
  const el=$('#'+id),selected=el.value;
  el.innerHTML=(id==='styleSector'?'':'<option value="">全部行业</option>')+(STYLE_LIBRARY.sectors||[]).map(s=>`<option value="${esc(s.id)}">${esc(s.label)}</option>`).join('');
  el.value=selected||(id==='styleSector'?'general':'');
 }
 styleBuilderOptions(previous);
 $('#aiStyleSaveAnalysis').classList.toggle('hidden',!STYLE_LIBRARY.can_manage);
 styleBrowserLoad();styleRender();
}
function styleSectorLabel(id){return (STYLE_LIBRARY.sectors||[]).find(s=>s.id===(id||'general'))?.label||'通用';}
function styleBuilderOptions(previous=$('#aiStyleTemplate').value){
 const sector=$('#aiStyleSector').value;
 $('#aiStyleTemplate').innerHTML='<option value="">保持站点当前风格</option>'+(STYLE_ANALYSIS?'<option value="@analysis">刚分析的参考风格</option>':'')+STYLE_LIBRARY.templates.filter(t=>t.enabled&&(!sector||(t.sector||'general')===sector)).map(t=>`<option data-user-content value="${esc(t.id)}">${esc(t.name)} · v${Number(t.version)}</option>`).join('');
 if([...$('#aiStyleTemplate').options].some(o=>o.value===previous))$('#aiStyleTemplate').value=previous;
}
$('#aiStyleSector').onchange=()=>{styleBuilderOptions();$('#aiStyleTemplate').onchange();};
$('#styleSectorFilter').onchange=()=>styleRender();
function styleRender(){styleRenderBrowser();}
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
$('#aiStyleManage').onclick=()=>navigateTo('styles');
function styleEdit(item){
 if(!styleCanLeave())return;
 navigateTo('styles');
 STYLE_EDIT=JSON.parse(JSON.stringify(item));
 for(const [id,key] of Object.entries({styleName:'name',styleCategory:'category',styleSource:'source_url',styleSummary:'summary',styleGuidance:'guidance'}))$('#'+id).value=item[key]||'';
 $('#styleEnabled').checked=item.enabled!==false;
 $('#styleHeading').value=item.tokens.type.heading;$('#styleRadius').value=parseInt(item.tokens.shape.radius);$('#stylePad').value=parseInt(item.tokens.layout.pad);
 $('#styleColors').innerHTML=Object.entries(STYLE_LABELS).map(([key,label])=>`<div class="field"><label for="styleColor-${key}">${label}</label><input type="color" id="styleColor-${key}" value="${esc(item.tokens.palette[key])}"></div>`).join('');
 styleEditExtras(item);styleEditPages(item);STYLE_DIRTY=false;
 $('#styleEditForm').classList.remove('hidden');$('#styleEditForm').scrollIntoView({block:'start'});
}
$('#aiStyleSaveAnalysis').onclick=()=>{if(STYLE_ANALYSIS)styleEdit({...STYLE_ANALYSIS,name:(STYLE_ANALYSIS.title||'参考网站').slice(0,70)+' 风格'});};
$('#styleCancel').onclick=()=>{if(!styleCanLeave())return;$('#styleEditForm').classList.add('hidden');STYLE_EDIT=null;STYLE_DIRTY=false;};
$('#styleSearch').oninput=styleRender;
$('#styleRefresh').onclick=async()=>{try{await styleLoad();aiMessage('#styleManageMsg','模板已刷新');}catch(e){aiMessage('#styleManageMsg',e.message,true);}};
$('#styleLibrary').onclick=async e=>{
 const button=e.target.closest('button');if(!button)return;
 if(button.dataset.styleFavorite){styleToggleFavorite(button.dataset.styleFavorite);return;}
 if(button.dataset.styleCompare){styleToggleCompare(button.dataset.styleCompare);return;}
 if(button.dataset.styleHistory){styleHistory(button.dataset.styleHistory);return;}
 const id=button.dataset.styleUse||button.dataset.styleEdit||button.dataset.styleCopy||button.dataset.styleDelete||button.dataset.stylePreview||button.dataset.styleExport;
 const item=STYLE_LIBRARY.templates.find(t=>t.id===id);if(!item)return;
 if(button.dataset.stylePreview){try{await stylePreview(item);}catch(e){aiMessage('#styleManageMsg',e.message,true);}return;}
 if(button.dataset.styleExport){styleExport(item);return;}
 if(button.dataset.styleUse){styleUseTemplate(item);return;}
 if(button.dataset.styleEdit){styleEdit(item);return;}
 if(button.dataset.styleDelete&&!confirm('删除此风格模板？已生成的网站和任务快照会保留。'))return;
 button.disabled=true;
 try{await aiRequest('/api/ai/styles',{action:button.dataset.styleCopy?'duplicate':'delete',id,version:item.version});await styleLoad();styleShow(null);aiMessage('#styleManageMsg','模板已更新');}
 catch(e){aiMessage('#styleManageMsg',e.message,true);}finally{button.disabled=false;}
};
$('#styleEditForm').onsubmit=async e=>{
 e.preventDefault();const button=e.submitter;button.disabled=true;
 try{
  const body=styleReadForm();
  for(const [id,key] of Object.entries({styleName:'name',styleCategory:'category',styleSource:'source_url',styleSummary:'summary',styleGuidance:'guidance'}))body[key]=$('#'+id).value.trim();
  body.enabled=$('#styleEnabled').checked;body.action='save';
  for(const key of Object.keys(STYLE_LABELS))body.tokens.palette[key]=$('#styleColor-'+key).value;
  body.tokens.type.heading=$('#styleHeading').value;body.tokens.shape.radius=$('#styleRadius').value+'px';body.tokens.layout.pad=$('#stylePad').value+'px';
  const data=await aiRequest('/api/ai/styles',body);STYLE_DIRTY=false;await styleLoad();
  $('#aiStyleSector').value='';styleBuilderOptions();$('#aiStyleTemplate').value=data.item.enabled?data.item.id:'';styleShow(data.item.enabled?data.item:null);
  $('#styleEditForm').classList.add('hidden');STYLE_EDIT=null;aiMessage('#styleManageMsg','风格模板已保存，可用于后续建站');
 }catch(e){aiMessage('#styleManageMsg',e.message,true);}finally{button.disabled=false;}
};

function renderAIContext(){
 const entries=window.aiContextActions||[];
 if(entries.length)$('#aiContextOptions').open=true;
 $('#aiContextList').innerHTML=entries.map(id=>`<p><span data-user-content>${esc(window.aiContextLabels?.[id]||id)}</span> <button type="button" class="ghost" data-context-remove="${esc(id)}">移除</button></p>`).join('')||'<p class="hint">尚未选择 MCP 资料；可先在运营助手运行已授权的只读工具或资源读取。</p>';
}
$('#aiContextList').onclick=e=>{const b=e.target.closest('[data-context-remove]');if(!b)return;window.aiContextActions=(window.aiContextActions||[]).filter(id=>id!==b.dataset.contextRemove);renderAIContext();};
$('#aiChooseContext').onclick=()=>navigateTo('automation');

// Independent style library: visual controls and JSON share the same bounded schema.
let STYLE_DIRTY=false;
const STYLE_ADV_LABELS={body_font:'正文字体',body_size:'正文字号（px）',heading_size:'首屏标题字号（px）',heading_weight:'标题字重',line_height:'正文行高',content_width:'内容宽度（px）',grid_gap:'网格间距（px）',columns:'桌面列数',mobile_pad:'手机区块间距（px）',hero:'首屏布局',header:'导航定位',card_style:'卡片样式',image_ratio:'图片比例'};
const STYLE_OPTION_LABELS={sans:'无衬线',serif:'衬线',rounded:'圆润',mono:'等宽',split:'左右分栏',center:'居中',editorial:'编辑式布局',minimal:'极简',sticky:'吸顶',static:'随页面滚动',bordered:'描边',flat:'平面',elevated:'阴影'};
const STYLE_BLOCKS={hero:'首屏',cards:'卡片',split:'图文分栏',stats:'统计',cta:'行动引导',band:'横幅',gallery:'图库',quotes:'评价',table:'表格',list:'列表',rich:'富文本',form:'联系表单'};
function styleColor(value){return /^#[0-9a-f]{6}$/i.test(value)?value:'#ffffff';}
function styleCanLeave(){if(!STYLE_DIRTY)return true;if(!confirm('尚有未保存的模板修改，继续离开？'))return false;STYLE_DIRTY=false;return true;}
function styleEditExtras(item){
 $('#styleSector').value=item.sector||'general';$('#styleIndustry').value=item.industry||'tech';$('#styleTags').value=(item.tags||[]).join(', ');
 $('#styleButtonRadius').value=parseInt(item.tokens.shape.button);$('#styleOverlay').value=item.tokens.photos.overlay;
 $('#styleAdvanced').innerHTML=Object.entries(STYLE_LIBRARY.advanced_schema||{}).map(([key,spec])=>{
  const value=item.tokens.advanced?.[key]??spec[0];
  const control=typeof spec[0]==='string'?`<select id="styleAdv-${key}">${spec.slice(1).map(v=>`<option value="${esc(v)}" ${value===v?'selected':''}>${esc(STYLE_OPTION_LABELS[v]||v)}</option>`).join('')}</select>`:`<input id="styleAdv-${key}" type="number" min="${spec[1]}" max="${spec[2]}" step="${key==='line_height'?'.05':'1'}" value="${Number(value)}" required>`;
  return `<div class="field"><label for="styleAdv-${key}">${esc(STYLE_ADV_LABELS[key]||key)}</label>${control}</div>`;
 }).join('');
 STYLE_EDIT.blueprint=[...(item.blueprint?.length?item.blueprint:['hero','cards','split','cta'])];styleBlueprint();
 $('#styleBlockType').innerHTML=Object.entries(STYLE_BLOCKS).map(([key,label])=>`<option value="${key}">${label}</option>`).join('');
 $('#styleJSON').value=JSON.stringify(item,null,2);
}
function styleReadForm(){
 const body=JSON.parse(JSON.stringify(STYLE_EDIT||{}));body.tokens=body.tokens||{};
 for(const [id,key] of Object.entries({styleName:'name',styleCategory:'category',styleSource:'source_url',styleSummary:'summary',styleGuidance:'guidance'}))body[key]=$('#'+id).value.trim();
 body.site_types=[...document.querySelectorAll('#styleTypeOptions input:checked')].map(e=>e.value);body.pages=styleReadPages();
 body.sector=$('#styleSector').value;body.industry=$('#styleIndustry').value;body.tags=$('#styleTags').value.split(/[,，]/).map(x=>x.trim()).filter(Boolean);body.enabled=$('#styleEnabled').checked;
 body.tokens.palette=Object.fromEntries(Object.keys(STYLE_LABELS).map(key=>[key,$('#styleColor-'+key).value]));
 body.tokens.type={heading:$('#styleHeading').value};body.tokens.shape={radius:$('#styleRadius').value+'px',button:$('#styleButtonRadius').value+'px'};
 body.tokens.layout={pad:$('#stylePad').value+'px'};body.tokens.photos={overlay:$('#styleOverlay').value};
 body.tokens.advanced=Object.fromEntries(Object.entries(STYLE_LIBRARY.advanced_schema||{}).map(([key,spec])=>[key,typeof spec[0]==='string'?$('#styleAdv-'+key).value:Number($('#styleAdv-'+key).value)]));
 return body;
}
function styleBlueprint(){
 $('#styleBlueprint').innerHTML=(STYLE_EDIT?.blueprint||[]).map((type,i)=>`<div class="share-row"><span>${i+1}. <span>${esc(STYLE_BLOCKS[type]||type)}</span></span><button type="button" class="ghost" data-style-block="up" data-index="${i}" ${i===0?'disabled':''}>上移</button><button type="button" class="ghost" data-style-block="down" data-index="${i}" ${i===STYLE_EDIT.blueprint.length-1?'disabled':''}>下移</button><button type="button" class="ghost" data-style-block="remove" data-index="${i}">移除</button></div>`).join('');
}
async function stylePreview(item){return styleOpenPreview(item);}

function styleExport(item){
 const data={...item};delete data.id;delete data.version;delete data.updated;delete data.origin;
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
 const a=document.createElement('a');a.href=url;a.download='style-template.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('#styleEditForm').addEventListener('input',()=>{STYLE_DIRTY=true;});
window.addEventListener('beforeunload',e=>{if(STYLE_DIRTY){e.preventDefault();e.returnValue='';}});
$('#styleNew').onclick=()=>styleEdit({name:'',category:'',industry:'tech',tags:[],blueprint:['hero','cards','split','cta'],enabled:true,tokens:{palette:{primary:'#315e57',primaryDark:'#203e39',accent:'#92512e',bg:'#fafaf7',surface:'#ffffff',ink:'#202b29',muted:'#53615d',deep:'#203e39'},shape:{radius:'16px',button:'8px'},type:{heading:'sans'},layout:{pad:'72px'},photos:{overlay:'0.46'}}});
$('#styleStatus').onchange=styleRender;
$('#stylePreviewWidth').onchange=()=>{$('#stylePreviewFrame').style.width=$('#stylePreviewWidth').value;};
$('#stylePreviewClose').onclick=()=>styleClosePreview();
$('#stylePreviewEdit').onclick=async()=>{try{await stylePreview(styleReadForm());}catch(e){aiMessage('#styleManageMsg',e.message,true);}};
$('#styleAddBlock').onclick=()=>{if(STYLE_EDIT.blueprint.length>=20){aiMessage('#styleManageMsg','最多添加 20 个区块',true);return;}STYLE_EDIT.blueprint.push($('#styleBlockType').value);STYLE_DIRTY=true;styleBlueprint();};
$('#styleBlueprint').onclick=e=>{const button=e.target.closest('[data-style-block]');if(!button)return;const i=Number(button.dataset.index),items=STYLE_EDIT.blueprint;const action=button.dataset.styleBlock;if(action==='remove')items.splice(i,1);else{const j=i+(action==='up'?-1:1);if(j>=0&&j<items.length)[items[i],items[j]]=[items[j],items[i]];}STYLE_DIRTY=true;styleBlueprint();};
$('#styleSyncJSON').onclick=()=>{$('#styleJSON').value=JSON.stringify(styleReadForm(),null,2);};
$('#styleApplyJSON').onclick=async()=>{try{const parsed=JSON.parse($('#styleJSON').value);const item={...parsed,id:STYLE_EDIT?.id,version:STYLE_EDIT?.version};const checked=await aiRequest('/api/ai/styles/preview',item);item.tokens=checked.tokens;Object.assign(item,checked.recipe);STYLE_DIRTY=false;styleEdit(item);STYLE_DIRTY=true;aiMessage('#styleManageMsg','JSON 已应用，保存后生效');}catch(e){aiMessage('#styleManageMsg',e.message,true);}};
$('#styleImport').onclick=()=>$('#styleImportFile').click();
$('#styleImportFile').onchange=async()=>{const file=$('#styleImportFile').files[0];if(!file)return;try{if(file.size>100000)throw Error('模板文件不能超过 100 KB');const item=JSON.parse(await file.text());delete item.id;delete item.version;delete item.origin;delete item.updated;const checked=await aiRequest('/api/ai/styles/preview',item);item.tokens=checked.tokens;Object.assign(item,checked.recipe);styleEdit(item);STYLE_DIRTY=true;}catch(e){aiMessage('#styleManageMsg',e.message,true);}finally{$('#styleImportFile').value='';}};
