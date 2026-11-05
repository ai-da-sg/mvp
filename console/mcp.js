/* Admin-only MCP connection management; no remote tool execution. */
let MCP_ITEMS=[],MCP_EDIT=null,MCP_EPOCH=0,MCP_LAST_TEST=null;
async function loadMCP(){MCP_EPOCH++;$('#mcpResult').classList.add('hidden');const data=await aiRequest('/api/mcp/servers');MCP_ITEMS=data.items||[];renderMCP();}
function renderMCP(){
 const q=$('#mcpSearch').value.trim().toLowerCase();
 $('#mcpList').innerHTML=MCP_ITEMS.filter(x=>[x.name,x.url,x.description].join(' ').toLowerCase().includes(q)).map(x=>`<article class="dom-row"><div class="h"><strong data-user-content>${esc(x.name)}</strong><span class="pill">${x.enabled?'已启用':'已停用'}</span><span class="hint">${x.has_token?'已保存凭据':'无认证'}</span></div><p data-user-content style="overflow-wrap:anywhere">${esc(x.url)}</p><p data-user-content style="overflow-wrap:anywhere">${esc(x.description)}</p><div class="h"><button type="button" data-mcp-edit="${esc(x.id)}">编辑</button><button type="button" data-mcp-toggle="${esc(x.id)}">${x.enabled?'停用':'启用'}</button><button type="button" data-mcp-test="${esc(x.id)}" ${x.enabled?'':'disabled'}>测试连接与能力</button><button type="button" class="ghost" data-mcp-delete="${esc(x.id)}">删除</button></div></article>`).join('')||'<p class="hint">没有匹配的 MCP 服务。</p>';
}
function editMCP(item){
 MCP_EDIT=item?{...item}:null;$('#mcpForm').reset();
 for(const [id,key] of Object.entries({mcpId:'id',mcpName:'name',mcpUrl:'url',mcpDescription:'description'}))$('#'+id).value=item?.[key]||'';
 const policy=item?.policy||{};
 $('#mcpSites').innerHTML=(STATE.sites||[]).map(s=>`<option value="${esc(s.slug)}" ${(policy.sites||[]).includes(s.slug)?'selected':''}>${esc(s.company)} / ${esc(s.domain)}</option>`).join('');
 document.querySelectorAll('#mcpPurposes input').forEach(e=>e.checked=(policy.purposes||[]).includes(e.value));
 $('#mcpToolRules').value=JSON.stringify(policy.tools||[],null,2);$('#mcpResources').value=(policy.resources||[]).join('\n');$('#mcpPrompts').value=(policy.prompts||[]).join('\n');$('#mcpLimit').value=policy.calls_per_hour||30;$('#mcpTimeout').value=policy.timeout||30;
 $('#mcpId').readOnly=!!item;$('#mcpEnabled').checked=item?item.enabled:true;$('#mcpToken').value='';aiMessage('#mcpFormMsg','');$('#mcpForm').classList.remove('hidden');$('#mcpName').focus();
}
$('#mcpSearch').oninput=renderMCP;
$('#mcpNew').onclick=()=>editMCP(null);
$('#mcpCancel').onclick=()=>{$('#mcpForm').classList.add('hidden');$('#mcpToken').value='';MCP_EDIT=null;};
$('#mcpRefresh').onclick=()=>loadMCP().catch(e=>aiMessage('#mcpMsg',e.message,true));
$('#mcpForm').onsubmit=async e=>{
 e.preventDefault();e.submitter.disabled=true;
 const body={action:'save',id:$('#mcpId').value,name:$('#mcpName').value,url:$('#mcpUrl').value,description:$('#mcpDescription').value,enabled:$('#mcpEnabled').checked,token:$('#mcpToken').value,clear_token:$('#mcpClear').checked};
 if(MCP_EDIT)body.version=MCP_EDIT.version;
 try{body.policy={purposes:[...document.querySelectorAll('#mcpPurposes input:checked')].map(e=>e.value),sites:[...$('#mcpSites').selectedOptions].map(e=>e.value),tools:JSON.parse($('#mcpToolRules').value||'[]'),resources:$('#mcpResources').value.split('\n').map(s=>s.trim()).filter(Boolean),prompts:$('#mcpPrompts').value.split('\n').map(s=>s.trim()).filter(Boolean),calls_per_hour:Number($('#mcpLimit').value),timeout:Number($('#mcpTimeout').value)};await aiRequest('/api/mcp/servers',body);$('#mcpCancel').click();await loadMCP();aiMessage('#mcpMsg','MCP 配置已保存');}
 catch(err){aiMessage('#mcpFormMsg',err.message,true);}finally{body.token='';e.submitter.disabled=false;}
};
$('#mcpList').onclick=async e=>{
 const b=e.target.closest('button');if(!b)return;
 const id=b.dataset.mcpEdit||b.dataset.mcpToggle||b.dataset.mcpTest||b.dataset.mcpDelete;const item=MCP_ITEMS.find(x=>x.id===id);if(!item)return;
 if(b.dataset.mcpEdit){editMCP(item);return;}
 if(b.dataset.mcpDelete&&!confirm('删除此 MCP 服务配置及凭据？'))return;
 b.disabled=true;
 try{
  if(b.dataset.mcpTest){
   const epoch=++MCP_EPOCH;$('#mcpResult').classList.add('hidden');aiMessage('#mcpMsg','正在连接 MCP 并查询能力，最多约 45 秒…');
   const {result:r}=await aiRequest('/api/mcp/test',{id,version:item.version});if(epoch!==MCP_EPOCH)return;
   MCP_LAST_TEST=item.id;$('#mcpResult').innerHTML=`<h3 data-user-content>${esc(item.name)} · ${esc(r.server)} ${esc(r.version)}</h3><p>协议：${esc(r.protocol)}</p>${[['tools','工具'],['resources','资源'],['prompts','提示词']].map(([k,label])=>`<details open><summary>${label}（${r[k].length}）</summary>${r[k].map(v=>`<p data-user-content style="overflow-wrap:anywhere"><b>${esc(v.name)}</b> <button type="button" class="ghost" data-policy-kind="${k}" data-policy-name="${esc(k==='resources'?v.uri:v.name)}">加入白名单</button><br>${esc(v.description)}${v.uri?'<br>URI: '+esc(v.uri):''}</p>${v.inputSchema?'<details><summary>参数定义</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+esc(JSON.stringify(v.inputSchema,null,2))+'</pre></details>':''}`).join('')||'<p class="hint">未提供条目</p>'}</details>`).join('')}${r.truncated?'<p class="hint">结果已截断，每类最多显示 100 条、读取 5 页。</p>':''}`;
   $('#mcpResult').classList.remove('hidden');aiMessage('#mcpMsg','MCP 连接成功，能力列表已更新');
  }else{
   await aiRequest('/api/mcp/servers',b.dataset.mcpDelete?{action:'delete',id,version:item.version}:{...item,action:'save',enabled:!item.enabled});
   if(MCP_EDIT?.id===id)$('#mcpCancel').click();await loadMCP();aiMessage('#mcpMsg','MCP 配置已更新');
  }
 }catch(err){aiMessage('#mcpMsg',err.message,true);}finally{b.disabled=false;}
};
new MutationObserver(()=>{if($('#p-mcp').classList.contains('hidden')){MCP_EPOCH++;$('#mcpToken').value='';}}).observe($('#p-mcp'),{attributes:true,attributeFilter:['class']});
new MutationObserver(()=>{if($('#p-llm').classList.contains('hidden'))$('#aiKey').value='';}).observe($('#p-llm'),{attributes:true,attributeFilter:['class']});

$('#mcpResult').onclick=e=>{
 const b=e.target.closest('[data-policy-kind]');if(!b)return;
 const item=MCP_ITEMS.find(x=>x.id===MCP_LAST_TEST);if(!item)return;
 if(MCP_EDIT?.id!==item.id)editMCP(item);
 try{
  const kind=b.dataset.policyKind,name=b.dataset.policyName;
  if(kind==='tools'){
   const rules=JSON.parse($('#mcpToolRules').value||'[]');
   if(!rules.some(r=>r.name===name))rules.push({name,mode:'confirm',bindings:{}});
   $('#mcpToolRules').value=JSON.stringify(rules,null,2);
  }else{
   const el=$(kind==='resources'?'#mcpResources':'#mcpPrompts');el.value=[...new Set([...el.value.split('\n').filter(Boolean),name])].join('\n');
  }
  $('#mcpForm details').open=true;$('#mcpForm').scrollIntoView({block:'start'});aiMessage('#mcpFormMsg','已加入待保存白名单，请设置用途、站点范围和执行规则后保存。');
 }catch(err){aiMessage('#mcpFormMsg','请先修正工具规则 JSON：'+err.message,true);}
};
