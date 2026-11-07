/* Opt-in real configured LLM through disposable application endpoints. No live site is published. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {ConsolePage}=require('./pages/console.cjs');
(async()=>{
 if(!process.env.KF_E2E_REAL_AI_BASE)throw Error('Set KF_E2E_REAL_AI_BASE to explicitly enable paid real model calls');
 const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),env:process.env,stdio:['pipe','pipe','inherit']});let browser;
 try{
  const cfg=JSON.parse(await Promise.race([once(readline.createInterface({input:child.stdout}),'line').then(([line])=>line),once(child,'exit').then(([code])=>{throw Error('Fixture exited before readiness: '+code);})]));browser=await chromium.launch();
  const page=await browser.newPage(),ui=new ConsolePage(page,cfg.origin);page.setDefaultTimeout(20000);
  await ui.login('ops-test',cfg.password);await ui.ready();await ui.navigate('GEO');await page.locator('#geoProfileForm').waitFor();
  const call=async(action,body)=>{const result=await page.evaluate(async({action,body})=>{try{return {data:await aiRequest('/api/geo/'+action,{slug:GEO.data.site.slug,revision:GEO.data.workspace.revision,...body})};}catch(e){return {error:e.message};}},{action,body});assert(!result.error,result.error);if(result.data.workspace)await page.evaluate(data=>{GEO.data.workspace=data.workspace;GEO.data.metrics=data.metrics;},result.data);return result.data;};
  await call('profile',{profile:{brand:'Demonstration workshop',market:'SG',language:'en',sector:'education'}});
  await call('facts',{item:{translations:{en:'This is a demonstration website for QA. Its sample service is a weekly workshop; no real booking is offered.',zh:'这是用于质量测试的演示网站。示例服务为每周工作坊，不提供真实预约。'},source_url:'https://example.test/services',verified_on:new Date().toISOString().slice(0,10),expires_on:'',approved:true,category:'service'}});
  const settings=await page.evaluate(()=>({profile_id:GEO.config.default_profile,prompt_revision:GEO.data.prompts.revision}));
  const report=[];
  for(const language of ['en','zh']){
   const modules=await page.evaluate(lang=>GEO.data.prompts.modules.filter(m=>m.language===lang).map(m=>m.id),language);
   const suggestions=await call('assist',{...settings,task:'questions',language,module_ids:modules,instructions:'For a clearly labelled demonstration site. Generate 3 useful questions only.'});assert(suggestions.questions.length>0);
   await call('questions',{item:suggestions.questions[0]});
   const result=await call('assist',{...settings,task:'content',language,module_ids:modules,page:'home',instructions:'Keep the proposed section under 500 characters. Clearly retain the demonstration status. Do not invent operational services.'});
   const proposal=result.workspace.proposals.at(-1);assert.equal(proposal.language,language);assert(proposal.facts.length);assert.equal(proposal.prompt_modules.length,modules.length);
   report.push({language,question_count:suggestions.questions.length,proposal_characters:proposal.text.length,profile:proposal.profile_id,model:proposal.model,source_fact_ids:proposal.facts.map(f=>f.id)});
  }
  await page.locator('[data-geo-step="4"]').click();await page.locator('[data-geo-action=review]').first().click();await page.locator('#geoReviewConfirmed').check();
  const saved=page.waitForResponse(r=>r.url().endsWith('/api/geo/draft'));await page.locator('#geoReviewForm button[type=submit]').click();assert.equal((await saved).status(),200);await page.waitForFunction(()=>!GEO.busy);
  const result=await (await page.request.get(cfg.origin+'/api/geo/workspace?slug=demo')).json();assert(result.workspace.proposals.some(p=>p.status==='draft'));
  fs.writeFileSync('/tmp/mvp-geo-live-results.json',JSON.stringify({passed:true,report},null,2));console.log('GEO real configured LLM: separate English/Chinese questions and proposals, evidence snapshots and reviewed draft transfer passed.');
 }finally{if(browser)await browser.close();child.stdin.end();if(child.exitCode===null)await once(child,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1;});
