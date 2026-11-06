/* Real HTTP financial views, adjustment history and idempotent payment. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),env:{...process.env,KF_E2E_BILLING:'1'},stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse((await once(readline.createInterface({input:child.stdout}),'line'))[0]);browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new ConsolePage(page,cfg.origin);page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await ui.login('finance-test',cfg.password);await ui.ready();await ui.navigate('账单收款');assert.equal(await page.locator('[data-bill-view]').count(),3);
  await page.locator('#billView').selectOption('overdue');assert.equal(await page.locator('[data-bill-view]').count(),1);
  const no=await page.locator('[data-bill-edit]').getAttribute('data-bill-edit');await page.locator('[data-bill-edit]').click();
  await page.locator('#billSubtotal').fill('120');await page.locator('#billTax').fill('10');await page.locator('#billDue').fill('2035-01-01');await page.locator('#billReason').fill('Additional agreed work');
  page.once('dialog',d=>d.dismiss());await page.locator('#billCancel').click();assert(await page.locator('#billFormDialog').isVisible());
  const adjusted=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/invoice/adjust');await page.locator('#billSave').click();assert.equal((await adjusted).status(),200);await page.locator('#billFormDialog').waitFor({state:'hidden'});await page.waitForFunction(()=>!document.querySelector('[data-bill-view]'));assert.equal(await page.locator('[data-bill-view]').count(),0);
  await page.locator('#billView').selectOption('unpaid');await page.locator(`[data-bill-view="${no}"]`).click();assert.match(await page.locator('#adminDetailDialog').innerText(),/Additional agreed work/);await page.locator('#adminDetailDialog button').click();
  page.once('dialog',d=>d.dismiss());await page.locator(`[data-bill-pay="${no}"]`).click();assert.equal(await page.locator(`[data-bill-pay="${no}"]`).count(),1);
  page.once('dialog',d=>d.accept());const paid=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/invoice/pay');await page.locator(`[data-bill-pay="${no}"]`).click();assert.equal((await paid).status(),200);await page.locator(`[data-bill-pay="${no}"]`).waitFor({state:'detached'});
  await page.evaluate(no=>aiRequest('/api/invoice/pay',{no}),no);const ledger=await(await page.request.get(cfg.origin+'/api/ledger/demo')).json();assert.equal(ledger.items.filter(x=>x.payment_invoice===no).length,1);
  await page.locator('#billView').selectOption('paid');assert.equal(await page.locator('[data-bill-view]').count(),2);assert.equal(await page.locator('[data-bill-edit]').count(),0);
  await page.locator('#billView').selectOption('unset');assert.equal(await page.locator('[data-bill-view]').count(),1);await page.locator('#billArchived').check();assert.equal(await page.locator('[data-bill-view]').count(),2);
  await page.locator('#billView').selectOption('services');await page.locator('[data-bill-renew="demo"]').waitFor();
  await page.locator('#billView').selectOption('all');await page.selectOption('#uiLanguage','en');await page.waitForFunction(()=>document.documentElement.lang==='en');await page.waitForFunction(()=>!/[\u3400-\u9fff]/.test(document.querySelector('#billMsg').textContent));
  await page.locator('[data-bill-edit]').first().click();await page.setViewportSize({width:375,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert(!/[\u3400-\u9fff]/.test(await page.locator('#billFormDialog').innerText()));
  if(process.env.E2E_OUTPUT){fs.mkdirSync(process.env.E2E_OUTPUT,{recursive:true});await page.screenshot({path:path.join(process.env.E2E_OUTPUT,'billing-mobile.png'),fullPage:true});}
  await page.locator('#billCancel').click();await page.setViewportSize({width:1440,height:1000});await page.selectOption('#uiLanguage','zh');await ui.logout();await ui.login('ops-test',cfg.password);await ui.ready();await ui.navigate('账单收款');assert.equal(await page.locator('[data-bill-edit],[data-bill-pay]').count(),0);
  assert.deepEqual(errors,[]);console.log('PASS real invoice filters, archived scope, adjustment history, dirty protection, payment confirmation/idempotency, finance/ops boundary and bilingual mobile dialog');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
