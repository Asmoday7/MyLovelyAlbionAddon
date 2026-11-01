// Optional UI acceptance: installed Playwright + Chromium, live app with real catalogue.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true,
    args: process.env.CHROMIUM_NO_SANDBOX === '1' ? ['--no-sandbox'] : [],
  });
  try {
    const page = await browser.newPage({viewport: {width: 1512, height: 982}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(process.env.ALBION_SMOKE_URL || 'http://127.0.0.1:8765');
    await page.locator('#layout-table').click();
    await page.waitForSelector('#rows tr');
    assert.equal(await page.locator('#rows tr').count(), 50);
    const response = page.waitForResponse(r => r.url().includes('/api/market?') && r.url().includes('search=T4_BAG'));
    await page.locator('#search').fill('T4_BAG');
    await response;
    await page.locator('#rows .item-id').filter({hasText: /^T4_BAG$/}).locator('..').getByRole('button').click();
    await page.waitForSelector('#detail-cities table');
    assert.equal(await page.locator('#detail-cities table').first().locator('tr').count() - 1, 8);
    await page.locator('#close-dialog').click();
    await page.locator('#select-all').check();
    assert.ok((await page.locator('#refresh').textContent()).includes('(10)'));
    const downloading = page.waitForEvent('download');
    await page.locator('#export-xlsx').click();
    const download = await downloading;
    assert.equal(download.suggestedFilename(), 'MarketPrices.xlsx');
    if (process.env.ALBION_ARTIFACT_DIR) await download.saveAs(process.env.ALBION_ARTIFACT_DIR + '/market.xlsx');
    if (!await page.locator('#nav-more').evaluate(node => node.open)) await page.locator('#nav-more summary').click();
    await page.locator('[data-view="sources"]').click();
    assert.match(await page.locator('#nats-state').textContent(), /Выключен/);
    await page.locator('[data-view="private"]').click();
    assert.equal(await page.locator('#private-launcher').isDisabled(), true);
    assert.match(await page.locator('#private-state').textContent(), /Выключен/);
    await page.locator('#private-start').click();
    assert.match(await page.locator('#notice').textContent(), /Сначала прочитайте/);
    await page.locator('#private-ack').check();
    await page.route('**/api/private/launch', async route => { const r=await page.request.post((process.env.ALBION_SMOKE_URL || 'http://127.0.0.1:8765')+'/api/private/start',{data:{server:'east',experimental_ack:true}}); await route.fulfill({status:r.status(),body:await r.text(),contentType:'application/json'}); });
    const enabled = page.waitForResponse(r => r.url().endsWith('/api/private/launch') && r.status() === 200);
    await page.locator('#private-start').click();
    await enabled;
    await page.waitForFunction(() => !document.querySelector('#private-launcher').disabled);
    assert.match(await page.locator('#private-privacy').textContent(), /не выполнена|не подтверждено/);
    const launchDownload = page.waitForEvent('download');
    await page.locator('#private-launcher').click();
    assert.equal((await launchDownload).suggestedFilename(), 'Start-PrivateScanner.ps1');
    if (process.env.ALBION_ARTIFACT_DIR) await page.screenshot({path: process.env.ALBION_ARTIFACT_DIR + '/private-scanner.png', fullPage: true});
    const disabled = page.waitForResponse(r => r.url().endsWith('/api/private/stop') && r.status() === 200);
    await page.locator('#private-stop').click();
    await disabled;
    await page.waitForFunction(() => document.querySelector('#private-launcher').disabled);
    await page.locator('[data-view="market"]').click();
    if (process.env.ALBION_ARTIFACT_DIR) await page.screenshot({path: process.env.ALBION_ARTIFACT_DIR + '/market-desktop.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.body.scrollWidth), 390);
    if (process.env.ALBION_ARTIFACT_DIR) await page.screenshot({path: process.env.ALBION_ARTIFACT_DIR + '/market-mobile.png', fullPage: true});
    assert.deepEqual(errors, []);
    console.log('Browser smoke passed: catalogue, search, eight markets, XLSX, opt-in private receiver, launcher download, stop, mobile layout; no JS errors.');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
