/* Shared administration controls. Never persist form values or credentials. */
const ADMIN_TEXT={defaultOrder:['默认顺序','Default order'],ascending:['升序','Ascending'],descending:['降序','Descending'],pageSize:['每页条数','Rows per page'],sort:['排序','Sort'],close:['关闭','Close'],previous:['上一页','Previous'],next:['下一页','Next'],empty:['没有匹配记录','No matching records'],loading:['读取中…','Loading…'],discard:['有未保存的修改，放弃修改？','Discard unsaved changes?']};
const AdminUI={
 thumbnail(src,alt='',large=false){return `<span class="asset-preview ${large?'asset-preview-large':''}"><img src="${esc(src)}" alt="${esc(alt)}" width="${large?640:96}" height="${large?360:64}" loading="lazy" decoding="async"><span hidden>${esc(this.text('预览不可用','Preview unavailable'))}</span></span>`;},
 str(key){return this.text(...ADMIN_TEXT[key]);},
 translate(){document.querySelectorAll('[data-admin-text]').forEach(node=>node.textContent=this.str(node.dataset.adminText));},
 text(zh,en){return document.documentElement.lang.startsWith('en')?en:zh;},
 messages:new Map(),
 message(id,pair,bad=false){this.messages.set(id,{pair,bad});aiMessage(id,this.text(...pair),bad,true);},
 pages:new Map(),
 schemas:new Map(),sizes:new Map(),sorts:new Map(),sorters:new Map(),
 ordered(id,items){const sort=this.sorts.get(id),value=this.sorters.get(id)?.[sort?.column];if(!value)return items;const compare=new Intl.Collator(document.documentElement.lang,{numeric:true,sensitivity:'base'});return [...items].sort((a,b)=>{const x=value(a),y=value(b);if(x==null||x==='')return y==null||y===''?0:1;if(y==null||y==='')return -1;return (typeof x==='number'&&typeof y==='number'?x-y:compare.compare(String(x),String(y)))*sort.direction;});},
 reveal(id,items,predicate){this.pages.set(id,Math.max(0,Math.floor(this.ordered(id,items).findIndex(predicate)/(this.sizes.get(id)||20))));},
 forms:[],
 async load(list,button,message,action){
  const node=$(list),refresh=$(button);node.setAttribute('aria-busy','true');refresh.disabled=true;this.message(message,ADMIN_TEXT.loading);
  try{await action();aiMessage(message,'');}catch(e){aiMessage(message,e.message,true);throw e;}finally{node.removeAttribute('aria-busy');refresh.disabled=false;}
 },
 canLeave(){for(const item of this.forms){if(item.dialog.open&&!item.close())return false;}document.getElementById('adminDetailDialog')?.close();return true;},
 table(id,items,columns,row){
  if(this.schemas.has(id)&&this.schemas.get(id)!==columns.length){this.sorts.delete(id);this.pages.set(id,0);}this.schemas.set(id,columns.length);
  const node=document.getElementById(id),size=this.sizes.get(id)||20,sort=this.sorts.get(id),sorters=this.sorters.get(id)||[];
  const ordered=this.ordered(id,items),page=Math.max(0,Math.min(this.pages.get(id)||0,Math.ceil(items.length/size)-1));this.pages.set(id,page);
  node.innerHTML=`${sorters.some(Boolean)?`<div class="table-mobile-sort"><label for="${id}Sort" data-admin-text="sort">${this.str('sort')}</label><select id="${id}Sort" data-admin-mobile-sort><option value="" data-admin-text="defaultOrder">${this.str('defaultOrder')}</option>${columns.map((c,i)=>sorters[i]?`<option value="${i}" ${sort?.column===i?'selected':''}>${c}</option>`:'').join('')}</select><button type="button" class="ghost" data-admin-direction data-admin-text="${sort?.direction===-1?'descending':'ascending'}" ${sort?'':'disabled'}>${this.str(sort?.direction===-1?'descending':'ascending')}</button></div>`:''}<div class="table-wrap"><table class="domain-table"><thead><tr>${columns.map((c,i)=>`<th scope="col" ${sorters[i]?`aria-sort="${sort?.column===i?(sort.direction===1?'ascending':'descending'):'none'}"`:''}>${sorters[i]?`<button type="button" class="ghost table-sort" data-admin-sort="${i}">${c}<span aria-hidden="true"> ${sort?.column===i?(sort.direction===1?'↑':'↓'):'↕'}</span></button>`:c}</th>`).join('')}</tr></thead><tbody>${ordered.slice(page*size,(page+1)*size).map(row).join('')||`<tr><td colspan="${columns.length}">${this.str('empty')}</td></tr>`}</tbody></table></div><div class="domain-pagination"><label for="${id}PageSize" data-admin-text="pageSize">${this.str('pageSize')}</label><select id="${id}PageSize" data-admin-size>${[10,20,50,100].map(n=>`<option value="${n}" ${n===size?'selected':''}>${n}</option>`).join('')}</select><span role="status">${items.length? page*size+1:0}–${Math.min((page+1)*size,items.length)} / ${items.length} · ${page+1} / ${Math.max(1,Math.ceil(items.length/size))}</span><button type="button" class="ghost" data-admin-text="previous" data-admin-page="-1" ${page?'':'disabled'}>${this.str('previous')}</button><button type="button" class="ghost" data-admin-text="next" data-admin-page="1" ${(page+1)*size>=items.length?'disabled':''}>${this.str('next')}</button></div>`;
  node.querySelectorAll('tbody button').forEach(button=>button.classList.add('ghost'));
  const rerender=selector=>{this.table(id,items,columns,row);const target=node.querySelector(selector);(target&&!target.disabled?target:node.querySelector('[data-admin-page]:not([disabled]),[data-admin-size]'))?.focus();};
  node.querySelectorAll('[data-admin-page]').forEach(b=>b.onclick=()=>{this.pages.set(id,page+Number(b.dataset.adminPage));rerender('[data-admin-page="'+b.dataset.adminPage+'"]');});
  node.querySelectorAll('[data-admin-sort]').forEach(b=>b.onclick=()=>{const column=Number(b.dataset.adminSort);this.sorts.set(id,{column,direction:sort?.column===column?-sort.direction:1});this.pages.set(id,0);rerender('[data-admin-sort="'+column+'"]');});
  const mobile=node.querySelector('[data-admin-mobile-sort]');if(mobile){mobile.onchange=()=>{if(mobile.value==='')this.sorts.delete(id);else this.sorts.set(id,{column:Number(mobile.value),direction:sort?.direction||1});this.pages.set(id,0);rerender('[data-admin-mobile-sort]');};node.querySelector('[data-admin-direction]').onclick=()=>{if(!sort)return;this.sorts.set(id,{...sort,direction:-sort.direction});this.pages.set(id,0);rerender('[data-admin-direction]');};}
  node.querySelector('[data-admin-size]').onchange=e=>{const next=Number(e.target.value);this.sizes.set(id,next);this.pages.set(id,Math.floor(page*size/next));rerender('[data-admin-size]');};
 },
 form(id,title,onClose){
  const form=document.getElementById(id),dialog=document.createElement('dialog');
  dialog.className='domain-dialog';dialog.id=id+'Dialog';
  const heading=form.querySelector('h3');heading.id=heading.id||id+'Title';dialog.setAttribute('aria-labelledby',heading.id);
  form.before(dialog);dialog.append(form);
  const header=document.createElement('div');header.className='domain-dialog-heading admin-modal-heading';heading.before(header);header.append(heading);
  const dismiss=document.createElement('button');dismiss.type='button';dismiss.className='ghost';dismiss.dataset.adminText='close';dismiss.textContent=this.str('close');header.append(dismiss);
  let dirty=false,opener=null;
  const close=(force=false)=>{
   if(!force&&form.querySelector('[type="submit"]:disabled'))return false;
   if(!force&&dirty&&!confirm(this.str('discard')))return false;
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
  dialog.setAttribute('aria-labelledby','adminDetailTitle');dialog.innerHTML=`<div class="domain-dialog-heading"><h3 id="adminDetailTitle" data-user-content>${esc(title)}</h3><button type="button" data-admin-text="close">${this.str('close')}</button></div>${html}`;
  dialog.querySelector('button').onclick=()=>dialog.close();dialog.showModal();
 }
};
new MutationObserver(()=>{AdminUI.translate();for(const [id,{pair,bad}] of AdminUI.messages)aiMessage(id,AdminUI.text(...pair),bad,true);}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});

