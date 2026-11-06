/* Read-only production checks: explicit URLs, no account credentials or successful writes. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const consoleURL=process.env.E2E_CONSOLE_URL;
const sites=(process.env.E2E_WORDPRESS_URLS||'').split(',').filter(Boolean);
assert(consoleURL&&sites.length,'Set E2E_CONSOLE_URL and E2E_WORDPRESS_URLS explicitly');
for(const url of [consoleURL,...sites])assert.equal(new URL(url).protocol,'https:');
(async()=>{
 const browser=await chromium.launch();const results=[];
 try{
  const context=await browser.newContext();const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  for(const width of [375,1440]){
   await page.setViewportSize({width,height:900});assert.equal((await page.goto(consoleURL+'/login')).status(),200);
   await page.getByLabel('用户名',{exact:true}).waitFor();await page.getByLabel('密码',{exact:true}).waitFor();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  }
  for(const endpoint of ['/api/state','/api/users','/api/ai/config','/api/domain/accounts','/api/mcp/servers'])assert.equal((await context.request.get(consoleURL+endpoint)).status(),401,endpoint);
  results.push({name:'production-console-login-and-auth-boundaries',status:'passed'});
  for(const base of sites){
   assert.equal((await page.goto(base+'/')).status(),200);await page.locator('h1').first().waitFor();
   const login=await context.request.get(base+'/wp-login.php',{maxRedirects:0});assert.equal(login.status(),303);assert.equal(login.headers().location,consoleURL+'/login');
   for(const endpoint of ['/xmlrpc.php','/readme.html','/wp-content/uploads/nonexistent-e2e.php'])assert.equal((await context.request.get(base+endpoint)).status(),403,base+endpoint);
   assert.equal((await context.request.get(base+'/wp-json/wp/v2/users?context=edit')).status(),401);
   results.push({name:base,status:'passed'});
  }
  assert.deepEqual(errors,[]);for(const r of results)console.log('PASS',r.name);
 }finally{await browser.close();const out=path.resolve(process.env.E2E_OUTPUT||path.join(__dirname,'../../output/e2e-real'));fs.mkdirSync(out,{recursive:true,mode:0o700});fs.writeFileSync(path.join(out,'production-results.json'),JSON.stringify(results,null,2),{mode:0o600});}
})().catch(e=>{console.error(e);process.exitCode=1});
