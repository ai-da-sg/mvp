/* Real application HTTP and follow-up persistence, isolated WP transport. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),env:{...process.env,KF_E2E_LEADS:'1'},stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse((await once(readline.createInterface({input:child.stdout}),'line'))[0]);browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new ConsolePage(page,cfg.origin);page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await ui.login('ops-test',cfg.password);await ui.ready();await ui.navigate('咨询线索');
  await page.waitForFunction(()=>document.querySelector('#ldFailures').textContent.includes('broken'));assert.match(await page.locator('#ldCount').innerText(),/101/);
  await page.locator('#ldMore').click();await page.waitForFunction(()=>!document.querySelector('#ldFailures').textContent);assert.match(await page.locator('#ldCount').innerText(),/102/);
  await page.locator('#ldMore').click();await page.waitForFunction(()=>document.querySelector('#ldMore').hidden);assert.match(await page.locator('#ldCount').innerText(),/104/);
  await page.locator('#ldSearch').fill('Enquiry 102');await page.locator('[data-lead-open="demo:102"]').click();
  assert.equal(await page.evaluate(()=>window.leadUnsafe),undefined);await page.locator('#leadStatus').selectOption('contacted');await page.locator('#leadNote').fill('Call tomorrow');
  page.once('dialog',d=>d.dismiss());await page.locator('#leadCancel').click();assert(await page.locator('#leadFormDialog').isVisible());
  const saved=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/leads/followup');await page.locator('#leadSave').click();assert.equal((await saved).status(),200);await page.locator('#leadFormDialog').waitFor({state:'hidden'});
  assert.match(await page.locator('#ldCount').innerText(),/104/,'Saving must retain the loaded pages');
  await page.locator('#ldStatus').selectOption('contacted');await page.locator('[data-lead-open="demo:102"]').click();assert.match(await page.locator('#leadHistory').innerText(),/Call tomorrow/);await page.locator('#leadCancel').click();
  await page.reload();await page.locator('#ldSlug').waitFor();await page.locator('#ldStatus').selectOption('contacted');await page.locator('[data-lead-open="demo:102"]').waitFor();
  await page.locator('#ldStatus').selectOption('');assert.equal(await page.locator('#ldArchived').count(),0);assert.equal(await page.locator('#ldSlug option[value="archived"]').count(),0);await page.locator('#ldSlug').selectOption('demo');await page.locator('[data-lead-open="demo:102"]').waitFor();
  await page.selectOption('#uiLanguage','en');await page.waitForFunction(()=>document.documentElement.lang==='en');await page.locator('[data-lead-open="demo:102"]').click();
  await page.setViewportSize({width:375,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  if(process.env.E2E_OUTPUT){fs.mkdirSync(process.env.E2E_OUTPUT,{recursive:true});await page.screenshot({path:path.join(process.env.E2E_OUTPUT,'leads-mobile.png'),fullPage:true});}
  assert(!/[\u3400-\u9fff]/.test(await page.locator('#leadFormDialog').innerText()));await page.locator('#leadCancel').click();
  await page.setViewportSize({width:1440,height:1000});await page.selectOption('#uiLanguage','zh');await ui.logout();await ui.login('finance-test',cfg.password);await ui.ready();assert.equal((await page.request.get(cfg.origin+'/api/leads')).status(),403);
  assert.deepEqual(errors,[]);console.log('PASS enquiry partial-failure retry, cross-site pagination, archived filters, persistent follow-ups, dirty protection, XSS escaping, mobile/English and finance boundary');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
