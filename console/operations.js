/* Structured message keys keep operational summaries bilingual and concise. */
const OPS_TEXT={
 health_unknown:['健康状态暂不可用','Health status unavailable'],
 site_unreachable:['网站访问异常','Website is not responding normally'],
 service_expiry:['服务将在 {days} 天内到期','Service expires in {days} days'],
 service_expired:['服务已过期 {days} 天','Service expired {days} days ago'],
 domain_expiry:['域名将在 {days} 天内到期','Domain expires in {days} days'],
 domain_expired:['域名已过期 {days} 天','Domain expired {days} days ago'],
 content_snapshot_old:['内容快照已超过 {days} 天','Content snapshot is {days} days old'],
 content_snapshot_missing:['尚无内容快照','No content snapshot yet'],
 generation_failed:['建站任务失败','Site generation failed'],
 action_attention:['操作结果需要处理','Operation needs attention'],
 workflow_attention:['交付流程需要处理','Delivery workflow needs attention'],
 publication_attention:['发布或恢复需要处理','Publication or recovery needs attention'],
 https_attention:['上次 HTTPS 检查需关注','Last HTTPS check needs attention'],
 mail_delivery_failed:['邮件投递失败','Email delivery failed'],
 mail_delivery_unknown:['邮件投递尚未确认','Email delivery is unconfirmed'],
 inspection_attention:['上次检查有 {checks} 项需关注','Last inspection has {checks} items needing attention']
};
let OPS_ITEMS=[],OPS_LOADING=false,OPS_LAST=0,OPS_SIGNATURE='',OPS_OPENED=false;
function operationText(item){
 let key=item.code;if(item.details.days<0&&['domain_expiry','service_expiry'].includes(key))key=key.replace('expiry','expired');
 const pair=OPS_TEXT[key]||OPS_TEXT.action_attention;
 return AdminUI.text(...pair).replace('{days}',String(Math.abs(item.details.days||0))).replace('{checks}',String(item.details.checks||0));
}
function renderOperations(){
 const query=$('#operationSearch').value.trim().toLocaleLowerCase(),severity=$('#operationSeverity').value;
 const items=OPS_ITEMS.filter(x=>(!severity||x.severity===severity)&&[x.company,x.domain,operationText(x)].join(' ').toLocaleLowerCase().includes(query));
 const signature=JSON.stringify([items,document.documentElement.lang]);if(signature===OPS_SIGNATURE)return;OPS_SIGNATURE=signature;
 $('#operationCount').textContent=String(OPS_ITEMS.filter(x=>!x.acknowledged).length);
 AdminUI.table('operationList',items,['事项','客户 / 站点','优先级','操作'],x=>`<tr><td>${esc(operationText(x))}${x.acknowledged?'<p class="hint">已知悉</p>':''}</td><td><span data-user-content>${esc(x.company)}</span><p class="hint" data-user-content>${esc(x.domain)}</p></td><td>${x.severity==='critical'?'紧急':x.severity==='warning'?'需关注':'提示'}</td><td><div class="domain-row-actions"><button type="button" data-operation-open="${esc(x.id)}">处理</button>${x.acknowledge?`<button type="button" class="ghost" data-operation-ack="${esc(x.id)}">${x.acknowledged?'恢复提醒':'已知悉'}</button>`:''}</div></td></tr>`);
}
async function refreshOperations(force=false){
 if(!['admin','ops'].includes(ROLE)||OPS_LOADING||(!force&&Date.now()-OPS_LAST<30000))return;
 OPS_LOADING=true;$('#operationRefresh').disabled=true;$('#operationList').setAttribute('aria-busy','true');
 try{
  const data=await aiRequest('/api/operations/overview?archived='+Number($('#operationArchived').checked)+'&ack='+Number($('#operationAcknowledged').checked));OPS_ITEMS=data.items||[];OPS_LAST=Date.now();renderOperations();
  if(!OPS_OPENED){$('#operationInbox').open=OPS_ITEMS.some(x=>x.severity==='critical');OPS_OPENED=true;}
  aiMessage('#operationMsg','');
 }catch(e){aiMessage('#operationMsg',e.message,true);}finally{OPS_LOADING=false;$('#operationRefresh').disabled=false;$('#operationList').removeAttribute('aria-busy');}
}
$('#operationRefresh').onclick=()=>refreshOperations(true);
$('#operationArchived').onchange=$('#operationAcknowledged').onchange=()=>refreshOperations(true);
$('#operationSearch').oninput=$('#operationSeverity').onchange=()=>{AdminUI.pages.set('operationList',0);renderOperations();};
$('#operationList').onclick=async e=>{
 const b=e.target.closest('[data-operation-open],[data-operation-ack]');if(!b)return;
 const item=OPS_ITEMS.find(x=>x.id===(b.dataset.operationOpen||b.dataset.operationAck));if(!item)return;
 b.disabled=true;
 try{
  if(b.dataset.operationAck){
   if(!item.acknowledged&&!confirm('从我的待办中隐藏这条记录？不会改变原任务结果，可通过“包含已知悉”恢复提醒。'))return;
   await aiRequest('/api/operations/ack',{id:item.id,revision:item.revision,action:item.acknowledged?'restore':'ack'});await refreshOperations(true);return;
  }
  const tab=CURRENT_TAB;let pending=null;
  if(['action','inspection'].includes(item.kind)){const data=await aiRequest('/api/automation/action/'+encodeURIComponent(item.reference));pending=data.item;}
  if(CURRENT_TAB!==tab)return;
  const previous=SiteContext.read();if(item.slug)SiteContext.save({slug:item.slug,archived:item.archived||previous.archived});
  if(item.route==='domain')$('#domainSearch').value=item.domain;
  if(item.route==='layout'){window.aiEditorTarget=item.slug;$('#publicationHistory').open=true;}
  if(item.route==='ai')window.aiContextTarget=item.slug;
  if(pending)window.autoPendingAction=pending;
  else if(item.route==='automation')$('#autoPurpose').value='maintenance';
  window.OPERATION_TARGET={kind:item.kind,reference:item.reference,route:item.route};
  if(!navigateTo(item.route)){SiteContext.save(previous);window.OPERATION_TARGET=null;window.autoPendingAction=null;window.aiEditorTarget=null;window.aiContextTarget=null;}
 }catch(err){aiMessage('#operationMsg',err.message,true);}finally{b.disabled=false;}
};
new MutationObserver(()=>{if(OPS_ITEMS.length)renderOperations();}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});

function focusOperationTarget(kind,selector){
 const target=window.OPERATION_TARGET;if(!target||target.kind!==kind||CURRENT_TAB!==target.route)return;
 const node=[...document.querySelectorAll(selector)].find(e=>e.dataset.operationReference===target.reference);
 window.OPERATION_TARGET=null;if(node){node.tabIndex=-1;node.focus({preventScroll:true});node.scrollIntoView({block:'center',behavior:'instant'});}
}
