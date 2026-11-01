// Run ONLY against an isolated temporary database populated with the real catalogue.
// The private packets below are synthetic test fixtures, never real observations.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
if (process.env.ALBION_CRAFT_TEST_DATA !== '1') throw new Error('Use a disposable test database and set ALBION_CRAFT_TEST_DATA=1.');
const base = process.env.ALBION_SMOKE_URL || 'http://127.0.0.1:8790';
const staff = 'T4_MAIN_NATURESTAFF_CRYSTAL';
const inputs = ['T4_PLANKS', 'T4_CLOTH', 'T4_ARTEFACT_MAIN_NATURESTAFF_CRYSTAL'];
(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true,
    args: process.env.CHROMIUM_NO_SANDBOX === '1' ? ['--no-sandbox'] : []});
  const context = await browser.newContext({viewport: {width: 1512, height: 982}, permissions: ['clipboard-read', 'clipboard-write']});
  const page = await context.newPage();
  const errors = [];
  let receiverStarted = false;
  page.on('pageerror', e => errors.push(e.message));
  const artifacts = process.env.ALBION_ARTIFACT_DIR;
  const post = async (path, body) => {
    const response = await page.request.post(base + path, {data: body});
    assert.ok(response.ok(), await response.text());
    return response.json();
  };
  const quantities = () => page.locator('#craft-resources .resource-qty').allTextContents();
  try {
    await page.goto(base);
    await page.locator('#layout-table').click();
    await page.waitForSelector('#rows tr');
    assert.equal(await page.evaluate(() => getComputedStyle(document.body).fontSize), '17px');
    assert.ok(await page.locator('#server').evaluate(n => n.getBoundingClientRect().height >= 46));
    assert.ok(await page.locator('#tier').isVisible());
    assert.ok(await page.locator('#enchantment').isVisible());
    assert.ok(await page.locator('#scope').isVisible());
    await page.locator('[data-view="craft"]').click();
    await page.locator('#craft-manual>summary').click();
    await page.locator('#craft-preview>summary').click();
    await page.waitForSelector('#craft-resources .craft-resource');
    assert.match(await page.locator('#craft-item-title').textContent(), /Кузнечный посох.*4\.0/);
    assert.deepEqual(await quantities(), ['16', '8', '1']);
    assert.match(await page.locator('#craft-resources').textContent(), /Pine Planks/);
    await page.locator('#craft-selector>summary').click();
    await page.locator('#craft-search').fill('forge bark');
    await page.waitForResponse(r => r.url().includes('/api/craft/search?search=forge+bark'));
    assert.equal(await page.locator('#craft-search-results button').count(), 1);
    await page.locator('#craft-enchantment').selectOption('1');
    await page.waitForFunction(() => document.querySelector('#craft-item-title').textContent.endsWith('4.1'));
    assert.equal(await page.locator('#craft-resources .craft-resource').first().getAttribute('data-item-id'), 'T4_PLANKS_LEVEL1@1');
    await page.locator('#craft-units').fill('10');
    await page.locator('#craft-units').blur();
    await page.waitForFunction(() => document.querySelector('#craft-resources .resource-qty').textContent === '160');
    assert.deepEqual(await quantities(), ['160', '80', '10']);
    await page.locator('#craft-enchantment').selectOption('0');
    await page.locator('#craft-city').selectOption('1002');
    await page.locator('#craft-sale-city').selectOption('3003');
    await page.locator('#craft-scope').selectOption('private');
    await page.waitForFunction(() => document.querySelector('#craft-public-refresh').disabled);
    assert.match(await page.locator('#craft-output').textContent(), /только заявку покупателя/);
    assert.equal(await page.locator('#craft-ready').textContent(), '0 / 3');
    await page.locator('#craft-next').click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'Pine Planks');
    assert.equal(await page.locator('#craft-ready').textContent(), '0 / 3');
    if (artifacts) {
      await page.locator('#craft-item-title').scrollIntoViewIfNeeded();
      await page.screenshot({path: artifacts + '/crafting-pack.png', fullPage: true});
    }
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.body.scrollWidth), 390);
    if (artifacts) await page.screenshot({path: artifacts + '/crafting-mobile.png', fullPage: true});
    await page.setViewportSize({width: 1512, height: 982});
    await page.locator('#craft-save').click();
    await page.waitForFunction(() => document.querySelectorAll('#craft-saved-list button').length === 1);
    await page.reload();
    await page.locator('#layout-table').click();
    await page.waitForSelector('#rows tr');
    await page.locator('[data-view="craft"]').click();
    await page.locator('#craft-saved-panel>summary').click();
    await page.locator('#craft-saved-list button').click();
    await page.waitForFunction(() => document.querySelector('#craft-units').value === '10');
    await page.waitForSelector('#craft-saved-list button.active');
    assert.equal(await page.locator('#craft-scope').inputValue(), 'private');
    assert.equal(await page.locator('#craft-city').inputValue(), '1002');
    assert.equal(await page.locator('#craft-sale-city').inputValue(), '3003');
    // A polling tick must not submit an empty quantity while the user edits it.
    await page.locator('#craft-units').fill('');
    await page.waitForTimeout(3300);
    assert.ok(await page.locator('#craft-plan').isVisible());
    await page.locator('#craft-units').fill('10');
    await page.locator('#craft-units').blur();
    await post('/api/private/start', {server: 'east', experimental_ack: true});
    receiverStarted = true;
    // Inspect the generated launcher as text; do not execute Windows code.
    const launcher = await (await page.request.get(base + '/api/private/launcher')).text();
    const destination = launcher.match(/http:\/\/127\.0\.0\.1:\d+\/private\/east\/[A-Za-z0-9_-]+/)?.[0];
    assert.ok(destination?.startsWith(base + '/private/'));
    await post(new URL(destination).pathname + '/marketorders.ingest', {Orders: inputs.map((id, i) => ({
      Id: 81000 + i, ItemTypeId: id, LocationId: '1002', QualityLevel: 1,
      UnitPriceSilver: 1000000, Amount: 1, AuctionType: 'offer', Expires: '2099-01-01T00:00:00Z'
    }))});
    await page.waitForFunction(() => document.querySelector('#craft-ready').textContent === '3 / 3', {timeout: 15000});
    assert.match(await page.locator('#craft-cost').textContent(), /25\s?000/);
    assert.equal(await page.locator('#craft-resources .craft-resource.ready').count(), 3);
    await page.locator('#craft-next').click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), "Adept's Forgebark Staff");
    await page.locator('#craft-scope').selectOption('public');
    await page.waitForFunction(() => document.querySelector('#craft-ready').textContent === '0 / 3');
    assert.equal(await page.locator('#craft-cost').textContent(), 'Нужны цены');
    await post('/api/private/stop', {});
    receiverStarted = false;
    // Reopening a saved pack changes the shared server selector. Returning to
    // the market must reload prices for that server rather than keep old rows.
    const westMarket = page.waitForResponse(r => r.url().includes('/api/market?server=west'));
    await page.locator('#server').selectOption('west');
    await westMarket;
    await page.locator('#craft-saved-list button').click();
    await page.waitForFunction(() => document.querySelector('#server').value === 'east');
    // An item can also open its pack directly from the price table.
    const eastMarket = page.waitForResponse(r => r.url().includes('/api/market?server=east'));
    await page.locator('[data-view="market"]').click();
    await eastMarket;
    await page.locator('#search').fill(staff);
    await page.waitForResponse(r => r.url().includes('/api/market?') && r.url().includes('search=' + staff));
    await page.locator('#rows .item-actions .quiet').first().click();
    await page.waitForFunction(() => !document.querySelector('#craft-view').hidden && document.querySelector('#craft-item-title').textContent.includes('4.0'));
    await page.locator('#craft-saved-list button').click();
    await page.locator('#craft-delete').click();
    await page.waitForFunction(() => document.querySelectorAll('#craft-saved-list button').length === 0);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({passed: true, realRecipe: 'Forgebark IV.0 and IV.1', batchQuantities: [160, 80, 10], savedPackSurvivesReload: true,
      syntheticLocalIngestUpdatesVisibleProgress: true, publicPrivateSeparated: true, clipboardDoesNotFakeScanning: true, mobileWidth: 390, javascriptErrors: errors.length}));
  } finally {
    if (receiverStarted) await page.request.post(base + '/api/private/stop', {data: {}}).catch(() => {});
    await browser.close();
  }
})().catch(e => {console.error(e); process.exit(1);});
