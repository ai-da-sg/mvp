/* Real HTTP history/recovery UI; WordPress transport is covered separately. */
const assert=require('node:assert/strict'),path=require('node:path');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),env:{...process.env,KF_E2E_PUBLICATION:'1'},stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse((await once(readline.createInterface({input:child.stdout}),'line'))[0]);browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new ConsolePage(page,cfg.origin);page.setDefaultTimeout(15000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));await ui.login('admin',cfg.password);await ui.ready();await ui.navigate('页面编辑');
  await page.locator('#publicationHistory summary').click();await page.locator('[data-publication-restore]').waitFor();assert.match(await page.locator('#publicationList').innerText(),/全部发布成功/);
  const before=await page.evaluate(async()=>await aiRequest('/api/publications/demo'));assert.equal(before.items.length,1);assert(!('before' in before.items[0]));assert(!('after' in before.items[0]));
  await page.locator('[data-publication-view]').click();assert.match(await page.locator('#adminDetailDialog').innerText(),/home/);await page.locator('#adminDetailDialog button').click();
  await page.selectOption('#uiLanguage','en');await page.waitForFunction(()=>document.documentElement.lang==='en');assert.match(await page.locator('#publicationList').innerText(),/Fully published/);
  page.once('dialog',d=>d.dismiss());await page.locator('[data-publication-restore]').click();assert.equal(await page.locator('[data-publication-restore]').count(),1);
  page.once('dialog',d=>d.accept());const restored=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/publish/restore');await page.locator('[data-publication-restore]').click();assert.equal((await restored).status(),200);
  await page.waitForFunction(()=>!document.querySelector('[data-publication-restore]'));assert.match(await page.locator('#publicationList').innerText(),/Restored/);
  const spec=await page.evaluate(async()=>await aiRequest('/api/spec/demo'));assert.equal(spec.spec.pages[0].title,'Publication recovery fixture');assert.equal(spec.dirty,true);
  await page.setViewportSize({width:375,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.setViewportSize({width:1440,height:1000});await page.selectOption('#uiLanguage','zh');await ui.logout();await ui.login('finance-test',cfg.password);await ui.ready();assert.equal((await page.request.get(cfg.origin+'/api/publications/demo')).status(),403);
  assert.deepEqual(errors,[]);console.log('PASS real HTTP publication history, redacted snapshots, restore confirmation, persisted recovery, draft retention, bilingual/mobile UI and finance boundary');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
