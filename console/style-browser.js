/* Template browsing, full-site demos, personal favorites and version history. */
let STYLE_COMPARE=new Set(),STYLE_PREVIEW_ITEM=null,STYLE_PREVIEW_EPOCH=0,STYLE_HISTORY_ID=null;
let STYLE_THUMBS=new Map(),STYLE_THUMB_QUEUE=[],STYLE_THUMB_ACTIVE=0,STYLE_FAVORITE_QUEUE=Promise.resolve();
const STYLE_THUMB_OBSERVER=new IntersectionObserver(entries=>{for(const e of entries)if(e.isIntersecting){STYLE_THUMB_OBSERVER.unobserve(e.target);STYLE_THUMB_QUEUE.push(e.target);stylePumpThumbnails();}},{rootMargin:'250px'});
const STYLE_THUMB_RESIZER=new ResizeObserver(entries=>{for(const e of entries)e.target.style.setProperty('--preview-scale',String(e.contentRect.width/1200));});
function styleBrowserLoad(){
 const select=$('#styleTypeFilter'),previous=select.value;
 select.innerHTML='<option value="">全部用途</option>'+(STYLE_LIBRARY.site_types||[]).map(t=>`<option value="${esc(t.id)}">${esc(t.label)}</option>`).join('');select.value=previous;
 STYLE_LIBRARY.favorites=STYLE_LIBRARY.favorites||[];
 STYLE_COMPARE=new Set([...STYLE_COMPARE].filter(id=>STYLE_LIBRARY.templates.some(t=>t.id===id)));
 $('.style-admin-tools').hidden=!STYLE_LIBRARY.can_manage;
}
function styleTypeLabel(id){return (STYLE_LIBRARY.site_types||[]).find(t=>t.id===id)?.label||id;}
function styleRenderBrowser(){
 const query=$('#styleSearch').value.trim().toLowerCase(),sector=$('#styleSectorFilter').value,type=$('#styleTypeFilter').value,state=$('#styleStatus').value,favorites=new Set(STYLE_LIBRARY.favorites||[]);
 const items=STYLE_LIBRARY.templates.filter(t=>(t.name+' '+t.summary+' '+t.category+' '+styleSectorLabel(t.sector)+' '+((STYLE_LIBRARY.sectors||[]).find(s=>s.id===t.sector)?.label_en||'')+' '+(t.tags||[]).join(' ')).toLowerCase().includes(query)&&(!sector||(t.sector||'general')===sector)&&(!type||(t.site_types||[]).includes(type))&&(!state||(state==='enabled')===t.enabled)&&(!$('#styleFavoritesOnly').checked||favorites.has(t.id)));
 const sort=$('#styleSort').value;
 if(sort==='name')items.sort((a,b)=>a.name.localeCompare(b.name));
 if(sort==='updated')items.sort((a,b)=>(b.updated||0)-(a.updated||0)||b.version-a.version||a.name.localeCompare(b.name));
 $('#styleResultCount').innerHTML=`<b>${items.length}</b> <span>套模板</span>`;
 $('#styleNew').hidden=!STYLE_LIBRARY.can_manage;$('#styleImport').hidden=!STYLE_LIBRARY.can_manage;
 STYLE_THUMB_OBSERVER.disconnect();STYLE_THUMB_RESIZER.disconnect();STYLE_THUMB_QUEUE=[];
 $('#styleLibrary').innerHTML=items.map(t=>`<article class="style-card"><button type="button" class="style-card-preview" data-style-preview="${esc(t.id)}" aria-label="${esc((window.kfText?.('载入预览…')||'载入预览…')+' '+t.name)}"><span class="style-thumb-loading" aria-hidden="true">载入预览…</span></button><div class="style-card-body"><div class="style-card-heading"><h3 data-user-content>${esc(t.name)}</h3><button type="button" class="ghost style-favorite" data-style-favorite="${esc(t.id)}" aria-pressed="${favorites.has(t.id)}" aria-label="${favorites.has(t.id)?'取消收藏':'收藏模板'}">${favorites.has(t.id)?'已收藏':'收藏'}</button></div><p class="hint"><span>${esc(styleSectorLabel(t.sector))}</span>${t.enabled?'':' · <span>已停用</span>'}</p><div class="style-card-actions"><button type="button" data-style-use="${esc(t.id)}" ${t.enabled?'':'disabled'}>使用</button><button type="button" class="ghost" data-style-compare="${esc(t.id)}" aria-pressed="${STYLE_COMPARE.has(t.id)}">${STYLE_COMPARE.has(t.id)?'移出比较':'加入比较'}</button><details class="style-card-menu"><summary aria-label="更多操作">更多</summary><div><button type="button" class="ghost" data-style-preview="${esc(t.id)}">预览</button><button type="button" class="ghost" data-style-export="${esc(t.id)}">导出</button>${STYLE_LIBRARY.can_manage?`<button type="button" class="ghost" data-style-edit="${esc(t.id)}">编辑</button><button type="button" class="ghost" data-style-copy="${esc(t.id)}">复制</button><button type="button" class="ghost" data-style-history="${esc(t.id)}">版本历史</button><button type="button" class="ghost danger" data-style-delete="${esc(t.id)}">删除</button>`:''}</div></details></div></div></article>`).join('')||'<div class="style-empty"><h3>没有匹配的模板</h3><p class="hint">尚无匹配模板。可新建模板或调整筛选条件。</p><button type="button" class="ghost" data-style-reset>清除筛选</button></div>';
 for(const element of document.querySelectorAll('.style-card-preview')){STYLE_THUMB_OBSERVER.observe(element);STYLE_THUMB_RESIZER.observe(element);}
 styleCompareBar();
}
async function stylePumpThumbnails(){
 while(STYLE_THUMB_ACTIVE<2&&STYLE_THUMB_QUEUE.length){
  const el=STYLE_THUMB_QUEUE.shift();if(!el.isConnected)continue;
  const item=STYLE_LIBRARY.templates.find(t=>t.id===el.dataset.stylePreview);if(!item)continue;
  STYLE_THUMB_ACTIVE++;
  (async()=>{try{
   const key=item.id+':'+item.version;let html=STYLE_THUMBS.get(key);
   if(!html){const data=await aiRequest('/api/ai/styles/preview',{...item,thumbnail:true});html=data.html;STYLE_THUMBS.set(key,html);}
   if(!el.isConnected)return;
   const frame=document.createElement('iframe');frame.setAttribute('sandbox','');frame.setAttribute('aria-hidden','true');frame.tabIndex=-1;frame.title='';frame.setAttribute('referrerpolicy','no-referrer');frame.srcdoc=html;el.replaceChildren(frame);el.setAttribute('aria-label',(window.kfText?.('预览')||'预览')+' '+item.name);
  }catch(_){if(el.isConnected){const hint=document.createElement('span');hint.setAttribute('aria-hidden','true');hint.textContent=window.kfText?.('预览暂不可用，点击重试')||'预览暂不可用，点击重试';el.replaceChildren(hint);el.setAttribute('aria-label',hint.textContent+' '+item.name);}}
  finally{STYLE_THUMB_ACTIVE--;stylePumpThumbnails();}})();
 }
}
function styleResetFilters(){for(const id of ['styleSearch','styleSectorFilter','styleTypeFilter','styleStatus'])$('#'+id).value='';$('#styleFavoritesOnly').checked=false;$('#styleSort').value='recommended';styleRender();}
$('#styleResetFilters').onclick=styleResetFilters;
$('#styleLibrary').addEventListener('click',e=>{if(e.target.closest('[data-style-reset]'))styleResetFilters();});
for(const id of ['styleTypeFilter','styleSort','styleFavoritesOnly'])$('#'+id).onchange=styleRender;
$('#styleBuildAI').onclick=()=>navigateTo('ai');
function styleToggleFavorite(id){
 STYLE_FAVORITE_QUEUE=STYLE_FAVORITE_QUEUE.then(async()=>{
  try{const favorite=!(STYLE_LIBRARY.favorites||[]).includes(id);const result=await aiRequest('/api/ai/styles/preferences',{id,favorite});STYLE_LIBRARY.favorites=result.favorites;styleRender();if(STYLE_PREVIEW_ITEM?.id===id)styleDetailFavoriteLabel();}
  catch(e){aiMessage('#styleManageMsg',e.message,true);}
 });return STYLE_FAVORITE_QUEUE;
}
function styleToggleCompare(id){
 if(STYLE_COMPARE.has(id))STYLE_COMPARE.delete(id);else if(STYLE_COMPARE.size<3)STYLE_COMPARE.add(id);else{aiMessage('#styleManageMsg','最多同时比较 3 套模板',true);return;}
 styleRender();if(!$('#styleComparePanel').classList.contains('hidden'))styleCompareRender();
}
function styleCompareBar(){
 $('#styleCompareBar').classList.toggle('hidden',!STYLE_COMPARE.size);$('#styleCompareCount').innerHTML=`<span>已选模板</span> <b>${STYLE_COMPARE.size}/3</b>`;$('#styleCompareOpen').disabled=STYLE_COMPARE.size<2;
 if(!STYLE_COMPARE.size)$('#styleComparePanel').classList.add('hidden');
}
function styleCompareRender(){
 const items=[...STYLE_COMPARE].map(id=>STYLE_LIBRARY.templates.find(t=>t.id===id)).filter(Boolean);
 const rows=[['模板行业',t=>styleSectorLabel(t.sector)],['适合用途',t=>(t.site_types||[]).map(styleTypeLabel).join(' / ')],['包含页面',t=>(t.pages||[]).map(p=>p.title).join(' / ')],['首页结构',t=>(t.blueprint||[]).map(k=>STYLE_BLOCKS[k]||k).join(' / ')],['标题字体',t=>STYLE_OPTION_LABELS[t.tokens.type.heading]||t.tokens.type.heading],['首屏布局',t=>STYLE_OPTION_LABELS[t.tokens.advanced?.hero]||'—'],['内容宽度（px）',t=>String(t.tokens.advanced?.content_width||1120)]];
 $('#styleCompareContent').innerHTML=`<table><thead><tr><th>比较项目</th>${items.map(t=>`<th data-user-content>${esc(t.name)}</th>`).join('')}</tr></thead><tbody>${rows.map(([label,get])=>`<tr><th scope="row">${label}</th>${items.map(t=>`<td${label==='包含页面'?' data-user-content':''}>${esc(get(t))}</td>`).join('')}</tr>`).join('')}<tr><th>操作</th>${items.map(t=>`<td><button type="button" data-compare-use="${esc(t.id)}" ${t.enabled?'':'disabled'}>使用此模板</button><button type="button" class="ghost" data-compare-preview="${esc(t.id)}">预览</button><button type="button" class="ghost" data-compare-remove="${esc(t.id)}">移除</button></td>`).join('')}</tr></tbody></table>`;
}
$('#styleCompareOpen').onclick=()=>{styleCompareRender();$('#styleComparePanel').classList.remove('hidden');$('#styleComparePanel').scrollIntoView({block:'start'});};
$('#styleCompareClose').onclick=()=>$('#styleComparePanel').classList.add('hidden');
$('#styleCompareClear').onclick=()=>{STYLE_COMPARE.clear();styleRender();};
$('#styleCompareContent').onclick=e=>{const b=e.target.closest('button');if(!b)return;const id=b.dataset.compareUse||b.dataset.comparePreview||b.dataset.compareRemove,item=STYLE_LIBRARY.templates.find(t=>t.id===id);if(!item)return;if(b.dataset.compareRemove)styleToggleCompare(id);else if(b.dataset.compareUse)styleUseTemplate(item);else stylePreview(item).catch(err=>aiMessage('#styleManageMsg',err.message,true));};
function styleUseTemplate(item){
 styleClosePreview();if(!navigateTo('ai'))return;
 $('#aiStyleSector').value=item.sector||'general';styleBuilderOptions(item.id);$('#aiStyleTemplate').value=item.id;styleShow(item);aiMessage('#aiStyleMsg','已选择 '+item.name);$('#aiStyleTemplate').scrollIntoView({block:'center'});
}
function styleDetailFavoriteLabel(){const b=$('#styleDetailFavorite');b.textContent=(STYLE_LIBRARY.favorites||[]).includes(STYLE_PREVIEW_ITEM?.id)?'取消收藏':'收藏模板';b.setAttribute('aria-pressed',String((STYLE_LIBRARY.favorites||[]).includes(STYLE_PREVIEW_ITEM?.id)));}
async function styleOpenPreview(item){
 const epoch=++STYLE_PREVIEW_EPOCH;const result=await aiRequest('/api/ai/styles/preview',item);if(epoch!==STYLE_PREVIEW_EPOCH)return;
 STYLE_PREVIEW_ITEM={...item,...result.recipe,tokens:result.tokens};
 $('#styleDetailTitle').textContent=item.name;$('#styleDetailTitle').dataset.userContent='';
 $('#styleDetailSector').textContent=styleSectorLabel(result.recipe.sector);$('#styleDetailSummary').textContent=item.summary||'';
 $('#styleDetailTypes').innerHTML=result.recipe.site_types.map(id=>`<span>${esc(styleTypeLabel(id))}</span>`).join(' / ');
 $('#styleDetailPages').innerHTML=result.recipe.pages.map(p=>`<li data-user-content>${esc(p.title)}</li>`).join('');
 $('#styleDetailSwatches').innerHTML=Object.entries(result.tokens.palette).slice(0,6).map(([k,c])=>`<span style="background:${styleColor(c)}" title="${esc(c)}"></span>`).join('');
 $('#stylePreviewPage').innerHTML=result.recipe.pages.map(p=>`<option data-user-content value="${esc(p.slug)}">${esc(p.title)}</option>`).join('');
 $('#styleDetailUse').disabled=!item.id||item.enabled===false;$('#styleDetailFavorite').hidden=!item.id;$('#styleDetailEdit').hidden=!STYLE_LIBRARY.can_manage||!item.id;
 const source=$('#styleDetailSource');source.hidden=!/^https?:\/\//.test(item.source_url||'');if(!source.hidden)source.href=item.source_url;
 styleDetailFavoriteLabel();$('#stylePreviewFrame').srcdoc=result.html;$('#stylePreviewFrame').style.width=$('#stylePreviewWidth').value;
 $('#stylePreviewPanel').classList.remove('hidden');if(!$('#styleDetailDialog').open)$('#styleDetailDialog').showModal();
}
function styleClosePreview(){STYLE_PREVIEW_EPOCH++;if($('#styleDetailDialog').open)$('#styleDetailDialog').close();$('#stylePreviewPanel').classList.add('hidden');$('#stylePreviewFrame').srcdoc='';}
$('#stylePreviewClose').onclick=styleClosePreview;
$('#styleDetailDialog').addEventListener('close',()=>{STYLE_PREVIEW_EPOCH++;$('#stylePreviewFrame').srcdoc='';});
$('#stylePreviewFull').onclick=()=>$('#styleDetailDialog').classList.toggle('expanded');
$('#stylePreviewPage').onchange=async()=>{try{const epoch=++STYLE_PREVIEW_EPOCH,result=await aiRequest('/api/ai/styles/preview',{...STYLE_PREVIEW_ITEM,preview_page:$('#stylePreviewPage').value});if(epoch===STYLE_PREVIEW_EPOCH)$('#stylePreviewFrame').srcdoc=result.html;}catch(e){aiMessage('#styleManageMsg',e.message,true);}};
$('#styleDetailUse').onclick=()=>styleUseTemplate(STYLE_PREVIEW_ITEM);
$('#styleDetailFavorite').onclick=()=>styleToggleFavorite(STYLE_PREVIEW_ITEM.id);
$('#styleDetailEdit').onclick=()=>{const item=STYLE_PREVIEW_ITEM;styleClosePreview();styleEdit(item);};
async function styleHistory(id){
 try{const data=await aiRequest('/api/ai/styles/history/'+encodeURIComponent(id));STYLE_HISTORY_ID=id;
 const current=STYLE_LIBRARY.templates.find(t=>t.id===id);$('#styleHistoryList').innerHTML=data.versions.slice().reverse().map(v=>`<article class="share-row"><span data-user-content>${esc(v.name)} · v${v.version}</span><span>${v.version===current.version?'当前版本':''}</span><button type="button" class="ghost" data-style-restore="${v.version}" ${v.version===current.version?'disabled':''}>恢复此版本</button></article>`).join('');$('#styleHistoryPanel').classList.remove('hidden');$('#styleHistoryPanel').scrollIntoView({block:'start'});
 }catch(e){aiMessage('#styleManageMsg',e.message,true);}
}
$('#styleHistoryClose').onclick=()=>$('#styleHistoryPanel').classList.add('hidden');
$('#styleHistoryList').onclick=async e=>{const b=e.target.closest('[data-style-restore]');if(!b||!confirm('恢复为新版本？已生成的网站保持不变。'))return;if(!styleCanLeave())return;b.disabled=true;try{const current=STYLE_LIBRARY.templates.find(t=>t.id===STYLE_HISTORY_ID);await aiRequest('/api/ai/styles',{action:'restore',id:current.id,version:current.version,restore_version:Number(b.dataset.styleRestore)});$('#styleEditForm').classList.add('hidden');STYLE_EDIT=null;await styleLoad();await styleHistory(current.id);aiMessage('#styleManageMsg','模板版本已恢复');}catch(err){aiMessage('#styleManageMsg',err.message,true);}finally{b.disabled=false;}};
function styleEditPages(item){
 const kinds=item.site_types||['business'];$('#styleTypeOptions').innerHTML=(STYLE_LIBRARY.site_types||[]).map(t=>`<label><input type="checkbox" value="${esc(t.id)}" ${kinds.includes(t.id)?'checked':''}>${esc(t.label)}</label>`).join('');
 STYLE_EDIT.pages=JSON.parse(JSON.stringify(item.pages||[{slug:'home',title:'Home',blueprint:item.blueprint||['hero','cards','cta']},{slug:'about',title:'About',blueprint:['hero','split','cta']},{slug:'contact',title:'Contact',blueprint:['hero','form']} ]));styleRenderPages();
}
function styleReadPages(){
 return [...document.querySelectorAll('.style-page-row')].map((row,i)=>({slug:row.querySelector('[data-page-field="slug"]').value.trim(),title:row.querySelector('[data-page-field="title"]').value.trim(),blueprint:i===0?[...(STYLE_EDIT.blueprint||[])]:row.querySelector('[data-page-field="blueprint"]').value.split(',').map(s=>s.trim()).filter(Boolean)}));
}
function styleRenderPages(){
 $('#stylePageRows').innerHTML=STYLE_EDIT.pages.map((p,i)=>`<div class="style-page-row"><div class="field"><label for="stylePageSlug-${i}">页面标识</label><input id="stylePageSlug-${i}" data-page-field="slug" value="${esc(p.slug)}" maxlength="20" ${i===0?'readonly':''}></div><div class="field"><label for="stylePageTitle-${i}">页面名称</label><input id="stylePageTitle-${i}" data-page-field="title" value="${esc(p.title)}" maxlength="80"></div><div class="field"><label for="stylePageBlocks-${i}">区块顺序（逗号分隔）</label><input id="stylePageBlocks-${i}" data-page-field="blueprint" value="${esc((p.blueprint||[]).join(', '))}" ${i===0?'disabled':''}></div>${i?`<button type="button" class="ghost" data-page-remove="${i}">移除</button>`:''}</div>`).join('');
}
$('#stylePageAdd').onclick=()=>{const pages=styleReadPages();if(pages.length>=8){aiMessage('#styleManageMsg','最多添加 8 个页面',true);return;}let i=pages.length;while(pages.some(p=>p.slug==='page-'+i))i++;pages.push({slug:'page-'+i,title:'New page',blueprint:['hero','split','cta']});STYLE_EDIT.pages=pages;STYLE_DIRTY=true;styleRenderPages();};
$('#stylePageRows').onclick=e=>{const b=e.target.closest('[data-page-remove]');if(!b)return;STYLE_EDIT.pages=styleReadPages();STYLE_EDIT.pages.splice(Number(b.dataset.pageRemove),1);STYLE_DIRTY=true;styleRenderPages();};
