/* Browser preferences apply to console UI, not tenant content or model output. */
(()=>{
 const keyTheme='kf-ui-theme',keyLanguage='kf-ui-language',root=document.documentElement;
 const read=(key,fallback)=>{try{return localStorage.getItem(key)||fallback;}catch(_){return fallback;}};
 let theme=read(keyTheme,'system'),language=read(keyLanguage,'zh');
 if(!['light','dark','system'].includes(theme))theme='system';if(!['zh','en'].includes(language))language='zh';
 const media=matchMedia('(prefers-color-scheme: dark)');
 function paintTheme(){root.dataset.theme=theme==='system'?(media.matches?'dark':'light'):theme;root.style.colorScheme=root.dataset.theme;}
 paintTheme();root.lang=language==='en'?'en':'zh-CN';
 const css=document.createElement('style');css.textContent=`
 :root{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--dim:#8b949e;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff;--surface:#21262d;--selected:#1c2d42;--selected-text:#9acbff;--input:#0d1117;--callout:#1c2530}
 html[data-theme=light]{--bg:#f4f6f9;--card:#ffffff;--line:#ccd5df;--fg:#172334;--dim:#536276;--ok:#187437;--warn:#875b00;--bad:#b42318;--acc:#175fba;--surface:#eaf0f6;--selected:#e4efff;--selected-text:#14529b;--input:#fff;--callout:#edf3fa}
 body{background:var(--bg)!important;color:var(--fg)!important}
 .ui-preferences{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 18px;justify-content:flex-end}
 .ui-preferences label{display:flex;gap:6px;align-items:center;margin:0;font-size:12px;color:var(--dim)}
 .ui-preferences select{width:auto!important;min-height:36px;padding:6px 8px;border-radius:6px;border:1px solid var(--line);background:var(--input);color:var(--fg);font-size:13px}
 .box{background:var(--card)!important;border-color:var(--line)!important;color:var(--fg)!important}
 .box label,.box .sub,.box details{color:var(--dim)!important}.box input{background:var(--input)!important;border-color:var(--line)!important;color:var(--fg)!important}
 .err{background:var(--card)!important;color:var(--bad)!important;border:1px solid var(--bad)}
 html[data-theme=light] .tab.on{background:var(--selected);color:var(--selected-text)}
 html[data-theme=light] .tab:hover,html[data-theme=light] .sec-row.on{background:var(--selected)}
 html[data-theme=light] .callout{background:var(--callout)}
 html[data-theme=light] input,html[data-theme=light] select,html[data-theme=light] textarea{background:var(--input);color:var(--fg)}
 html[data-theme=light] button.ghost,html[data-theme=light] .sec-row button,html[data-theme=light] .dom-row button,html[data-theme=light] .share-row button,html[data-theme=light] .tile .ops button,html[data-theme=light] .fld .sub button{background:var(--surface);color:var(--fg);border-color:var(--line)}
 html[data-theme=light] .sec-row .section-select{background:transparent}
 html[data-theme=light] button.danger{color:var(--bad)}
 :where(button,input,select,textarea,summary,a):focus-visible{outline:2px solid var(--acc);outline-offset:3px}
 @media(max-width:600px){.ui-preferences{justify-content:flex-start}.ui-preferences select{font-size:16px;min-height:44px}}
 `;document.head.append(css);
 const messages=window.KF_MESSAGES||{},reverse=Object.fromEntries(Object.entries(messages).map(([zh,en])=>[en,zh]));
 const patterns=[
  [/^未保存 · (\d+) 页$/,n=>`Unsaved · ${n} page(s)`],
  [/^已发布 (\d+) 个页面$/,n=>`Published ${n} page(s)`],
  [/^导航菜单 · (.+)$/,v=>'Navigation · '+translate(v)],
  [/^请检查以下 (\d+) 项$/,n=>`Please check ${n} field(s)`],
  [/^上移区块 (\d+)$/,n=>`Move section ${n} up`],[/^下移区块 (\d+)$/,n=>`Move section ${n} down`],[/^删除区块 (\d+)$/,n=>`Delete section ${n}`],
  [/^编辑区块 (\d+)：(.+)$/,(n,v)=>`Edit section ${n}: ${v}`],
  [/^(.+) 天后$/,n=>`In ${n} days`],[/^已过期 (\d+) 天$/,n=>`Expired ${n} days ago`],
  [/^最后刷新 (.+)$/,v=>`Last refreshed ${v}`],
  [/^新建(场景模板|可复用模块)$/,v=>'New '+translate(v)],[/^编辑(场景模板|可复用模块)$/,v=>'Edit '+translate(v)],
  [/^已校验组合 · (\d+) 个模块 · (\d+) 字$/,(n,c)=>`Validated · ${n} modules · ${c} characters`],
  [/^(\d+) 个模块$/,n=>`${n} modules`],
  [/^(.+)，可跨场景复用$/,v=>`${translate(v)}; reusable across scenarios`],
  [/^(.+) · 模板 v(\d+)$/,(v,n)=>`${translate(v)} · Template v${n}`],
  [/^(上移|下移) (.+)$/,(direction,v)=>`Move ${translate(v)} ${direction==='上移'?'up':'down'}`],
  [/^(停用|启用)「(.+)」？已创建任务保留原版本。$/,(action,v)=>`${action==='停用'?'Disable':'Enable'} “${v}”? Existing jobs retain their original version.`],
  [/^(.+) · v(\d+)$/,(v,n)=>`${translate(v)} · v${n}`],
  [/^提示词：(.+) · v(\d+)$/,(v,n)=>`Prompt: ${translate(v)} · v${n}`],
  [/^将调用 (.+) 生成内容，企业名称和建站要求会发送至该配置的接口。$/,v=>`Using ${v}. Business information and the brief will be sent to this endpoint.`],
  [/^发布站点「(.+)」的「(.+)」？\n将先保存编辑内容，再更新线上页面。客户会立即看到。$/,(site,pages)=>`Publish “${pages}” on site “${site}”?\nEdits will be saved before updating the live pages. Customers will see them immediately.`],
  [/^发布失败：(.+)；草稿已保留，请查看改动后重试。$/,v=>`Publish failed: ${translate(v)}. Draft retained; review changes and retry.`],
  [/^JSON 无效：(.+)$/,v=>`Invalid JSON: ${v}`],
  [/^数据刷新失败：(.+)。请检查网络，稍后会自动重试。$/,v=>`Refresh failed: ${translate(v)}. Check your connection; retrying automatically.`],
  [/^(.+)（(管理员|运营|财务)）$/,(v,r)=>`${v} (${translate(r)})`],
 ];

 function translate(value){
  if(language!=='en')return reverse[value]||value;
  if(messages[value])return messages[value];
  for(const [regex,render] of patterns){const match=value.match(regex);if(match)return render(...match.slice(1));}
  // Translate known UI status prefixes while keeping names and free text intact.
  for(const [prefix,label] of [['失败：','Failed: '],['已保存','Saved'],['编辑中：','Editing: '],['已复制：','Copied: '],['已发送到 ','Sent to '],['已生成，有效期至 ','Created, valid until '],['有效至 ','Valid until '],['上次检查：','Last checked: '],['已创建 ','Created '],['新密码：','New password: ']]){
   if(value.startsWith(prefix))return label+translate(value.slice(prefix.length));
  }
  if(value.includes(' / '))return value.split(' / ').map(v=>messages[v]||v).join(' / ');
  if(value.includes(' · '))return value.split(' · ').map(v=>messages[v]||v).join(' · ');
  return value;
 }
 window.kfText=translate;window.kfLanguage=()=>language;
 const original=new WeakMap(),attributes=new WeakMap();
 function renderText(node){
  const old=original.get(node),current=node.nodeValue;
  const source=old&&current===old.rendered?old.source:(reverse[current.trim()]||current);
  const trim=source.trim(),translated=language==='en'?translate(trim):trim;
  const rendered=source.replace(trim,translated);
  original.set(node,{source,rendered});if(node.nodeValue!==rendered)node.nodeValue=rendered;
 }
 let rendering=false;
 function localize(){
  if(rendering||!document.body)return;rendering=true;
  try{
   const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement.closest('script,style,textarea,pre,[data-user-content]')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});
   const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
   for(const n of nodes){
    const parent=n.parentElement;
    if(parent.tagName==='OPTION'&&!parent.hasAttribute('value'))parent.setAttribute('value',parent.textContent);
    renderText(n);
   }
   document.querySelectorAll('[placeholder],[title],[aria-label],[data-label]').forEach(e=>{
    if(e.closest('[data-user-content]'))return;
    const map=attributes.get(e)||{};
    for(const key of ['placeholder','title','aria-label','data-label']){
     if(!e.hasAttribute(key))continue;
     const current=e.getAttribute(key),old=map[key],source=old&&current===old.rendered?old.source:(reverse[current]||current);
     const rendered=language==='en'?translate(source):source;map[key]={source,rendered};if(current!==rendered)e.setAttribute(key,rendered);
    }attributes.set(e,map);
   });
   const title=document.querySelector('title');if(title)renderText(title.firstChild);
  }finally{rendering=false;}
 }
 // Native dialogs are UI too; preserve their synchronous behavior.
 for(const name of ['alert','confirm','prompt']){const native=window[name].bind(window);window[name]=(message,...args)=>native(translate(String(message)),...args);}
 let scheduled=false;
 const observer=new MutationObserver(()=>{if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;localize();});}});
 function apply(){root.lang=language==='en'?'en':'zh-CN';paintTheme();localize();document.querySelectorAll('[data-ui-theme]').forEach(e=>e.value=theme);document.querySelectorAll('[data-ui-language]').forEach(e=>e.value=language);}
 document.addEventListener('DOMContentLoaded',()=>{
  const target=document.querySelector('.topbar')||document.querySelector('.box');if(!target)return;
  const bar=document.createElement('div');bar.className='ui-preferences';
  bar.innerHTML='<label for="uiTheme">主题 <select id="uiTheme" data-ui-theme><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select></label><label for="uiLanguage">语言 <select id="uiLanguage" data-ui-language><option value="zh">中文</option><option value="en">English</option></select></label>';
  if(target.classList.contains('box'))target.prepend(bar);else target.after(bar);
  bar.addEventListener('change',e=>{
   if(e.target.matches('[data-ui-theme]'))theme=e.target.value;
   if(e.target.matches('[data-ui-language]'))language=e.target.value;
   try{localStorage.setItem(keyTheme,theme);localStorage.setItem(keyLanguage,language);}catch(_){}
   apply();
  });
  observer.observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['placeholder','title','aria-label','data-label']});apply();
 });
 media.addEventListener('change',paintTheme);
 window.addEventListener('storage',e=>{if(e.key===keyTheme&&['system','light','dark'].includes(e.newValue))theme=e.newValue;if(e.key===keyLanguage&&['zh','en'].includes(e.newValue))language=e.newValue;apply();});
})();
