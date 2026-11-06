/* Domain account metadata is queryable; plaintext passwords are ephemeral and TOTP-gated. */
let DOMAIN_SITES=[], DOMAIN_ACCOUNTS=[], DOMAIN_ALLOWED=false, DOMAIN_EDIT=null;
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
 const d=await domainRequest('/api/domains');DOMAIN_SITES=d.items||[];
 DOMAIN_ALLOWED=false;DOMAIN_ACCOUNTS=[];
 const r=await fetch('/api/domain/accounts');
 if(r.ok){const v=await r.json();DOMAIN_ALLOWED=true;DOMAIN_ACCOUNTS=v.items||[];}
 else if(r.status!==403)throw Error(r.status===401?'登录已过期，请重新登录':'管理账号加载失败，请刷新');
 renderDomainRegistry();
}
function renderDomainRegistry(){
 const query=$('#domainSearch').value.trim().toLowerCase();
 const rows=DOMAIN_SITES.map(site=>{
  const match=(site.domain+' '+site.company+' '+(site.manage?.registrar||'')).toLowerCase().includes(query);
  const accounts=DOMAIN_ACCOUNTS.filter(a=>a.slug===site.slug&&(match||[a.provider,a.url,a.username,a.configuration].join(' ').toLowerCase().includes(query)));
  if(!match&&!accounts.length)return '';
  const url=site.url||'https://'+site.domain;
  return `<section class="dom-row"><div class="h"><b class="name">${esc(site.domain)}</b><span>${esc(site.company||site.slug)}</span><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">访问网站</a>${DOMAIN_ALLOWED?`<button type="button" data-domain-add="${esc(site.slug)}">添加管理机构</button>`:''}</div>
   <p class="hint">${esc(site.manage?.registrar||'注册商未登记')}${site.manage?.expires?' · 到期日 '+esc(site.manage.expires):''}</p>
   ${accounts.map(a=>`<article style="border-top:1px solid var(--line);padding:16px 0"><div class="h"><strong>${esc(a.provider)}</strong><span class="pill">${esc(DOMAIN_CATEGORIES[a.category]||a.category)}</span><button type="button" data-domain-edit="${esc(a.id)}">编辑</button><button type="button" class="ghost" data-domain-delete="${esc(a.id)}">删除</button></div>
    <p style="overflow-wrap:anywhere"><span>管理后台：</span>${a.url?`<a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.url)}</a>`:'<span>未填写</span>'}</p>
    <p style="overflow-wrap:anywhere">用户名：${a.username?`<span data-user-content>${esc(a.username)}</span>`:'<span>未填写</span>'}</p>
    <p><span>密码：</span><span>${a.has_password?'••••••••':'未保存'}</span> ${a.has_password?`<button type="button" class="ghost" data-domain-reveal="${esc(a.id)}">TOTP 验证后显示</button>`:''}</p>
    <details><summary>配置信息</summary>${a.configuration?`<pre data-user-content style="white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit">${esc(a.configuration)}</pre>`:'<p>未填写</p>'}</details>
    <p class="hint"><span>版本 ${Number(a.version)}</span> · <span data-user-content>${esc(a.updated_by)}</span> · ${esc(new Date(a.updated*1000).toLocaleString())}</p></article>`).join('')}
   ${!accounts.length&&DOMAIN_ALLOWED?'<p class="hint">尚未登记匹配的管理机构账号。</p>':''}</section>`;
 }).join('');
 $('#dList').innerHTML=rows||'<p class="hint">没有匹配的域名或管理账号。</p>';
}
function editDomainAccount(item,slug){
 hideDomainSecret();DOMAIN_EDIT=item?{...item}:null;
 $('#domainAccountSite').innerHTML=DOMAIN_SITES.map(s=>`<option value="${esc(s.slug)}">${esc(s.domain)}</option>`).join('');
 $('#domainAccountSite').value=item?.slug||slug;$('#domainAccountSite').disabled=!!item;
 for(const [id,key] of Object.entries({domainAccountCategory:'category',domainAccountProvider:'provider',domainAccountUrl:'url',domainAccountUsername:'username',domainAccountConfig:'configuration'}))$('#'+id).value=item?.[key]||(key==='category'?'registrar':'');
 $('#domainAccountPassword').value='';$('#domainAccountClear').checked=false;
 $('#domainAccountTitle').textContent=item?'编辑管理机构账号':'添加管理机构账号';
 domainMessage('#domainAccountMsg','');$('#domainAccountForm').classList.remove('hidden');$('#domainAccountForm').scrollIntoView({block:'start'});$('#domainAccountProvider').focus();
}
function hideDomainSecret(){
 DOMAIN_REVEAL_EPOCH++;clearTimeout(DOMAIN_SECRET_TIMER);DOMAIN_SECRET_TIMER=null;
 $('#domainSecretValue').value='';$('#domainSecretWrap').classList.add('hidden');$('#domainRevealCode').value='';
}
function closeDomainReveal(){hideDomainSecret();if($('#domainRevealDialog').open)$('#domainRevealDialog').close();DOMAIN_REVEAL_ID=null;}
$('#domainSearch').oninput=renderDomainRegistry;
$('#domainRefresh').onclick=async()=>{try{await loadDomainRegistry();domainMessage('#dMsg','资料已刷新');}catch(e){domainMessage('#dMsg',e.message,true);}};
$('#domainAccountCancel').onclick=()=>{$('#domainAccountPassword').value='';$('#domainAccountForm').classList.add('hidden');DOMAIN_EDIT=null;};
$('#dList').onclick=async e=>{
 const button=e.target.closest('button');if(!button)return;
 if(button.dataset.domainAdd){editDomainAccount(null,button.dataset.domainAdd);return;}
 const id=button.dataset.domainEdit||button.dataset.domainDelete||button.dataset.domainReveal;
 const item=DOMAIN_ACCOUNTS.find(a=>a.id===id);if(!item)return;
 if(button.dataset.domainEdit){editDomainAccount(item);return;}
 if(button.dataset.domainReveal){
  hideDomainSecret();DOMAIN_REVEAL_ID=id;$('#domainRevealLabel').textContent=item.provider+' · '+item.username;
  domainMessage('#domainRevealMsg','');$('#domainRevealDialog').showModal();$('#domainRevealCode').focus();return;
 }
 if(!confirm('删除此管理机构账号及保存的密码？此操作不会删除域名或网站。'))return;
 button.disabled=true;
 try{await domainRequest('/api/domain/accounts',{action:'delete',id,version:item.version});if(DOMAIN_EDIT?.id===id)$('#domainAccountCancel').click();await loadDomainRegistry();domainMessage('#dMsg','管理账号已删除');}
 catch(e){domainMessage('#dMsg',e.message,true);}finally{button.disabled=false;}
};
$('#domainAccountForm').onsubmit=async e=>{
 e.preventDefault();const button=e.submitter;button.disabled=true;
 const body={action:'save',slug:$('#domainAccountSite').value,category:$('#domainAccountCategory').value,
  provider:$('#domainAccountProvider').value.trim(),url:$('#domainAccountUrl').value.trim(),username:$('#domainAccountUsername').value,
  configuration:$('#domainAccountConfig').value,password:$('#domainAccountPassword').value,clear_password:$('#domainAccountClear').checked};
 if(DOMAIN_EDIT)Object.assign(body,{id:DOMAIN_EDIT.id,version:DOMAIN_EDIT.version});
 try{await domainRequest('/api/domain/accounts',body);$('#domainAccountPassword').value='';$('#domainAccountForm').classList.add('hidden');DOMAIN_EDIT=null;await loadDomainRegistry();domainMessage('#dMsg','管理机构账号已保存');}
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
