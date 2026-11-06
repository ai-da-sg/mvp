/* Enquiries across sites; original submissions stay in WordPress. */
const LEAD_TEXT={search:['搜索姓名、联系方式或内容','Search name, contact or message'],site:['站点','Site'],all:['全部站点','All sites'],status:['处理状态','Status'],any:['全部状态','All statuses'],new:['待处理','New'],contacted:['已联系','Contacted'],won:['已转化','Converted'],closed:['已关闭','Closed'],archived:['包含归档站点','Include archived sites'],refresh:['刷新','Refresh'],retry:['重试未完成读取','Retry incomplete results'],more:['读取更多线索','Load more enquiries'],detail:['线索详情与跟进','Enquiry and follow-up'],note:['新增跟进备注','Add a follow-up note'],save:['保存跟进','Save follow-up'],close:['关闭','Close'],history:['跟进历史','Follow-up history'],none:['暂无跟进记录','No follow-up history'],contact:['联系人','Contact'],date:['提交时间','Submitted'],action:['操作','Actions'],view:['查看 / 跟进','View / follow up'],loaded:['已读取 {count} 条，当前显示 {shown} 条','{count} loaded; {shown} shown'],partial:['以下站点读取失败，结果不完整：','Results are incomplete. Could not read:'],limit:['每次读取每站点最多 100 条；可继续读取更多。','Each request reads up to 100 enquiries per site. Load more to continue.'],saved:['跟进已保存','Follow-up saved'],mail:['原提交邮件未发送','Original submission email was not sent'],loading:['正在读取线索…','Loading enquiries…']};
const LEAD_ERRORS={
 'Invalid enquiry update':['线索更新参数无效','Invalid enquiry update'],
 'Follow-up note must be at most 2000 characters':['跟进备注最多 2000 字','Follow-up note must be at most 2000 characters'],
 'Enquiry changed; refresh before saving':['线索已被更新，请关闭并重新打开后核对；未保存的备注仍保留在此。','Enquiry changed. Close and reopen to review it; your unsaved note is still here.'],
 'Add a note or change the status':['请填写备注或更改处理状态','Add a note or change the status'],
 'Unable to read enquiries from this site':['无法读取此站点的线索，请稍后重试','Unable to read enquiries from this site; try again later'],
 'Enquiry no longer exists':['原始线索已不存在','Enquiry no longer exists']
};
let LEAD_ITEMS=[],LEAD_SOURCES=[],LEAD_PAGE=1,LEAD_MORE=false,LEAD_EPOCH=0,LEAD_EDIT=null,LEAD_READY=false,LEAD_SCOPE='',LEAD_CONTEXT='';
function leadText(key){return AdminUI.text(...LEAD_TEXT[key]);}
function leadError(error){const pair=LEAD_ERRORS[error.message];return pair?AdminUI.text(...pair):error.message;}
function leadTranslate(){
 document.querySelectorAll('[data-lead-text]').forEach(e=>e.textContent=leadText(e.dataset.leadText));
 for(const id of ['ldStatus','leadStatus']){const sel=$('#'+id),old=sel.value;sel.innerHTML=(id==='ldStatus'?`<option value="">${esc(leadText('any'))}</option>`:'')+['new','contacted','won','closed'].map(s=>`<option value="${s}">${esc(leadText(s))}</option>`).join('');if([...sel.options].some(o=>o.value===old))sel.value=old;}
 leadSites();renderLeads();if(LEAD_EDIT)renderLeadDetail();
}
function leadSites(){
 const sel=$('#ldSlug'),old=sel.value;
 sel.innerHTML=`<option value="">${esc(leadText('all'))}</option>`+(STATE.sites||[]).filter(s=>$('#ldArchived').checked||!s.archived).map(s=>`<option value="${esc(s.slug)}" data-user-content>${esc(s.company+' / '+s.slug)}</option>`).join('');
 if([...sel.options].some(o=>o.value===old))sel.value=old;
}
function renderLeads(){
 const q=$('#ldSearch').value.trim().toLocaleLowerCase(),status=$('#ldStatus').value;
 const rows=LEAD_ITEMS.filter(x=>(!status||x.followup.status===status)&&[x.title,x.email,x.phone,x.msg,x.company,x.domain].join(' ').toLocaleLowerCase().includes(q));
 $('#ldCount').textContent=leadText('loaded').replace('{count}',LEAD_ITEMS.length).replace('{shown}',rows.length);
 const failures=LEAD_SOURCES.filter(x=>x.error);
 $('#ldFailures').textContent=failures.length?leadText('partial')+failures.map(x=>x.company+' / '+x.slug).join(', '):'';
 $('#ldFailures').className=failures.length?'callout':'';
 AdminUI.table('ldList',rows,['contact','site','status','date','action'].map(leadText),x=>`<tr><td data-user-content><b>${esc(String(x.title||'').split(' — ')[0])}</b><p>${esc(x.email||x.phone||'')}</p></td><td data-user-content>${esc(x.company)}<p class="hint">${esc(x.domain)}</p></td><td>${esc(leadText(x.followup.status))}</td><td data-user-content>${esc(x.date||'')}</td><td><button type="button" data-lead-open="${esc(x.slug+':'+x.id)}">${esc(leadText('view'))}</button></td></tr>`);
 $('#ldMore').textContent=leadText(failures.length?'retry':'more');$('#ldMore').hidden=!LEAD_MORE;$('#ldMore').title=leadText('limit');
}
async function loadLeads(reset=true,force=false){
 const scope=JSON.stringify([$('#ldSlug').value,$('#ldArchived').checked]);
 if(scope!==LEAD_SCOPE){LEAD_SCOPE=scope;LEAD_ITEMS=[];LEAD_SOURCES=[];LEAD_MORE=false;renderLeads();}
 const epoch=++LEAD_EPOCH,page=reset?1:LEAD_PAGE+1;
 $('#ldRefresh').disabled=$('#ldMore').disabled=true;$('#ldList').setAttribute('aria-busy','true');aiMessage('#ldMsg',leadText('loading'));
 try{
  const query=new URLSearchParams({slug:$('#ldSlug').value,page:String(page),archived:Number($('#ldArchived').checked),refresh:Number(force||LEAD_SOURCES.some(x=>x.error))});
  const data=await aiRequest('/api/leads?'+query);if(epoch!==LEAD_EPOCH)return;
  LEAD_ITEMS=[...new Map((reset?data.items:[...LEAD_ITEMS,...data.items]).map(x=>[x.slug+':'+x.id,x])).values()];
  LEAD_SOURCES=data.sources;const partial=data.sources.some(x=>x.error);LEAD_PAGE=partial?page-1:page;LEAD_MORE=partial||data.has_more;renderLeads();aiMessage('#ldMsg','');
 }catch(e){if(epoch===LEAD_EPOCH)aiMessage('#ldMsg',leadError(e),true);}
 finally{if(epoch===LEAD_EPOCH){$('#ldRefresh').disabled=$('#ldMore').disabled=false;$('#ldList').removeAttribute('aria-busy');}}
}
function renderLeadDetail(){
 const x=LEAD_EDIT;if(!x)return;
 $('#leadOriginal').innerHTML=`<p data-user-content><b>${esc(x.title||'')}</b><br>${esc(x.company)} · ${esc(x.date||'')}<br>${esc(x.email||'')} ${esc(x.phone||'')}</p><p style="white-space:pre-wrap;overflow-wrap:anywhere" data-user-content>${esc(x.msg||'')}</p>${x.sent==='0'?`<p class="hint">${esc(leadText('mail'))}</p>`:''}`;
 $('#leadHistory').innerHTML=x.followup.history.map(h=>`<article><p data-user-content>${esc(new Date(h.at*1000).toLocaleString())} · ${esc(h.by)}</p><p>${esc(leadText(h.from))} → ${esc(leadText(h.to))}</p><p style="white-space:pre-wrap;overflow-wrap:anywhere" data-user-content>${esc(h.note)}</p></article>`).reverse().join('')||`<p class="hint">${esc(leadText('none'))}</p>`;
}
const LEAD_DIALOG=AdminUI.form('leadForm','',()=>{LEAD_EDIT=null;$('#leadNote').value='';});
$('#leadCancel').onclick=()=>LEAD_DIALOG.close();
$('#ldList').onclick=e=>{const b=e.target.closest('[data-lead-open]');if(!b)return;LEAD_EDIT=LEAD_ITEMS.find(x=>x.slug+':'+x.id===b.dataset.leadOpen);if(!LEAD_EDIT)return;$('#leadStatus').value=LEAD_EDIT.followup.status;$('#leadNote').value='';aiMessage('#leadMsg','');renderLeadDetail();LEAD_DIALOG.open();$('#leadStatus').focus();};
$('#leadForm').onsubmit=async e=>{
 e.preventDefault();const x=LEAD_EDIT;if(!x)return;$('#leadSave').disabled=true;
 try{const data=await aiRequest('/api/leads/followup',{slug:x.slug,id:x.id,version:x.followup.version,status:$('#leadStatus').value,note:$('#leadNote').value});x.followup=data.item;LEAD_DIALOG.close(true);renderLeads();aiMessage('#ldMsg',leadText('saved'));}
 catch(error){aiMessage('#leadMsg',leadError(error),true);}finally{$('#leadSave').disabled=false;}
};
$('#ldSearch').oninput=$('#ldStatus').onchange=()=>{AdminUI.pages.set('ldList',0);renderLeads();};
$('#ldSlug').onchange=()=>{if($('#ldSlug').value)SiteContext.save({slug:$('#ldSlug').value,archived:$('#ldArchived').checked});LEAD_CONTEXT=JSON.stringify(SiteContext.read());loadLeads();};
$('#ldArchived').onchange=()=>{SiteContext.save({archived:$('#ldArchived').checked});LEAD_CONTEXT=JSON.stringify(SiteContext.read());leadSites();loadLeads();};
$('#ldRefresh').onclick=()=>loadLeads(true,true);$('#ldMore').onclick=()=>loadLeads(false);
function initLeads(){const context=SiteContext.read(),changed=JSON.stringify(context)!==LEAD_CONTEXT;if(!LEAD_READY||changed){$('#ldArchived').checked=!!context.archived;leadSites();if([...$('#ldSlug').options].some(o=>o.value===context.slug&&o.value))$('#ldSlug').value=context.slug;else if(context.slug==='')$('#ldSlug').value=$('#ldSlug').options[1]?.value||'';if($('#ldSlug').value)SiteContext.save({slug:$('#ldSlug').value,archived:$('#ldArchived').checked});LEAD_READY=true;LEAD_CONTEXT=JSON.stringify(SiteContext.read());}else leadSites();loadLeads();}
new MutationObserver(leadTranslate).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});leadTranslate();
