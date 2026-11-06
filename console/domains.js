/* Domain account metadata is queryable; plaintext passwords are ephemeral and TOTP-gated. */
let DOMAIN_SITES=[], DOMAIN_ACCOUNTS=[], DOMAIN_ALLOWED=false, DOMAIN_EDIT=null;
let DOMAIN_MANAGE=false,DOMAIN_PAGE=1,DOMAIN_DETAIL=null,DOMAIN_RECORD=null;
let DOMAIN_REVEAL_ID=null, DOMAIN_SECRET_TIMER=null, DOMAIN_REVEAL_EPOCH=0;
const DOMAIN_CATEGORIES={registrar:'域名注册商',dns:'DNS 服务商',hosting:'托管服务商',other:'其他机构'};
async function domainRequest(path,body){
 const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 let data;try{data=await r.json();}catch(_){throw Error(r.status===401?'登录已过期，请重新登录':'服务响应异常');}
 if(!r.ok)throw Error(data.error||'操作失败');return data;
}
function domainMessage(id,text,bad=false){const el=$(id);el.textContent=text;el.className='msg '+(bad?'bad':'ok');}
async function loadDomainRegistry(){
 hideDomainSecret();
 const d=await domainRequest('/api/domains');DOMAIN_SITES=d.items||[];DOMAIN_MANAGE=d.can_manage===true;
 DOMAIN_ALLOWED=false;DOMAIN_ACCOUNTS=[];
 const r=await fetch('/api/domain/accounts');
 if(r.ok){const v=await r.json();DOMAIN_ALLOWED=true;DOMAIN_ACCOUNTS=v.items||[];}
 else if(r.status!==403)throw Error(r.status===401?'登录已过期，请重新登录':'管理账号加载失败，请刷新');
 renderDomainRegistry();
}
function domainAccounts(site){return DOMAIN_ACCOUNTS.filter(a=>a.slug===site.slug||(site.site_slug&&a.slug===site.site_slug));}
function domainExpiry(site){const value=site.manage?.expires;if(!value)return null;const today=new Date(Date.now()+8*3600000).toISOString().slice(0,10);return Math.round((Date.parse(value+'T00:00:00Z')-Date.parse(today+'T00:00:00Z'))/86400000);}
function renderDomainRegistry(){
 const query=$('#domainSearch').value.trim().toLowerCase(),filter=$('#domainExpiryFilter').value;
 const rows=DOMAIN_SITES.filter(site=>{
  const searchable=[site.domain,site.company,site.manage?.registrar,site.manage?.note,...domainAccounts(site).flatMap(a=>[a.provider,a.url,a.username,a.configuration])].join(' ').toLowerCase();
  const days=domainExpiry(site);return searchable.includes(query)&&(!filter||(filter==='unset'?days===null:days!==null&&(filter==='expired'?days<0:days>=0&&days<=30)));
 }).sort((a,b)=>a.domain.localeCompare(b.domain));
 const total=Math.max(1,Math.ceil(rows.length/25));DOMAIN_PAGE=Math.max(1,Math.min(DOMAIN_PAGE,total));
 $('#domainCount').innerHTML='<span>匹配域名</span> <b>'+rows.length+'</b>';
 $('#domainPage').textContent=DOMAIN_PAGE+' / '+total;$('#domainPrev').disabled=DOMAIN_PAGE<=1;$('#domainNext').disabled=DOMAIN_PAGE>=total;
 $('#domainNew').hidden=!DOMAIN_MANAGE;
 $('#dList').innerHTML='<table class="domain-table"><thead><tr><th>域名</th><th>客户 / 站点</th><th>注册商</th><th>到期日</th><th>管理账号</th><th>操作</th></tr></thead><tbody>'+rows.slice((DOMAIN_PAGE-1)*25,DOMAIN_PAGE*25).map(site=>{
  const accounts=domainAccounts(site),registrar=site.manage?.registrar||accounts.find(a=>a.category==='registrar')?.provider,days=domainExpiry(site);
  return `<tr><td><b data-user-content>${esc(site.domain)}</b></td><td><span data-user-content>${esc(site.company||'—')}</span><div class="hint">${site.site_slug?`<span data-user-content>${esc(site.site_slug)}</span>`:'<span>独立登记</span>'}</div></td><td>${registrar?`<span data-user-content>${esc(registrar)}</span>`:'<span>未登记</span>'}</td><td><span data-user-content>${esc(site.manage?.expires||'—')}</span>${days!==null&&days<=30?`<div class="pill" style="color:var(--warn)">${days<0?'已过期':'即将到期'}</div>`:''}</td><td>${DOMAIN_ALLOWED?accounts.length:'—'}</td><td><div class="domain-row-actions"><button type="button" class="ghost" data-domain-view="${esc(site.slug)}">查看</button>${DOMAIN_MANAGE?`<button type="button" class="ghost" data-domain-record-edit="${esc(site.slug)}">编辑</button><button type="button" class="ghost danger" data-domain-record-delete="${esc(site.slug)}">删除</button>`:''}</div></td></tr>`;
 }).join('')+'</tbody></table>'+(rows.length?'':'<div class="empty-results"><p>没有匹配的域名或管理账号。</p><button type="button" class="ghost" data-domain-reset>清除筛选</button></div>');
 if(DOMAIN_DETAIL){const item=DOMAIN_SITES.find(s=>s.slug===DOMAIN_DETAIL);if(item)renderDomainDetail(item);else $('#domainDetailDialog').close();}
}
function renderDomainDetail(site){
 $('#domainDetailTitle').textContent=site.domain;
 $('#domainDetailMeta').innerHTML=`<dl class="domain-meta"><dt>客户 / 站点</dt><dd data-user-content>${esc(site.company||site.site_slug||'—')}</dd><dt>注册商</dt><dd data-user-content>${esc(site.manage?.registrar||'—')}</dd><dt>到期日</dt><dd data-user-content>${esc(site.manage?.expires||'—')}</dd><dt>归属</dt><dd>${site.manage?.owner==='client'?'在客户账户':'在我们账户（代管）'}</dd><dt>自动续费</dt><dd>${site.manage?.auto_renew?'已启用':'已停用'}</dd><dt>备注</dt><dd data-user-content>${esc(site.manage?.note||'—')}</dd></dl><a href="${esc(site.url||'https://'+site.domain)}" target="_blank" rel="noopener noreferrer">访问网站</a>`;
 $('#domainDetailAdd').hidden=!DOMAIN_ALLOWED;$('#domainDetailAdd').dataset.domainAdd=site.slug;
 $('#domainAccountsList').innerHTML=!DOMAIN_ALLOWED?'<p class="hint">当前角色无权访问管理机构账号</p>':domainAccounts(site).length?'<table class="domain-table"><thead><tr><th>管理机构</th><th>机构类型</th><th>用户名</th><th>密码</th><th>操作</th></tr></thead><tbody>'+domainAccounts(site).map(a=>`<tr><td><b data-user-content>${esc(a.provider)}</b>${a.url?`<div><a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">管理后台</a></div>`:''}<details><summary>配置信息</summary><pre data-user-content>${esc(a.configuration||'—')}</pre><p><span>版本 ${Number(a.version)}</span> · <span data-user-content>${esc(a.updated_by)}</span></p></details></td><td>${esc(DOMAIN_CATEGORIES[a.category]||a.category)}</td><td>${a.username?`<span data-user-content>${esc(a.username)}</span>`:'<span>未填写</span>'}</td><td>${a.has_password?`<span>••••••••</span><button type="button" class="ghost" data-domain-reveal="${esc(a.id)}">TOTP 验证后显示</button>`:'<span>未保存</span>'}</td><td><div class="domain-row-actions"><button type="button" class="ghost" data-domain-edit="${esc(a.id)}">编辑</button><button type="button" class="ghost danger" data-domain-delete="${esc(a.id)}">删除</button></div></td></tr>`).join('')+'</tbody></table>':'<p class="hint">尚未登记匹配的管理机构账号。</p>';
}
function openDomainDetail(site){DOMAIN_DETAIL=site.slug;renderDomainDetail(site);domainMessage('#domainDetailMsg','');$('#domainDetailDialog').showModal();$('#domainDetailClose').focus();}
function editDomainRecord(site){
 DOMAIN_RECORD=site||null;$('#domainRecordForm').reset();$('#domainRecordTitle').textContent=site?'编辑域名':'新增域名';
 $('#domainRecordName').value=site?.domain||'';$('#domainRecordCompany').value=site?.company||'';
 $('#domainRecordName').readOnly=!!site?.site_slug;$('#domainRecordCompany').readOnly=!!site?.site_slug;
 $('#domainRecordBinding').textContent=site?.site_slug?'已关联站点，域名及客户名称由站点维护。':'仅登记管理信息，不会购买域名或修改 DNS。';
 for(const [id,key] of Object.entries({domainRecordRegistrar:'registrar',domainRecordExpiry:'expires',domainRecordNote:'note'}))$('#'+id).value=site?.manage?.[key]||'';
 $('#domainRecordOwner').value=site?.manage?.owner||'us';$('#domainRecordRenew').checked=site?.manage?.auto_renew??true;
 domainMessage('#domainRecordMsg','');$('#domainRecordDialog').showModal();$('#domainRecordName').focus();
}
$('#domainNew').onclick=()=>editDomainRecord(null);
$('#domainRecordCancel').onclick=()=>$('#domainRecordDialog').close();
$('#domainDetailClose').onclick=()=>$('#domainDetailDialog').close();
$('#domainDetailDialog').addEventListener('close',()=>{DOMAIN_DETAIL=null;closeDomainReveal();});
$('#domainRecordForm').onsubmit=async e=>{
 e.preventDefault();const button=e.submitter;button.disabled=true;
 const body={action:'save',domain:$('#domainRecordName').value.trim(),company:$('#domainRecordCompany').value.trim(),registrar:$('#domainRecordRegistrar').value.trim(),expires:$('#domainRecordExpiry').value,owner:$('#domainRecordOwner').value,auto_renew:$('#domainRecordRenew').checked,note:$('#domainRecordNote').value};
 if(DOMAIN_RECORD)Object.assign(body,{id:DOMAIN_RECORD.slug,version:DOMAIN_RECORD.version});
 try{await domainRequest('/api/domain/records',body);$('#domainRecordDialog').close();await loadDomainRegistry();domainMessage('#dMsg','域名信息已保存');}catch(err){domainMessage('#domainRecordMsg',err.message,true);}finally{button.disabled=false;}
};
$('#dList').onclick=async e=>{
 const b=e.target.closest('button');if(!b)return;
 if(b.hasAttribute('data-domain-reset')){$('#domainSearch').value='';$('#domainExpiryFilter').value='';DOMAIN_PAGE=1;renderDomainRegistry();return;}
 const id=b.dataset.domainView||b.dataset.domainRecordEdit||b.dataset.domainRecordDelete,site=DOMAIN_SITES.find(s=>s.slug===id);if(!site)return;
 if(b.dataset.domainView){openDomainDetail(site);return;}
 if(b.dataset.domainRecordEdit){editDomainRecord(site);return;}
 if(!confirm('删除此域名管理记录？不会注销域名、停止网站或删除 DNS 记录。'))return;
 b.disabled=true;try{await domainRequest('/api/domain/records',{action:'delete',id,version:site.version});await loadDomainRegistry();domainMessage('#dMsg','域名管理记录已删除');}catch(err){domainMessage('#dMsg',err.message,true);}finally{if(b.isConnected)b.disabled=false;}
};
$('#domainExpiryFilter').onchange=()=>{DOMAIN_PAGE=1;renderDomainRegistry();};
$('#domainPrev').onclick=()=>{DOMAIN_PAGE--;renderDomainRegistry();};$('#domainNext').onclick=()=>{DOMAIN_PAGE++;renderDomainRegistry();};

function editDomainAccount(item,slug){
 hideDomainSecret();DOMAIN_EDIT=item?{...item}:null;
 $('#domainAccountSite').innerHTML=DOMAIN_SITES.map(s=>`<option value="${esc(item&&item.slug===s.site_slug?item.slug:s.slug)}">${esc(s.domain)}</option>`).join('');
 $('#domainAccountSite').value=item?.slug||slug;$('#domainAccountSite').disabled=!!item;
 for(const [id,key] of Object.entries({domainAccountCategory:'category',domainAccountProvider:'provider',domainAccountUrl:'url',domainAccountUsername:'username',domainAccountConfig:'configuration'}))$('#'+id).value=item?.[key]||(key==='category'?'registrar':'');
 $('#domainAccountPassword').value='';$('#domainAccountClear').checked=false;
 $('#domainAccountTitle').textContent=item?'编辑管理机构账号':'添加管理机构账号';
 domainMessage('#domainAccountMsg','');$('#domainAccountForm').classList.remove('hidden');$('#domainAccountDialog').showModal();$('#domainAccountProvider').focus();
}
function hideDomainSecret(){
 DOMAIN_REVEAL_EPOCH++;clearTimeout(DOMAIN_SECRET_TIMER);DOMAIN_SECRET_TIMER=null;
 $('#domainSecretValue').value='';$('#domainSecretWrap').classList.add('hidden');$('#domainRevealCode').value='';
}
function closeDomainReveal(){hideDomainSecret();if($('#domainRevealDialog').open)$('#domainRevealDialog').close();DOMAIN_REVEAL_ID=null;}
$('#domainSearch').oninput=()=>{DOMAIN_PAGE=1;renderDomainRegistry();};
$('#domainRefresh').onclick=async()=>{try{await loadDomainRegistry();domainMessage('#dMsg','资料已刷新');}catch(e){domainMessage('#dMsg',e.message,true);}};
$('#domainAccountCancel').onclick=()=>{$('#domainAccountPassword').value='';$('#domainAccountForm').classList.add('hidden');$('#domainAccountDialog').close();DOMAIN_EDIT=null;};
$('#domainAccountsList').onclick=async e=>{
 const button=e.target.closest('button');if(!button)return;
  const id=button.dataset.domainEdit||button.dataset.domainDelete||button.dataset.domainReveal;
 const item=DOMAIN_ACCOUNTS.find(a=>a.id===id);if(!item)return;
 if(button.dataset.domainEdit){editDomainAccount(item);return;}
 if(button.dataset.domainReveal){
  hideDomainSecret();DOMAIN_REVEAL_ID=id;$('#domainRevealLabel').textContent=item.provider+' · '+item.username;
  domainMessage('#domainRevealMsg','');$('#domainRevealDialog').showModal();$('#domainRevealCode').focus();return;
 }
 if(!confirm('删除此管理机构账号及保存的密码？此操作不会删除域名或网站。'))return;
 button.disabled=true;
 try{await domainRequest('/api/domain/accounts',{action:'delete',id,version:item.version});if(DOMAIN_EDIT?.id===id)$('#domainAccountCancel').click();await loadDomainRegistry();domainMessage('#domainDetailMsg','管理账号已删除');}
 catch(e){domainMessage('#domainDetailMsg',e.message,true);}finally{button.disabled=false;}
};
$('#domainAccountForm').onsubmit=async e=>{
 e.preventDefault();const button=e.submitter;button.disabled=true;
 const body={action:'save',slug:$('#domainAccountSite').value,category:$('#domainAccountCategory').value,
  provider:$('#domainAccountProvider').value.trim(),url:$('#domainAccountUrl').value.trim(),username:$('#domainAccountUsername').value,
  configuration:$('#domainAccountConfig').value,password:$('#domainAccountPassword').value,clear_password:$('#domainAccountClear').checked};
 if(DOMAIN_EDIT)Object.assign(body,{id:DOMAIN_EDIT.id,version:DOMAIN_EDIT.version});
 try{await domainRequest('/api/domain/accounts',body);$('#domainAccountPassword').value='';$('#domainAccountForm').classList.add('hidden');$('#domainAccountDialog').close();DOMAIN_EDIT=null;await loadDomainRegistry();domainMessage('#dMsg','管理机构账号已保存');}
 catch(e){domainMessage('#domainAccountMsg',e.message,true);}finally{button.disabled=false;body.password='';}
};
$('#domainRevealForm').onsubmit=async e=>{
 e.preventDefault();const button=$('#domainRevealSubmit');button.disabled=true;
 const id=DOMAIN_REVEAL_ID,code=$('#domainRevealCode').value;
 hideDomainSecret();const epoch=DOMAIN_REVEAL_EPOCH;domainMessage('#domainRevealMsg','正在验证…');
 try{
  const data=await domainRequest('/api/domain/accounts/reveal',{id,code});
  if(epoch!==DOMAIN_REVEAL_EPOCH||!$('#domainRevealDialog').open)return;
  $('#domainSecretValue').value=data.password;$('#domainSecretWrap').classList.remove('hidden');
  domainMessage('#domainRevealMsg','验证成功。密码将在 30 秒后隐藏。');
  DOMAIN_SECRET_TIMER=setTimeout(()=>{hideDomainSecret();domainMessage('#domainRevealMsg','密码已隐藏，再次显示需要新的 TOTP 验证码。');},30000);
 }catch(e){if(epoch===DOMAIN_REVEAL_EPOCH)domainMessage('#domainRevealMsg',e.message,true);}
 finally{button.disabled=false;$('#domainRevealCode').value='';}
};
$('#domainRevealClose').onclick=closeDomainReveal;
$('#domainRevealDialog').addEventListener('close',hideDomainSecret);
$('#domainRevealDialog').addEventListener('cancel',hideDomainSecret);
$('#domainSecretHide').onclick=()=>{hideDomainSecret();domainMessage('#domainRevealMsg','密码已隐藏');};
document.addEventListener('visibilitychange',()=>{if(document.hidden)closeDomainReveal();});
new MutationObserver(()=>{if($('#p-domain').classList.contains('hidden')){closeDomainReveal();$('#domainAccountPassword').value='';}}).observe($('#p-domain'),{attributes:true,attributeFilter:['class']});

$('#domainDetailAdd').onclick=()=>editDomainAccount(null,DOMAIN_DETAIL);
$('#domainAccountDialog').addEventListener('close',()=>{$('#domainAccountPassword').value='';$('#domainAccountForm').classList.add('hidden');DOMAIN_EDIT=null;});
new MutationObserver(()=>{if($('#p-domain').classList.contains('hidden'))for(const id of ['domainRecordDialog','domainAccountDialog','domainDetailDialog'])if($('#'+id).open)$('#'+id).close();}).observe($('#p-domain'),{attributes:true,attributeFilter:['class']});
