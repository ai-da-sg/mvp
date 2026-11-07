/* Real console endpoints and persistent disposable site data. */
const assert=require('node:assert/strict'),path=require('node:path');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
class GeoPage extends ConsolePage {
 async step(index){await this.page.locator(`[data-geo-step="${index}"]`).click();await this.page.locator(`[data-geo-step="${index}"][aria-current="step"]`).waitFor();}
 async save(form,endpoint){const response=this.page.waitForResponse(r=>r.url().endsWith('/api/geo/'+endpoint)&&r.request().method()==='POST');await this.page.locator(form).locator('button[type=submit]').click();assert.equal((await response).status(),200);await this.page.waitForFunction(()=>!GEO.busy);}
}
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),env:process.env,stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse(await Promise.race([once(readline.createInterface({input:child.stdout}),'line').then(([line])=>line),once(child,'exit').then(([code])=>{throw Error('Fixture exited before readiness: '+code);})]));browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new GeoPage(page,cfg.origin);page.setDefaultTimeout(15000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));await ui.login('ops-test',cfg.password);await ui.ready();await ui.navigate('GEO');
  await page.locator('#geoProfileForm').waitFor();await page.locator('#geoBrand').fill('Demo workshop');await ui.save('#geoProfileForm','profile');
  await ui.step(1);await page.locator('#geoStepContent > details > summary').click();await page.locator('#geoFactEn').fill('Offers weekly workshops');await page.locator('#geoFactZh').fill('提供每周工作坊');await page.locator('#geoSource').fill('https://example.test/services');await page.locator('#geoApproved').check();await ui.save('#geoFactForm','facts');
  assert.match(await page.locator('#geoFactList').innerText(),/Offers weekly workshops/);
  await ui.step(2);await page.locator('#geoStepContent > details > summary').first().click();await page.locator('#geoQuestion').fill('Which workshops are available?');await ui.save('#geoQuestionForm','questions');
  await ui.step(3);await page.getByText('记录一次搜索观测',{exact:true}).click();await page.locator('#geoPlatform').fill('Example search');await page.locator('#geoMode').fill('Search');await page.locator('#geoEnvironment').fill('Singapore; signed out; new conversation');await page.locator('#geoAnswer').fill('Demo workshop offers weekly workshops.');await page.locator('#geoCitations').fill('https://example.test/services');await page.locator('#geoMention').selectOption('yes');await page.locator('#geoAccuracy').selectOption('yes');await ui.save('#geoObservationForm','observations');
  await ui.step(5);assert.match(await page.locator('#geoMetrics').innerText(),/1\/1 \(100%\)/);
  await page.locator('[data-geo-action=evidence]').click();assert.match(await page.locator('#adminDetailDialog').innerText(),/operator_import/);await page.locator('#adminDetailDialog button').first().click();
  const download=page.waitForEvent('download');await page.locator('[data-geo-action=export]').first().click();assert.match((await download).suggestedFilename(),/^geo-demo/);
  await page.selectOption('#uiLanguage','en');await page.waitForFunction(()=>document.documentElement.lang==='en');
  assert(!/[\u3400-\u9fff]/u.test(await page.locator('#geoRoot').innerText()));
  await ui.step(0);await page.locator('#geoBrand').fill('Unsaved');page.once('dialog',d=>d.dismiss());await page.locator('[data-geo-step="1"]').click();assert.equal(await page.locator('#geoBrand').inputValue(),'Unsaved');
  page.once('dialog',d=>d.accept());await ui.step(1);await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:'/tmp/mvp-geo-mobile.png',fullPage:true});
  await page.reload();await page.locator('#geoRoot #geoProfileForm').waitFor();assert.equal(await page.locator('#geoBrand').inputValue(),'Demo workshop');
  assert.deepEqual(errors,[]);console.log('GEO real HTTP browser flow passed: facts, questions, observations, metrics, export, English, mobile, persistence.');
 }finally{if(browser)await browser.close();child.stdin.end();if(child.exitCode===null)await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1;});
