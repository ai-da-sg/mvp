/* Real HTTP build review and persisted prompt version evidence. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse((await once(readline.createInterface({input:child.stdout}),'line'))[0]);browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new ConsolePage(page,cfg.origin);page.setDefaultTimeout(15000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));await ui.login('admin',cfg.password);await ui.ready();await ui.navigate('AI 建站');
  await page.locator('#aiProfile option').first().waitFor({state:'attached'});assert(await page.locator('#aiGenerate').isHidden());
  await page.locator('#aiMode').selectOption('new');await page.locator('#aiBuildNext').click();
  assert.equal(await page.locator('#aiBuildSteps [aria-current="step"]').getAttribute('data-build-step'),'1');
  assert.equal(await page.locator('#aiCompany').evaluate(e=>e===document.activeElement),true,await page.evaluate(()=>JSON.stringify({focus:document.activeElement?.id,invalid:[...document.querySelectorAll('#aiBuildStep1 input,#aiBuildStep1 select')].filter(e=>!e.validity.valid).map(e=>e.id)})));
  await page.locator('#aiMode').selectOption('existing');await ui.buildStep(2);await page.locator('#aiBuildNext').click();
  assert.equal(await page.locator('#aiBrief').evaluate(e=>e===document.activeElement),true);
  await page.getByLabel('建站要求 / 额外补充',{exact:true}).fill('A truthful service website.');await ui.buildStep(2);
  await page.locator('#aiPromptTemplate').selectOption('company');await page.locator('#promptServices').fill('Website maintenance');
  await page.locator('#promptAudience').fill('Singapore SMEs');await page.locator('#promptGoal').fill('Request a quote');
  const reviewed=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/ai/prompts/preview');await ui.buildStep(3);const snapshot=await(await reviewed).json();
  for(const m of snapshot.modules)assert((await page.locator('#aiBuildReview').innerText()).includes(m.name+' · v'+m.version));
  assert(await page.locator('#aiGenerate').isVisible());assert(await page.locator('#aiBuildStep2').isHidden());
  await ui.buildStep(1);assert.equal(await page.locator('#aiBrief').inputValue(),'A truthful service website.');
  await page.locator('#aiBrief').fill('Updated, truthful service website.');await ui.buildStep(2);assert.equal(await page.locator('#promptServices').inputValue(),'Website maintenance');await ui.buildStep(3);
  await page.selectOption('#uiLanguage','en');await page.waitForFunction(()=>document.documentElement.lang==='en');assert((await page.locator('#aiStepTitle3').innerText()).includes('Review'));
  for(const theme of ['light','dark'])for(const width of [375,768,1440]){
   await page.selectOption('#uiTheme',theme);await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   if(process.env.E2E_OUTPUT){fs.mkdirSync(process.env.E2E_OUTPUT,{recursive:true});await page.screenshot({path:path.join(process.env.E2E_OUTPUT,`builder-${theme}-${width}.png`),fullPage:true});}
  }
  // Another operator edits the library after review; submission must reject
  // the stale revision before creating any generation job.
  await page.evaluate(async()=>{
   const library=await aiRequest('/api/ai/prompts');const item=library.templates.find(t=>t.id==='company');
   await aiRequest('/api/ai/prompts',{...item,action:'save',kind:'templates',revision:library.revision,description:item.description+' Updated.'});
  });
  const stale=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/ai/prompts/preview');await page.locator('#aiGenerate').click();assert.equal((await stale).status(),409);
  assert.equal((await(await page.request.get(cfg.origin+'/api/ai/jobs')).json()).jobs.length,0);
  await ui.buildStep(2);const refreshed=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/ai/prompts');await page.locator('#aiBuildRefreshPrompts').click();await refreshed;
  await page.waitForFunction(()=>!document.querySelector('#aiBuildRefreshPrompts').disabled);await ui.buildStep(3);
  const submitted=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/ai/build'&&r.request().method()==='POST');await page.locator('#aiGenerate').click();const response=await submitted;assert.equal(response.status(),202);const job=(await response.json()).job;
  await page.waitForFunction(async id=>{const d=await(await fetch('/api/ai/jobs')).json();return d.jobs.find(j=>j.id===id)?.status==='completed';},job.id);
  const saved=(await(await page.request.get(cfg.origin+'/api/ai/jobs')).json()).jobs.find(j=>j.id===job.id);
  assert.deepEqual(saved.prompt.modules,snapshot.modules);assert.equal(saved.prompt.template.version,snapshot.template.version+1);assert(saved.prompt.preview.includes('Updated, truthful service website.'));
  await page.locator(`[data-operation-reference="${job.id}"]`).waitFor();await page.locator(`[data-operation-reference="${job.id}"] details summary`).click();
  for(const m of snapshot.modules)assert((await page.locator(`[data-operation-reference="${job.id}"]`).innerText()).includes(m.name+' · v'+m.version));
  assert.deepEqual(errors,[]);console.log('PASS real HTTP staged builder, validated module/version review, retained inputs, bilingual/responsive themes and persisted generation snapshot');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
