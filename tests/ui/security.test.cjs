const assert=require('node:assert/strict');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/security_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','inherit']});
 let browser;
 try{
  const lines=readline.createInterface({input:child.stdout});
  const first=await Promise.race([once(lines,'line').then(x=>x[0]),once(child,'exit').then(()=>{throw Error('Security fixture exited early')}),new Promise((_,reject)=>{const t=setTimeout(()=>reject(Error('Security fixture startup timed out')),15000);t.unref()})]);
  const cfg=JSON.parse(first);browser=await chromium.launch({headless:true});
  const ctx=await browser.newContext();await ctx.addCookies([{name:'kf_sid',value:cfg.cookie,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'}]);
  const page=await ctx.newPage();
  await page.goto(cfg.origin+'/');
  const token=await page.locator('meta[name="kf-csrf"]').getAttribute('content');assert.match(token,/^[a-f0-9]{64}$/);
  // The real page's fetch wrapper must attach CSRF automatically.
  const save=await page.evaluate(async()=>{const r=await fetch('/api/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'disable',user:'finance-test'})});return r.status});
  assert.equal(save,200);
  const sibling=await ctx.newPage();await sibling.goto(cfg.sibling);
  await sibling.evaluate(async origin=>{try{await fetch(origin+'/api/users',{method:'POST',mode:'no-cors',credentials:'include',headers:{'Content-Type':'text/plain'},body:JSON.stringify({action:'enable',user:'finance-test'})})}catch(_){}},cfg.origin);
  const users=await page.evaluate(async()=>await(await fetch('/api/users')).json());
  assert.equal(users.items.find(x=>x.user==='finance-test').active,false,'Sibling origin must not mutate account');
  await page.goto(cfg.origin+'/s/fixture-share/home');await page.waitForTimeout(150);
  assert.equal(await page.evaluate(()=>window.__unsafe||0),0);
  assert.ok((await page.locator('body').innerText()).includes('Safe preview'));
  assert.equal(await page.evaluate(()=>getComputedStyle(document.body).color),'rgb(12, 34, 56)','Sandbox must retain stylesheet loading');
  assert.equal(await page.evaluate(()=>{try{void document.cookie;return false}catch(_){return true}}),true,'Preview must have opaque origin');
  // No active SVG or executable URL survives the HTML5 sanitizer.
  assert.equal(await page.locator('svg').count(),0);
  assert.equal(await page.locator('a[href^="javascript:"]').count(),0);
  console.log('PASS real HTTP CSRF enforcement, legitimate console writes, stored XSS filtering and opaque preview with CSS');
 }finally{
  if(browser)await browser.close();
  if(child.exitCode===null){child.stdin.end('\n');await Promise.race([once(child,'exit'),new Promise(resolve=>{const t=setTimeout(()=>{child.kill();resolve()},5000);t.unref()})]);}
 }
})().catch(e=>{console.error(e);process.exitCode=1});
