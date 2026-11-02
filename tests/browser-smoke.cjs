// Optional integration check against a running real ASR server, with a WAV file
// as a fake microphone. This never records the computer's physical microphone.
const {chromium} = require('../work/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const audio = path.resolve(process.env.SMOKE_AUDIO_PATH || 'work/zh.wav');
  const browser = await chromium.launch({channel:'msedge',headless:true,args:[
    '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${audio}`,
  ]});
  const context = await browser.newContext({permissions:['microphone'],viewport:{width:1440,height:1050}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(process.env.SMOKE_BASE_URL || 'http://127.0.0.1:8001');
    await page.locator('#start:enabled').waitFor();
    // Session creation must disable capture immediately, even before HTTP returns.
    const creation = page.waitForResponse(r => r.url().endsWith('/api/sessions') && r.request().method() === 'POST');
    await page.locator('#settings-toggle').click();
    await page.locator('#new-session').click();
    assert.ok(await page.locator('#start').isDisabled());
    const created = await (await creation).json();
    await page.waitForFunction(id => localStorage.getItem('caption-session') === id, created.id);
    await page.locator('#start:enabled').waitFor();
    await page.locator('#start').click();
    await page.locator('.segment.provisional').first().waitFor({timeout:120000});
    console.log('provisional subtitle observed');
    const confirmed = page.locator('.segment.committed').first();
    await confirmed.waitFor({timeout:120000});
    // Auto-save changes the status class; keep following this segment's ID.
    const first = page.locator(`.segment[data-id="${await confirmed.getAttribute('data-id')}"]`);
    const original = await first.locator('.segment-text').textContent();
    assert.ok(original.length > 0);
    console.log('real ASR text:',original);
    await first.locator('.segment-text').click();
    const editor = first.locator('.segment-text');
    const corrected = '人工校正測試：這段文字必須鎖定保留。';
    await editor.fill(corrected);
    // Let later speech reach the server while a draft is open.
    await page.waitForTimeout(1800);
    assert.equal(await editor.innerText(),corrected);
    assert.equal(await page.locator('#recording-status').textContent(),'正在收音');
    await editor.press('Control+Enter');
    await page.locator('.segment.human_corrected').waitFor();
    assert.equal(await page.locator('.segment.human_corrected .segment-text').textContent(),corrected);
    await page.locator('#stop').click();
    await page.locator('#start:enabled').waitFor({timeout:120000});
    assert.equal(await page.locator('.segment.provisional').count(),0);
    await editor.press('Tab');
    await page.locator('#settings-toggle').click();
    await page.selectOption('#export-format','json');
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#export').click();
    const download = await downloadPromise;
    const data = JSON.parse(await fs.readFile(await download.path(),'utf8'));
    assert.ok(data.segments.some(row => row.text === corrected && row.locked && row.status === 'human_corrected'));
    assert.ok(data.segments.every(row => row.end >= row.start));
    await page.reload();
    await page.locator('.segment.human_corrected').waitFor();
    assert.equal(await page.locator('.segment.human_corrected .segment-text').textContent(),corrected);
    await page.screenshot({path:process.env.SMOKE_SCREENSHOT_PATH || 'work/smoke-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'work/smoke-mobile.png',fullPage:true});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.deepEqual(errors,[]);
    console.log('PASS: fake microphone -> real ASR -> provisional/committed -> edit during capture -> locked -> stop -> export -> reload; mobile layout; no browser errors');
  } catch (error) {
    await page.screenshot({path:'work/smoke-failure.png',fullPage:true});
    throw error;
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
