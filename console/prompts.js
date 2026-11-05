/* Shared template/module library. Composition is validated on the server before generation. */
let PROMPTS=null, PROMPT_MODULES=[], PROMPT_EDIT_MODULES=[], PROMPT_EDIT_KIND='templates';
const promptVariableIds={audience:'promptAudience',services:'promptServices',goal:'promptGoal',tone:'promptTone',facts:'promptFacts'};
function promptSelection(){
 if(!$('#aiPromptTemplate').value)return null;
 return {revision:PROMPTS.revision,template_id:$('#aiPromptTemplate').value,module_ids:[...PROMPT_MODULES],variables:Object.fromEntries(Object.entries(promptVariableIds).map(([k,id])=>[k,$('#'+id).value.trim()]))};
}
function promptInvalidate(){ $('#aiPromptPreview').value='';$('#aiPromptMsg').textContent='资料或模块已变化，可重新预览；生成时会校验最新组合。'; }
function promptModuleList(target,selected,admin=false){
 const choices=PROMPTS.modules.filter(m=>m.enabled||selected.includes(m.id));
 const ordered=[...selected.map(id=>choices.find(m=>m.id===id)).filter(Boolean),...choices.filter(m=>!selected.includes(m.id))];
 $(target).innerHTML=ordered.map(m=>{const i=selected.indexOf(m.id);return `<div class="share-row"><label style="flex:1;margin:0"><input type="checkbox" data-prompt-module="${esc(m.id)}" ${i>=0?'checked':''}> ${esc(m.name)} <span class="hint">${esc(PROMPTS.categories[m.category]||m.category)} · v${m.version}${m.enabled?'':' · 已停用'}</span></label>${i>=0?`<button type="button" class="ghost" data-move="${esc(m.id)}" data-dir="-1" aria-label="上移 ${esc(m.name)}" ${i===0?'disabled':''}>↑</button><button type="button" class="ghost" data-move="${esc(m.id)}" data-dir="1" aria-label="下移 ${esc(m.name)}" ${i===selected.length-1?'disabled':''}>↓</button>`:''}</div>`;}).join('');
}
function promptRenderOptions(){
 const category=$('#aiPromptCategory').value,old=$('#aiPromptTemplate').value;
 const options=PROMPTS.templates.filter(t=>t.enabled&&(!category||t.category===category));
 $('#aiPromptTemplate').innerHTML='<option value="">自由输入（不使用模板）</option>'+options.map(t=>`<option value="${esc(t.id)}">${esc(t.name)} · v${t.version}</option>`).join('');
 if(options.some(t=>t.id===old))$('#aiPromptTemplate').value=old;
 if(old&&!$('#aiPromptTemplate').value)promptChoose();
 else if(old){promptModuleList('#aiPromptModules',PROMPT_MODULES);promptInvalidate();}
}
async function loadPromptLibrary(){
 PROMPTS=await aiRequest('/api/ai/prompts');
 const selected=$('#aiPromptCategory').value;
 $('#aiPromptCategory').innerHTML='<option value="">全部场景</option>'+[...new Set(PROMPTS.templates.filter(t=>t.enabled).map(t=>t.category))].map(c=>`<option>${esc(c)}</option>`).join('');
 $('#aiPromptCategory').value=selected;promptRenderOptions();
}
async function initPromptComposer(){
 if(!PROMPTS)await loadPromptLibrary();
}
function promptChoose(){
 const t=PROMPTS.templates.find(t=>t.id===$('#aiPromptTemplate').value);
 $('#aiPromptFields').classList.toggle('hidden',!t);$('#aiBrief').required=!t;
 for(const id of ['promptAudience','promptServices','promptGoal'])$('#'+id).required=!!t;
 $('#aiPromptDescription').textContent=t?t.description+' · 模板 v'+t.version:'直接填写完整建站要求，或选择一个场景模板。';
 if(t){
  PROMPT_MODULES=[...t.module_ids];
  // Preserve business facts; only replace scenario defaults when empty or still equal to prior default.
  for(const [key,id] of Object.entries(promptVariableIds)){
   const input=$('#'+id),value=t.defaults[key]||'';
   if(!input.value || input.value===input.dataset.defaultValue)input.value=value;
   input.dataset.defaultValue=value;
  }
  promptModuleList('#aiPromptModules',PROMPT_MODULES);
 }
 promptInvalidate();
}
$('#aiPromptCategory').onchange=()=>{promptRenderOptions();promptChoose();};
$('#aiPromptTemplate').onchange=promptChoose;
for(const id of [...Object.values(promptVariableIds),'aiBrief'])$('#'+id).addEventListener('input',promptInvalidate);
for(const [target,isEdit] of [['#aiPromptModules',false],['#promptEditModules',true]]){
 $(target).addEventListener('change',e=>{
  const id=e.target.dataset.promptModule;if(!id)return;
  const list=isEdit?PROMPT_EDIT_MODULES:PROMPT_MODULES;
  if(e.target.checked){if(!list.includes(id))list.push(id);}else list.splice(list.indexOf(id),1);
  promptModuleList(target,list,isEdit);$(target).querySelector(`[data-prompt-module="${id}"]`)?.focus();if(!isEdit)promptInvalidate();
 });
 $(target).addEventListener('click',e=>{
  const b=e.target.closest('[data-move]');if(!b)return;
  const list=isEdit?PROMPT_EDIT_MODULES:PROMPT_MODULES,i=list.indexOf(b.dataset.move),j=i+Number(b.dataset.dir);
  if(i<0||j<0||j>=list.length)return;
  [list[i],list[j]]=[list[j],list[i]];promptModuleList(target,list,isEdit);if(!isEdit)promptInvalidate();
  $(target).querySelector(`[data-move="${b.dataset.move}"][data-dir="${b.dataset.dir}"]`)?.focus();
 });
}
async function previewPrompt(){
 const selection=promptSelection();if(!selection)return null;
 const result=await aiRequest('/api/ai/prompts/preview',{selection,brief:$('#aiBrief').value.trim()});
 $('#aiPromptPreview').value=result.preview;$('#aiPromptPreviewBox').open=true;
 aiMessage('#aiPromptMsg','已校验组合 · '+result.modules.length+' 个模块 · '+result.preview.length+' 字');
 return result;
}
$('#aiPromptPreviewBtn').onclick=async()=>{
 const b=$('#aiPromptPreviewBtn');b.disabled=true;
 try{await previewPrompt();}catch(e){aiMessage('#aiPromptMsg',e.message,true);}finally{b.disabled=false;}
};
function renderPromptLibrary(){
 const kind=$('#promptLibraryKind').value,q=$('#promptLibrarySearch').value.toLowerCase(),admin=PROMPTS.can_manage;
 const items=PROMPTS[kind].filter(t=>(t.name+' '+t.category+' '+t.description).toLowerCase().includes(q));
 $('#promptLibraryNew').hidden=!admin;
 $('#promptLibraryList').innerHTML=items.map(t=>`<div class="dom-row"><div class="h"><b>${esc(t.name)}</b><span class="pill">${esc(PROMPTS.categories[t.category]||t.category)}</span><span class="hint">v${t.version} · ${t.enabled?'启用':'停用'}</span></div><p class="hint">${esc(t.description)}</p>${kind==='templates'?`<p class="hint">${t.module_ids.length} 个模块</p><button type="button" class="ghost" data-use-prompt="${esc(t.id)}" ${t.enabled?'':'disabled'}>用于建站</button>`:''}${admin?` <button type="button" class="ghost" data-edit-prompt="${esc(t.id)}">编辑与历史</button> <button type="button" class="ghost" data-copy-prompt="${esc(t.id)}">复制为新条目</button> <button type="button" class="ghost" data-toggle-prompt="${esc(t.id)}">${t.enabled?'停用':'启用'}</button>`:''}<details><summary>查看提示词内容</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(t.body)}</pre></details></div>`).join('')||'<p class="hint">没有符合条件的条目。</p>';
 $('#promptSources').innerHTML=PROMPTS.sources.map(s=>`<p><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a></p>`).join('');
}
async function initPrompts(){await loadPromptLibrary();renderPromptLibrary();}
$('#promptLibraryKind').onchange=renderPromptLibrary;$('#promptLibrarySearch').oninput=renderPromptLibrary;
$('#promptLibraryRefresh').onclick=async()=>{try{await initPrompts();aiMessage('#promptLibraryMsg','提示词库已刷新');}catch(e){aiMessage('#promptLibraryMsg',e.message,true);}};
function editPrompt(item=null,copy=false){
 PROMPT_EDIT_KIND=$('#promptLibraryKind').value;
 $('#promptEditForm').reset();$('#promptEditForm').classList.remove('hidden');$('#promptEditMsg').textContent='';
 $('#promptEditForm').dataset.revision=PROMPTS.revision;
 $('#promptEditId').value=copy?'':item?.id||'';$('#promptEditId').readOnly=!!item&&!copy;
 $('#promptEditName').value=(item?.name||'')+(copy?'（副本）':'');
 $('#promptEditCategory').value=item?.category||(PROMPT_EDIT_KIND==='modules'?'copy':'自定义场景');
 $('#promptEditDescription').value=item?.description||'';$('#promptEditBody').value=item?.body||'';
 $('#promptEditEnabled').checked=item?.enabled??true;
 $('#promptCategories').innerHTML=PROMPT_EDIT_KIND==='modules'?Object.entries(PROMPTS.categories).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join(''):'';
 $('#promptEditTemplateFields').hidden=PROMPT_EDIT_KIND!=='templates';
 PROMPT_EDIT_MODULES=[...(item?.module_ids||[])];promptModuleList('#promptEditModules',PROMPT_EDIT_MODULES,true);
 $('#promptEditDefaults').value=JSON.stringify(item?.defaults||{},null,2);
 $('#promptEditTitle').textContent=(item&&!copy?'编辑':'新建')+(PROMPT_EDIT_KIND==='templates'?'场景模板':'可复用模块');
 $('#promptEditHistory').innerHTML=copy?'':(item?.history||[]).slice().reverse().map(h=>`<div class="share-row"><span>v${h.version} · ${esc(h.name)}</span><button type="button" class="ghost" data-restore-prompt="${h.version}">恢复为新版本</button></div>`).join('');
 $('#promptEditForm').scrollIntoView({block:'start'});$('#promptEditName').focus();
}
$('#promptLibraryNew').onclick=()=>editPrompt();$('#promptEditCancel').onclick=()=>$('#promptEditForm').classList.add('hidden');
$('#promptLibraryList').onclick=async e=>{
 const b=e.target.closest('button');if(!b)return;
 const id=b.dataset.editPrompt||b.dataset.copyPrompt||b.dataset.togglePrompt||b.dataset.usePrompt;
 const item=PROMPTS[$('#promptLibraryKind').value].find(t=>t.id===id);if(!item)return;
 if(b.dataset.usePrompt){navigateTo('ai');$('#aiPromptCategory').value='';promptRenderOptions();$('#aiPromptTemplate').value=id;promptChoose();return;}
 if(b.dataset.editPrompt||b.dataset.copyPrompt){editPrompt(item,!!b.dataset.copyPrompt);return;}
 if(!confirm((item.enabled?'停用':'启用')+'「'+item.name+'」？已创建任务保留原版本。'))return;
 b.disabled=true;
 try{PROMPTS=await aiRequest('/api/ai/prompts',{kind:$('#promptLibraryKind').value,id,action:'toggle',revision:PROMPTS.revision});renderPromptLibrary();promptRenderOptions();}
 catch(err){aiMessage('#promptLibraryMsg',err.message,true);}finally{b.disabled=false;}
};
$('#promptEditForm').onsubmit=async e=>{
 e.preventDefault();const button=e.submitter;button.disabled=true;
 try{
  const body={action:'save',kind:PROMPT_EDIT_KIND,revision:Number($('#promptEditForm').dataset.revision),id:$('#promptEditId').value,name:$('#promptEditName').value,category:$('#promptEditCategory').value,description:$('#promptEditDescription').value,body:$('#promptEditBody').value,enabled:$('#promptEditEnabled').checked};
  if(PROMPT_EDIT_KIND==='templates'){body.module_ids=PROMPT_EDIT_MODULES;body.defaults=JSON.parse($('#promptEditDefaults').value||'{}');}
  PROMPTS=await aiRequest('/api/ai/prompts',body);renderPromptLibrary();promptRenderOptions();$('#promptEditForm').classList.add('hidden');aiMessage('#promptLibraryMsg','新版本已保存；已创建任务的提示词不受影响。');
 }catch(err){aiMessage('#promptEditMsg',err.message,true);}finally{button.disabled=false;}
};
$('#promptEditHistory').onclick=async e=>{
 const b=e.target.closest('[data-restore-prompt]');if(!b||!confirm('以此历史内容创建新版本？'))return;b.disabled=true;
 try{PROMPTS=await aiRequest('/api/ai/prompts',{action:'restore',kind:PROMPT_EDIT_KIND,id:$('#promptEditId').value,version:Number(b.dataset.restorePrompt),revision:Number($('#promptEditForm').dataset.revision)});renderPromptLibrary();promptRenderOptions();$('#promptEditForm').classList.add('hidden');aiMessage('#promptLibraryMsg','历史内容已恢复为新版本。');}
 catch(err){aiMessage('#promptEditMsg',err.message,true);}finally{b.disabled=false;}
};
$('#promptLibraryExport').onclick=()=>{
 if(!PROMPTS)return;
 const blob=new Blob([JSON.stringify({schema_version:1,revision:PROMPTS.revision,templates:PROMPTS.templates,modules:PROMPTS.modules},null,2)],{type:'application/json'});
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='prompt-library-v'+PROMPTS.revision+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
