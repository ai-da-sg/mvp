/* Real HTTP handlers and optional real remote MCP discovery. No route.fulfill / mocked APIs.
   Accounts and writes are isolated; external MCP requests are explicitly opt-in and read-only. */
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
const output=path.resolve(process.env.E2E_OUTPUT||path.join(__dirname,'../../output/e2e-real'));
function totp(){const key=Buffer.from('48656c6c6f21deadbeef','hex'),b=Buffer.alloc(8);b.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));const h=crypto.createHmac('sha1',key).update(b).digest(),i=h[19]&15;return String((h.readUInt32BE(i)&0x7fffffff)%1000000).padStart(6,'0');}
(async()=>{
 fs.mkdirSync(output,{recursive:true,mode:0o700});
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','pipe']});
 let browser;const results=[];let stderr='';child.stderr.on('data',d=>{stderr+=d});
 try{
  const lines=readline.createInterface({input:child.stdout});
  const first=await Promise.race([once(lines,'line').then(x=>x[0]),once(child,'exit').then(()=>{throw Error('Fixture exited: '+stderr)}),new Promise((_,reject)=>{const t=setTimeout(()=>reject(Error('Fixture timeout')),15000);t.unref()})]);
  const cfg=JSON.parse(first);browser=await chromium.launch({headless:true});
  async function scenario(name,run){
   if(process.env.E2E_FILTER&&!name.includes(process.env.E2E_FILTER))return;
   const context=await browser.newContext();await context.tracing.start({screenshots:true,snapshots:true,sources:true});
   const page=await context.newPage();page.setDefaultTimeout(12000);const ui=new ConsolePage(page,cfg.origin);const errors=[];page.on('pageerror',e=>errors.push(e.message));
   try{await run({page,context,ui});assert.deepEqual(errors,[]);results.push({name,status:'passed'});console.log('PASS',name);await context.tracing.stop();}
   catch(e){results.push({name,status:'failed',error:e.message});console.error('FAIL',name,e.message);await page.screenshot({path:path.join(output,name+'.png'),fullPage:true}).catch(()=>{});await context.tracing.stop({path:path.join(output,name+'.zip')});}
   finally{await context.close();}
  }
  await scenario('login-logout-revocation',async({page,context,ui})=>{
   await ui.login('admin','incorrect-password');await page.getByRole('alert').waitFor();
   assert.equal((await context.request.get(cfg.origin+'/api/state')).status(),401);
   await ui.login('admin',cfg.password);await ui.ready();
   const previous=await context.storageState();assert.equal((await context.request.get(cfg.origin+'/api/state')).status(),200);
   await ui.logout();assert.equal((await context.request.get(cfg.origin+'/api/state')).status(),401);
   const replay=await browser.newContext({storageState:previous});try{assert.equal((await replay.request.get(cfg.origin+'/api/state')).status(),401);}finally{await replay.close();}
  });
  for(const [user,role,usersStatus] of [['ops-test','ops',403],['finance-test','finance',403]]){
   await scenario(role+'-server-permissions',async({page,context,ui})=>{
    await ui.login(user,cfg.password);await ui.ready();
    const state=await(await context.request.get(cfg.origin+'/api/state')).json();assert.equal(state.role,role);
    assert.equal((await context.request.get(cfg.origin+'/api/users')).status(),usersStatus);
    assert.equal((await context.request.get(cfg.origin+'/api/audit')).status(),403);
    if(role==='finance')assert.equal((await context.request.get(cfg.origin+'/api/spec/demo')).status(),403);
    await ui.logout();
   });
  }
  await scenario('mfa-login-and-replay',async({page,ui})=>{
   await ui.login('mfa-test',cfg.password,'000000');await page.getByRole('alert').waitFor();
   const code=totp();await ui.login('mfa-test',cfg.password,code);await ui.ready();await ui.logout();
   await ui.login('mfa-test',cfg.password,code);await page.getByRole('alert').waitFor();
  });
  await scenario('draft-save-reload-preview',async({page,context,ui})=>{
   await ui.login('admin',cfg.password);await ui.ready();await ui.navigate('页面编辑');
   await page.locator('#lSlug').selectOption('demo');await page.locator('[data-page-edit=home]').click();await page.locator('.section-select').first().click();
   const field=page.locator('#lForm input').first();await field.fill('E2E real persistence');
   const saved=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/spec'&&r.request().method()==='POST');await page.locator('#lSave').click();assert.equal((await saved).status(),200);
   await page.reload();await page.locator('[data-page-edit=home]').click();await page.locator('.section-select').first().click();assert.equal(await page.locator('#lForm input').first().inputValue(),'E2E real persistence');
   const popupPromise=context.waitForEvent('page');await page.locator('#lPreview').click();const popup=await popupPromise;
   await popup.getByText('E2E real persistence',{exact:true}).waitFor();await popup.close();
  });
  await scenario('focused-ui-disclosures',async({page,ui})=>{
   await ui.login('admin',cfg.password);await ui.ready();await ui.navigate('AI 建站');
   const help=page.locator('#p-ai > .page-help');assert.equal(await help.evaluate(e=>e.open),false);
   assert.equal(await page.locator('#aiReferenceOptions').evaluate(e=>e.open),false);
   assert.equal(await page.locator('#aiContextOptions').evaluate(e=>e.open),false);
   await page.getByLabel('建站要求 / 额外补充',{exact:true}).fill('保留已输入的业务需求');
   await help.locator('summary').focus();await page.keyboard.press('Enter');assert.equal(await help.evaluate(e=>e.open),true);
   await help.locator('summary').press('Enter');
   await ui.buildStep(2);
   await page.locator('#aiReferenceOptions > summary').click();await page.getByLabel('参考网站地址',{exact:true}).fill('https://example.com/');
   await page.locator('#aiReferenceOptions > summary').click();await page.locator('#aiReferenceOptions > summary').click();
   assert.equal(await page.getByLabel('参考网站地址',{exact:true}).inputValue(),'https://example.com/');
   for(const theme of ['light','dark']){
    await page.selectOption('#uiTheme',theme);await page.setViewportSize({width:375,height:812});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   }
   await page.selectOption('#uiLanguage','en');await page.waitForFunction(()=>document.querySelector('#p-ai > .page-help > summary').textContent==='Building guide');
   assert.equal(await page.locator('#aiBrief').inputValue(),'保留已输入的业务需求');
   assert.equal(await page.locator('#aiGenerate').isVisible(),false);await ui.buildStep(3);assert.equal(await page.locator('#aiGenerate').isVisible(),true);
  });
  if(process.env.E2E_REMOTE_MCP==='1')for(const preset of ['cloudflare-docs','aws-knowledge']){
   await scenario('live-mcp-'+preset,async({page,ui})=>{
    await ui.login('admin',cfg.password);await ui.ready();await ui.navigate('MCP 管理');
    await page.locator('#mcpPreset').selectOption(preset);await page.locator('#mcpUsePreset').click();
    const saved=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/mcp/servers'&&r.request().method()==='POST');await page.locator('#mcpForm button[type=submit]').click();assert.equal((await saved).status(),200);
    const discovery=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/mcp/test',{timeout:60000});await page.locator(`[data-mcp-test="${preset}"]`).click();
    const response=await discovery;const data=await response.json();assert.equal(response.status(),200,JSON.stringify(data));assert(data.result.tools.length>0);
    await page.locator('#mcpResult').waitFor();
   });
  }
 }finally{
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2),{mode:0o600});
  if(browser)await browser.close();if(child.exitCode===null){child.stdin.end('\n');await Promise.race([once(child,'exit'),new Promise(resolve=>{const t=setTimeout(()=>{child.kill();resolve()},5000);t.unref()})]);}
 }
 assert(results.length>0,'No scenarios selected');
 if(results.some(r=>r.status==='failed'))process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
