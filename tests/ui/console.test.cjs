/* Run production HTML/JS against isolated API fixtures; never connect to live services. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'../..');
const promptBase=fs.mkdtempSync(path.join(require('node:os').tmpdir(),'kf-prompt-ui-'));
function promptAPI(action,body={}){return JSON.parse(execFileSync('python3',['-c',`import sys,json;sys.path.insert(0,'core');import kf_prompts;s=kf_prompts.PromptStore(sys.argv[1]);b=json.load(sys.stdin);action=sys.argv[2];r=s.compose(b['selection'],b.get('brief','')) if action=='preview' else (s.change(b) if action=='save' else s.public(True));print(json.dumps(r,ensure_ascii=False))`,promptBase,action],{cwd:root,input:JSON.stringify(body),encoding:'utf8'}));}
const pages=JSON.parse(execFileSync('python3',['-c',`
import ast,json,pathlib
import sys
sys.path.insert(0,'core')
import kf_prompts
m=ast.parse(pathlib.Path('console/kf_console.py').read_text())
result={'library':dict(kf_prompts.defaults(),variables=kf_prompts.VARIABLES,categories=kf_prompts.CATEGORIES,sources=kf_prompts.SOURCES,can_manage=True)}
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
 let role='admin',failSave=false,failPublish=false;const calls=[];
 const state=()=>({role,me:'reviewer',sites:[{slug:'demo',company:'演示工作室',domain:'demo.example',state:'active',http:200,running:2,port:18080,owner:'reviewer',plan:'Starter',days_left:20}],plans:[{id:'starter',name:'Starter',price:1800}],industries:[['tech','科技']],invoices:[]});
 const spec={dirty:false,types:['hero'],schemas:{hero:{label:'首屏',fields:[{k:'title',label:'标题',type:'text'}]}},spec:{pages:[{slug:'home',title:'首页',sections:[{type:'hero',title:'A'},{type:'hero',title:'B'}]},{slug:'contact',title:'联系',sections:[{type:'hero',title:'Contact'}]}]}};
 await context.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname;
  assert.equal(u.hostname,'review.invalid','Unexpected external request');
  if(p==='/'||p==='/login')return route.fulfill({contentType:'text/html',body:pages[p==='/'?'console':'login']});
  if(['/ai.js','/prompts.js','/locale.js','/appearance.js'].includes(p))return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(root,'console',p.slice(1)),'utf8')});
  if(p.startsWith('/preview/')){calls.push({path:p});return route.fulfill({contentType:'text/html',body:'<h1>Preview</h1>'});}
  let data={items:[]},status=200;
  if(p==='/api/state')data=state();
  if(p.startsWith('/api/spec/'))data=spec;
  if(p==='/api/spec'){
   const body=req.postDataJSON();calls.push({path:p,body});
   if(failSave){status=503;data={error:'模拟保存失败'};}
   else{spec.spec.pages.find(p=>p.slug===body.page).sections=body.sections;spec.dirty=true;data={ok:true};}
  }
  if(p==='/api/publish'){calls.push({path:p,body:req.postDataJSON()});status=failPublish?500:200;data=failPublish?{error:'模拟发布失败'}:{pages:1,dirty:false};}
  if(p==='/api/ai/prompts'){if(req.method()==='POST')promptAPI('save',req.postDataJSON());data={...promptAPI('read'),can_manage:role==='admin'};}
  if(p==='/api/ai/prompts/preview')data=promptAPI('preview',req.postDataJSON());
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
 role='finance';await page.reload();await page.waitForSelector('#rows');await page.waitForFunction(()=>document.querySelector('[data-t=layout]').style.display==='none');
 assert.equal(await page.locator('.nav-group').last().isVisible(),false);
 assert.equal(await page.locator('#f').isVisible(),false);
 assert.deepEqual(errors,[]);
 console.log('PASS responsive menus, saved navigation, role filtering and no JavaScript errors');
 }finally{await browser.close();fs.rmSync(promptBase,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
