import {expect, test} from '@playwright/test';
test('Arabic RTL, English navigation, live metadata and role-restricted controls',async({page})=>{
 await page.route('**/admin/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  let value:unknown={items:[],total:0,page:0};
  if(path==='/admin/me')value={subject:'test-reader',role:'READ_ONLY',permissions:['read'],csrf:null};
  if(path==='/admin/health')value={readiness:{status:'ready',checks:{postgresql:true,redis:true}},queue_depth:3,pending_approvals:1,release:{app_version:'0.8.0',build_git_sha:'test-build'}};
  if(path==='/admin/data/users')value={items:[{id:1,language:'ar',is_active:true}],total:1,page:0};
  await route.fulfill({contentType:'application/json',body:JSON.stringify(value)});
 });
 await page.goto('/admin-web/');
 await expect(page.locator('html')).toHaveAttribute('dir','rtl');
 await expect(page.getByRole('heading',{name:'نظرة عامة'})).toBeVisible();
 await expect(page.getByText('0.8.0',{exact:true}).first()).toBeVisible();
 await page.getByRole('button',{name:'المستخدمون',exact:true}).click();
 await expect(page.locator('tbody')).toContainText('ar');
 await expect(page.getByRole('button',{name:'إيقاف',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'English',exact:true}).click();
 await expect(page.locator('html')).toHaveAttribute('dir','ltr');
 await expect(page.getByRole('heading',{name:'Users',exact:true})).toBeVisible();
 await page.screenshot({path:'/tmp/wakeelm-admin-en.png',fullPage:true});
});
test('unauthenticated dashboard offers trusted OIDC login',async({page})=>{
 await page.route('**/admin/me',route=>route.fulfill({status:401,body:'Unauthorized'}));
 await page.goto('/admin-web/');
 await expect(page.locator('a[href="/admin/login"]')).toBeVisible();
 await expect(page.locator('nav')).toHaveCount(0);
});
