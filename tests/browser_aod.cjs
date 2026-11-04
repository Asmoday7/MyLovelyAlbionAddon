// Native JSON fixtures and actual loopback server; no Windows client or game is used.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const base=process.env.ALBION_SMOKE_URL;
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
  const page=await browser.newPage({viewport:{width:1512,height:982}}), errors=[], external=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(!r.url().startsWith(base))external.push(r.url());});
  await page.goto(base);
  await page.locator('#setup-private').click();
  await page.locator('#private-start').click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Сначала прочитайте'));
  await page.locator('#private-ack').check();
  const denied=page.waitForResponse(r=>r.url().endsWith('/api/private/launch'));
  await page.locator('#private-start').click();
  assert.equal((await denied).status(),400); // Linux must refuse an unprotected/unsupported launch.
  const started=await page.request.post(base+'/api/private/start',{data:{server:'east',experimental_ack:true}});
  assert.ok(started.ok());
  // The test obtains the ephemeral path from its isolated fixture file, never from a product endpoint.
  const path=require('node:fs').readFileSync(process.env.ALBION_TEST_DESTINATION,'utf8').trim();
  const payload={Orders:[{Id:42,ItemTypeId:'T4_BAG',LocationId:'3005',QualityLevel:1,EnchantmentLevel:0,UnitPriceSilver:1500000,Amount:7,AuctionType:'offer',Expires:'2099-01-01T00:00:00Z'}]};
  assert.ok((await page.request.post(path+'/marketorders.ingest',{data:payload})).ok());
  assert.ok((await page.request.post(path+'/marketorders.ingest',{data:payload})).ok());
  await page.waitForFunction(()=>document.querySelector('#private-counts').textContent.includes('Ордеров обработано: 2'));
  assert.match(await page.locator('#private-counts').textContent(),/уникальных на сервере: 1/);
  const mixed={Orders:[{...payload.Orders[0],Id:100},{...payload.Orders[0],Id:101,ItemTypeId:'T4_RUNE',QualityLevel:0}]};
  const rejected=await page.request.post(path+'/marketorders.ingest',{data:mixed});
  assert.equal(rejected.status(),400);
  await page.waitForFunction(()=>!document.querySelector('#private-rejection').hidden);
  assert.match(await page.locator('#private-rejection').textContent(),/Ордер 2.*T4_RUNE.*QualityLevel.*получено 0/);
  const diagnostic=await (await page.request.get(base+'/api/private/status')).json();
  assert.equal(diagnostic.own_orders,1);
  assert.equal(diagnostic.last_rejection.order,2);
  assert.equal(diagnostic.rejected,1);
  assert.doesNotMatch(await page.locator('#private-rejection').textContent(),/\/private\//);
  assert.equal(await page.locator('#server').isDisabled(),true);
  assert.match(await page.locator('#private-region').textContent(),/Сервер игры: не передаётся/);
  const download=page.waitForEvent('download');await page.locator('#private-orders-export').click();
  assert.equal((await download).suggestedFilename(),'My-Market-Orders.xlsx');
  await page.locator('#private-view details summary').click();
  await page.locator('#private-logs-refresh').click();
  if(process.env.ALBION_ARTIFACT_DIR)await page.screenshot({path:process.env.ALBION_ARTIFACT_DIR+'/aod-panel.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.body.scrollWidth),390);
  const stopped=page.waitForResponse(r=>r.url().endsWith('/api/private/stop'));await page.locator('#private-stop').click();assert.ok((await stopped).ok());
  assert.equal((await page.request.get(base+'/api/private/status')).ok(),true);
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  console.log('PASS: UI launch guard, native HTTP rescan, unique orders, exact mixed-page rejection, atomic rollback, region label, Excel, logs, stop, mobile, no external browser requests. Synthetic fixtures only.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
