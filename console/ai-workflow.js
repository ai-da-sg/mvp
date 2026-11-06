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
