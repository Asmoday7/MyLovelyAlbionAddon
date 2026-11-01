// Only scripts/check_craft_batch_ui.py's synthetic quotes and native history.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const base=process.env.ALBION_SMOKE_URL;
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1512,height:982},permissions:['clipboard-read','clipboard-write']});
 const page=await context.newPage(),errors=[],external=[];
 page.on('pageerror',e=>{errors.push(e.message);console.error('Browser error:',e.message);});page.on('request',r=>{if(!r.url().startsWith(base))external.push(r.url());});
 try{
  await page.goto(base);await page.waitForSelector('.market-card');await page.locator('[data-view="craft"]').click();
  await page.waitForFunction(()=>document.querySelector('#craft-item-title').textContent.includes('4.0'));
  await page.locator('#craft-city').selectOption('1002');await page.locator('#craft-sale-city').selectOption('1002');
  assert.equal(await page.locator('#craft-selector').getAttribute('open'),null);
  assert.equal(await page.locator('#craft-workspace').evaluate(e=>getComputedStyle(e).display),'block');
  await page.locator('#craft-units').fill('10');await page.locator('#craft-units').blur();
  await page.waitForFunction(()=>document.querySelector('#craft-produced').textContent==='10 шт.');
  await page.locator('#batch-add').click();await page.waitForFunction(()=>document.querySelector('#batch-count').textContent==='1');
  await page.locator('#craft-selector summary').click();await page.locator('#craft-search').fill('T4_MEAL_STEW');
  await page.waitForFunction(()=>document.querySelector('#craft-item-title').textContent.includes('T4_MEAL_STEW'));
  await page.locator('#craft-units').fill('11');await page.locator('#craft-units').blur();
  await page.waitForFunction(()=>document.querySelector('#craft-produced').textContent==='20 шт.');
  await page.locator('#batch-add').click();await page.waitForFunction(()=>document.querySelector('#batch-count').textContent==='2');
  assert.equal(await page.locator('#batch-materials tr').count(),3);
  assert.match(await page.locator('[data-material-id="T4_CLOTH"]').textContent(),/88/);
  await page.locator('#batch-no-focus').fill('20');await page.locator('#batch-no-focus').blur();
  await page.waitForFunction(()=>document.querySelector('#batch-profit-no-focus').textContent.includes('6 097'));
  await page.locator('#batch-focus').fill('40');await page.locator('#batch-focus').blur();
  await page.waitForFunction(()=>document.querySelector('#batch-profit-focus').textContent.includes('6 769'));
  assert.match(await page.locator('#batch-lines').textContent(),/28 продано/);
  assert.match(await page.locator('#batch-lines').textContent(),/Партия выше выбранной доли/);
  // Fresh price coverage must not disable the actual shopping queue.
  await page.locator('#batch-copy-name').click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'Pine Planks');
  await page.locator('#batch-copy-quantity').click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'160');
  const bought=page.getByRole('spinbutton',{name:'Уже куплено Pine Planks',exact:true});
  await bought.fill('100');await bought.blur();
  await page.waitForFunction(()=>document.querySelector('#batch-queue-quantity').textContent.includes('60'));
  assert.match(await page.locator('#batch-profit-no-focus').textContent(),/6 097/); // stock is not free.
  await page.locator('#batch-copy-quantity').click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'60');
  await page.locator('#batch-export-loadout').click();
  await page.waitForFunction(()=>!document.querySelector('#batch-loadout-result').hidden);
  const preset=JSON.parse(await page.evaluate(()=>navigator.clipboard.readText()));
  assert.equal(preset.version,1);assert.equal(preset.icon,6);
  assert.deepEqual(preset.inventory.map(r=>[r.item,r.quality,r.stack]),[
    ['T4_PLANKS',1,60],['T4_CLOTH',1,88],['T4_ARTEFACT_MAIN_NATURESTAFF_CRYSTAL',1,10]]);
  await page.locator('#batch-done').click();await page.waitForFunction(()=>document.querySelector('#batch-queue-name').textContent==='Fine Cloth');
  assert.ok(await page.locator('#batch-loadout-result').isHidden());
  await page.locator('#batch-name').fill('Оружие и расходники');await page.locator('#batch-save').click();
  await page.waitForFunction(()=>document.querySelector('#batch-feedback').textContent.includes('сохранены'));
  if(process.env.ALBION_ARTIFACT_DIR){await page.locator('#batch-workspace').scrollIntoViewIfNeeded();await page.screenshot({path:process.env.ALBION_ARTIFACT_DIR+'/craft-batch.png',fullPage:true});}
  await page.reload();await page.locator('[data-view="craft"]').click();
  await page.waitForFunction(()=>document.querySelector('#batch-count').textContent==='2');
  assert.equal(await page.getByRole('spinbutton',{name:'Уже куплено Pine Planks',exact:true}).inputValue(),'160');
  await page.locator('#craft-scope').selectOption('private');
  await page.waitForFunction(()=>document.querySelector('#batch-context').textContent.includes('мои наблюдения'));
  // Invalid public downloads have a visible explanation and preserve the draft.
  await page.locator('#batch-refresh').click();
  await page.waitForFunction(()=>document.querySelector('#batch-feedback').textContent.includes('Публичные загрузки выключены'));
  assert.equal(await page.locator('#batch-lines tr').count(),2);
  assert.equal(await page.locator('#craft-scope').inputValue(),'private');
  await page.request.post(base+'/api/settings/public-api',{data:{enabled:true}});
  await page.locator('#batch-refresh').click();
  await page.waitForFunction(()=>document.querySelector('#batch-feedback').textContent.includes('Обновление завершено'));
  assert.equal(await page.locator('#craft-scope').inputValue(),'all');
  assert.match(await page.locator('#batch-profit-no-focus').textContent(),/6 992/);
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.body.scrollWidth),390);
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  console.log('PASS: mixed recipes, aggregated quantities, no/focus profit, partial liquidity, independent shopping queue, persistent progress, inline public-download error, mobile. Synthetic fixtures only.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
