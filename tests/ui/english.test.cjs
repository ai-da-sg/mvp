/* English UI audit against real HTTP handlers; no mocked responses. */
const assert=require('node:assert/strict'),path=require('node:path');
const {spawn}=require('node:child_process'),{once}=require('node:events'),readline=require('node:readline'),fs=require('node:fs');const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const child=spawn(process.env.PYTHON||'python3',['tests/e2e_browser_fixture.py'],{cwd:path.resolve(__dirname,'../..'),stdio:['pipe','pipe','ignore'],env:{...process.env,KF_E2E_DOMAIN:'1'}});let browser;const findings={};
try{const lines=readline.createInterface({input:child.stdout});const cfg=JSON.parse(await Promise.race([once(lines,'line').then(x=>x[0]),once(child,'exit').then(()=>{throw Error('Fixture exited')}),new Promise((_,reject)=>{const t=setTimeout(()=>reject(Error('Fixture timeout')),15000);t.unref()})]));browser=await chromium.launch();const page=await browser.newPage();await page.addInitScript(()=>{window.pendingRequests=0;const realFetch=window.fetch;window.fetch=async(...args)=>{window.pendingRequests++;try{return await realFetch(...args)}finally{window.pendingRequests--}}});
async function settle(){await page.waitForFunction(()=>window.pendingRequests===0);await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));}
await page.goto(cfg.origin+'/login');await page.selectOption('#uiLanguage','en');
await page.getByLabel('Username',{exact:true}).fill('admin');await page.getByLabel('Password',{exact:true}).fill('incorrect-password');await page.getByRole('button',{name:'Sign in',exact:true}).click();await page.getByRole('alert').waitFor();await settle();assert(!/[\u3400-\u9fff]/.test(await page.getByRole('alert').innerText()));
await page.selectOption('#uiLanguage','zh');await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill(cfg.password);await page.getByRole('button',{name:'登录',exact:true}).click();await page.waitForURL(cfg.origin+'/');await page.selectOption('#uiLanguage','en');await page.waitForFunction(()=>document.documentElement.lang==='en');
async function scan(label,selector='body'){await settle();findings[label]=await page.locator(selector).evaluate(root=>{const out=[];const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);while(walker.nextNode()){const n=walker.currentNode;if(n.parentElement.closest('script,style,textarea,pre,[data-user-content]'))continue;const t=n.textContent.trim();if(/[\u3400-\u9fff]/.test(t)&&t!=='中文')out.push(t);}for(const el of root.querySelectorAll('[placeholder],[title],[aria-label],[data-label]')){if(el.closest('[data-user-content]'))continue;for(const k of ['placeholder','title','aria-label','data-label']){const t=el.getAttribute(k);if(t&&/[\u3400-\u9fff]/.test(t))out.push(t);}}return [...new Set(out)]});}
await scan('static');const tabs=await page.locator('[data-t]').evaluateAll(es=>es.map(e=>e.dataset.t));
for(const key of tabs){const b=page.locator(`[data-t="${key}"]`);await b.evaluate(e=>e.closest('details').open=true);await b.click();await page.locator('#p-'+key).waitFor();await settle();await scan(key,'#p-'+key);
if(key==='automation'){for(const v of ['build','dns','mail','maintenance']){await page.selectOption('#autoPurpose',v);await settle();await page.locator('#autoStepNext').click();for(const tool of await page.locator('#autoTool option').evaluateAll(es=>es.map(e=>e.value))){await page.selectOption('#autoTool',tool);await scan('tool-'+tool,'#p-automation');}await page.locator('#autoStepBack').click();}}
if(key==='styles'){await page.locator('#styleNew').evaluate(e=>{const d=e.closest('details');if(d)d.open=true;});await page.locator('#styleNew').click();await scan('styles-editor','#styleEditForm');await page.locator('#styleCancel').click();
 // Check asynchronously rendered controls and combined labels, not just the empty library.
 const ids=await page.evaluate(()=>STYLE_LIBRARY.templates.slice(0,3).map(t=>t.id));
 await page.evaluate(ids=>{styleToggleCompare(ids[0]);styleToggleCompare(ids[1]);},ids);
 await page.locator('#styleCompareOpen').click();await scan('styles-comparison','#styleComparePanel');
 await page.locator('#styleCompareClose').click();
 await page.evaluate(id=>styleHistory(id),ids[0]);await scan('styles-history','#styleHistoryPanel');
 await page.locator('#styleHistoryClose').click();
 await page.evaluate(id=>stylePreview(STYLE_LIBRARY.templates.find(t=>t.id===id)),ids[0]);
 await scan('styles-detail','#styleDetailDialog');
 await page.locator('#styleDetailFavorite').click();await settle();await scan('styles-detail-favorite','#styleDetailDialog');
 for(const language of ['zh','en']){await page.selectOption('#uiLanguage',language,{force:true});await settle();}
 await scan('styles-detail-switched','#styleDetailDialog');
 await page.locator('#stylePreviewClose').click();
 await scan('styles-library-switched','#styleLibrary');
}
if(key==='providers'){await page.locator('#providerNew').click();for(const value of await page.locator('#providerKind option').evaluateAll(es=>es.map(e=>e.value))){await page.selectOption('#providerKind',value);await scan('provider-'+value,'#providerForm');}page.once('dialog',d=>d.accept());await page.locator('#providerCancel').click();}
if(key==='domain'){await page.locator('#domainNew').click();await scan('domain-record-form','#domainRecordDialog');await page.locator('#domainRecordCancel').click();await page.locator('[data-domain-view]').first().click();await scan('domain-detail','#domainDetailDialog');await page.locator('#domainDetailClose').click();}
if(key==='mcp'){await page.locator('#mcpNew').click();await scan('mcp-form','#mcpForm');await page.locator('#mcpCancel').click();}
}

