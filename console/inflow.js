/* GEOInflow stays a secondary site tool; MVP owns the session and site context. */
const INFLOW={data:null,report:null,resource:'human/sources',days:30,tablePage:1,epoch:0,busy:false};
const inflowText=(zh,en)=>AdminUI.text(zh,en);
const inflowAPI=(action,body)=>aiRequest('/api/inflow/'+action,body);
const inflowButton=(action,zh,en)=>`<button type="button" class="ghost" data-inflow-action="${action}">${inflowText(zh,en)}</button>`;
function inflowCanLeave(){if(INFLOW.busy){showGlobalError(inflowText('正在处理分析配置，请稍候。','Processing analytics settings. Please wait.'));return false;}return true;}
async function initInflow(){
 const selector=document.createElement('select');const slug=SiteContext.fill(selector),epoch=++INFLOW.epoch;
 $('#inflowRoot').innerHTML=`<p role="status">${inflowText('读取中…','Loading…')}</p>`;
 if(!slug){$('#inflowRoot').innerHTML=`<p>${inflowText('请先创建或恢复站点。','Create or restore a site first.')}</p>`;return;}
 try{const data=await inflowAPI('workspace?slug='+encodeURIComponent(slug));if(epoch!==INFLOW.epoch)return;
 if(INFLOW.data?.site.slug!==data.site.slug)INFLOW.tablePage=1;INFLOW.data=data;INFLOW.report=null;inflowRender();Workspace.render();if(data.binding?.status==='ready')await inflowLoadReport();
 }catch(e){if(epoch===INFLOW.epoch)$('#inflowRoot').innerHTML=`<p role="alert">${esc(e.message)}</p>${inflowButton('reload','重试','Retry')}`;}
}
function inflowRender(){
 const d=INFLOW.data;if(!d)return;const ready=d.binding?.status==='ready';
 const resources=[['human/sources','AI 引荐','AI referrals'],['human/overview','访问趋势','Visitors'],['ai/bots','爬虫访问','Crawler activity'],['ai/pages','内容覆盖','Content coverage'],['conversions','转化','Conversions']];
 $('#inflowRoot').innerHTML=`<div class="domain-form-actions">${inflowButton('reload','刷新','Refresh')}${inflowButton('geo','GEO 优化','GEO improvements')}${ROLE==='admin'?inflowButton('settings','连接设置','Connection settings'):''}</div>
 <p class="hint">${inflowText('建站后查看真实访问、AI 引荐与抓取证据。','Review real visits, AI referrals and crawl evidence after building your site.')} <span>Powered by GEOInflow</span></p>
 ${!d.connection.enabled?`<div class="callout">${inflowText('尚未连接分析服务。管理员可在连接设置中完成配置。','Analytics is not connected. An administrator can configure the connection.')}</div>`:''}
 <details id="inflowSetup" ${ready?'':'open'}><summary>${inflowText('数据接入','Data connection')}</summary><p>${inflowText(ready?'站点已绑定':'站点尚未绑定',ready?'Site connected':'Site not connected')}${ready?' · '+inflowText(d.binding.tracking?'追踪已启用':'追踪未启用',d.binding.tracking?'Tracking enabled':'Tracking disabled'):''}</p>
 ${ROLE==='admin'&&d.connection.verified?`<div class="domain-form-actions">${ready?inflowButton('tracking',d.binding.tracking?'停用追踪':'安装追踪',d.binding.tracking?'Disable tracking':'Install tracking')+inflowButton('catalog','导入内容目录','Import content inventory')+inflowButton('logs','导入访问日志','Import access logs')+inflowButton('disconnect','解除绑定','Disconnect'):inflowButton('bind','连接此站点','Connect this site')+(d.binding?.tracking?inflowButton('tracking','停用追踪','Disable tracking'):'')+(d.binding?inflowButton('disconnect','解除绑定','Disconnect'):'')}</div>`:''}
 ${ready?`<p class="hint">${inflowText('浏览器追踪、服务器日志和内容目录独立接入；缺少数据不会显示为零。','Browser tracking, server logs and content inventories are independent inputs; missing data is not zero.')}</p>`:''}</details>
 ${ready?`<div class="formrow">${geoSelect('inflowResource','报告','Report',resources.map(([v,z,e])=>[v,inflowText(z,e)]),INFLOW.resource)}${geoSelect('inflowDays','时间范围','Date range',[[7,inflowText('近 7 天','Last 7 days')],[30,inflowText('近 30 天','Last 30 days')],[90,inflowText('近 90 天','Last 90 days')]].map(([v,l])=>[String(v),l]),String(INFLOW.days))}</div><p class="hint">Asia/Singapore · ${inflowText('爬虫访问、AI 回答引用与真实转化分别统计。','Crawl activity, answer citations and conversions are measured separately.')}</p><div id="inflowReport"></div>`:''}<p id="inflowMsg" role="status"></p>`;
 for(const id of ['inflowResource','inflowDays'])document.getElementById(id)?.addEventListener('change',()=>{INFLOW.resource=$('#inflowResource').value;INFLOW.days=Number($('#inflowDays').value);INFLOW.tablePage=1;inflowLoadReport();});
 if(ready&&INFLOW.report)inflowRenderReport();
}
const INFLOW_LABELS={
 '访客数 UV':'Visitors','浏览量 PV':'Pageviews','跳出率':'Bounce rate','平均访问时长':'Average duration','新访客占比':'New visitor share',
 '直接访问':'Direct visits','传统搜索':'Search engines','AI 搜索引荐':'AI search referrals','AI 引荐转化率':'AI referral conversion rate',
 '被 AI 抓取页面':'Pages requested by AI','反复抓取页面':'Repeatedly requested pages','从未被抓页面':'Pages without observed crawls','平均抓取深度':'Average crawl depth','全站转化率':'Site conversion rate','今日转化':'Conversions today','转化页 TOP1':'Top conversion page','白皮书下载':'White paper downloads',
 '训练':'Training','搜索':'Search','用户触发':'User-triggered','其他':'Other','未知':'Unknown','已收录目录，所选范围无 AI 抓取':'In the inventory; no AI crawl observed in this range','社交媒体':'Social media','引荐':'Referral','秒':'seconds','次':'requests',
 channel:'渠道 / Channel',bounceRate:'跳出率 / Bounce rate',conversionRate:'转化率 / Conversion rate',aiRequests:'AI 请求 / AI requests',lastVisit:'最近访问 / Last visit',lastCrawled:'最近抓取 / Last crawl',reason:'原因 / Reason',category:'类别 / Category',trend:'变化 / Change',rateState:'数据状态 / Data state',path:'页面 / Page',source:'来源 / Source',name:'名称 / Name',bot:'爬虫 / Crawler',vendor:'供应商 / Provider',type:'类型 / Type',requests:'请求 / Requests',visits:'访问 / Visits',sessions:'会话 / Sessions',pageviews:'浏览量 / Pageviews',visitors:'访客 / Visitors',conversions:'转化 / Conversions',rate:'比率 / Rate',title:'标题 / Title',count:'数量 / Count',value:'数值 / Value',status:'状态 / Status',verification:'身份核验 / Identity evidence',lastSeen:'最近访问 / Last seen',pages:'页面数 / Pages',share:'占比 / Share'
};
const inflowLabel=value=>{const v=String(value??'');const mapped=INFLOW_LABELS[v];if(mapped?.includes(' / ')){const [zh,en]=mapped.split(' / ');return inflowText(zh,en);}if(mapped)return inflowText(v,mapped);return /[\u3400-\u9fff]/u.test(v)&&document.documentElement.lang.startsWith('en')?'Metric':v;};
const inflowValue=value=>{const v=String(value??'');return INFLOW_LABELS[v]?inflowLabel(v):v;};
const inflowState=value=>inflowText(...({available:['可用','Available'],empty:['尚无数据','No data yet'],not_connected:['未接入','Not connected'],unsupported:['不支持','Unsupported'],estimated:['估计值','Estimated'],unavailable:['暂不可用','Unavailable']}[value]||['未知','Unknown']));
async function inflowLoadReport(){
 const d=INFLOW.data,epoch=++INFLOW.epoch,resource=INFLOW.resource,days=INFLOW.days;
 $('#inflowReport').innerHTML=`<p role="status">${inflowText('读取报告中…','Loading report…')}</p>`;
 try{const report=await inflowAPI('report?'+new URLSearchParams({slug:d.site.slug,resource,days,page:INFLOW.tablePage}));if(epoch!==INFLOW.epoch)return;INFLOW.report=report;inflowRenderReport();}
 catch(e){if(epoch===INFLOW.epoch&&$('#inflowReport'))$('#inflowReport').innerHTML=`<p role="alert">${esc(e.message)}</p>${inflowButton('report','重试','Retry')}`;}
}
function inflowRenderReport(){
 const r=INFLOW.report,root=$('#inflowReport');if(!r||!root)return;
 if(r.pending){root.innerHTML=`<p>${inflowText('报告正在计算，请稍后刷新。','Report is being calculated. Refresh shortly.')}</p>${inflowButton('report','刷新','Refresh')}`;return;}
 const cards=(r.cards||[]).slice(0,5),tables=Object.entries(r.tables||{}).filter(([,v])=>Array.isArray(v));
 root.innerHTML=`${r.meta?.demo?`<p>${inflowText('示例数据','Demonstration data')}</p>`:''}<div class="formrow">${cards.map(c=>`<div class="callout"><strong>${esc(inflowLabel(c.label))}</strong><p>${c.value===null?'—':esc(inflowValue(c.value))} ${esc(inflowValue(c.unit||''))}</p><small>${inflowState(c.state)}</small></div>`).join('')}</div>
 <p>${Object.entries(r.states||{}).map(([k,v])=>esc(inflowText(({human:'访问',logs:'日志',catalog:'内容目录',goals:'转化目标'})[k]||k,({human:'Visits',logs:'Logs',catalog:'Inventory',goals:'Goals'})[k]||k)+': '+inflowState(v))).join(' · ')}</p>
 ${tables.map(([key],i)=>`<div id="inflowTable${i}"></div>`).join('')}${!tables.length?`<p>${inflowText('当前范围没有明细。','No details for this range.')}</p>`:''}
 ${Object.values(r.meta?.tablePages||{}).some(p=>p.total>20)?`<div class="domain-form-actions">${inflowButton('previous-page','上一页明细','Previous details')}<span>${INFLOW.tablePage}</span>${inflowButton('next-page','下一页明细','Next details')}</div>`:''}<details><summary>${inflowText('数据范围','Data scope')}</summary><p>${esc(new Date(r.range.startAt).toLocaleString())} → ${esc(new Date(r.range.endAt).toLocaleString())} · ${esc(r.range.timezone)}</p>${r.meta?.snapshot?`<p>${inflowText('数据截止','Data through')}: ${esc(new Date(r.meta.snapshot.dataThrough).toLocaleString())}</p>`:''}</details>`;
 tables.forEach(([key,rows],i)=>{const choices={srcBody:['source','channel','sessions','share','bounceRate','conversionRate'],botBody:['name','vendor','type','requests','pages','lastVisit'],apBody:['path','title','requests','bots','lastCrawled'],blindList:['path','reason'],goalBody:['name','count','rate','trend','path'],envGrid:['category','name','share']};const cols=(choices[key]||[...new Set(rows.flatMap(x=>Object.keys(x)))].filter(k=>!k.endsWith('Id')&&k!=='id').slice(0,6));if(!cols.length)return;AdminUI.table('inflowTable'+i,rows,cols.map(inflowLabel),row=>`<tr>${cols.map(k=>`<td data-user-content>${esc(row[k]===null?'—':typeof row[k]==='object'?JSON.stringify(row[k]):inflowValue(row[k]))}</td>`).join('')}</tr>`);});
}
async function inflowModal(title,fields,action){
 const host=document.createElement('div');host.innerHTML=`<form id="inflowForm"><h3>${esc(title)}</h3>${fields}<button type="submit">${inflowText('保存','Save')}</button><p id="inflowFormMsg" role="status"></p></form>`;document.body.append(host);
 const modal=AdminUI.form('inflowForm',title,()=>{const dialog=$('#inflowFormDialog');AdminUI.forms=AdminUI.forms.filter(x=>x.dialog!==dialog);host.remove();});
 $('#inflowForm').onsubmit=async e=>{e.preventDefault();const submit=e.target.querySelector('[type=submit]');submit.disabled=true;INFLOW.busy=true;try{await action();modal.close(true);}catch(err){$('#inflowFormMsg').textContent=err.message;}finally{submit.disabled=false;INFLOW.busy=false;}};modal.open();
}
async function inflowSettings(){
 const c=await inflowAPI('config');
 await inflowModal(inflowText('GEOInflow 连接','GEOInflow connection'),geoSelect('inflowMode','部署方式','Deployment',[['managed',inflowText('本机托管','Managed locally')],['remote',inflowText('外部 HTTPS 服务','External HTTPS service')]],c.connection.url==='http://127.0.0.1:3002'?'managed':'remote')+geoField('inflowURL','外部服务地址','External service origin',c.connection.url==='http://127.0.0.1:3002'?'':c.connection.url,'url')+geoField('inflowKey','API Key（留空保留）','API key (leave blank to keep)','','password','autocomplete="new-password"')+`<label><input id="inflowEnabled" type="checkbox" ${c.connection.enabled?'checked':''}>${inflowText('启用','Enable')}</label><p class="hint">${inflowText('保存时验证连接。API Key 不会返回浏览器。','The connection is verified on save. API keys are never returned to the browser.')}</p>`,
 async()=>{const saved=await inflowAPI('connection',{revision:c.revision,url:$('#inflowMode').value==='managed'?'http://127.0.0.1:3002':$('#inflowURL').value,token:$('#inflowKey').value,enabled:$('#inflowEnabled').checked});c.revision=saved.revision;$('#inflowKey').value='';if(saved.connection.enabled){const verified=await inflowAPI('test',{revision:saved.revision});c.revision=verified.revision;}if(CURRENT_TAB==='inflow')await initInflow();});
}
async function inflowRun(action){if(INFLOW.busy)return;INFLOW.busy=true;const buttons=[...document.querySelectorAll('#inflowRoot button')];buttons.forEach(b=>b.disabled=true);try{await action();}catch(e){AdminUI.message('#inflowMsg',[e.message,e.message],true);}finally{INFLOW.busy=false;buttons.forEach(b=>b.disabled=false);}}
document.addEventListener('click',async e=>{
 const siteButton=e.target.closest('[data-inflow-site]');if(siteButton){navigateTo('inflow',true,siteButton.dataset.inflowSite);return;}
 const b=e.target.closest('[data-inflow-action]');if(!b||INFLOW.busy)return;
 const action=b.dataset.inflowAction,d=INFLOW.data;
 if(action==='settings'){INFLOW.busy=true;try{await inflowSettings();}catch(err){showGlobalError(err.message);}finally{INFLOW.busy=false;}return;}
 if(action==='test'){
  b.disabled=true;try{const c=await inflowAPI('config');await inflowAPI('test',{revision:c.revision});$('#inflowFormMsg').textContent=inflowText('连接已验证。关闭窗口后刷新站点。','Connection verified. Close this window and refresh the site.');}catch(err){$('#inflowFormMsg').textContent=err.message;}finally{b.disabled=false;}return;
 }
 if(action==='geo'){navigateTo('geo',true,d.site.slug);return;}
 if(action==='reload'){await initInflow();return;}
 if(action==='previous-page'||action==='next-page'){const max=Math.max(1,...Object.values(INFLOW.report?.meta?.tablePages||{}).map(p=>Math.ceil(p.total/20)));INFLOW.tablePage=Math.min(max,Math.max(1,INFLOW.tablePage+(action==='next-page'?1:-1)));await inflowLoadReport();return;}
 if(action==='report'){await inflowLoadReport();return;}
 if(action==='bind'){await inflowModal(inflowText('连接站点','Connect site'),geoField('inflowWebsite','已有网站 UUID（留空自动创建）','Existing website UUID (blank to create)','','text','maxlength="36"'),async()=>{await inflowAPI('bind',{slug:d.site.slug,revision:d.revision,website_id:$('#inflowWebsite').value});await initInflow();});return;}
 if(['catalog','logs'].includes(action)){await inflowModal(inflowText(action==='catalog'?'导入内容目录':'导入访问日志',action==='catalog'?'Import content inventory':'Import access logs'),geoSelect('inflowFormat','文件格式','File format',(action==='catalog'?['sitemap','csv','json']:['combined','json']).map(x=>[x,x]))+geoField('inflowFile','文件（最多 250 KB）','File (up to 250 KB)','','file','required')+`<p class="hint">${inflowText('仅导入当前站点的真实记录。重复日志由分析服务校验。','Import real records for this site only. The analytics service checks duplicate logs.')}</p>`,async()=>{const f=$('#inflowFile').files[0];if(!f||f.size>256000)throw Error(inflowText('请选择不超过 250 KB 的文件。','Select a file up to 250 KB.'));await inflowAPI(action,{slug:d.site.slug,format:$('#inflowFormat').value,content:await f.text()});await initInflow();});return;}
 if(['tracking','disconnect'].includes(action)){if(!confirm(inflowText(action==='tracking'?'更新此站点的追踪设置？':'解除绑定？远端历史数据将保留。',action==='tracking'?'Update tracking for this site?':'Disconnect? Remote history will be retained.')))return;await inflowRun(async()=>{await inflowAPI(action,{slug:d.site.slug,revision:d.revision,enabled:!d.binding?.tracking,public_origin:location.origin});await initInflow();});}
});
new MutationObserver(()=>{if(CURRENT_TAB==='inflow'&&!INFLOW.busy)inflowRender();}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