/* Share a site selection between operational pages, without changing access scopes. */
const SiteContext={
 key(){return 'kf-site-context:'+String(STATE.me||'');},
 read(){try{const value=JSON.parse(sessionStorage.getItem(this.key())||'{}');return {slug:value.slug};}catch(_){return {};}},
 save(value,sync=true){try{sessionStorage.setItem(this.key(),JSON.stringify({slug:value.slug??this.read().slug}));}catch(_){}if(sync&&typeof Workspace!=='undefined')Workspace.sync();},
 fill(sel,preferred){
  if(!sel.dataset.siteContext){
   sel.dataset.siteContext='1';
   sel.addEventListener('change',e=>{if(!Workspace.canSelect(sel.value)){sel.value=this.read().slug||'';e.stopImmediatePropagation();return;}this.save({slug:sel.value});},true);
  }
  let context=this.read();
  if(preferred){const site=(STATE.sites||[]).find(s=>s.slug===preferred);if(site){this.save({slug:preferred});context=this.read();}}
  const sites=(STATE.sites||[]).filter(s=>!s.archived);
  const selected=preferred||context.slug||sel.value;
  sel.innerHTML=sites.map(s=>`<option value="${esc(s.slug)}" data-user-content>${esc(s.company+' / '+s.slug)}${s.archived?' ('+AdminUI.text('已归档','Archived')+')':''}</option>`).join('')||`<option value="">${AdminUI.text('没有可选站点','No available sites')}</option>`;
  if(sites.some(s=>s.slug===selected))sel.value=selected;
  this.save({slug:sel.value});return sel.value;
 }
};

