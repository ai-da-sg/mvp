/* Domain registry and provider-account CRUD through real HTTP handlers. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse((await once(readline.createInterface({input:child.stdout}),'line'))[0]);browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new ConsolePage(page,cfg.origin);
  await page.addInitScript(()=>{window.pendingRequests=0;const original=window.fetch;window.fetch=async(...a)=>{window.pendingRequests++;try{return await original(...a)}finally{window.pendingRequests--}}});
  async function settle(){await page.waitForFunction(()=>window.pendingRequests===0);await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));}
  await ui.login('admin',cfg.password);await ui.ready();await ui.navigate('域名管理');await settle();
  assert.equal(await page.locator('#dList table').count(),1);
  assert.deepEqual(await page.evaluate(()=>[-1,0,1].map(offset=>domainExpiry({manage:{expires:new Date(Date.now()+8*3600000+offset*86400000).toISOString().slice(0,10)}}))),[-1,0,1]);
  await page.locator('#domainNew').click();await page.locator('#domainRecordName').fill('registry.sg');await page.locator('#domainRecordCompany').fill('Registry customer');await page.locator('#domainRecordRegistrar').fill('Name.com');await page.locator('#domainRecordExpiry').fill('2027-01-01');await page.locator('#domainRecordForm button[type=submit]').click();await settle();
  assert.equal(await page.locator('#domainRecordDialog').isVisible(),false);
  await page.evaluate(async()=>{for(let i=0;i<24;i++)await domainRequest('/api/domain/records',{domain:`fixture-${i}.sg`});await loadDomainRegistry();});
  assert.equal(await page.locator('#dList tbody tr').count(),25);await page.locator('#domainNext').click();assert.equal(await page.locator('#dList tbody tr').count(),1);
  await page.locator('#domainSearch').fill('registry.sg');assert.equal(await page.locator('#dList tbody tr').count(),1);
  await page.locator('[data-domain-record-edit]').click();await page.locator('#domainRecordRegistrar').fill('Updated registrar');await page.locator('#domainRecordForm button[type=submit]').click();await settle();assert.match(await page.locator('#dList').innerText(),/Updated registrar/);
  await page.locator('[data-domain-view]').click();await page.locator('#domainDetailAdd').click();await page.locator('#domainAccountProvider').fill('Registrar portal');await page.locator('#domainAccountUrl').fill('https://example.com/admin');await page.locator('#domainAccountUsername').fill('operator@example.com');await page.locator('#domainAccountPassword').fill('private-fixture-password');await page.locator('#domainAccountConfig').fill('Nameservers: ns1.example.com');await page.locator('#domainAccountForm button[type=submit]').click();await settle();
  assert.equal(await page.locator('#domainAccountPassword').inputValue(),'');assert(!(await page.locator('#domainAccountsList').innerText()).includes('private-fixture-password'));
  await page.locator('[data-domain-edit]').click();assert.equal(await page.locator('#domainAccountPassword').inputValue(),'');await page.locator('#domainAccountUsername').fill('updated@example.com');await page.locator('#domainAccountForm button[type=submit]').click();await settle();
  await page.locator('[data-domain-reveal]').click();await page.locator('#domainRevealCode').fill('123456');await page.locator('#domainRevealSubmit').click();await settle();assert.equal(await page.locator('#domainSecretValue').inputValue(),'');assert.match(await page.locator('#domainRevealMsg').innerText(),/TOTP/);await page.locator('#domainRevealClose').click();
  await page.setViewportSize({width:375,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.equal(await page.locator('#domainDetailDialog').evaluate(e=>e.scrollWidth<=e.clientWidth),true);
  await page.locator('#domainDetailClose').click();page.once('dialog',d=>d.accept());await page.locator('[data-domain-record-delete]').click();await settle();assert.match(await page.locator('#dMsg').innerText(),/先删除/);
  await page.locator('[data-domain-view]').click();page.once('dialog',d=>d.accept());await page.locator('[data-domain-delete]').click();await settle();assert.equal(await page.locator('[data-domain-reveal]').count(),0);await page.locator('#domainDetailClose').click();
  await page.reload();await settle();await page.locator('#domainSearch').fill('registry.sg');assert.match(await page.locator('#dList').innerText(),/Updated registrar/);
  page.once('dialog',d=>d.accept());await page.locator('[data-domain-record-delete]').click();await settle();assert.equal(await page.locator('[data-domain-view]').count(),0);
  await page.locator('#domainSearch').fill('');await page.selectOption('#domainExpiryFilter','unset');assert.equal(await page.locator('#dList tbody tr').count(),25);
  await page.selectOption('#uiLanguage','en');await settle();
  const out=process.env.E2E_DOMAIN_OUTPUT;if(out){fs.mkdirSync(out,{recursive:true});for(const width of [375,1440]){await page.setViewportSize({width,height:900});await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(out,`domains-${width}.png`)});}}
  await page.setViewportSize({width:1440,height:1000});await page.selectOption('#uiLanguage','zh');await ui.logout();await ui.login('finance-test',cfg.password);await ui.ready();await ui.navigate('域名管理');await settle();assert.equal(await page.locator('#domainNew').isVisible(),false);assert.equal(await page.locator('[data-domain-record-edit],[data-domain-record-delete]').count(),0);
  console.log('PASS real domain list CRUD, independent accounts, persistence, pagination/search/filter, deletion protection, password gating, mobile dialog and finance permissions');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
