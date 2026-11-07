/* Publication history contains summaries only; snapshots stay on the server. */
const PUBLICATION_LABELS={publishing:'发布中',published:'全部发布成功',partial:'部分发布',failed:'发布失败',interrupted:'中断待核实',restoring:'恢复中',restored:'已恢复',restore_failed:'恢复未完成'};
let PUBLICATIONS=[];
function publicationLabel(item){return item.operation==='delete_page'&&item.state==='published'?AdminUI.text('页面已删除','Page deleted'):(PUBLICATION_LABELS[item.state]||esc(item.state));}
async function loadPublications(){
 const slug=$('#lSlug').value;if(!slug){PUBLICATIONS=[];$('#publicationList').innerHTML='';return;}
 const data=await aiRequest('/api/publications/'+encodeURIComponent(slug));
 if(slug!==$('#lSlug').value)return;
 PUBLICATIONS=data.items||[];
 AdminUI.table('publicationList',PUBLICATIONS,['发布时间','操作账号','结果','操作'],item=>`<tr data-operation-reference="${esc(item.id)}"><td><time data-user-content>${esc(new Date(item.created*1000).toLocaleString())}</time></td><td data-user-content>${esc(item.user)}</td><td>${publicationLabel(item)}</td><td><div class="domain-row-actions"><button type="button" class="ghost" data-publication-view="${esc(item.id)}">查看</button>${item.can_restore?`<button type="button" class="ghost" data-publication-restore="${esc(item.id)}">恢复发布前内容</button>`:''}</div></td></tr>`);
 focusOperationTarget('publication','#publicationList [data-operation-reference]');
}
$('#publicationRefresh').onclick=()=>loadPublications().catch(e=>aiMessage('#publicationMsg',e.message,true));
$('#publicationList').onclick=async e=>{
 const b=e.target.closest('[data-publication-view],[data-publication-restore]');if(!b)return;
 const item=PUBLICATIONS.find(x=>x.id===(b.dataset.publicationView||b.dataset.publicationRestore));if(!item)return;
 if(b.dataset.publicationView){
  AdminUI.detail(item.id,`<p>${publicationLabel(item)}</p><ul>${item.results.map(r=>`<li><span data-user-content>${esc(r.stage)}</span> · <span>${r.ok?'成功':'失败'}</span>${r.error?`<p>${esc(r.error)}</p>`:''}</li>`).join('')}</ul>${item.error?`<p class="msg bad">${esc(item.error)}</p>`:''}<p class="hint">${item.operation==='delete_page'?AdminUI.text('恢复会同时还原删除前的页面、导航与草稿。','Recovery restores the page, navigation and draft before deletion.'):'恢复仅涉及本次发布的页面、设计和导航，草稿保留。'}</p>`);return;
 }
 if(EDITOR_BUSY||!confirm(item.operation==='delete_page'?AdminUI.text('恢复删除前的页面、导航和草稿？','Restore the page, navigation and draft before deletion?'):'恢复到本次发布前的页面、设计和导航？本次新建的页面将移除，草稿保留。'))return;
 const restored=await editorAction(async()=>{
  await saveDrafts();
  const result=await aiRequest('/api/publish/restore',{slug:$('#lSlug').value,id:item.id,version:item.version,confirmed:true});
  const refreshed=await aiRequest('/api/spec/'+encodeURIComponent($('#lSlug').value));PAGE_LIVE=refreshed.live?.pages||[];
  LSPEC.dirty=result.dirty;paintDirty();await loadPublications().catch(e=>aiMessage('#publicationMsg',e.message,true));
  $('#lMsg').className='msg ok';$('#lMsg').textContent='已恢复发布前内容，草稿保留。';
  aiMessage('#pageMsg',item.operation==='delete_page'?AdminUI.text('页面及删除前的草稿已恢复。','Page and its draft before deletion restored.') : AdminUI.text('发布前内容已恢复，草稿保留。','Previous publication restored; draft retained.'));
 });
 if(restored&&item.operation==='delete_page')await loadSpec($('#lSlug').value,true);
};
