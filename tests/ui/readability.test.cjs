/* Real HTTP UI checks for the task-oriented console redesign. */
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const readline=require('node:readline');
const path=require('node:path');
const fs=require('node:fs');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
const output=path.resolve(__dirname,'../../output/e2e-real/readability');
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','inherit']});
 let browser;
 try{
  const lines=readline.createInterface({input:child.stdout});
  const cfg=JSON.parse(await Promise.race([once(lines,'line').then(x=>x[0]),once(child,'exit').then(()=>{throw Error('Fixture exited')}),new Promise((_,reject)=>{const t=setTimeout(()=>reject(Error('Fixture timeout')),15000);t.unref()})]));
  browser=await chromium.launch();const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{window.pendingRequests=0;const original=window.fetch;window.fetch=async(...args)=>{window.pendingRequests++;try{return await original(...args)}finally{window.pendingRequests--}}});
  const settle=async()=>{await page.waitForFunction(()=>window.pendingRequests===0);await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));};
  const ui=new ConsolePage(page,cfg.origin);await ui.login('admin',cfg.password);await ui.ready();await settle();
  assert.equal(await page.locator('#siteCreate').evaluate(e=>e.open),false);
  await page.locator('#newSite').click();assert.equal(await page.locator('#siteCreate').evaluate(e=>e.open),true);
  assert.equal(await page.locator('#f input[name=company]').evaluate(e=>e===document.activeElement),true);
  await page.locator('#f input[name=company]').fill('保留草稿');await page.locator('#siteCreate>summary').click();
  await page.locator('#siteSearch').fill('no-such-customer');await page.getByText('没有匹配的站点',{exact:true}).waitFor();
  await page.getByRole('button',{name:'清除筛选',exact:true}).click();await page.getByText('Demo',{exact:true}).first().waitFor();
  await page.locator('#siteSearch').fill('EXAMPLE.TEST');assert.equal(await page.locator('#rows tr').count(),1);
  await page.locator('#siteStatus').selectOption('active');await page.getByText('没有匹配的站点',{exact:true}).waitFor();
  await page.getByRole('button',{name:'清除筛选',exact:true}).click();
  await page.locator('#newSite').click();assert.equal(await page.locator('#f input[name=company]').inputValue(),'保留草稿');await page.locator('#siteCreate>summary').click();
  const tabs=await page.locator('[data-t]').evaluateAll(es=>es.map(e=>e.dataset.t));
  async function navigate(key){
   if(await page.locator('#navToggle').isVisible()&&await page.locator('#navToggle').getAttribute('aria-expanded')==='false')await page.locator('#navToggle').click();
   const button=page.locator(`[data-t="${key}"]`);const group=page.locator('.nav-group').filter({has:button});
   if(!await group.evaluate(e=>e.open))await group.locator('summary').click();await button.click();await settle();
  }
  const captures=new Set(['sites','ai','automation','providers','domain','team']);
  for(const language of ['zh','en']){
   await page.selectOption('#uiLanguage',language);
   for(const theme of ['light','dark']){
    await page.selectOption('#uiTheme',theme);
    for(const width of [375,768,1440]){
     await page.setViewportSize({width,height:1000});
     for(const tab of tabs){
      await navigate(tab);
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
      if(overflow){console.log(await page.locator('body *').evaluateAll(es=>es.filter(e=>e.getBoundingClientRect().right>innerWidth&&e.getBoundingClientRect().width).map(e=>({tag:e.tagName,id:e.id,cls:e.className,width:e.getBoundingClientRect().width})).slice(-15)));await page.screenshot({path:path.join(output,'overflow.png'),fullPage:true});}
      assert.equal(overflow,false,`${language}/${theme}/${width}/${tab}: horizontal overflow`);
      assert.equal(await page.locator(`[data-t="${tab}"]`).getAttribute('aria-current'),'page');
      await page.evaluate(()=>scrollTo(0,0));
      if(language==='en'&&theme==='light'&&captures.has(tab))await page.screenshot({path:path.join(output,`${tab}-${width}.png`),fullPage:true});
      if(tab==='sites'&&theme==='dark'&&language==='en'&&width===1440)await page.screenshot({path:path.join(output,'sites-dark.png'),fullPage:true});
     }
    }
   }
  }
  await page.setViewportSize({width:375,height:900});await navigate('sites');await page.locator('#navToggle').click();await page.locator('#navToggle').press('Escape');assert.equal(await page.locator('#navToggle').getAttribute('aria-expanded'),'false');
  await page.selectOption('#uiLanguage','zh');await ui.logout();await ui.login('finance-test',cfg.password);await ui.ready();await settle();
  assert.equal(await page.locator('#newSite').isVisible(),false);assert.equal(await page.locator('#siteCreate').isVisible(),false);
  assert.deepEqual(errors,[]);console.log('PASS readability: search, filters, retained form, role boundaries, keyboard navigation and all 20 pages in 2 languages × 2 themes × 3 widths');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
