/* Every seeded template rendered via the real preview endpoint, with no external assets. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','inherit']});let browser;
 try{
  const lines=readline.createInterface({input:child.stdout}),cfg=JSON.parse((await once(lines,'line'))[0]);
  browser=await chromium.launch();const page=await browser.newPage();const ui=new ConsolePage(page,cfg.origin);
  await ui.login('admin',cfg.password);await ui.ready();
  const library=await(await page.request.get(cfg.origin+'/api/ai/styles')).json();
  assert.equal(library.templates.length,28);assert.equal(library.templates.filter(t=>t.introduced_version===2).length,20);
  const preview=await browser.newPage(),external=[];preview.on('request',r=>{if(/^https?:/.test(r.url()))external.push(r.url());});
  const out=process.env.E2E_CATALOG_OUTPUT;if(out)fs.mkdirSync(out,{recursive:true});
  for(const item of library.templates){
   const data=await page.evaluate(async item=>{const r=await fetch('/api/ai/styles/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(item)});if(!r.ok)throw Error(await r.text());return r.json();},item);
   assert.equal(data.recipe.sector,item.sector);
   for(const width of [375,768,1440]){
    await preview.setViewportSize({width,height:1000});await preview.setContent(data.html);
    const actual=await preview.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,heading:getComputedStyle(document.querySelector('h1')).fontFamily,width:getComputedStyle(document.documentElement).getPropertyValue('--kf-max').trim(),title:document.querySelector('h1').textContent}));
    assert.equal(actual.overflow,false,item.id+'/'+width);assert.equal(actual.title,item.name);
    assert.equal(actual.width,item.tokens.advanced.content_width+'px');
    assert.match(actual.heading,{serif:/Georgia/,mono:/monospace/,rounded:/ui-rounded/,sans:/Arial/}[item.tokens.type.heading]);
    if(out)await preview.screenshot({path:path.join(out,item.id+'-'+width+'.png'),fullPage:true});
   }
  }
  assert.deepEqual(external,[]);console.log('PASS all 28 templates: real preview, industry metadata, fonts, widths, responsive layout and no external assets');
 }finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1});
