// Isolated UI check: delayed failing API; no runtime business data is created.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  try {
    for (const width of [390, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
      const cdp = await page.context().newCDPSession(page);
      await cdp.send('Network.enable');
      await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 400, downloadThroughput: 150000, uploadThroughput: 75000 });
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
      await page.route('**/api/v1/**', async route => { await new Promise(resolve => setTimeout(resolve, 7000)); await route.abort('failed').catch(() => {}); });
      await page.goto(process.env.TEST_ORIGIN + '/search', { waitUntil: 'domcontentloaded', timeout: 120000 });
      const skeleton = page.getByRole('status', { name: 'در حال دریافت کالاها' });
      await skeleton.waitFor({ state: 'visible', timeout: 90000 });
      assert.equal(await skeleton.getAttribute('aria-busy'), 'true');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
      console.log(`PASS width=${width}: accessible skeleton, no horizontal overflow; 400ms latency, 4x CPU`);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
