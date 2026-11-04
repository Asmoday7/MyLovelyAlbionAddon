// Only scripts/check_materials_ui.py's disposable local receiver and database.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const base=process.env.ALBION_SMOKE_URL;
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
  const page=await browser.newPage({viewport:{width:1512,height:982}}),errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(!r.url().startsWith(base))external.push(r.url());});
  const ingress=require('node:fs').readFileSync(process.env.ALBION_TEST_DESTINATION,'utf8');
  await page.goto(base);await page.waitForSelector('.market-card');
  await page.locator('#city').selectOption('1002');await page.locator('#scope').selectOption('private');
  await page.locator('#quality').selectOption('all');
  await page.waitForFunction(()=>document.querySelector('.market-card .q1').textContent.includes('7 600'));
  await page.getByRole('button',{name:'График и города',exact:true}).click();
  await page.locator('[data-period="168"]').click();
  const row={Id:42,ItemTypeId:'T4_PLANKS_LEVEL3@3',LocationId:'1000',QualityLevel:1,
    EnchantmentLevel:3,UnitPriceSilver:75000000,Amount:20,AuctionType:'offer',Expires:'2099-01-01T00:00:00Z'};
  const orders=await page.request.post(ingress+'/marketorders.ingest',{
    data:{Orders:[row,{...row,Id:43,UnitPriceSilver:60000000,AuctionType:'request'}]}});
  assert.ok(orders.ok(),await orders.text());
  const end=Math.floor(Date.now()/3600000)*3600;
  const histories=Array.from({length:28},(_,i)=>({Timestamp:(BigInt(end-i*21600)*10000000n+621355968000000000n).toString(),
    ItemAmount:2,SilverAmount:2000000}));
  assert.ok((await page.request.post(ingress+'/markethistories.ingest',{
    data:{AlbionId:1,LocationId:'1000',QualityLevel:1,Timescale:1,MarketHistories:histories}})).ok());
  await page.waitForFunction(()=>document.querySelector('#detail-prices .q1').textContent.includes('7 500'),{},{timeout:15000});
  await page.waitForFunction(()=>document.querySelector('#history-summary').textContent.includes('28 точек из игры'));
  assert.match(await page.locator('#detail-prices .q1').textContent(),/6 000/);
  assert.equal(await page.locator('#history-quality').inputValue(),'1');
  assert.match(await page.locator('#history-received').textContent(),/История получена:/);
  for(const q of [2,3,4,5])assert.doesNotMatch(await page.locator(`#detail-prices .q${q}`).textContent(),/7 500|6 000/);
  const stored=await (await page.request.get(base+'/api/private/orders?server=east')).json();
  assert.equal(stored.rows.length,2);
  assert.ok(stored.rows.every(r=>r.location==='1002'&&r.raw_location==='1000'&&r.market_type==='city'&&r.quality===1&&r.enchantment===3));
  assert.equal(await page.locator('#app-version').textContent(),'Версия 0.3.1');
  if(process.env.ALBION_ARTIFACT_DIR)await page.screenshot({path:process.env.ALBION_ARTIFACT_DIR+'/materials-live.png'});
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  console.log('PASS: material rescan across city/market, prices and weekly history update inside open dialog, normal quality independent of .3 enchantment, original location retained, version displayed. Synthetic fixtures only.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
