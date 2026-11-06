/* Shared administration controls. Never persist form values or credentials. */
const AdminUI={
 text(zh,en){return document.documentElement.lang.startsWith('en')?en:zh;},
 messages:new Map(),
 message(id,pair,bad=false){this.messages.set(id,{pair,bad});aiMessage(id,this.text(...pair),bad,true);},
 pages:new Map(),
 forms:[],
 async load(list,button,message,action){
  const node=$(list),refresh=$(button);node.setAttribute('aria-busy','true');refresh.disabled=true;aiMessage(message,this.text('读取中…','Loading…'));
  try{await action();aiMessage(message,'');}catch(e){aiMessage(message,e.message,true);throw e;}finally{node.removeAttribute('aria-busy');refresh.disabled=false;}
 },
 canLeave(){for(const item of this.forms){if(item.dialog.open&&!item.close())return false;}document.getElementById('adminDetailDialog')?.close();return true;},
 table(id,items,columns,row){
  const node=document.getElementById(id),size=20;
  const page=Math.max(0,Math.min(this.pages.get(id)||0,Math.ceil(items.length/size)-1));this.pages.set(id,page);
  node.innerHTML=`<div class="table-wrap"><table class="domain-table"><thead><tr>${columns.map(c=>`<th scope="col">${c}</th>`).join('')}</tr></thead><tbody>${items.slice(page*size,(page+1)*size).map(row).join('')||`<tr><td colspan="${columns.length}">${this.text('没有匹配记录','No matching records')}</td></tr>`}</tbody></table></div><div class="domain-pagination"><span role="status">${items.length} · ${page+1} / ${Math.max(1,Math.ceil(items.length/size))}</span><button type="button" data-admin-page="-1" ${page?'':'disabled'}>${this.text('上一页','Previous')}</button><button type="button" data-admin-page="1" ${(page+1)*size>=items.length?'disabled':''}>${this.text('下一页','Next')}</button></div>`;
  node.querySelectorAll('[data-admin-page]').forEach(b=>b.onclick=()=>{this.pages.set(id,page+Number(b.dataset.adminPage));this.table(id,items,columns,row);});
 },
 form(id,title,onClose){
  const form=document.getElementById(id),dialog=document.createElement('dialog');
  dialog.className='domain-dialog';dialog.id=id+'Dialog';
  const heading=form.querySelector('h3');heading.id=heading.id||id+'Title';dialog.setAttribute('aria-labelledby',heading.id);
  form.before(dialog);dialog.append(form);
  const header=document.createElement('div');header.className='domain-dialog-heading admin-modal-heading';heading.before(header);header.append(heading);
  const dismiss=document.createElement('button');dismiss.type='button';dismiss.className='ghost';dismiss.textContent='关闭';header.append(dismiss);
  let dirty=false,opener=null;
  const close=(force=false)=>{
   if(!force&&form.querySelector('[type="submit"]:disabled'))return false;
   if(!force&&dirty&&!confirm(this.text('有未保存的修改，放弃修改？','Discard unsaved changes?')))return false;
   dirty=false;dialog.close();form.classList.add('hidden');onClose();opener?.focus();return true;
  };
  form.addEventListener('input',()=>dirty=true);form.addEventListener('change',()=>dirty=true);
  dismiss.onclick=()=>close();
  dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  this.forms.push({dialog,close});
  window.addEventListener('beforeunload',e=>{if(dialog.open&&dirty){e.preventDefault();e.returnValue='';}});
  return {open(){opener=document.activeElement;dirty=false;form.classList.remove('hidden');dialog.showModal();form.querySelector('input:not([readonly]):not([disabled])')?.focus();},close,dirty(){dirty=true;}};
 },
 detail(title,html){
  let dialog=document.getElementById('adminDetailDialog');if(!dialog){dialog=document.createElement('dialog');dialog.id='adminDetailDialog';dialog.className='domain-dialog';document.body.append(dialog);}
  dialog.setAttribute('aria-labelledby','adminDetailTitle');dialog.innerHTML=`<div class="domain-dialog-heading"><h3 id="adminDetailTitle" data-user-content>${esc(title)}</h3><button type="button">${this.text('关闭','Close')}</button></div>${html}`;
  dialog.querySelector('button').onclick=()=>dialog.close();dialog.showModal();
 }
};
new MutationObserver(()=>{for(const [id,{pair,bad}] of AdminUI.messages)aiMessage(id,AdminUI.text(...pair),bad,true);}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});

/* Share a site selection between operational pages, without changing access scopes. */
const SiteContext={
 key(){return 'kf-site-context:'+String(STATE.me||'');},
 read(){try{return JSON.parse(sessionStorage.getItem(this.key())||'{}');}catch(_){return {};}},
 save(value){try{sessionStorage.setItem(this.key(),JSON.stringify({...this.read(),...value}));}catch(_){}},
 fill(sel,preferred){
  if(!sel.dataset.siteContext){
   sel.dataset.siteContext='1';
   const label=document.createElement('label');label.className='site-archive-toggle';
   label.innerHTML='<input type="checkbox"> <span>包含归档站点</span>';sel.after(label);
   const checkbox=label.querySelector('input');sel._archiveToggle=checkbox;
   checkbox.onchange=()=>{this.save({archived:checkbox.checked});this.fill(sel);sel.dispatchEvent(new Event('change',{bubbles:true}));};
   sel.addEventListener('change',()=>this.save({slug:sel.value}),true);
  }
  let context=this.read();
  if(preferred){const site=(STATE.sites||[]).find(s=>s.slug===preferred);if(site){this.save({slug:preferred,archived:context.archived||!!site.archived});context=this.read();}}
  sel._archiveToggle.checked=!!context.archived;
  const sites=(STATE.sites||[]).filter(s=>context.archived||!s.archived);
  const selected=preferred||context.slug||sel.value;
  sel.innerHTML=sites.map(s=>`<option value="${esc(s.slug)}" data-user-content>${esc(s.company+' / '+s.slug)}${s.archived?' ('+AdminUI.text('已归档','Archived')+')':''}</option>`).join('')||`<option value="">${AdminUI.text('没有可选站点','No available sites')}</option>`;
  if(sites.some(s=>s.slug===selected))sel.value=selected;
  this.save({slug:sel.value});return sel.value;
 }
};
