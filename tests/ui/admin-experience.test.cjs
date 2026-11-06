/* Shared admin controls against real HTTP handlers and disposable persisted data. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse((await once(readline.createInterface({input:child.stdout}),'line'))[0]);browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new ConsolePage(page,cfg.origin);page.setDefaultTimeout(15000);
  const output=process.env.E2E_ADMIN_OUTPUT;if(output)fs.mkdirSync(output,{recursive:true,mode:0o700});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await ui.login('admin',cfg.password);await ui.ready();
  await ui.navigate('供应商账号');await page.locator('#providerNew').click();
  await page.locator('#providerId').fill('admin-ui');await page.locator('#providerName').fill('Account A');await page.selectOption('#providerKind','cloudflare');await page.locator('#provider-token').fill('fixture-secret');await page.selectOption('#providerSites',['demo']);await page.locator('#providerCaps input[value=dns]').check();
  await page.locator('#providerForm button[type=submit]').click();await page.locator('[data-provider-view="admin-ui"]').waitFor();assert.equal(await page.locator('#providerFormDialog').isVisible(),false);
  await page.locator('[data-provider-edit="admin-ui"]').click();assert.equal(await page.locator('#provider-token').inputValue(),'');await page.locator('#providerName').fill('Unsaved');
  page.once('dialog',d=>d.dismiss());await page.keyboard.press('Escape');assert.equal(await page.locator('#providerFormDialog').isVisible(),true);
  page.once('dialog',d=>d.accept());await page.keyboard.press('Escape');assert.equal(await page.locator('#providerFormDialog').isVisible(),false);
  await page.locator('[data-provider-view="admin-ui"]').click();assert(!(await page.locator('#adminDetailDialog').innerText()).includes('fixture-secret'));await page.locator('#adminDetailDialog button').click();
  await page.evaluate(async()=>{for(let i=0;i<21;i++)await aiRequest('/api/automation/providers',{id:'page-'+i,name:'Page '+i,provider:'cloudflare',enabled:true,sites:['demo'],capabilities:['dns'],values:{token:'fixture-only'}});await loadProviders();});
  assert.equal(await page.locator('#providerList tbody tr').count(),20);await page.locator('#providerList [data-admin-page="1"]').click();assert.equal(await page.locator('#providerList tbody tr').count(),2);
  await page.locator('#providerSearch').fill('Account A');assert.equal(await page.locator('#providerList tbody tr').count(),1);
  if(output)await page.screenshot({path:path.join(output,'providers-desktop.png')});
  await ui.navigate('MCP 管理');await page.locator('#mcpNew').click();await page.locator('#mcpId').fill('admin-ui');await page.locator('#mcpName').fill('Local configuration');await page.locator('#mcpUrl').fill('https://example.com/mcp');await page.locator('#mcpToken').fill('fixture-mcp-secret');await page.locator('#mcpForm button[type=submit]').click();await page.locator('[data-mcp-view]').waitFor();
  await page.locator('[data-mcp-edit]').click();assert.equal(await page.locator('#mcpToken').inputValue(),'');await page.locator('#mcpDescription').fill('Saved description');await page.locator('#mcpForm button[type=submit]').click();await page.locator('#mcpFormDialog').waitFor({state:'hidden'});
  await page.locator('[data-mcp-view]').click();assert.match(await page.locator('#adminDetailDialog').innerText(),/Saved description/);await page.locator('#adminDetailDialog button').click();
  await page.setViewportSize({width:375,height:900});await page.locator('[data-mcp-edit]').click();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.equal(await page.locator('#mcpFormDialog').evaluate(e=>e.scrollWidth<=e.clientWidth),true);if(output)await page.screenshot({path:path.join(output,'mcp-mobile.png')});await page.locator('#mcpCancel').click();await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(async()=>{await aiRequest('/api/site/archive',{slug:'demo',archived:true,version:0});await load();});
  await ui.navigate('客户管理');assert.equal(await page.locator('#clSlug').inputValue(),'');await page.locator('#clSlug + label input').check();assert.equal(await page.locator('#clSlug').inputValue(),'demo');
  await ui.navigate('咨询线索');assert.equal(await page.locator('#ldSlug').inputValue(),'demo');assert.equal(await page.locator('#ldSlug + label input').isChecked(),true);
  await page.locator('#ldSlug + label input').uncheck();assert.equal(await page.locator('#ldSlug').inputValue(),'');await page.reload();await page.waitForFunction(()=>STATE.sites.length>0);await ui.navigate('客户管理');assert.equal(await page.locator('#clSlug').inputValue(),'');
  await page.evaluate(async()=>{await aiRequest('/api/site/archive',{slug:'demo',archived:false,version:1});await load();});await ui.navigate('咨询线索');assert.equal(await page.locator('#ldSlug').inputValue(),'demo');
  assert.deepEqual(errors,[]);console.log('PASS real provider/MCP CRUD, pagination, details, dirty Escape protection, secret clearing, mobile modal and shared archive context');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
