/* Progressive build flow. Review uses the server's composed prompt snapshot. */
const BUILD_TEXT={
 steps:['建站步骤','Build steps'],one:['站点与需求','Site and requirements'],two:['风格与提示词','Style and prompts'],three:['确认生成','Review and generate'],
 next:['下一步','Continue'],review:['校验并查看摘要','Validate and review'],back:['上一步','Back'],checking:['正在校验…','Validating…'],refresh:['刷新提示词库','Refresh prompt library'],
 changed:['配置已变化，请重新校验后生成。','Settings changed. Review them again before generating.'],
 site:['站点','Site'],model:['模型','Model'],language:['页面语言','Page language'],style:['视觉风格','Visual style'],
 free:['自由输入，不使用提示词模板','Free input, without a prompt template'],template:['提示词模板','Prompt template'],modules:['实际组合模块（按顺序）','Composed modules (in order)'],
 brief:['建站要求','Requirements'],preview:['查看最终提示词','View the final prompt'],context:['发送给模型的参考资料','Reference data shared with the model'],
 none:['未选择','None selected'],research:['允许已授权的 MCP 只读查询','Authorized read-only MCP research enabled'],
 newSite:['将创建站点、数据库和套餐账单，生成结果先保存为草稿。','Creates a site, database and plan invoice. Generated content is saved as a draft.'],
 draft:['生成结果保存为草稿；预览并确认后再发布。','Generated content is saved as a draft. Preview and confirm it before publishing.'],
 mock:['模拟模式，不调用真实模型','Simulation; no real model call'],actual:['将发送业务资料至所选模型接口','Business data will be sent to the selected model endpoint']
};
let BUILD_STEP=1,BUILD_REVIEW=null,BUILD_SIGNATURE='',BUILD_BUSY=false,BUILD_SKIP_BRIEF=true;
function buildMessage(value='',bad=false){AdminUI.message('#aiBuildMsg',Object.values(BUILD_TEXT).find(pair=>pair.includes(value))||[value,value],bad);}
function buildText(key){return AdminUI.text(...BUILD_TEXT[key]);}
function buildSignature(){return JSON.stringify([...$('#aiBuildForm').querySelectorAll('input,select,textarea')].filter(e=>!e.readOnly&&e.id!=='aiReplace').map(e=>[e.id,e.value,e.type==='checkbox'?e.checked:null]).concat([['context',window.aiContextActions||[]],['prompt',promptSelection()],['style',STYLE_LIBRARY?.templates.find(t=>t.id===$('#aiStyleTemplate').value)||STYLE_ANALYSIS]]));}
function buildRender(){
 $('#aiBuildSteps').setAttribute('aria-label',buildText('steps'));
 $('#aiBuildRefreshPrompts').textContent=buildText('refresh');
 $('#aiBuildSteps').innerHTML=['one','two','three'].map((key,i)=>`<button type="button" class="ghost" data-build-step="${i+1}" ${i+1===BUILD_STEP?'aria-current="step"':''} ${i+1>BUILD_STEP||BUILD_BUSY?'disabled':''}>${i+1}. ${esc(buildText(key))}</button>`).join('');
 ['one','two','three'].forEach((key,i)=>{$('#aiBuildStep'+(i+1)).hidden=BUILD_STEP!==i+1;$('#aiStepTitle'+(i+1)).textContent=buildText(key);});
 $('#aiBuildBack').hidden=BUILD_STEP===1;$('#aiBuildBack').disabled=BUILD_BUSY;$('#aiBuildBack').textContent=buildText('back');
 $('#aiBuildNext').hidden=BUILD_STEP===3;$('#aiBuildNext').disabled=BUILD_BUSY||!AI_READY;$('#aiBuildNext').textContent=buildText(BUILD_BUSY?'checking':BUILD_STEP===1?'next':'review');
 if(BUILD_REVIEW)buildRenderReview();
}
function buildShow(step,focus=true){BUILD_STEP=step;buildRender();if($('#aiBuildForm .form-error-summary'))renderValidation($('#aiBuildForm'));if(focus)$('#aiStepTitle'+step).focus();}
function buildValidate(step,skipBrief=false){
 const invalid=[...$('#aiBuildStep'+step).querySelectorAll('input,select,textarea')].find(e=>!(skipBrief&&e.id==='aiBrief')&&e.willValidate&&!e.validity.valid);
 if(!invalid)return true;
 BUILD_SKIP_BRIEF=skipBrief;buildShow(step);for(let p=invalid.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
 renderValidation($('#aiBuildForm'));invalid.focus();return false;
}
function buildRenderReview(){
 const row=(label,value)=>`<div><dt>${esc(buildText(label))}</dt><dd data-user-content>${esc(value)}</dd></div>`;
 const option=id=>$(id).selectedOptions[0]?.textContent||'';
 const prompt=BUILD_REVIEW.prompt;
 const context=[...document.querySelectorAll('#aiContextOptions input[value]:checked')].map(e=>e.parentElement.textContent.trim());
 if(window.aiContextActions?.length)context.push(`MCP: ${window.aiContextActions.length}`);
 const profile=AI_CONFIG?.profiles.find(p=>p.id===$('#aiProfile').value);
 $('#aiBuildReview').innerHTML=`<dl class="ai-build-review">${row('site',$('#aiMode').value==='new'?$('#aiCompany').value+' / '+$('#aiDomain').value:option('#aiSite'))}${row('model',option('#aiProfile'))}${row('language',option('#aiLanguage'))}${row('style',option('#aiStyleTemplate'))}${row('template',prompt?prompt.template.name+' · v'+prompt.template.version:buildText('free'))}</dl>
 ${prompt?`<h4>${esc(buildText('modules'))}</h4><ol>${prompt.modules.map(m=>`<li data-user-content>${esc(m.name)} · v${Number(m.version)}</li>`).join('')}</ol><details><summary>${esc(buildText('preview'))}</summary><pre class="ai-build-prompt" data-user-content>${esc(prompt.preview)}</pre></details>`:`<h4>${esc(buildText('brief'))}</h4><p data-user-content>${esc($('#aiBrief').value)}</p>`}
 <p>${esc(buildText('context'))}: <span data-user-content>${esc($('#aiMode').value==='existing'&&context.length?context.join(' · '):buildText('none'))}</span></p>
 ${$('#aiMode').value==='existing'&&$('#aiAutoResearch').checked?`<p>${esc(buildText('research'))}</p>`:''}
 <p class="callout">${esc(buildText(profile?.protocol==='mock'?'mock':'actual'))}</p><p class="hint">${esc(buildText($('#aiMode').value==='new'?'newSite':'draft'))}</p>`;
}
async function buildContinue(){
 if(BUILD_BUSY||!AI_READY)return;
 if(BUILD_STEP===1){if(buildValidate(1,true))buildShow(2);return;}
 if(!buildValidate(1)||!buildValidate(2))return;
 BUILD_BUSY=true;buildRender();buildMessage('');const signature=buildSignature();
 try{
  styleSelection();
  const prompt=promptSelection()?await previewPrompt():null;
  if(signature!==buildSignature())throw Error(buildText('changed'));
  BUILD_REVIEW={prompt};BUILD_SIGNATURE=signature;buildShow(3);
 }catch(e){buildMessage(e.message,true);}
 finally{BUILD_BUSY=false;buildRender();}
}
function buildCanSubmit(){
 if(BUILD_STEP!==3){buildContinue();return false;}
 if(!BUILD_REVIEW||BUILD_SIGNATURE!==buildSignature()){BUILD_REVIEW=null;buildShow(2);buildMessage(buildText('changed'),true);return false;}
 return buildValidate(1)&&buildValidate(2);
}
function buildReconcile(){
 if(BUILD_REVIEW&&BUILD_SIGNATURE!==buildSignature()){BUILD_REVIEW=null;if(BUILD_STEP===3)buildShow(2,false);}
}
$('#aiBuildForm').addEventListener('input',buildReconcile);
$('#aiBuildForm').addEventListener('change',buildReconcile);
$('#aiBuildForm').validationControls=()=>[...$('#aiBuildStep'+BUILD_STEP).querySelectorAll('input,select,textarea')].filter(e=>!(BUILD_SKIP_BRIEF&&e.id==='aiBrief'));
$('#aiBuildNext').onclick=buildContinue;
$('#aiBuildRefreshPrompts').onclick=async()=>{
 const button=$('#aiBuildRefreshPrompts');button.disabled=true;
 try{await loadPromptLibrary();buildReconcile();buildMessage('');}catch(e){buildMessage(e.message,true);}finally{button.disabled=false;}
};
$('#aiBuildBack').onclick=()=>buildShow(BUILD_STEP-1);
$('#aiBuildSteps').onclick=e=>{const b=e.target.closest('[data-build-step]');if(b&&!b.disabled)buildShow(Number(b.dataset.buildStep));};
new MutationObserver(buildRender).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
buildRender();

/* Shared, explicit opt-in writing assistance. Only allowlisted visible business fields leave the browser. */
document.addEventListener('DOMContentLoaded',()=>{
 const t=(zh,en)=>AdminUI.text(zh,en),value=id=>document.getElementById(id)?.value||'',label=id=>{const e=document.getElementById(id);return e?.selectedOptions?.[0]?.textContent||e?.value||'';};
 const dialog=document.createElement('dialog');dialog.id='aiAssistDialog';dialog.className='domain-dialog';dialog.setAttribute('aria-labelledby','aiAssistTitle');
 dialog.innerHTML='<h3 id="aiAssistTitle"></h3><label for="aiAssistProfile" id="aiAssistProfileLabel"></label><select id="aiAssistProfile"></select><p id="aiAssistNotice" class="hint"></p><button type="button" id="aiAssistGenerate"></button><label for="aiAssistResult" id="aiAssistResultLabel"></label><textarea id="aiAssistResult" rows="10" style="width:100%;box-sizing:border-box" data-user-content></textarea><div class="domain-form-actions"><button type="button" id="aiAssistReplace"></button><button type="button" id="aiAssistAppend"></button><button type="button" class="ghost" id="aiAssistClose"></button></div><p id="aiAssistMsg" role="status" class="msg"></p>';document.body.append(dialog);
 let target=null,snapshot='',contextStamp='',busy=false,epoch=0;
 const ids=['aiBrief','promptServices','promptFacts','styleSummary','styleGuidance','promptEditBody','promptEditDescription','workflowBrief','auto-brief','auto-body'];
 function context(el){
  const scope=el.id.startsWith('promptEdit')?'prompts':el.id.startsWith('auto-')||el.id==='workflowBrief'?'automation':'build';
  const data={field:el.id,language:scope==='build'?label('aiLanguage'):document.documentElement.lang};
  const map=scope==='prompts'?{name:'promptEditName',category:'promptEditCategory',description:'promptEditDescription'}:scope==='automation'?{site:'autoSite',purpose:'autoPurpose',operation:'autoTool'}:{company:'aiCompany',site:'aiSite',industry:'aiIndustry',requirements:'aiBrief',facts:'promptFacts',category:'aiPromptCategory',style:'aiStyleTemplate',template:'aiPromptTemplate',audience:'promptAudience',services:'promptServices',goal:'promptGoal',tone:'promptTone'};
  for(const [k,id] of Object.entries(map))data[k]=label(id);
  if(scope==='prompts')data.modules=JSON.stringify(PROMPT_EDIT_MODULES.map(id=>PROMPTS?.modules.find(m=>m.id===id)?.name||id));
  if(scope==='build'){if(value('aiMode')==='existing'){data.company=label('aiSite');delete data.industry;}else data.site=value('aiDomain');data.modules=JSON.stringify(PROMPT_MODULES.map(id=>PROMPTS?.modules.find(m=>m.id===id)?.name||id));}
  return {scope,context:data};
 }
 function translate(){
  const labels={aiAssistTitle:['AI 补写','AI writing'],aiAssistProfileLabel:['模型','Model'],aiAssistNotice:['将当前业务选项与已有文本发送至所选模型。审核结果后再插入或替换。','Sends current business options and text to the selected model. Review before inserting or replacing.'],aiAssistGenerate:busy?['正在生成…','Generating…']:['生成建议','Generate suggestion'],aiAssistResultLabel:['建议内容（可编辑）','Suggested text (editable)'],aiAssistReplace:['替换原文','Replace text'],aiAssistAppend:['追加到末尾','Append text'],aiAssistClose:['取消','Cancel']};
  for(const [id,pair] of Object.entries(labels))document.getElementById(id).textContent=t(...pair);
  document.querySelectorAll('[data-ai-assist]').forEach(b=>b.textContent=t('AI 补写','AI writing'));
 }
 function attach(){for(const id of ids){const el=document.getElementById(id);if(!el||el.dataset.assistAttached)continue;el.dataset.assistAttached='1';const b=document.createElement('button');b.type='button';b.className='ghost';b.dataset.aiAssist=id;b.textContent=t('AI 补写','AI writing');el.after(b);b.onclick=async()=>{
   target=el;snapshot=el.value;contextStamp=JSON.stringify(context(el));epoch++;busy=false;$('#aiAssistResult').value='';$('#aiAssistMsg').textContent='';$('#aiAssistReplace').disabled=$('#aiAssistAppend').disabled=true;$('#aiAssistGenerate').disabled=true;$('#aiAssistProfile').innerHTML='';translate();dialog.showModal();const token=epoch;
   try{const config=await aiRequest('/api/ai/config');if(token!==epoch)return;const profiles=config.profiles.filter(p=>p.protocol!=='mock');$('#aiAssistProfile').innerHTML=profiles.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');const preferred=value(el.id==='workflowBrief'?'workflowProfile':el.id.startsWith('auto-')?'auto-profile_id':'aiProfile')||config.default_profile;if(profiles.some(p=>p.id===preferred))$('#aiAssistProfile').value=preferred;$('#aiAssistGenerate').disabled=!profiles.length;if(!profiles.length)$('#aiAssistMsg').textContent=t('请先在系统设置配置真实模型。','Configure a real model in system settings first.');}catch(e){if(token===epoch)$('#aiAssistMsg').textContent=e.message;}
  };}}
 $('#aiAssistGenerate').onclick=async()=>{if(busy||!target)return;busy=true;const token=++epoch;$('#aiAssistGenerate').disabled=true;$('#aiAssistReplace').disabled=$('#aiAssistAppend').disabled=true;$('#aiAssistMsg').textContent='';translate();try{const payload=JSON.parse(contextStamp);const result=await aiRequest('/api/ai/assist',{...payload,profile_id:value('aiAssistProfile'),text:snapshot,limit:target.maxLength>0?Math.min(target.maxLength,12000):6000});if(token!==epoch)return;$('#aiAssistResult').value=result.text;$('#aiAssistReplace').disabled=$('#aiAssistAppend').disabled=false;}catch(e){if(token===epoch)$('#aiAssistMsg').textContent=e.message;}finally{if(token===epoch){busy=false;$('#aiAssistGenerate').disabled=false;translate();}}};
 function apply(append){if(!target?.isConnected||target.value!==snapshot||JSON.stringify(context(target))!==contextStamp){$('#aiAssistMsg').textContent=t('原文或选项已变化，请关闭后重新补写。','Text or options changed. Close and start again.');return;}const text=(append&&snapshot?snapshot+'\n\n':'')+value('aiAssistResult');if(!text.trim()||(target.maxLength>0&&text.length>target.maxLength)){$('#aiAssistMsg').textContent=t('内容为空或超过字段长度上限。','Text is empty or exceeds the field limit.');return;}target.value=text;target.dispatchEvent(new Event('input',{bubbles:true}));target.dispatchEvent(new Event('change',{bubbles:true}));dialog.close();target.focus();}
 $('#aiAssistReplace').onclick=()=>apply(false);$('#aiAssistAppend').onclick=()=>apply(true);$('#aiAssistClose').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{epoch++;busy=false;$('#aiAssistResult').value='';});
 new MutationObserver(attach).observe($('#autoFields'),{childList:true,subtree:true});new MutationObserver(translate).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});attach();translate();

 // Same step navigation and focus pattern as AI Build; execution still uses its original confirmation form.
 const root=$('#p-automation'),selection=$('#autoSite').closest('.formrow'),form=$('#autoForm'),review=$('#autoReview');let step=1;
 const nav=document.createElement('nav');nav.className='ai-build-steps';nav.id='autoSteps';selection.before(nav);
 const title=document.createElement('h3');title.tabIndex=-1;nav.after(title);
 const actions=document.createElement('div');actions.className='domain-form-actions';actions.innerHTML='<button type="button" class="ghost" id="autoStepBack"></button><button type="button" id="autoStepNext"></button>';review.after(actions);
 function render(focus=false){const names=[t('站点与任务','Site and task'),t('填写参数','Parameters'),t('确认执行','Review and execute')];nav.setAttribute('aria-label',t('运营步骤','Operation steps'));nav.innerHTML=names.map((name,i)=>`<button type="button" class="ghost" data-auto-step="${i+1}" ${step===i+1?'aria-current="step"':''} ${i+1>step?'disabled':''}>${i+1}. ${esc(name)}</button>`).join('');title.textContent=names[step-1];selection.hidden=step!==1;form.hidden=step!==2;review.hidden=step!==3;$('#autoStepBack').hidden=step===1;$('#autoStepNext').hidden=step!==1;$('#autoStepNext').disabled=$('#autoTool').disabled||!value('autoTool');$('#autoStepBack').textContent=t('上一步','Back');$('#autoStepNext').textContent=t('下一步','Continue');if(focus)title.focus();}
 function show(n){step=n;render(true);}
 $('#autoStepNext').onclick=()=>{if(value('autoSite')&&value('autoTool'))show(2);};$('#autoStepBack').onclick=()=>show(Math.max(1,step-1));nav.onclick=e=>{const b=e.target.closest('[data-auto-step]');if(b&&!b.disabled)show(Number(b.dataset.autoStep));};
 new MutationObserver(()=>render()).observe($('#autoTool'),{attributes:true,attributeFilter:['disabled'],childList:true});
 window.autoWizardReview=()=>show(3);window.autoWizardReset=()=>show(1);window.autoWizardParameters=()=>show(2);
 // Changing parameters always requires a fresh server preview; the old action cannot be executed here.
 form.addEventListener('input',()=>{review.classList.add('hidden');});form.addEventListener('change',()=>{review.classList.add('hidden');});
 new MutationObserver(()=>render()).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});render();
});
