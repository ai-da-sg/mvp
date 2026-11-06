/* Real HTTP operations workflow with disposable application data. */
const assert=require('node:assert/strict'),path=require('node:path');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
const fs=require('node:fs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),env:{...process.env,KF_E2E_OPERATIONS:'1'},stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse((await once(readline.createInterface({input:child.stdout}),'line'))[0]);browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new ConsolePage(page,cfg.origin);page.setDefaultTimeout(15000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));await ui.login('ops-test',cfg.password);await ui.ready();
  await page.locator('#operationInbox summary').click();
  await page.locator('[data-operation-ack]').waitFor();
  const data=await (await page.request.get(cfg.origin+'/api/operations/overview')).json();
  const job=data.items.find(x=>x.kind==='generation');assert(job);assert(!JSON.stringify(data).includes('Private generation details'));
  const ack=page.locator(`[data-operation-ack="${job.id}"]`);
  page.once('dialog',d=>d.dismiss());await ack.click();assert.equal(await ack.count(),1);
  page.once('dialog',d=>d.accept());await ack.click();await ack.waitFor({state:'detached'});
  await page.getByLabel('包含已知悉',{exact:true}).check();await ack.waitFor();assert.equal(await ack.innerText(),'恢复提醒');
  await ack.click();await page.waitForFunction(id=>document.querySelector(`[data-operation-ack="${id}"]`)?.textContent==='已知悉',job.id);
  await page.getByLabel('搜索待办',{exact:true}).fill('不存在的待办');assert.equal(await page.locator('[data-operation-open]').count(),0);
  await page.getByLabel('搜索待办',{exact:true}).fill('');await ack.waitFor();
  const refreshed=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/state'&&new URL(r.url()).searchParams.get('refresh')==='1');
  await page.getByRole('button',{name:'立即检测',exact:true}).click();assert.equal((await refreshed).status(),200);
  await page.selectOption('#uiLanguage','en');await page.waitForFunction(()=>document.documentElement.lang==='en');
  await page.waitForFunction(()=>document.querySelector('#operationList').textContent.includes('Site generation failed'));
  assert(!/[\u3400-\u9fff]/u.test(await page.locator('#operationInbox').innerText()));
  const confirmation=page.waitForEvent('dialog');
  const clicking=ack.click();const dialog=await confirmation;
  assert.match(dialog.message(),/Hide this item from my inbox/);assert(!/[\u3400-\u9fff]/u.test(dialog.message()));await dialog.dismiss();await clicking;
  await page.getByLabel('Search tasks',{exact:true}).fill('no-matching-task');
  await page.selectOption('#uiLanguage','zh');await page.waitForFunction(()=>document.querySelector('#operationList').textContent.includes('没有匹配记录'));
  assert.equal(await page.locator('#operationSearch').inputValue(),'no-matching-task');
  await page.selectOption('#uiLanguage','en');await page.waitForFunction(()=>document.querySelector('#operationList').textContent.includes('No matching records'));
  assert.equal(await page.locator('#operationList [data-admin-page="-1"]').innerText(),'Previous');
  await page.getByLabel('Search tasks',{exact:true}).fill('');await ack.waitFor();
  await page.setViewportSize({width:375,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  if(process.env.E2E_OUTPUT){fs.mkdirSync(process.env.E2E_OUTPUT,{recursive:true});await page.screenshot({path:path.join(process.env.E2E_OUTPUT,'operations-mobile.png'),fullPage:true});}
  await page.setViewportSize({width:1440,height:1000});await page.selectOption('#uiLanguage','zh');
  await page.locator(`[data-operation-open="${job.id}"]`).click();
  await page.waitForFunction(id=>document.activeElement?.dataset.operationReference===id,job.reference);
  assert.equal(await page.evaluate(()=>CURRENT_TAB),'ai');
  await ui.logout();await ui.login('finance-test',cfg.password);await ui.ready();assert(await page.locator('#operationInbox').isHidden());
  assert.equal((await page.request.get(cfg.origin+'/api/operations/overview')).status(),403);
  assert.deepEqual(errors,[]);console.log('PASS real HTTP inbox, personal acknowledgement and restoration, search, manual probe, task navigation, bilingual/mobile UI and finance boundary');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
