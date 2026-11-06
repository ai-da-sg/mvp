class ConsolePage {
 constructor(page,origin){this.page=page;this.origin=origin;}
 async login(user,password,code=''){
  await this.page.goto(this.origin+'/login');
  await this.page.getByLabel('用户名',{exact:true}).fill(user);
  await this.page.getByLabel('密码',{exact:true}).fill(password);
  if(code)await this.page.getByLabel('验证码或恢复码',{exact:false}).fill(code);
  await this.page.getByRole('button',{name:'登录',exact:true}).click();
 }
 async ready(){await this.page.waitForURL(this.origin+'/');await this.page.waitForFunction(()=>document.querySelector('#whoami').textContent!=='—');}
 async navigate(name){
  const button=this.page.getByRole('button',{name,exact:true,includeHidden:true});
  const group=this.page.locator('.nav-group').filter({has:button});
  if(!await group.evaluate(e=>e.open))await group.locator('summary').click();
  await button.click();
 }
 async logout(){await this.page.getByRole('link',{name:'退出',exact:true}).click();await this.page.waitForURL('**/login');}
}
module.exports={ConsolePage};