document.addEventListener('error',e=>{const img=e.target;if(img.tagName==='IMG'&&img.parentElement?.classList.contains('asset-preview')){img.hidden=true;img.nextElementSibling.hidden=false;}},true);

/* Account pages keep their broad scope; site tools share an explicit, linkable workspace. */
const Workspace={
 pages:new Set(['automation','ai','layout','design','media','share','dns']),
 parse(){const [key,query='']=location.hash.slice(1).split('?');return {key,site:new URLSearchParams(query).get('site')};},
 isSite(key){return this.pages.has(key)&&(key!=='ai'||$('#aiMode').value!=='new');},
 route(key){const slug=SiteContext.read().slug;return '#'+key+(this.isSite(key)&&slug?'?site='+encodeURIComponent(slug):'');},
 canSelect(slug){
  if(!(STATE.sites||[]).some(s=>s.slug===slug&&!s.archived)){showGlobalError(AdminUI.text('站点不可用或已归档，请从站点总览选择。','Site unavailable or archived. Select an active site from the overview.'));return false;}
  if(slug!==SiteContext.read().slug&&(EDITOR_BUSY||LOCAL_DIRTY.size||JSON_DIRTY)){showGlobalError(AdminUI.text('页面编辑有未保存内容，请先保存后再切换站点。','Save your page edits before switching sites.'));return false;}
  return true;
 },
 sync(){if(!NAV_READY)return;this.render();if(this.pages.has(CURRENT_TAB))history.replaceState(null,'',this.route(CURRENT_TAB));},
 render(){
  const root=$('#siteWorkspace'),select=$('#workspaceSite');root.hidden=CURRENT_TAB==='ai'||!this.isSite(CURRENT_TAB);
  for(const id of ['autoSite','lSlug','dSlug','mSlug','sSlug','dnSlug'])document.getElementById(id).closest('.field').hidden=true;
  const sites=(STATE.sites||[]).filter(s=>!s.archived);const slug=SiteContext.read().slug||'';
  select.innerHTML=sites.map(s=>`<option value="${esc(s.slug)}" data-user-content>${esc(s.company+' / '+s.slug)}</option>`).join('')||`<option value="">${AdminUI.text('没有可选站点','No available sites')}</option>`;select.value=slug;select.disabled=!sites.length;
  const tab=document.querySelector('.tab.on');if(tab){const group=tab.closest('details').querySelector('summary').textContent;const site=sites.find(s=>s.slug===slug);const scope=this.isSite(CURRENT_TAB)&&site?`<span>${AdminUI.text('站点','Site')}</span> / <span data-user-content>${esc(site.company||site.slug)}</span>`:esc(AdminUI.text(CURRENT_TAB==='account'?'个人设置':'账户',CURRENT_TAB==='account'?'Personal settings':'Account'));$('#breadcrumb').innerHTML=scope+' / '+(CURRENT_TAB==='account'?'':esc(group)+' / ')+esc(tab.textContent);}

 },
 search(){
  const query=$('#featureSearch').value.trim().toLocaleLowerCase(),box=$('#featureResults');box.hidden=!query;if(!query){box.replaceChildren();return;}
  const tabs=[...document.querySelectorAll('.tab')].filter(t=>t.style.display!=='none'&&[t.dataset.t,t.dataset.label,t.textContent,...(Object.entries(window.KF_MESSAGES||{}).find(pair=>pair.includes(t.dataset.label))||[])].some(v=>String(v||'').toLocaleLowerCase().includes(query)));
  box.innerHTML=tabs.map(t=>`<button type="button" class="ghost" data-feature="${esc(t.dataset.t)}">${esc(t.textContent)}</button>`).join('')||`<p role="status">${AdminUI.text('没有匹配功能','No matching features')}</p>`;
  box.querySelectorAll('button').forEach(b=>b.onclick=()=>{if(navigateTo(b.dataset.feature)){$('#featureSearch').value='';this.search();}});
 }
};
$('#workspaceSite').onchange=()=>{const old=SiteContext.read().slug;if(!navigateTo(CURRENT_TAB,true,$('#workspaceSite').value))$('#workspaceSite').value=old||'';};
$('#workspaceOverview').onclick=()=>navigateTo('sites');
$('#featureSearch').oninput=()=>Workspace.search();
$('#featureSearch').onkeydown=e=>{if(e.key==='ArrowDown'){e.preventDefault();$('#featureResults button')?.focus();}else if(e.key==='Escape'){$('#featureSearch').value='';Workspace.search();}else if(e.key==='Enter'){e.preventDefault();$('#featureResults button')?.click();}};
$('#featureResults').onkeydown=e=>{const buttons=[...$('#featureResults').querySelectorAll('button')],index=buttons.indexOf(document.activeElement);if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();buttons[(index+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();}if(e.key==='Escape'){$('#featureSearch').value='';Workspace.search();$('#featureSearch').focus();}};
new MutationObserver(()=>{Workspace.render();Workspace.search();}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