// Exercise populated domain accounts through real HTTP, including empty fields.
await page.evaluate(async()=>{
 await domainRequest('/api/domain/accounts',{action:'save',slug:'demo',category:'registrar',provider:'English audit',url:'https://example.com',username:'',configuration:'',password:''});
 await loadDomainRegistry();
});
await scan('domain-populated','#dList');
assert.match(await page.locator('#dList').innerText(),/English audit/);
assert.equal(await page.locator('#dList [data-user-content]').filter({hasText:'未填写'}).count(),0);
// Save a local provider record through HTTP; no external DNS or mail operation.
await page.evaluate(async()=>{
 await aiRequest('/api/automation/providers',{id:'english-audit',name:'用户账号名称',provider:'cloudflare',enabled:true,sites:['demo'],capabilities:['dns'],values:{token:'fixture-only-token'}});
 await loadProviders();
});
await scan('provider-populated','#providerList');
assert.equal(await page.locator('#providerList td[data-user-content]').first().innerText(),'用户账号名称');
await page.evaluate(()=>document.querySelector('[data-provider-view]').click());await scan('provider-detail','#adminDetailDialog');assert.match(await page.locator('#adminDetailDialog').innerText(),/Authorized sites/);await page.locator('#adminDetailDialog button').click();
// Renderer coverage for remote capability payloads; no external MCP calls or mocked HTTP.
await page.evaluate(()=>renderMCPCapabilities({id:'audit',name:'Audit MCP'}, {
 server:'Audit',version:'1',protocol:'2025-06-18',truncated:true,
 tools:[{name:'search',description:'保留服务商原始描述',inputSchema:{type:'object'}}],resources:[],prompts:[]
}));
await scan('mcp-capabilities','#mcpResult');
assert.equal(await page.locator('#mcpResult [data-policy-kind]').innerText(),'Add to allowlist');
assert.equal(await page.locator('#mcpResult [data-user-content]').filter({hasText:'保留服务商原始描述'}).innerText(),'保留服务商原始描述');
for(const language of ['zh','en']){
 await page.selectOption('#uiLanguage',language);await settle();
 assert.equal(await page.locator('#mcpResult [data-policy-kind]').innerText(),language==='en'?'Add to allowlist':'加入白名单');
}
// Check operation previews without executing DNS changes or sending mail.
for(const state of ['prepared','uncertain','succeeded']){
 await page.evaluate(state=>showAutoReview({id:'audit',summary:'DNS preview',slug:'demo',tool:'dns.change',mode:'totp',state,arguments:{before:null,after:{name:'www',type:'A',content:'192.0.2.1',ttl:300}}}),state);
 await scan('operation-'+state,'#autoReview');
}
await page.evaluate(()=>showAutoReview({id:'audit',summary:'Mail preview',slug:'demo',tool:'mail.send',mode:'confirm',state:'prepared',arguments:{to:'test@example.com',subject:'Example',body:'User-authored content'}}));
await scan('mail-preview','#autoReview');
// Statuses and notifications appear only after operations; check the actual literals too.
const dynamicMessages=['DNS 执行配置已保存','MCP 配置已保存','供应商账号认证','已选择 Editorial Studio','版本 3','到期日 2027-01-01','工具（12）','未填写','已暂停','待确认','结果待核实','管理机构账号已保存','密码已隐藏','风格模板已保存，可用于后续建站','请先修正工具规则 JSON：Unexpected token'];
assert.deepEqual(await page.evaluate(messages=>messages.filter(message=>/[\u3400-\u9fff]/.test(kfText(message))),dynamicMessages),[]);

await page.evaluate(()=>{const node=document.createElement('div');node.dataset.userContent='';node.id='preservedContent';node.textContent='用户填写的中文内容';document.body.append(node)});
for(const language of ['zh','en']){await page.selectOption('#uiLanguage',language);await settle();assert.equal(await page.locator('#preservedContent').innerText(),'用户填写的中文内容');}
assert.equal(await page.evaluate(()=>kfText('API Key（留空保留已保存值）')),'API Key (leave blank to keep existing)');
assert.equal(await page.evaluate(()=>kfText('恢复码 3')),'Recovery codes: 3');

const failures=Object.fromEntries(Object.entries(findings).filter(([,values])=>values.length));assert.deepEqual(failures,{},'Untranslated English UI text');console.log('PASS English UI audit:',Object.keys(findings).length,'page and form states; language switching and real login errors');
}catch(error){const page=browser?.contexts()[0]?.pages()[0];if(page){const output=path.resolve(__dirname,'../../output/e2e-real');fs.mkdirSync(output,{recursive:true});await page.screenshot({path:path.join(output,'english-failure.png'),fullPage:true}).catch(()=>{});}throw error;}finally{if(browser)await browser.close();child.stdin.end('\n');await once(child,'exit');}})().catch(e=>{console.error(e);process.exitCode=1});
