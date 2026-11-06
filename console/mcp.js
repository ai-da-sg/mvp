/* Administrator-managed remote MCP connections and scoped policies. */
let MCP_ITEMS=[],MCP_EDIT=null,MCP_EPOCH=0,MCP_LAST_TEST=null,MCP_ACCOUNTS=[];
async function loadMCP(){return AdminUI.load('#mcpList','#mcpRefresh','#mcpMsg',async()=>{MCP_EPOCH++;$('#mcpResult').classList.add('hidden');const data=await aiRequest('/api/mcp/servers');MCP_ITEMS=data.items||[];const cfg=await aiRequest('/api/automation/config');MCP_ACCOUNTS=(cfg.provider_accounts||[]).filter(a=>a.capabilities.includes('mcp'));renderMCP();});}
function renderMCP(){
 const q=$('#mcpSearch').value.trim().toLowerCase();
 AdminUI.table('mcpList',MCP_ITEMS.filter(x=>[x.name,x.url,x.description].join(' ').toLowerCase().includes(q)),['服务名称','状态','认证方式','操作'],x=>`<tr><td><strong data-user-content>${esc(x.name)}</strong><p class="hint" data-user-content>${esc(x.url)}</p></td><td>${x.enabled?'已启用':'已停用'}</td><td>${x.account_id?'供应商账号认证':x.has_token?'已保存凭据':'无认证'}</td><td><div class="domain-row-actions"><button type="button" class="ghost" data-mcp-view="${esc(x.id)}">查看</button><button type="button" data-mcp-edit="${esc(x.id)}">编辑</button><button type="button" data-mcp-toggle="${esc(x.id)}">${x.enabled?'停用':'启用'}</button><button type="button" data-mcp-test="${esc(x.id)}" ${x.enabled?'':'disabled'}>测试连接与能力</button><button type="button" class="ghost" data-mcp-delete="${esc(x.id)}">删除</button></div></td></tr>`);

}
function editMCP(item){
 MCP_EDIT=item?{...item}:null;$('#mcpForm').reset();
 for(const [id,key] of Object.entries({mcpId:'id',mcpName:'name',mcpUrl:'url',mcpDescription:'description'}))$('#'+id).value=item?.[key]||'';
 $('#mcpAccount').innerHTML='<option value="">使用 Bearer Token / 无认证</option>'+MCP_ACCOUNTS.map(a=>`<option value="${esc(a.id)}">${esc(a.name+' / '+a.provider)}</option>`).join('');$('#mcpAccount').value=item?.account_id||'';
 const policy=item?.policy||{};
 $('#mcpSites').innerHTML=(STATE.sites||[]).map(s=>`<option value="${esc(s.slug)}" ${(policy.sites||[]).includes(s.slug)?'selected':''}>${esc(s.company)} / ${esc(s.domain)}</option>`).join('');
 document.querySelectorAll('#mcpPurposes input').forEach(e=>e.checked=(policy.purposes||[]).includes(e.value));
 $('#mcpToolRules').value=JSON.stringify(policy.tools||[],null,2);$('#mcpResources').value=(policy.resources||[]).join('\n');$('#mcpPrompts').value=(policy.prompts||[]).join('\n');$('#mcpLimit').value=policy.calls_per_hour||30;$('#mcpTimeout').value=policy.timeout||30;
 $('#mcpId').readOnly=!!item;$('#mcpEnabled').checked=item?item.enabled:true;$('#mcpToken').value='';aiMessage('#mcpFormMsg','');MCP_MODAL.open();$('#mcpName').focus();
}
$('#mcpSearch').oninput=()=>{AdminUI.pages.set('mcpList',0);renderMCP();};
$('#mcpNew').onclick=()=>editMCP(null);
const MCP_MODAL=AdminUI.form('mcpForm','MCP 服务配置',()=>{$('#mcpToken').value='';MCP_EDIT=null;});
$('#mcpCancel').onclick=()=>MCP_MODAL.close();
$('#mcpRefresh').onclick=()=>loadMCP().catch(e=>aiMessage('#mcpMsg',e.message,true));
$('#mcpForm').onsubmit=async e=>{
 e.preventDefault();e.submitter.disabled=true;
 const body={action:'save',id:$('#mcpId').value,name:$('#mcpName').value,url:$('#mcpUrl').value,description:$('#mcpDescription').value,enabled:$('#mcpEnabled').checked,account_id:$('#mcpAccount').value,token:$('#mcpToken').value,clear_token:$('#mcpClear').checked};
 if(MCP_EDIT)body.version=MCP_EDIT.version;
 try{body.policy={purposes:[...document.querySelectorAll('#mcpPurposes input:checked')].map(e=>e.value),sites:[...$('#mcpSites').selectedOptions].map(e=>e.value),tools:JSON.parse($('#mcpToolRules').value||'[]'),resources:$('#mcpResources').value.split('\n').map(s=>s.trim()).filter(Boolean),prompts:$('#mcpPrompts').value.split('\n').map(s=>s.trim()).filter(Boolean),calls_per_hour:Number($('#mcpLimit').value),timeout:Number($('#mcpTimeout').value)};await aiRequest('/api/mcp/servers',body);MCP_MODAL.close(true);await loadMCP();aiMessage('#mcpMsg','MCP 配置已保存');}
 catch(err){aiMessage('#mcpFormMsg',err.message,true);}finally{body.token='';e.submitter.disabled=false;}
};
$('#mcpList').onclick=async e=>{
 const b=e.target.closest('button');if(!b)return;
 const id=b.dataset.mcpView||b.dataset.mcpEdit||b.dataset.mcpToggle||b.dataset.mcpTest||b.dataset.mcpDelete;const item=MCP_ITEMS.find(x=>x.id===id);if(!item)return;
 if(b.dataset.mcpView){AdminUI.detail(item.name,`<dl class="domain-meta"><dt>MCP 服务地址</dt><dd data-user-content>${esc(item.url)}</dd><dt>服务说明</dt><dd data-user-content>${esc(item.description)}</dd><dt>授权站点</dt><dd data-user-content>${esc((item.policy?.sites||[]).join(', '))}</dd><dt>配置版本</dt><dd>${Number(item.version)}</dd></dl>`);return;}
 if(b.dataset.mcpEdit){editMCP(item);return;}
 if(b.dataset.mcpDelete&&!confirm('删除此 MCP 服务配置及凭据？'))return;
 b.disabled=true;
 try{
  if(b.dataset.mcpTest){
   const epoch=++MCP_EPOCH;$('#mcpResult').classList.add('hidden');aiMessage('#mcpMsg','正在连接 MCP 并查询能力，最多约 45 秒…');
   const {result:r}=await aiRequest('/api/mcp/test',{id,version:item.version});if(epoch!==MCP_EPOCH)return;
   renderMCPCapabilities(item,r);
   $('#mcpResult').classList.remove('hidden');aiMessage('#mcpMsg','MCP 连接成功，能力列表已更新');
  }else{
   await aiRequest('/api/mcp/servers',b.dataset.mcpDelete?{action:'delete',id,version:item.version}:{...item,action:'save',enabled:!item.enabled});
   if(MCP_EDIT?.id===id)MCP_MODAL.close(true);await loadMCP();aiMessage('#mcpMsg','MCP 配置已更新');
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
  MCP_MODAL.dirty();$('#mcpForm details').open=true;$('#mcpForm').scrollIntoView({block:'start'});aiMessage('#mcpFormMsg','已加入待保存白名单，请设置用途、站点范围和执行规则后保存。');
 }catch(err){aiMessage('#mcpFormMsg','请先修正工具规则 JSON：'+err.message,true);}
};

$('#mcpUsePreset').onclick=()=>{
 const presets={
  'cloudflare-docs':{name:'Cloudflare 文档',url:'https://docs.mcp.cloudflare.com/mcp',tools:['search_cloudflare_documentation']},
  'cloudflare-api':{name:'Cloudflare API',url:'https://mcp.cloudflare.com/mcp',tools:['docs','search']},
  'aws-knowledge':{name:'AWS Knowledge',url:'https://knowledge-mcp.global.api.aws',tools:['aws___search_documentation','aws___read_documentation']},
  'aws-api':{name:'AWS MCP（新加坡）',url:'https://aws-mcp.ap-southeast-1.api.aws/mcp',tools:['aws___search_documentation','aws___read_documentation']}
 };
 const id=$('#mcpPreset').value;if(!id)return;editMCP(null);const p=presets[id];if(p){$('#mcpId').value=id;$('#mcpName').value=p.name;$('#mcpUrl').value=p.url;$('#mcpToolRules').value=JSON.stringify(p.tools.map(name=>({name,mode:'read',bindings:{}})),null,2);}
 MCP_MODAL.dirty();aiMessage('#mcpFormMsg','预设尚未保存。请选择账号、用途和站点；通用脚本执行工具不会自动加入白名单。');
};
$('#mcpAccount').onchange=()=>{if($('#mcpAccount').value)$('#mcpToken').value='';};

function renderMCPCapabilities(item,r){
 MCP_LAST_TEST=item.id;$('#mcpResult').innerHTML=`<h3 data-user-content>${esc(item.name)} · ${esc(r.server)} ${esc(r.version)}</h3><p>协议：${esc(r.protocol)}</p>${[['tools','工具'],['resources','资源'],['prompts','提示词']].map(([k,label])=>`<details open><summary>${label}（${r[k].length}）</summary>${r[k].map(v=>`<p style="overflow-wrap:anywhere"><b data-user-content>${esc(v.name)}</b> <button type="button" class="ghost" data-policy-kind="${k}" data-policy-name="${esc(k==='resources'?v.uri:v.name)}">加入白名单</button><br><span data-user-content>${esc(v.description)}</span>${v.uri?'<br>URI: '+esc(v.uri):''}</p>${v.inputSchema?'<details><summary>参数定义</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+esc(JSON.stringify(v.inputSchema,null,2))+'</pre></details>':''}`).join('')||'<p class="hint">未提供条目</p>'}</details>`).join('')}${r.truncated?'<p class="hint">结果已截断，每类最多显示 100 条、读取 5 页。</p>':''}`;
}
