// Only scripts/check_history_ui.py's disposable native/API fixtures.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const base=process.env.ALBION_SMOKE_URL;
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
  const page=await browser.newPage({viewport:{width:1512,height:982}}), errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(!r.url().startsWith(base))external.push(r.url());});
  await page.goto(base);await page.waitForSelector('.market-card');
  await page.locator('#city').selectOption('3005');
  await page.locator('#scope').selectOption('private');
  await page.locator('#quality').selectOption('4');
  await page.getByRole('button',{name:'График и города',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#history-quality').value==='4');
  await page.locator('[data-period="168"]').click();
  await page.waitForFunction(()=>document.querySelector('#history-summary').textContent.includes('28 точек из игры'));
  assert.equal(await page.locator('#history-chart circle').count(),28);
  assert.match(await page.locator('#history-summary').textContent(),/56 продано/);
  assert.doesNotMatch(await page.locator('#history-summary').textContent(),/3\/168/);
  await page.locator('[data-period="672"]').click();
  await page.waitForFunction(()=>document.querySelector('#history-summary').textContent.includes('шкала «4 недели»'));
  assert.equal(await page.locator('#history-chart circle').count(),28);
  // Disabled public loads are explained INSIDE the modal and do not change its source.
  await page.locator('#history-fetch').click();
  await page.waitForFunction(()=>document.querySelector('#history-feedback').textContent.includes('Публичные загрузки выключены'));
  assert.equal(await page.locator('#history-source').inputValue(),'private');
  assert.equal(await page.locator('#history-chart circle').count(),28);
  await page.request.post(base+'/api/settings/public-api',{data:{enabled:true}});
  await page.locator('#history-fetch').click();
  await page.waitForFunction(()=>document.querySelector('#history-feedback').textContent.includes('Общая история загружена'));
  assert.equal(await page.locator('#history-source').inputValue(),'public');
  assert.equal(await page.locator('#scope').inputValue(),'private');
  assert.match(await page.locator('#history-summary').textContent(),/7 продано/);
  await page.locator('#history-source').selectOption('private');
  await page.waitForFunction(()=>document.querySelector('#history-summary').textContent.includes('28 точек из игры'));
  if(process.env.ALBION_ARTIFACT_DIR)await page.screenshot({path:process.env.ALBION_ARTIFACT_DIR+'/history-regression.png'});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.body.scrollWidth),390);
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  console.log('PASS: game week/month points, inline permission error, public history fetch from private prices, separate sources, mobile, no external browser requests. Synthetic fixtures only.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
