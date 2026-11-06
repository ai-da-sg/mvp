/* Complete template browsing interactions against real local HTTP handlers. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse((await once(readline.createInterface({input:child.stdout}),'line'))[0]);
  browser=await chromium.launch();const page=await browser.newPage({viewport:{width:1440,height:1000}}),ui=new ConsolePage(page,cfg.origin);
  await ui.login('admin',cfg.password);await ui.ready();
  await page.locator('[data-t=styles]').evaluate(e=>e.closest('details').open=true);await page.locator('[data-t=styles]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.style-card').length===28);
  const library=await(await page.request.get(cfg.origin+'/api/ai/styles')).json(),items=library.templates;
  const first=items[0];
  await page.selectOption('#styleTypeFilter',first.site_types[0]);await page.selectOption('#styleSectorFilter',first.sector);
  await page.locator('#styleSearch').fill(first.name);
  assert.equal(await page.locator('.style-card').count(),1);
  await page.locator(`[data-style-favorite="${first.id}"]`).click();
  await page.waitForFunction(id=>STYLE_LIBRARY.favorites.includes(id),first.id);
  await page.locator('#styleFavoritesOnly').check();assert.equal(await page.locator('.style-card').count(),1);
  await page.reload();await page.waitForFunction(id=>STYLE_LIBRARY.favorites?.includes(id),first.id);
  await page.locator('#styleResetFilters').click();
  await page.selectOption('#styleSort','name');
  const names=await page.locator('.style-card-heading h3').allTextContents();
  assert.deepEqual(names,[...names].sort((a,b)=>a.localeCompare(b)));
  await page.selectOption('#styleSort','recommended');
  for(const item of items.slice(0,4))await page.locator(`[data-style-compare="${item.id}"]`).click();
  assert.equal(await page.evaluate(()=>STYLE_COMPARE.size),3);
  await page.locator('#styleCompareOpen').click();assert.equal(await page.locator('#styleCompareContent thead th').count(),4);
  await page.locator(`[data-compare-remove="${items[2].id}"]`).click();assert.equal(await page.locator('#styleCompareContent thead th').count(),3);
  await page.locator(`[data-compare-preview="${first.id}"]`).click();
  await page.locator('#styleDetailDialog').waitFor();
  assert.equal(await page.locator('#stylePreviewPage option').count(),first.pages.length);
  await page.selectOption('#stylePreviewPage',first.pages[1].slug);
  const frame=page.frameLocator('#stylePreviewFrame');
  await frame.locator(`#demo-${first.pages[1].slug}`).waitFor();
  assert.equal(await frame.locator('#demo-home').isVisible(),false);
  await frame.locator('header a[href$="#demo-home"]').click();
  await frame.locator('#demo-home').waitFor();
  assert.equal(await frame.locator(`#demo-${first.pages[1].slug}`).isVisible(),false);
  await page.selectOption('#stylePreviewWidth','375px');
  assert.equal(await page.locator('#stylePreviewFrame').evaluate(e=>e.style.width),'375px');
  await page.locator('#stylePreviewFull').click();assert.equal(await page.locator('#styleDetailDialog').evaluate(e=>e.classList.contains('expanded')),true);
  await page.keyboard.press('Escape');assert.equal(await page.locator('#styleDetailDialog').isVisible(),false);
  await page.locator('#styleCompareClose').click();
  await page.locator('.style-card-preview').first().click();await page.locator('#styleDetailUse').click();
  await page.locator('#p-ai').waitFor();assert.equal(await page.locator('#aiStyleTemplate').inputValue(),first.id);
  // Version restoration writes a new version and retains the old snapshot.
  await page.evaluate(async id=>{const old=STYLE_LIBRARY.templates.find(t=>t.id===id);await aiRequest('/api/ai/styles',{...old,name:'Edited template',action:'save'});await styleLoad();},first.id);
  await page.locator('[data-t=styles]').click();
  const menu=page.locator(`[data-style-history="${first.id}"]`);await menu.evaluate(e=>e.closest('details').open=true);await menu.click();await page.locator('#styleHistoryPanel').waitFor();
  assert.equal(await page.locator('[data-style-restore]').count(),2);
  page.once('dialog',d=>d.accept());await page.locator('[data-style-restore="1"]').click();
  await page.waitForFunction(id=>STYLE_LIBRARY.templates.find(t=>t.id===id).version===3,first.id);
  assert.equal(await page.evaluate(id=>STYLE_LIBRARY.templates.find(t=>t.id===id).name,first.id),first.name);
  await page.locator('#styleHistoryClose').click();await page.locator('#styleCompareClear').click();
  assert.equal(await page.locator('#styleCompareBar').isVisible(),false);
  await page.locator('#styleSearch').fill('no-template-has-this-name');await page.locator('[data-style-reset]').click();
  assert.equal(await page.locator('.style-card').count(),28);
  for(const card of await page.locator('.style-card-preview').all()){await card.scrollIntoViewIfNeeded();await card.locator('iframe').waitFor();}
  await page.evaluate(()=>window.scrollTo(0,0));
  const output=process.env.E2E_TEMPLATE_OUTPUT;if(output)fs.mkdirSync(output,{recursive:true});
  for(const width of [1440,375]){
   await page.setViewportSize({width,height:1000});await page.locator('.style-card-preview iframe').first().waitFor();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   if(output)await page.screenshot({path:path.join(output,`library-${width}.png`),fullPage:false});
  }
  console.log('PASS template purpose/industry/search filters, persistent favorites, comparison limits, page/device preview, keyboard close, use and version restoration');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
