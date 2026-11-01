// Run only via scripts/check_craft_ideas_ui.py; all prices/history are synthetic.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const base=process.env.ALBION_SMOKE_URL,STAFF='T4_MAIN_NATURESTAFF_CRYSTAL';
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1512,height:982},permissions:['clipboard-read','clipboard-write']});
 const page=await context.newPage(),errors=[],external=[];
 page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});page.on('request',r=>{if(!r.url().startsWith(base))external.push(r.url());});
 try{
  await page.goto(base);await page.waitForSelector('.market-card');await page.locator('#city').selectOption('1002');
  await page.locator('[data-view="craft"]').click();
  await page.waitForSelector('#ideas-results .craft-opportunity');
  assert.equal(await page.locator('#ideas-results .craft-opportunity').count(),1);
  assert.equal(await page.locator('#ideas-results .craft-opportunity').getAttribute('data-item-id'),STAFF);
  assert.equal(await page.locator('#ideas-results .craft-frame').count(),5);
  assert.match(await page.locator('#ideas-results .opportunity-stats').textContent(),/140/);
  assert.doesNotMatch(await page.locator('#ideas-results .opportunity-stats').textContent(),/1.?140/);
  assert.equal(await page.locator('#ideas-results select').count(),0);
  assert.equal(await page.locator('#craft-manual').getAttribute('open'),null);
  await page.locator('#ideas-show').selectOption('all');await page.waitForFunction(()=>document.querySelectorAll('#ideas-results article').length===4);
  await page.locator('#ideas-sort').selectOption('profit_asc');
  await page.waitForFunction(()=>document.querySelector('#ideas-results article').dataset.itemId==='T4_MAIN_AXE');
  assert.equal(await page.locator('#ideas-results article').last().getAttribute('data-item-id'),'T4_OFF_BOOK');
  await page.locator('#ideas-show').selectOption('loss');await page.waitForFunction(()=>document.querySelectorAll('#ideas-results article').length===1);
  assert.equal(await page.locator('#ideas-results article').getAttribute('data-item-id'),'T4_MAIN_AXE');
  await page.locator('#ideas-show').selectOption('recommended');await page.waitForFunction(()=>document.querySelector('#ideas-results article')?.dataset.itemId==='T4_MAIN_NATURESTAFF_CRYSTAL');
  if(process.env.ALBION_ARTIFACT_DIR)await page.screenshot({path:process.env.ALBION_ARTIFACT_DIR+'/craft-ideas-desktop.png',fullPage:true});
  await page.getByRole('spinbutton',{name:"Количество для Adept's Forgebark Staff",exact:true}).fill('3');
  await page.locator('#ideas-results button').click();await page.waitForFunction(()=>document.querySelector('#batch-count').textContent==='1');
  assert.equal(await page.locator('#batch-lines .craft-frame').count(),5);
  assert.equal(await page.locator('#batch-lines select').count(),0);
  assert.equal(await page.locator('#batch-settings').getAttribute('open'),null);
  await page.locator('#batch-export-loadout').click();
  await page.waitForFunction(()=>document.querySelector('#batch-feedback').textContent.includes('Подготовлено кодов'));
  const code=JSON.parse(await page.evaluate(()=>navigator.clipboard.readText()));
  assert.deepEqual(code.inventory.map(r=>r.stack),[48,24,3]);
  // One explicit click enables and downloads shared data without visiting Settings.
  await page.locator('#ideas-update').click();
  await page.waitForFunction(()=>document.querySelector('#ideas-feedback').textContent.includes('Цены материалов, готовых вещей и продажи всех рамок обновлены'));
  assert.equal(await page.locator('#craft-view').isVisible(),true);assert.equal(await page.locator('#sources-view').isHidden(),true);
  const calls=JSON.parse(require('node:fs').readFileSync(process.env.ALBION_IDEAS_CALLS,'utf8'));
  assert.deepEqual([...new Set(calls.filter(r=>r.kind==='history').map(r=>r.q))].sort(),[1,2,3,4,5]);
  assert.equal(calls.filter(r=>r.kind==='prices'&&r.ids.includes('T4_PLANKS')).length,1);
  await page.waitForFunction(()=>document.querySelector('#ideas-results .opportunity-stats').textContent.includes('672'));
  // New observed data must automatically remove a losing craft from recommendations.
  await page.request.post(base+'/api/import',{data:{kind:'prices',server:'east',data:[{item_id:STAFF,city:'Lymhurst',quality:1,
    sell_price_min:100,sell_price_min_date:new Date().toISOString()}]}});
  await page.waitForFunction(()=>!document.querySelector('#ideas-empty').hidden,{},{timeout:25000});
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.body.scrollWidth),390);
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  console.log('PASS: automatic candidate discovery, all quality summaries, signed sort/filter, no masterpiece inflation, add-to-shopping/export, same-page bulk update, live rerank and mobile. Fixtures only.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
