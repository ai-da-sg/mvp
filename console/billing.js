/* Financial views and versioned adjustments; no card or bank API is called. */
const BILL_TEXT={search:['搜索账单、客户或域名','Search invoice, customer or domain'],view:['账单视图','Invoice view'],all:['全部账单','All invoices'],unpaid:['待收款','Unpaid'],overdue:['逾期未付','Overdue'],renewals:['续费账单','Renewal invoices'],services:['30 天内需续费的服务','Services due within 30 days'],paid:['已付款','Paid'],unset:['未设置付款到期日','No payment due date'],refresh:['刷新','Refresh'],adjust:['调整账单','Adjust invoice'],subtotal:['未税金额 (SGD)','Subtotal (SGD)'],tax:['税额 (SGD)','Tax (SGD)'],due:['付款到期日','Payment due date'],reason:['调整原因','Adjustment reason'],save:['保存调整','Save adjustment'],cancel:['取消','Cancel'],total:['总额','Total'],invoice:['账单号','Invoice'],customer:['客户 / 域名','Customer / domain'],amount:['金额','Amount'],status:['状态','Status'],action:['操作','Actions'],detail:['详情 / 历史','Details / history'],pay:['确认收款','Confirm payment'],retry:['继续处理','Resume processing'],processing:['处理未完成','Processing incomplete'],history:['变更历史','Change history'],none:['暂无变更记录','No changes recorded'],unknown:['未设置','Not set'],saved:['账单调整已保存','Invoice adjustment saved'],paidDone:['收款已记录','Payment recorded'],paidConfirm:['确认已收到此账单的全额款项？','Confirm that the full invoice amount has been received?'],renewYears:['续费几年？（1-5）','Renew for how many years? (1–5)'],renew:['续费','Renew'],renewed:['续费已处理，账单：','Renewal processed. Invoice: '],expires:['服务到期日','Service expiry'],adjustment:['账单调整','Invoice adjustment'],payment:['收款记录','Payment recorded'],renewal:['服务续费','Service renewal'],before:['调整前','Before'],after:['调整后','After'],applied:['续费期限已延长，收款时不会再次延期','Renewal already applied; payment will not extend it again'],pendingRenewal:['收款后延长服务期限','Service term extends after payment']};
const BILL_ERRORS={
 'Invalid amount':['金额必须为有效的非负数','Enter a valid nonnegative amount'],
 'Invalid due date':['请输入有效的付款到期日','Enter a valid payment due date'],
 'Invalid service expiry; review before renewing':['服务到期日无效，请核对后再续费','Invalid service expiry. Review it before renewing'],
 'An adjustment reason is required (maximum 500 characters)':['请填写调整原因，最多 500 字','Enter an adjustment reason (up to 500 characters)'],
 'Paid or processing invoices cannot be adjusted':['已付款或处理中的账单不能调整','Paid or processing invoices cannot be adjusted'],
 'Invoice changed; refresh before saving':['账单已变化，请刷新并核对后重试','Invoice changed. Refresh and review it before retrying'],
 'No invoice changes':['账单内容没有变化','No invoice changes'],
 'Renewal years must be between 1 and 5':['续费年数必须是 1 至 5 的整数','Renewal years must be an integer between 1 and 5'],
 'A renewal invoice already exists for a different period':['已有不同年限的待付续费账单，请先核对','An unpaid renewal invoice already exists for a different period; review it first'],
 'Choose a valid plan before renewing':['请先配置有效套餐再续费','Choose a valid plan before renewing'],
 'Payment is incomplete; retry this invoice to resume safely':['收款处理未完成，请重试此账单继续处理','Payment is incomplete. Retry this invoice to resume safely'],
 'Renewal is incomplete; retry to resume safely':['续费处理未完成，请重试继续处理','Renewal is incomplete. Retry to resume safely'],
 'Service expiry changed during processing; review required':['处理中服务到期日发生变化，需要管理员核对','Service expiry changed during processing; administrator review is required'],
 'Invoice changed during processing; review required':['处理中账单发生变化，需要管理员核对','Invoice changed during processing; administrator review is required'],
 'Invoice not found':['账单不存在','Invoice not found'], 'Invalid invoice':['账单编号无效','Invalid invoice']
};
let BILL_EDIT=null,BILL_SIGNATURE='';
function billText(key){return AdminUI.text(...BILL_TEXT[key]);}
function billMessage(id,value='',bad=false){const pair=typeof value==='string'?(BILL_TEXT[value]||[value,value]):(BILL_ERRORS[value.message]||[value.message,value.message]);AdminUI.message(id,pair,bad);}
function billError(error){return BILL_ERRORS[error.message]?AdminUI.text(...BILL_ERRORS[error.message]):error.message;}
function billTranslate(){document.querySelectorAll('[data-bill-text]').forEach(e=>e.textContent=billText(e.dataset.billText));const old=$('#billView').value;$('#billView').innerHTML=['all','unpaid','overdue','renewals','services','paid','unset'].map(k=>`<option value="${k}">${esc(billText(k))}</option>`).join('');$('#billView').value=old||'all';renderBilling();billTotal();}
function renderBilling(){
 const sites=STATE.sites||[],q=$('#billSearch').value.trim().toLocaleLowerCase(),view=$('#billView').value||'all';
 const all=(STATE.invoices||[]).filter(i=>!sites.find(s=>s.slug===i.slug)?.archived);
 const matching=x=>[x.no,x.company,x.domain,x.plan_name].join(' ').toLocaleLowerCase().includes(q);
 const items=all.filter(i=>matching(i)&&(view==='unpaid'?i.status!=='paid':view==='paid'?i.status==='paid':view==='overdue'?i.overdue:view==='renewals'?i.kind==='renewal':view==='unset'?!i.due_date&&i.status!=='paid':true));
 const renewals=sites.filter(s=>(!s.archived)&&s.days_left!==null&&s.days_left!==undefined&&s.days_left<=30&&matching(s));
 const signature=JSON.stringify([all,items,renewals,view,document.documentElement.lang,ROLE,STATE.can_pay,STATE.can_adjust_invoice,STATE.can_renew]);if(signature===BILL_SIGNATURE)return;BILL_SIGNATURE=signature;
 const unpaid=all.filter(i=>i.status!=='paid'),paid=all.filter(i=>i.status==='paid');
 $('#billStats').innerHTML=[['unpaid',money(unpaid.reduce((a,i)=>a+i.total,0))],['paid',money(paid.reduce((a,i)=>a+i.total,0))],['overdue',unpaid.filter(i=>i.overdue).length]].map(([k,v])=>`<div class="stat"><b>${esc(v)}</b><span>${esc(billText(k))}</span></div>`).join('');
 if(view==='services'){
  AdminUI.table('billList',renewals,['customer','expires','action'].map(billText),s=>`<tr><td data-user-content>${esc(s.company)}<p class="hint">${esc(s.domain)}</p></td><td>${esc(s.expires||'')}</td><td>${STATE.can_renew?`<button type="button" data-bill-renew="${esc(s.slug)}">${esc(billText('renew'))}</button>`:'—'}</td></tr>`);return;
 }
 AdminUI.table('billList',items,['invoice','customer','amount','status','due','action'].map(billText),i=>`<tr><td data-user-content>${esc(i.no)}</td><td data-user-content>${esc(i.company)}<p class="hint">${esc(i.domain||'')}</p></td><td>${money(i.total)}</td><td>${esc(billText(i.processing?'processing':i.status==='paid'?'paid':i.overdue?'overdue':'unpaid'))}</td><td>${esc(i.due_date||billText('unknown'))}</td><td><div class="domain-row-actions"><a href="/api/invoice/${encodeURIComponent(i.no)}/pdf">PDF</a><button class="ghost" type="button" data-bill-view="${esc(i.no)}">${esc(billText('detail'))}</button>${(STATE.can_pay||STATE.can_adjust_invoice)&&i.status!=='paid'?`${STATE.can_pay?`<button type="button" data-bill-pay="${esc(i.no)}">${esc(billText(i.processing?'retry':'pay'))}</button>`:''}${STATE.can_adjust_invoice&&!i.processing?`<button class="ghost" type="button" data-bill-edit="${esc(i.no)}">${esc(billText('adjust'))}</button>`:''}`:''}</div></td></tr>`);
}
function billHistory(item){
 const values=v=>`${billText('subtotal')}: ${money(v.subtotal)} · ${billText('tax')}: ${money(v.gst)} · ${billText('total')}: ${money(v.total)} · ${billText('due')}: ${esc(v.due_date||billText('unknown'))}`;
 AdminUI.detail(item.no,`<p data-user-content>${esc(item.company)} · ${esc(item.plan_name)}</p><p>${billText('total')}: ${money(item.total)}</p>${item.kind==='renewal'?`<p>${esc(billText(item.renewal_applied?'applied':'pendingRenewal'))}</p>`:''}<h4>${esc(billText('history'))}</h4>${(item.history||[]).slice().reverse().map(h=>`<article><p>${esc(billText(h.event))} · <span data-user-content>${esc(h.at)} · ${esc(h.by)}</span></p>${h.reason?`<p data-user-content>${esc(h.reason)}</p>`:''}${h.before?`<p>${billText('before')}: ${values(h.before)}</p><p>${billText('after')}: ${values(h.after)}</p>`:''}</article>`).join('')||`<p>${esc(billText('none'))}</p>`}`);
}
function billTotal(){const value=Number($('#billSubtotal').value)+Number($('#billTax').value);$('#billEditTotal').textContent=billText('total')+': '+(Number.isFinite(value)?money(value):'—');}
const BILL_DIALOG=AdminUI.form('billForm','',()=>{BILL_EDIT=null;$('#billReason').value='';});
$('#billCancel').onclick=()=>BILL_DIALOG.close();$('#billSubtotal').oninput=$('#billTax').oninput=billTotal;
$('#billList').onclick=async e=>{
 const b=e.target.closest('[data-bill-view],[data-bill-edit],[data-bill-pay],[data-bill-renew]');if(!b)return;
 if(b.dataset.billRenew){b.disabled=true;try{await renewSite(b.dataset.billRenew);}finally{b.disabled=false;}return;}
 const no=b.dataset.billView||b.dataset.billEdit||b.dataset.billPay,item=(STATE.invoices||[]).find(i=>i.no===no);if(!item)return;
 if(b.dataset.billView){billHistory(item);return;}
 if(b.dataset.billPay){b.disabled=true;try{await pay(no);}finally{b.disabled=false;}return;}
 BILL_EDIT=item;$('#billEditNo').textContent=no+' · '+item.company;$('#billSubtotal').value=item.subtotal;$('#billTax').value=item.gst;$('#billDue').value=item.due_date||'';$('#billReason').value='';billMessage('#billEditMsg','');billTotal();BILL_DIALOG.open();
};
$('#billForm').onsubmit=async e=>{e.preventDefault();if(!BILL_EDIT)return;$('#billSave').disabled=true;try{await aiRequest('/api/invoice/adjust',{no:BILL_EDIT.no,version:BILL_EDIT.version||0,subtotal:$('#billSubtotal').value,gst:$('#billTax').value,due_date:$('#billDue').value,reason:$('#billReason').value});BILL_DIALOG.close(true);await load();billMessage('#billMsg','saved');}catch(error){billMessage('#billEditMsg',error,true);}finally{$('#billSave').disabled=false;}};
async function pay(no){const item=(STATE.invoices||[]).find(i=>i.no===no);if(!item)return;if(!confirm(billText('paidConfirm')+'\n'+item.company+' · '+money(item.total)))return;try{await aiRequest('/api/invoice/pay',{no,version:item.version||0});await load();billMessage('#billMsg','paidDone');}catch(error){try{await load();}catch(_){}billMessage('#billMsg',error,true);}}
async function renewSite(slug){const value=prompt(billText('renewYears'),'1');if(!value)return;try{const result=await aiRequest('/api/renew',{slug,years:Number(value)});await load();alert(billText('renewed')+result.invoice+'\n'+result.expires);}catch(error){alert(billError(error));}}
$('#billSearch').oninput=$('#billView').onchange=()=>{AdminUI.pages.set('billList',0);renderBilling();};
$('#billRefresh').onclick=async()=>{const b=$('#billRefresh');b.disabled=true;try{await load();billMessage('#billMsg','');}catch(e){billMessage('#billMsg',e,true);}finally{b.disabled=false;}};
new MutationObserver(billTranslate).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});billTranslate();
