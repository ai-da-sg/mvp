const assert=require('node:assert/strict'),path=require('node:path');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const live=process.env.KF_E2E_GEO_COLLECTION==='live';
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),env:{...process.env,KF_E2E_GEO_COLLECTION:live?'live':'fixture'},stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse(await once(readline.createInterface({input:child.stdout}),'line').then(([line])=>line));browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new ConsolePage(page,cfg.origin);page.setDefaultTimeout(live?180000:15000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=500)errors.push(r.url()+' '+r.status());});page.on('dialog',d=>d.accept());
  await ui.login('admin',cfg.password);await ui.ready();await ui.navigate('GEO 采集连接');
  await page.locator('[data-gc-action=new-connection]').click();await page.locator('#gcID').fill('geo-test');await page.locator('#gcName').fill('Search connection');await page.locator('#gcSites').selectOption('demo');
  if(live)await page.locator('#gcImport').selectOption(process.env.KF_E2E_REAL_AI_PROFILE||'chatgpt');else await page.locator('#gcKey').fill('fixture-test-secret');
  await page.locator('#gcConnectionForm button[type=submit]').click();await page.locator('#gcConnectionForm').waitFor({state:'detached'});
  await page.locator('[data-gc-action=test]').click();await page.waitForFunction(()=>!GEO_COLLECTION.busy);assert.match(await page.locator('#gcAccounts').innerText(),/已验证/);
  await page.locator('[data-gc-action=edit-connection]').click();assert.equal(await page.locator('#gcKey').inputValue(),'');
  await page.locator('#gcName').fill('Unsaved connection name');await page.selectOption('#uiLanguage','en');
  await page.waitForFunction(()=>document.querySelector('#gcConnectionForm h3')?.textContent==='Edit connection');
  assert.equal(await page.locator('#gcName').inputValue(),'Unsaved connection name');
  assert(!/[\u3400-\u9fff]/u.test(await page.locator('#geoSettingsRoot').innerText()));
  await page.locator('[data-gc-action=cancel-connection]').click();await page.selectOption('#uiLanguage','zh');
  await ui.navigate('GEO');await page.locator('#geoBrand').fill('Demo');
  await page.locator('#geoProfileForm button[type=submit]').click();await page.waitForFunction(()=>!GEO.busy);
  await page.locator('[data-geo-step="2"]').click();await page.locator('#geoStepContent > details > summary').first().click();await page.locator('#geoQuestion').fill('What is the official website of the National Library Board of Singapore?');
  await page.locator('#geoQuestionForm button[type=submit]').click();await page.waitForFunction(()=>!GEO.busy);
  await page.locator('[data-geo-step="3"]').click();await page.locator('[data-gc-action=new-plan]').click();await page.locator('#gcPlanName').fill('Baseline');
  await page.locator('#gcQuestions').selectOption({index:0});await page.locator('#gcConnections').selectOption('geo-test');
  await page.locator('#gcPlanForm button[type=submit]').click();await page.locator('#gcPlanForm').waitFor({state:'detached'});
  await page.locator('[data-gc-action=run]').click();await page.waitForFunction(()=>!GEO_COLLECTION.busy);
  await page.waitForFunction(()=>document.getElementById('gcRuns')?.innerText.includes('完成'),null,{timeout:live?180000:15000});
  const data=await page.evaluate(async()=>({collection:await gcRequest('config?slug=demo'),workspace:await aiRequest('/api/geo/workspace?slug=demo')}));
  assert.equal(data.collection.runs[0].result.status,'completed');assert.equal(data.collection.accounts[0].requests_today,2);assert.equal(data.workspace.workspace.observations.length,1);assert.equal(data.workspace.workspace.observations[0].provenance,'official_api');assert(!JSON.stringify(data).includes('fixture-test-secret'));
  await page.selectOption('#uiLanguage','en');await page.waitForFunction(()=>document.documentElement.lang==='en');await page.locator('[data-gc-action=new-plan]').waitFor();
  assert(!/[\u3400-\u9fff]/u.test(await page.locator('#geoCollection').innerText()));
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert.deepEqual(errors,[]);console.log(live?'GEO live official API browser collection passed.':'GEO collection browser flow passed with deterministic provider response.');
 }finally{if(browser)await browser.close();child.stdin.end();if(child.exitCode===null)await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1;});
