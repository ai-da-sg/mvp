/* Style management through real HTTP handlers and real draft generation. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','inherit']});let browser;
 try{
  const lines=readline.createInterface({input:child.stdout});const cfg=JSON.parse((await once(lines,'line'))[0]);
  browser=await chromium.launch();const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(15000);
  const ui=new ConsolePage(page,cfg.origin),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await ui.login('admin',cfg.password);await ui.ready();await ui.navigate('风格模板');
  await page.waitForFunction(()=>document.querySelectorAll('.style-card').length===28);
  const initial=await(await page.request.get(cfg.origin+'/api/ai/styles')).json();assert.equal(initial.templates.length,28);
  const counts=initial.templates.reduce((m,t)=>(m[t.sector]=(m[t.sector]||0)+1,m),{});
  for(const [sector,count] of Object.entries(counts)){
   await page.selectOption('#styleSectorFilter',sector);
   assert.equal(await page.locator('.style-card').count(),count,sector);
  }
  await page.selectOption('#styleSectorFilter','hospitality');
  await page.locator('#styleSearch').fill('Tidal');assert.equal(await page.locator('.style-card').count(),1);
  await page.selectOption('#styleStatus','disabled');assert.equal(await page.locator('.style-card').count(),0);
  await page.selectOption('#styleStatus','');await page.locator('#styleSearch').fill('');await page.selectOption('#styleSectorFilter','');
  await page.locator('#styleNew').evaluate(e=>{const d=e.closest('details');if(d)d.open=true;});await page.locator('#styleNew').click();await page.locator('#styleSector').selectOption('restaurant');await page.locator('#styleName').fill('E2E editorial');await page.locator('#styleCategory').fill('Testing');await page.locator('#styleIndustry').selectOption('restaurant');await page.locator('#styleTags').fill('original, test');
  await page.getByText('高级视觉参数',{exact:true}).click();await page.locator('#styleAdv-heading_size').fill('84');await page.locator('#styleAdv-hero').selectOption('editorial');await page.locator('#styleAdv-columns').fill('2');
  await page.locator('#styleButtonRadius').fill('4');await page.getByText('页面结构与特殊要求',{exact:true}).click();await page.locator('#styleBlockType').selectOption('gallery');await page.locator('#styleAddBlock').click();
  await page.locator('#stylePreviewEdit').click();await page.frameLocator('#stylePreviewFrame').getByRole('heading',{name:'E2E editorial',exact:true}).waitFor();assert.equal(await page.locator('#stylePreviewFrame').getAttribute('sandbox'),'');
  assert.equal(await page.frameLocator('#stylePreviewFrame').locator('html').evaluate(e=>getComputedStyle(e).getPropertyValue('--kf-heading-size').trim()),'84px');
  await page.selectOption('#stylePreviewWidth','375px');assert.equal(Math.round((await page.locator('#stylePreviewFrame').boundingBox()).width),375);
  await page.locator('#stylePreviewClose').click();
  const saved=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/ai/styles'&&r.request().method()==='POST');await page.locator('#styleEditForm button[type=submit]').click();const data=await(await saved).json();assert(data.item,data.error);let item=data.item;
  assert.equal(item.industry,'restaurant');assert.equal(item.sector,'restaurant');assert.equal(item.tokens.advanced.heading_size,84);assert.equal(item.blueprint.at(-1),'gallery');
  await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.style-card').length===29);
  await page.locator(`[data-style-edit="${item.id}"]`).evaluate(e=>{const d=e.closest('details');if(d)d.open=true;});await page.locator(`[data-style-edit="${item.id}"]`).click();assert.equal(await page.locator('#styleAdv-heading_size').inputValue(),'84');
  await page.locator('#styleName').fill('Retained local edit');page.once('dialog',d=>d.dismiss());await ui.navigate('站点总览');assert.equal(await page.locator('#p-styles').isVisible(),true);
  page.once('dialog',d=>d.accept());await page.locator('#styleCancel').click();
  await page.locator(`[data-style-export="${item.id}"]`).evaluate(e=>{const d=e.closest('details');if(d)d.open=true;});await page.locator(`[data-style-export="${item.id}"]`).click();
  await page.locator('#styleImportFile').setInputFiles({name:'import.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({...item,name:'Imported recipe'}))});await page.locator('#styleName').waitFor();assert.equal(await page.locator('#styleName').inputValue(),'Imported recipe');
  const imported=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/ai/styles'&&r.request().method()==='POST');await page.locator('#styleEditForm button[type=submit]').click();const copy=(await(await imported).json()).item;assert.notEqual(copy.id,item.id);assert.equal(copy.sector,'restaurant');
  await page.locator('#styleSearch').fill('Imported recipe');await page.waitForFunction(()=>document.querySelectorAll('.style-card').length===1);
  page.once('dialog',d=>d.accept());await page.locator(`[data-style-delete="${copy.id}"]`).evaluate(e=>{const d=e.closest('details');if(d)d.open=true;});await page.locator(`[data-style-delete="${copy.id}"]`).click();await page.getByText('尚无匹配模板。可新建模板或调整筛选条件。',{exact:true}).waitFor();
  await page.locator('#styleSearch').fill('E2E editorial');await page.locator(`[data-style-use="${item.id}"]`).evaluate(e=>{const d=e.closest('details');if(d)d.open=true;});await page.locator(`[data-style-use="${item.id}"]`).click();await page.locator('#aiBrief').fill('Create a concise restaurant website with truthful sample content.');await page.locator('#aiProfile').selectOption('mock');
  assert.equal(await page.locator('#aiStyleTemplate').inputValue(),item.id);assert.equal(await page.locator('#aiStyleSector').inputValue(),'restaurant');
  assert.equal(await page.locator('#aiStyleTemplate option[data-user-content]').count(),counts.restaurant+1);
  const build=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/ai/build'&&r.request().method()==='POST');await page.locator('#aiGenerate').click();const job=(await(await build).json()).job;assert(job);
  await page.waitForFunction(async id=>{const r=await fetch('/api/ai/jobs');const d=await r.json();return d.jobs.find(j=>j.id===id)?.status==='completed';},job.id);
  const completed=(await(await page.request.get(cfg.origin+'/api/ai/jobs')).json()).jobs.find(j=>j.id===job.id);assert.equal(completed.style.tokens.advanced.heading_size,84);assert.equal(completed.style.industry,'restaurant');assert.equal(completed.style.sector,'restaurant');
  const preview=await(await page.request.get(cfg.origin+'/preview/demo/home')).text();assert(preview.includes('--kf-heading-size:84px'));assert(preview.includes('--kf-columns:2'));
  for(const width of [375,768,1440]){await page.setViewportSize({width,height:1000});if(await page.locator('#navToggle').isVisible())await page.locator('#navToggle').click();await ui.navigate('风格模板');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
  assert.deepEqual(errors,[]);console.log('PASS real style CRUD/import, responsive preview, unsaved protection, model-simulation draft and advanced design persistence');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
