/* Run production HTML/JS against isolated API fixtures; never connect to live services. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'../..');
const promptBase=fs.mkdtempSync(path.join(require('node:os').tmpdir(),'kf-prompt-ui-'));
function promptAPI(action,body={}){return JSON.parse(execFileSync('python3',['-c',`import sys,json;sys.path.insert(0,'core');import kf_prompts;s=kf_prompts.PromptStore(sys.argv[1]);b=json.load(sys.stdin);action=sys.argv[2];r=s.compose(b['selection'],b.get('brief','')) if action=='preview' else (s.change(b) if action=='save' else s.public(True));print(json.dumps(r,ensure_ascii=False))`,promptBase,action],{cwd:root,input:JSON.stringify(body),encoding:'utf8'}));}
function styleAPI(action,body={}){return JSON.parse(execFileSync('python3',['-c',`import sys,json;sys.path.insert(0,'core');import kf_styles;s=kf_styles.StyleStore(sys.argv[1]);b=json.load(sys.stdin);action=sys.argv[2];r=kf_styles.extract('<title>Reference</title><style>body{color:#345678;font-family:Georgia,serif}</style>',[],'https://example.com/',[]) if action=='analyze' else ({'item':s.change(b),**s.public(True)} if action=='save' else s.public(True));print(json.dumps(r,ensure_ascii=False))`,promptBase,action],{cwd:root,input:JSON.stringify(body),encoding:'utf8'}));}
const pages=JSON.parse(execFileSync('python3',['-c',`
import ast,json,pathlib
import sys
sys.path.insert(0,'core')
import kf_prompts,kf_providers
m=ast.parse(pathlib.Path('console/kf_console.py').read_text())
result={'providerCatalog':kf_providers.CATALOG,'library':dict(kf_prompts.defaults(),variables=kf_prompts.VARIABLES,categories=kf_prompts.CATEGORIES,sources=kf_prompts.SOURCES,can_manage=True)}
for n in m.body:
 if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PAGE' for t in n.targets): result['console']=ast.literal_eval(n.value)
 if isinstance(n,ast.FunctionDef) and n.name=='login_page':
  ns={}; exec(compile(ast.Module(body=[n],type_ignores=[]),'login','exec'),ns);result['login']=ns['login_page']()
print(json.dumps(result))
`],{cwd:root,encoding:'utf8'}));
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();page.setDefaultTimeout(8000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let role='admin',failSave=false,failPublish=false;const calls=[];let domainAccounts=[],domainPassword='',mcpItems=[],providerItems=[],failProviderProbe=false;
 const state=()=>({role,me:'reviewer',sites:[{slug:'demo',company:'演示工作室',domain:'demo.example',state:'active',http:200,running:2,port:18080,owner:'reviewer',plan:'Starter',days_left:20}],plans:[{id:'starter',name:'Starter',price:1800}],industries:[['tech','科技']],invoices:[]});
 const spec={dirty:false,types:['hero'],schemas:{hero:{label:'首屏',fields:[{k:'title',label:'标题',type:'text'}]}},spec:{pages:[{slug:'home',title:'首页',sections:[{type:'hero',title:'A'},{type:'hero',title:'B'}]},{slug:'contact',title:'联系',sections:[{type:'hero',title:'Contact'}]}]}};
 await context.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname;
  assert.equal(u.hostname,'review.invalid','Unexpected external request');
  if(p==='/'||p==='/login')return route.fulfill({contentType:'text/html',body:pages[p==='/'?'console':'login']});
  if(['/ai.js','/prompts.js','/locale.js','/appearance.js','/domains.js','/mcp.js','/automation.js','/providers.js'].includes(p))return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(root,'console',p.slice(1)),'utf8')});
  if(p.startsWith('/preview/')){calls.push({path:p});return route.fulfill({contentType:'text/html',body:'<h1>Preview</h1>'});}
  let data={items:[]},status=200;
  if(p==='/api/state')data=state();
  if(p==='/api/automation/config')await new Promise(resolve=>setTimeout(resolve,100));
  if(p==='/api/automation/config')data={tools:[{name:'site.context',purpose:'build'},{name:'site.publish',purpose:'build'}],dns_providers:[],provider_accounts:providerItems,can_configure:role==='admin'};
  if(p==='/api/automation/providers'){
   if(req.method()==='POST'){const {values,...b}=req.postDataJSON();providerItems=b.action==='delete'?[]:[{...b,version:(b.version||0)+1,config:Object.fromEntries(Object.entries(values).filter(([k])=>!pages.providerCatalog[b.provider].fields.find(f=>f.key===k).secret))}];}
   data={catalog:pages.providerCatalog,items:providerItems};
  }
  if(p==='/api/automation/providers/test'){if(failProviderProbe){status=400;data={error:'测试连接失败，请检查 Token 和权限'};}else data={result:{provider:'cpanel',ok:true,message:'只读连接测试成功；未验证 DNS 写入权限，也未修改资源。'}};}
  if(p==='/api/automation/available')data={items:[]};
  if(p==='/api/automation/actions'||p==='/api/automation/workflows')data={items:[]};
  if(p==='/api/automation/prepare'){const b=req.postDataJSON();data={item:{id:'fixture-action',slug:b.slug,tool:b.tool,user:'reviewer',mode:b.tool==='site.publish'?'confirm':'read',state:'prepared',summary:'Fixture operation',digest:'fixture-digest',arguments:{purpose:'build',...b.arguments}}};}
  if(p==='/api/automation/execute')data={item:{id:'fixture-action',slug:'demo',tool:'site.context',user:'reviewer',mode:'read',state:'succeeded',summary:'Fixture context',digest:'fixture-digest',arguments:{purpose:'build'},result:{company:'Demo'}}};
  if(p==='/api/mcp/servers'){
   if(req.method()==='POST'){const {token,clear_token,...b}=req.postDataJSON();mcpItems=b.action==='delete'?[]:[{...b,version:(b.version||0)+1,has_token:!!token||mcpItems[0]?.has_token}];}
   data={items:mcpItems};
  }
  if(p==='/api/mcp/test')data={result:{server:'Fixture MCP',version:'1',protocol:'2025-06-18',tools:[{name:'search',description:'Search fixture data'}],resources:[],prompts:[]}};
  if(p==='/api/domains')data={items:[{slug:'demo',domain:'demo.example',company:'演示工作室',manage:{}}]};
  if(p==='/api/domain/accounts'){
   if(req.method()==='POST'){
    const b=req.postDataJSON();
    if(b.action==='delete')domainAccounts=[];
    else{if(b.password)domainPassword=b.password;const {password,clear_password,...metadata}=b;domainAccounts=[{...metadata,id:'account1',version:1,has_password:!!domainPassword,updated:1700000000,updated_by:'reviewer'}];}
   }
   data={items:domainAccounts,mfa_enabled:true};
  }
  if(p==='/api/domain/accounts/reveal'){
   if(req.postDataJSON().code==='123456')data={password:domainPassword,expires_in:30};
   else{status=403;data={error:'TOTP 无效'};}
  }
  if(p==='/api/wordpress/sites')data={sites:{demo:{url:'https://demo.example',enabled:role!=='finance'}}};
  if(p.startsWith('/api/spec/'))data=spec;
  if(p==='/api/spec'){
   const body=req.postDataJSON();calls.push({path:p,body});
   if(failSave){status=503;data={error:'模拟保存失败'};}
   else{spec.spec.pages.find(p=>p.slug===body.page).sections=body.sections;spec.dirty=true;data={ok:true};}
  }
  if(p==='/api/publish'){calls.push({path:p,body:req.postDataJSON()});status=failPublish?500:200;data=failPublish?{error:'模拟发布失败'}:{pages:1,dirty:false};}
  if(p==='/api/ai/prompts'){if(req.method()==='POST')promptAPI('save',req.postDataJSON());data={...promptAPI('read'),can_manage:role==='admin'};}
  if(p==='/api/ai/prompts/preview')data=promptAPI('preview',req.postDataJSON());
  if(p==='/api/ai/styles')data={...styleAPI(req.method()==='POST'?'save':'read',req.method()==='POST'?req.postDataJSON():{}),can_manage:role==='admin'};
  if(p==='/api/ai/styles/analyze')data=styleAPI('analyze');
  if(p==='/api/ai/build'){calls.push({path:p,body:req.postDataJSON()});status=202;data={job:{id:'fixture'}};}
  if(p==='/api/ai/config')data={can_configure:role==='admin',profiles:[{id:'mock',name:'模拟',model:'mock',protocol:'mock'}],presets:[],default_profile:'mock'};
  if(p==='/api/ai/jobs')data={jobs:[]};
  if(p.startsWith('/api/diff/'))data={changes:[]};
  return route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
 });
 const nav=async key=>{
  const toggle=page.locator('#navToggle');if(await toggle.isVisible() && await toggle.getAttribute('aria-expanded')==='false')await toggle.click();
  const group=page.locator('.nav-group').filter({has:page.locator(`[data-t="${key}"]`)});
  if(!await group.getAttribute('open')){if(!await group.evaluate(e=>e.open))await group.locator('summary').click();}
  await page.locator(`[data-t="${key}"]`).click();
  await page.waitForFunction(k=>!document.querySelector('#p-'+k).classList.contains('hidden'),key);
 };
 await page.goto('http://review.invalid/login');
 await page.locator('#loginCode').pressSequentially('abcd-1234');assert.equal(await page.locator('#loginCode').inputValue(),'abcd-1234');
 assert.equal(await page.locator('input:not([type=hidden])').evaluateAll(es=>es.filter(e=>!e.labels.length).length),0);
 assert.equal(await page.locator('#loginCode').evaluate(e=>Math.round(e.getBoundingClientRect().width)),await page.locator('form').evaluate(e=>Math.round(e.getBoundingClientRect().width)));
 console.log('PASS recovery input, labels and login layout');
 await page.goto('http://review.invalid/');await page.waitForSelector('#rows button');
 await page.locator('#btn').click();await page.waitForSelector('#f .form-error-summary');
 assert.equal(await page.locator('#f .form-error-summary').evaluate(e=>document.activeElement===e),true);
 await page.locator('#f input[name=company]').fill('Test');await page.locator('#f input[name=domain]').fill('demo.example');
 assert.equal(await page.locator('#f input[name=slug]').inputValue(),'demo');
 console.log('PASS linked validation summary and suggested site identifier');
 await page.locator('#rows details summary').click();await page.locator('#rows button').first().focus();
 await page.evaluate(()=>load());assert.equal(await page.locator('#rows details').evaluate(e=>e.open),true);
 assert.equal(await page.locator('#rows button').first().evaluate(e=>document.activeElement===e),true);
 await page.locator('.nav-group summary').nth(1).focus();await page.keyboard.press('Enter');
 await page.locator('[data-t=layout]').focus();await page.keyboard.press('Enter');
 await page.waitForSelector('.section-select');assert.equal(new URL(page.url()).hash,'#layout');
 await page.locator('.section-select').first().click();await page.locator('#lForm input').fill('Edited A');
 assert.equal(await page.evaluate(()=>{const e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented;}),true);
 await page.locator('.section-select').nth(1).click();await page.locator('.section-select').first().click();assert.equal(await page.locator('#lForm input').inputValue(),'Edited A');
 await page.selectOption('#lPage','contact');await page.locator('.section-select').first().click();await page.locator('#lForm input').fill('Edited Contact');
 await nav('sites');await nav('layout');assert.equal(await page.locator('#lForm input').inputValue(),'Edited Contact');
 await page.locator('#lSave').click();await page.waitForFunction(()=>!document.querySelector('#lSave').disabled);
 assert.equal(spec.spec.pages[0].sections[0].title,'Edited A');assert.equal(spec.spec.pages[1].sections[0].title,'Edited Contact');
 console.log('PASS keyboard navigation and edits retained across sections, pages and navigation');
 await page.locator('#lForm input').fill('Retained on failure');failSave=true;
 await page.locator('#lSave').click();await page.waitForFunction(()=>!document.querySelector('#lSave').disabled);
 assert.match(await page.locator('#lMsg').textContent(),/模拟保存失败/);assert.match(await page.locator('#lDirty').textContent(),/未保存/);
 failSave=false;await page.locator('#lSave').click();await page.waitForFunction(()=>!document.querySelector('#lSave').disabled);
 assert.equal(spec.spec.pages[1].sections[0].title,'Retained on failure');
 await page.locator('details.adv summary').click();await page.locator('#lJson').fill('{broken');await page.selectOption('#lPage','home');assert.equal(await page.locator('#lPage').inputValue(),'contact');
 await page.locator('#lJson').fill(JSON.stringify({type:'hero',title:'JSON edit'}));await page.locator('#lApplyJson').click();assert.equal(await page.locator('#lForm input').inputValue(),'JSON edit');
 console.log('PASS failed save retry and invalid/valid JSON handling');
 calls.length=0;page.once('dialog',d=>d.accept());await page.locator('#lPublish').click();await page.waitForFunction(()=>!document.querySelector('#lPublish').disabled);
 assert.deepEqual(calls.map(c=>c.path),['/api/spec','/api/publish']);assert.equal(calls[0].body.sections[0].title,'JSON edit');
 await page.locator('#lForm input').fill('Preview content');calls.length=0;
 const popupPromise=context.waitForEvent('page');await page.locator('#lPreview').click();const popup=await popupPromise;await popup.waitForURL('**/preview/demo/contact');
 assert.deepEqual(calls.map(c=>c.path),['/api/spec','/preview/demo/contact']);await popup.close();
 failPublish=true;page.once('dialog',d=>d.accept());await page.locator('#lPublish').click();await page.waitForFunction(()=>!document.querySelector('#lPublish').disabled);assert.match(await page.locator('#lMsg').textContent(),/草稿已保留/);failPublish=false;
 console.log('PASS save before publish/preview and honest publish failure state');
 await page.reload();await page.waitForSelector('#lPage option',{state:'attached'});assert.equal(await page.locator('#pageTitle').textContent(),'页面编辑');
 const out=process.env.UI_SCREENSHOTS;if(out)fs.mkdirSync(out,{recursive:true});
 if(out)await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
 for(const width of [390,760]){
  await page.setViewportSize({width,height:844});await nav('sites');
  assert.equal(await page.locator('#navToggle').getAttribute('aria-expanded'),'false');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.locator('#navToggle').click();await page.keyboard.press('Escape');assert.equal(await page.locator('#navToggle').getAttribute('aria-expanded'),'false');
  if(out)await page.screenshot({path:path.join(out,'mobile-'+width+'.png'),fullPage:true});
 }
 await page.setViewportSize({width:1440,height:1000});
 assert.equal(await page.locator('.kf-wp-entry').getAttribute('href'),'https://demo.example/?kf_mvp_sso=begin');
 await nav('ai');await page.waitForFunction(()=>document.querySelector('#aiPromptTemplate').options.length>1);
 await page.selectOption('#aiPromptTemplate','company');await page.locator('#promptServices').fill('真实设计服务');
 await page.locator('#aiPromptPreviewBtn').click();await page.waitForFunction(()=>document.querySelector('#aiPromptPreview').value.includes('真实设计服务'));
 assert.equal(await page.locator('#aiBrief').getAttribute('required'),null);
 await page.selectOption('#uiTheme','light');await page.selectOption('#uiLanguage','en');
 await page.waitForFunction(()=>document.documentElement.lang==='en'&&document.querySelector('#pageTitle').textContent==='AI builder');
 assert.equal(await page.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgb(244, 246, 249)');
 assert.equal(await page.locator('#promptServices').inputValue(),'真实设计服务');assert.equal(await page.locator('#aiPromptTemplate').inputValue(),'company');
 assert.equal(await page.locator('#aiLanguage').inputValue(),'zh','Interface language must not change generated content language');
 if(out)await page.screenshot({path:path.join(out,'ai-light-en.png'),fullPage:true});
 await page.setViewportSize({width:375,height:812});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'AI composer must fit mobile');
 if(out)await page.screenshot({path:path.join(out,'ai-mobile-en.png'),fullPage:true});
 await page.setViewportSize({width:1440,height:1000});
 calls.length=0;await page.locator('#aiGenerate').click();await page.waitForFunction(()=>!document.querySelector('#aiGenerate').disabled);
 assert.equal(calls.find(c=>c.path==='/api/ai/build').body.prompt_selection.template_id,'company');
 assert.equal(await page.locator('#promptServices').inputValue(),'真实设计服务');
 await page.locator('#aiReferenceOptions > summary').click();
 await page.locator('#aiReferenceUrl').fill('https://example.com/');await page.locator('#aiAnalyzeStyle').click();
 await page.waitForFunction(()=>document.querySelector('#aiStyleTemplate').value==='@analysis');
 assert.ok((await page.locator('#aiStyleSummary').textContent()).includes('serif'));
 await page.locator('#aiStyleSaveAnalysis').click();await page.locator('#styleName').fill('参考风格测试');
 await page.locator('#styleEditForm button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('#styleEditForm').classList.contains('hidden'));
 let style=styleAPI('read').templates[0];assert.equal(style.name,'参考风格测试');
 calls.length=0;await page.locator('#aiGenerate').click();await page.waitForFunction(()=>!document.querySelector('#aiGenerate').disabled);
 assert.equal(calls.find(c=>c.path==='/api/ai/build').body.style_template_id,style.id);
 await page.locator('[data-style-edit]').click();await page.locator('#styleName').fill('已修改风格');await page.locator('#styleEnabled').uncheck();
 await page.locator('#styleEditForm button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('#styleEditForm').classList.contains('hidden'));
 assert.equal(styleAPI('read').templates[0].version,2);assert.equal(await page.locator('#aiStyleTemplate').inputValue(),'');
 await page.locator('[data-style-copy]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-style-edit]').length===2);
 page.once('dialog',d=>d.accept());await page.locator('[data-style-delete]').first().click();await page.waitForFunction(()=>document.querySelectorAll('[data-style-edit]').length===1);
 assert.equal(styleAPI('read').templates.length,1);
 console.log('PASS reference analysis, save, selection, edit, disable, copy and delete');
 await nav('prompts');await page.waitForSelector('#promptLibraryList .dom-row');
 page.once('dialog',d=>d.accept());await page.locator('[data-toggle-prompt="company"]').click();
 await page.waitForFunction(()=>document.querySelector('#aiPromptTemplate').value==='');
 assert.equal(await page.locator('#aiBrief').getAttribute('required'),'');
 assert.equal(await page.locator('#promptServices').getAttribute('required'),null);
 assert.equal(await page.locator('#promptServices').inputValue(),'真实设计服务');
 if(out)await page.screenshot({path:path.join(out,'prompts-light-en.png'),fullPage:true});
 await page.selectOption('#promptLibraryKind','modules');await page.locator('#promptLibraryNew').click();
 await page.locator('#promptEditId').fill('ui-custom');await page.locator('#promptEditName').fill('UI Custom');await page.locator('#promptEditCategory').fill('copy');await page.locator('#promptEditBody').fill('Write clear copy for {{audience}}.');
 await page.locator('#promptEditForm button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('#promptEditForm').classList.contains('hidden'));
 assert.equal(promptAPI('read').modules.find(m=>m.id==='ui-custom').version,1);
 await page.locator('[data-edit-prompt="ui-custom"]').click();await page.locator('#promptEditBody').fill('Revised {{audience}} guidance');await page.locator('#promptEditForm button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('#promptEditForm').classList.contains('hidden'));
 await page.locator('[data-edit-prompt="ui-custom"]').click();page.once('dialog',d=>d.accept());await page.locator('[data-restore-prompt="1"]').click();await page.waitForFunction(()=>document.querySelector('#promptEditForm').classList.contains('hidden'));
 assert.equal(promptAPI('read').modules.find(m=>m.id==='ui-custom').body,'Write clear copy for {{audience}}.');
 console.log('PASS prompt composition, generation selection, versioned editing and restore');
 await nav('layout');await page.locator('.section-select').first().click();await page.locator('#lForm input').fill('不要翻译我的正文');
 await page.selectOption('#uiLanguage','zh');assert.equal(await page.locator('#lForm input').inputValue(),'不要翻译我的正文');
 await page.selectOption('#uiLanguage','en');assert.equal(await page.locator('#lForm input').inputValue(),'不要翻译我的正文');
 await page.locator('#lSave').click();await page.waitForFunction(()=>!document.querySelector('#lSave').disabled);
 await page.emulateMedia({colorScheme:'dark'});await page.selectOption('#uiTheme','system');await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');
 await page.emulateMedia({colorScheme:'light'});await page.waitForFunction(()=>document.documentElement.dataset.theme==='light');
 await page.reload();await page.waitForSelector('#uiLanguage');assert.equal(await page.locator('#uiLanguage').inputValue(),'en');assert.equal(await page.locator('#uiTheme').inputValue(),'system');
 await page.goto('http://review.invalid/login');await page.waitForFunction(()=>document.querySelector('button[type=submit]').textContent==='Sign in');
 assert.equal(await page.locator('#uiLanguage').inputValue(),'en');await page.selectOption('#uiLanguage','zh');await page.selectOption('#uiTheme','dark');
 await page.goto('http://review.invalid/');await page.waitForSelector('#rows',{state:'attached'});await nav('sites');
 console.log('PASS theme and bilingual preferences, system updates, login persistence and edit preservation');
 await nav('llm');await page.waitForSelector('#aiConfigForm');
 assert.equal(await page.locator('#p-ai #aiConfigForm').count(),0);assert.equal(await page.locator('[data-t=llm]').evaluate(e=>e.closest('.nav-group').dataset.group),'3');
 await page.locator('#aiKey').fill('temporary-key');await nav('mcp');assert.equal(await page.locator('#aiKey').inputValue(),'');
 await page.locator('#mcpNew').click();await page.locator('#mcpId').fill('fixture');await page.locator('#mcpName').fill('Fixture service');await page.locator('#mcpUrl').fill('https://example.com/mcp');await page.locator('#mcpToken').fill('fixture-bearer-token');
 await page.locator('#mcpForm button[type=submit]').click();await page.waitForSelector('[data-mcp-edit]');assert.equal(await page.locator('#mcpToken').inputValue(),'');assert.ok(!(await page.locator('#mcpList').textContent()).includes('fixture-bearer-token'));
 await page.locator('[data-mcp-edit]').click();assert.equal(await page.locator('#mcpToken').inputValue(),'');await page.locator('#mcpCancel').click();
 await page.locator('#mcpSearch').fill('missing');assert.equal(await page.locator('[data-mcp-edit]').count(),0);await page.locator('#mcpSearch').fill('');
 await page.locator('[data-mcp-test]').click();await page.waitForSelector('#mcpResult:not(.hidden)');assert.match(await page.locator('#mcpResult').textContent(),/search/);
 await page.setViewportSize({width:375,height:812});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 if(out)await page.screenshot({path:path.join(out,'mcp-mobile.png'),fullPage:true});await page.setViewportSize({width:1440,height:1000});
 await page.locator('[data-mcp-toggle]').click();await page.waitForFunction(()=>document.querySelector('[data-mcp-test]').disabled);
 page.once('dialog',d=>d.accept());await page.locator('[data-mcp-delete]').click();await page.waitForFunction(()=>!document.querySelector('[data-mcp-edit]'));
 await nav('automation');await page.locator('#autoPrepare').click();await page.waitForSelector('#autoConfirmForm');
 await page.locator('#autoConfirmForm button[type=submit]').click();await page.waitForSelector('#autoUseContext');
 await page.locator('#autoUseContext').click();await page.waitForSelector('#p-ai:not(.hidden)');assert.match(await page.locator('#aiContextList').textContent(),/Fixture context/);await page.locator('[data-context-remove]').click();
 await nav('automation');await page.selectOption('#autoTool','site.publish');await page.locator('#autoPrepare').click();await page.waitForSelector('#autoConfirmed');assert.equal(await page.locator('#autoConfirmed').isChecked(),false);
 await page.setViewportSize({width:375,height:812});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Operations assistant must fit mobile');
 if(out)await page.screenshot({path:path.join(out,'automation-mobile.png'),fullPage:true});await page.setViewportSize({width:1440,height:1000});
 console.log('PASS scoped automation preview, confirmation and AI context selection');
 console.log('PASS LLM settings navigation, credential clearing, MCP create/search/edit/test/disable/delete');
 await nav('providers');await page.locator('#providerNew').click();await page.selectOption('#providerKind','namecom');
 await page.locator('#providerId').fill('name-account');await page.locator('#providerName').fill('Name.com fixture');await page.locator('#provider-username').fill('test-user');await page.locator('#provider-token').fill('private-api-token');
 await page.selectOption('#providerSites',['demo']);await page.locator('#providerCaps input[value=dns]').check();await page.locator('#providerForm button[type=submit]').click();await page.waitForSelector('[data-provider-edit]');
 assert.ok(!(await page.locator('#providerList').textContent()).includes('private-api-token'));
 await page.locator('[data-provider-edit]').click();assert.equal(await page.locator('#provider-token').inputValue(),'');await page.locator('#provider-token').fill('unsaved-secret');await nav('sites');assert.equal(await page.locator('#provider-token').inputValue(),'');
 await nav('providers');await page.locator('#providerNew').click();await page.selectOption('#providerKind','cldy');assert.equal(await page.locator('#providerCaps input').count(),1);assert.match(await page.locator('#providerFields').textContent(),/SMTP/);
 await page.setViewportSize({width:375,height:812});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Provider form fits mobile');
 if(out)await page.screenshot({path:path.join(out,'providers-mobile.png'),fullPage:true});await page.setViewportSize({width:1440,height:1000});await page.locator('#providerCancel').click();
 page.once('dialog',d=>d.accept());await page.locator('[data-provider-delete]').click();await page.waitForFunction(()=>!document.querySelector('[data-provider-edit]'));
 console.log('PASS Name.com account scope, write-only credentials, CLDY capability guidance and responsive provider forms');
 for(const kind of ['webnic','vodien','readyspace','cpanel']){await page.locator('#providerNew').click();await page.selectOption('#providerKind',kind);assert.ok((await page.locator('#providerFields').textContent()).length>50);if(['vodien','readyspace'].includes(kind))assert.equal(await page.locator('#providerCaps input[value=dns]').count(),0);await page.locator('#providerCancel').click();}
 await page.locator('#providerNew').click();await page.selectOption('#providerKind','cpanel');await page.locator('#providerId').fill('cpanel-account');await page.locator('#providerName').fill('cPanel fixture');await page.locator('#provider-endpoint').fill('https://panel.example.com:2083');await page.locator('#provider-username').fill('demo');await page.locator('#provider-token').fill('private-cpanel-token');await page.selectOption('#providerSites',['demo']);await page.locator('#providerCaps input[value=dns]').check();await page.locator('#providerForm button[type=submit]').click();await page.waitForSelector('[data-provider-test]');
 await page.locator('[data-provider-test]').click();await page.waitForFunction(()=>document.querySelector('#providerMsg').textContent.includes('只读连接测试成功'));assert.ok(!(await page.locator('#providerList').textContent()).includes('private-cpanel-token'));
 failProviderProbe=true;await page.locator('[data-provider-test]').click();await page.waitForFunction(()=>document.querySelector('#providerMsg').textContent.includes('测试连接失败'));
 await nav('automation');await page.locator('#autoDNSConfig').evaluate(e=>e.open=true);await page.waitForFunction(()=>!document.querySelector('#autoPrepare').disabled);await page.selectOption('#autoDNSProvider','cpanel');assert.equal(await page.locator('#autoDNSAccount option[value=cpanel-account]').count(),1);assert.equal(await page.locator('#autoDNSToken').isDisabled(),true);
 await nav('providers');await page.locator('[data-provider-edit]').click();await page.setViewportSize({width:375,height:812});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);if(out)await page.screenshot({path:path.join(out,'sg-cpanel-mobile.png'),fullPage:true});await page.setViewportSize({width:1440,height:1000});await page.locator('#providerCancel').click();
 page.once('dialog',d=>d.accept());await page.locator('[data-provider-delete]').click();await page.waitForFunction(()=>!document.querySelector('[data-provider-edit]'));
 console.log('PASS Singapore provider capability boundaries, cPanel account, read-only probe success/failure and DNS account selection');

 await nav('domain');await page.locator('[data-domain-add]').click();
 await page.locator('#domainAccountProvider').fill('Registrar fixture');await page.locator('#domainAccountUrl').fill('https://registrar.example/');
 await page.locator('#domainAccountUsername').fill('operator@example.com');await page.locator('#domainAccountPassword').fill('fixture-password-only');await page.locator('#domainAccountConfig').fill('NS: ns1.example.com');
 await page.locator('#domainAccountForm button[type=submit]').click();await page.waitForSelector('[data-domain-reveal]');
 assert.equal(await page.locator('#domainAccountPassword').inputValue(),'');assert.ok(!(await page.locator('#dList').textContent()).includes('fixture-password-only'));
 await page.locator('#domainSearch').fill('ns1.example');assert.equal(await page.locator('[data-domain-edit]').count(),1);
 await page.locator('#domainSearch').fill('no-matching-provider');assert.equal(await page.locator('[data-domain-edit]').count(),0);await page.locator('#domainSearch').fill('');
 await page.locator('[data-domain-edit]').click();assert.equal(await page.locator('#domainAccountPassword').inputValue(),'');await page.locator('#domainAccountProvider').fill('Updated registrar');
 await page.locator('#domainAccountForm button[type=submit]').click();await page.waitForSelector('#domainAccountForm.hidden',{state:'attached'});
 await page.locator('[data-domain-reveal]').click();await page.locator('#domainRevealCode').fill('000000');await page.locator('#domainRevealSubmit').click();
 await page.waitForFunction(()=>document.querySelector('#domainRevealMsg').textContent.includes('TOTP 无效'));assert.equal(await page.locator('#domainSecretValue').inputValue(),'');
 await page.locator('#domainRevealCode').fill('123456');await page.locator('#domainRevealSubmit').click();await page.waitForSelector('#domainSecretWrap:not(.hidden)');
 assert.equal(await page.locator('#domainSecretValue').inputValue(),'fixture-password-only');
 await page.setViewportSize({width:375,height:812});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 if(out)await page.screenshot({path:path.join(out,'domain-reveal-mobile.png'),fullPage:true});
 await page.locator('#domainRevealClose').click();assert.equal(await page.locator('#domainSecretValue').inputValue(),'');
 await page.setViewportSize({width:1440,height:1000});await page.locator('[data-domain-reveal]').click();await page.locator('#domainRevealCode').fill('123456');await page.locator('#domainRevealSubmit').click();await page.waitForSelector('#domainSecretWrap:not(.hidden)');
 await page.waitForFunction(()=>document.querySelector('#domainSecretValue').value==='',null,{timeout:35000});
 await page.locator('#domainRevealClose').click();page.once('dialog',d=>d.accept());await page.locator('[data-domain-delete]').click();await page.waitForFunction(()=>!document.querySelector('[data-domain-edit]'));
 console.log('PASS domain account create, search, edit, TOTP reveal, mobile layout, automatic hiding and delete');
 await nav('sites');role='finance';await page.reload();await page.waitForSelector('#rows');await page.waitForFunction(()=>document.querySelector('[data-t=layout]').style.display==='none');
 assert.equal(await page.locator('.nav-group').last().isVisible(),false);
 assert.equal(await page.locator('#f').isVisible(),false);
 assert.deepEqual(errors,[]);
 console.log('PASS responsive menus, saved navigation, role filtering and no JavaScript errors');
 }finally{await browser.close();fs.rmSync(promptBase,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
