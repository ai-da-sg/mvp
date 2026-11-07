/* Prompt library list/dialog CRUD through real HTTP handlers and disposable data. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse((await once(readline.createInterface({input:child.stdout}),'line'))[0]);browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new ConsolePage(page,cfg.origin);page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await ui.login('admin',cfg.password);await ui.ready();await ui.navigate('提示词库');await page.locator('[data-view-prompt]').first().waitFor();
  if(process.env.E2E_OUTPUT){fs.mkdirSync(process.env.E2E_OUTPUT,{recursive:true});await page.screenshot({path:path.join(process.env.E2E_OUTPUT,'prompts-list.png'),fullPage:true});}
  await page.selectOption('#promptLibraryKind','modules');assert.equal(await page.locator('#promptLibraryList tbody tr').count(),20);
  await page.locator('#promptLibraryList [data-admin-page="1"]').click();assert.equal(await page.locator('#promptLibraryList tbody tr').count(),1);
  await page.locator('#promptLibraryNew').click();await page.locator('#promptEditId').fill('list-proof');await page.locator('#promptEditName').fill('List proof');await page.locator('#promptEditCategory').fill('copy');await page.locator('#promptEditBody').fill('Write for {{audience}}. <img src=x onerror=alert(1)>');
  page.once('dialog',d=>d.dismiss());await page.keyboard.press('Escape');assert(await page.locator('#promptEditFormDialog').isVisible());
  await page.locator('#promptEditForm button[type=submit]').click();await page.locator('#promptEditFormDialog').waitFor({state:'hidden'});await page.locator('[data-view-prompt="list-proof"]').click();
  assert.match(await page.locator('#adminDetailDialog').innerText(),/Write for/);assert.equal(await page.locator('#adminDetailDialog img').count(),0);await page.locator('#adminDetailDialog button').click();
  await page.locator('[data-edit-prompt="list-proof"]').click();await page.locator('#promptEditBody').fill('Updated {{audience}} guidance');await page.locator('#promptEditForm button[type=submit]').click();await page.locator('#promptEditFormDialog').waitFor({state:'hidden'});
  let library=await(await page.request.get(cfg.origin+'/api/ai/prompts')).json();assert.equal(library.modules.find(x=>x.id==='list-proof').version,2);
  await page.selectOption('#uiLanguage','en');await page.locator('[data-edit-prompt="list-proof"]').click();await page.setViewportSize({width:375,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert(await page.locator('#promptEditFormDialog').evaluate(e=>e.scrollWidth<=e.clientWidth));if(process.env.E2E_OUTPUT)await page.screenshot({path:path.join(process.env.E2E_OUTPUT,'prompts-edit-mobile.png'),fullPage:true});await page.locator('#promptEditCancel').click();
  page.once('dialog',d=>d.dismiss());await page.locator('[data-delete-prompt="list-proof"]').click();assert.equal(await page.locator('[data-view-prompt="list-proof"]').count(),1);
  page.once('dialog',d=>d.accept());await page.locator('[data-delete-prompt="list-proof"]').click();await page.locator('[data-view-prompt="list-proof"]').waitFor({state:'detached'});
  library=await(await page.request.get(cfg.origin+'/api/ai/prompts')).json();assert(!library.modules.some(x=>x.id==='list-proof'));
  await page.setViewportSize({width:1440,height:1000});await page.selectOption('#uiLanguage','zh');await ui.logout();await ui.login('ops-test',cfg.password);await ui.ready();await ui.navigate('提示词库');await page.locator('[data-view-prompt]').first().waitFor();assert.equal(await page.locator('[data-edit-prompt],[data-delete-prompt]').count(),0);assert(await page.locator('#promptLibraryNew').isHidden());
  assert.deepEqual(errors,[]);console.log('PASS real prompt list pagination, detail escaping, modal CRUD, history, dirty protection, mobile layout and role boundaries');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
