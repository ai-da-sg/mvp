/* Read-only acceptance checks for explicitly supplied deployed showcase URLs.
   KF_SHOWCASE_URLS='https://preschool.ai-da.sg,https://tech.ai-da.sg,https://clinic.ai-da.sg'
   Optional PLAYWRIGHT_MODULE points to an installed Playwright module. */
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const urls=(process.env.KF_SHOWCASE_URLS||'').split(',').filter(Boolean);
assert(urls.length,'Set KF_SHOWCASE_URLS explicitly; this test never submits forms.');
(async()=>{const browser=await chromium.launch();try{
 for(const base of urls){
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  for(const width of [375,768,1024,1440]){
   await page.setViewportSize({width,height:900});
   const response=await page.goto(base,{waitUntil:'networkidle'});assert.equal(response.status(),200);
   assert.equal(await page.locator('h1').count(),1);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   assert.deepEqual(await page.locator('img').evaluateAll(es=>es.filter(i=>!i.complete||!i.naturalWidth).map(i=>i.src)),[]);
   if(width<=900){
    const toggle=page.locator('.kf-menu-toggle');await toggle.click();assert.equal(await toggle.getAttribute('aria-expanded'),'true');
    await page.locator('.kf-nav a').first().focus();await page.keyboard.press('Escape');assert.equal(await toggle.getAttribute('aria-expanded'),'false');assert(await toggle.evaluate(e=>e===document.activeElement));
   }
  }
  const links=await page.locator('.kf-nav a').evaluateAll(es=>es.map(a=>a.href));
  for(const href of links){assert.equal(new URL(href).origin,new URL(base).origin);const response=await page.goto(href);assert.equal(response.status(),200);}
  await page.goto(new URL('/contact/',base).href);
  assert.equal(await page.locator('.kf-form input:not([type=hidden]):not(.kf-hp),.kf-form textarea').evaluateAll(es=>es.filter(e=>!e.labels.length).length),0);
  assert.equal(await page.locator('.kf-form').evaluate(f=>f.checkValidity()),false);
  await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).scrollBehavior),'auto');
  assert.deepEqual(errors,[]);await page.close();console.log('PASS responsive navigation, page links, form labels and reduced motion:',base);
 }
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
