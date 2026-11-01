// Optional real-network acceptance: start with an EMPTY data directory.
// Loads the real catalogue; no synthetic prices are inserted into the app.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true,
    args: process.env.CHROMIUM_NO_SANDBOX === '1' ? ['--no-sandbox'] : []});
  const artifacts = process.env.ALBION_ARTIFACT_DIR;
  try {
    const page = await browser.newPage({viewport: {width: 1512, height: 982}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const base = process.env.ALBION_SMOKE_URL || 'http://127.0.0.1:8780';
    await page.goto(base);
    await page.waitForFunction(() => document.querySelector('#item-count').textContent !== '—');
    assert.equal(await page.locator('#market-workspace').isHidden(), true);
    assert.equal(await page.locator('#setup-sync').isVisible(), true);
    assert.equal(await page.locator('#refresh').isDisabled(), true);
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme), 'light');
    if (artifacts) await page.screenshot({path: artifacts + '/first-run.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.body.scrollWidth), 390);
    if (artifacts) await page.screenshot({path: artifacts + '/first-run-mobile.png', fullPage: true});
    await page.setViewportSize({width: 1512, height: 982});
    await page.request.post(base+'/api/settings/public-api',{data:{enabled:true}});
    await page.locator('#setup-sync').click();
    await page.waitForFunction(() => !document.querySelector('#job-progress').hidden);
    assert.equal(await page.locator('#setup-sync').isDisabled(), true);
    // Reload during the live download: the UI must reconnect to its active job.
    await page.reload();
    await page.waitForFunction(() => !document.querySelector('#market-workspace').hidden && document.querySelector('#job-progress').hidden, {timeout: 180000});
    const status = await (await page.request.get(base + '/api/status')).json();
    assert.ok(status.items > 1000);
    assert.equal(status.quotes, 0);
    await page.locator('#layout-table').click();
    await page.locator('#example-crystal').click();
    await page.waitForFunction(() => document.querySelectorAll('#rows tr').length === 1);
    assert.match(await page.locator('#rows').textContent(), /Кристалл разлома \(знаток\)/);
    assert.equal(await page.locator('#extra-filters').evaluate(node => node.open), false);
    const cityChanged = page.waitForResponse(r => r.url().includes('/api/market?') && r.url().includes('city=1002'));
    await page.locator('#city').selectOption('1002');
    await cityChanged;
    assert.equal(await page.locator('#market-table th.advanced-column').first().isVisible(), false);
    if (artifacts) await page.screenshot({path: artifacts + '/friendly-market.png', fullPage: true});
    const request = page.waitForRequest(r => r.url().endsWith('/api/market/refresh') && r.method() === 'POST');
    await page.locator('#rows .row-refresh').click();
    const body = (await request).postDataJSON();
    assert.deepEqual(body.items, ['T4_ARTEFACT_2H_GLAIVE_CRYSTAL']);
    assert.deepEqual(body.cities, ['1002']);
    assert.deepEqual(body.qualities, [1]);
    await page.waitForFunction(() => document.querySelector('#job-progress').hidden, {timeout: 120000});
    const outcome = await page.locator('#notice').textContent();
    assert.ok(outcome.includes('Не удалось') || outcome.includes('Получено') || outcome.includes('Запрос выполнен'), outcome);
    if (outcome.includes('Не удалось')) {
      assert.equal(await page.locator('#error-details').isVisible(), true);
      assert.ok((await page.locator('#error-text').textContent()).length > 0);
    }
    await page.locator('[data-view="help"]').click();
    assert.match(await page.locator('#help-view').textContent(), /не подтверждают получение рыночных данных/);
    if (artifacts) await page.screenshot({path: artifacts + '/friendly-help.png', fullPage: true});
    await page.locator('[data-view="market"]').click();
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.body.scrollWidth), 390);
    if (artifacts) await page.screenshot({path: artifacts + '/friendly-market-mobile.png', fullPage: true});
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({firstRunPassed: true, realCatalogueItems: status.items, singleItemRequestCorrect: true, priceOutcome: outcome, javascriptErrors: errors.length}));
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exit(1);});
