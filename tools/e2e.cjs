const { chromium } = require('playwright');

const BASE = 'http://127.0.0.1:8787';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1560, height: 980 } });
  page.setDefaultTimeout(20000);
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message));

  const imageNodes = page.locator('.node').filter({ has: page.locator('.node-title', { hasText: '图片' }) });
  const videoNode = page.locator('.node').filter({ has: page.locator('.node-title', { hasText: '视频' }) });

  async function waitDone(node, label, timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const t = await node.locator('.status').innerText().catch(() => '');
      process.stdout.write(`\r  ${label}: ${t.slice(0, 70)}`.padEnd(90));
      if (t.includes('✅') || t.includes('❌')) { console.log(); return t; }
      await page.waitForTimeout(2500);
    }
    console.log();
    return 'TIMEOUT';
  }

  console.log('1) 打开工作台…');
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  console.log('2) 生成首帧（图片节点 #1）…');
  await imageNodes.nth(0).locator('.gen').click();
  const r1 = await waitDone(imageNodes.nth(0), '首帧', 180000);
  await page.screenshot({ path: 'docs/run-1-first.png' });
  console.log('   ->', r1);

  console.log('3) 生成尾帧（图片节点 #2）…');
  await imageNodes.nth(1).locator('.gen').click();
  const r2 = await waitDone(imageNodes.nth(1), '尾帧', 180000);
  await page.screenshot({ path: 'docs/run-2-last.png' });
  console.log('   ->', r2);

  console.log('4) 首尾帧合成视频（视频节点）…');
  await videoNode.locator('.gen').click();
  const r3 = await waitDone(videoNode, '视频', 420000);
  await page.screenshot({ path: 'docs/run-3-video.png' });
  console.log('   ->', r3);

  const summary = await page.evaluate(() => ({
    statuses: [...document.querySelectorAll('.node')].map((n) => ({
      type: n.querySelector('.node-title')?.innerText,
      status: n.querySelector('.status')?.innerText,
    })),
    images: [...document.querySelectorAll('.node .preview img')].map((i) => i.src),
    video: document.querySelector('.node video')?.src || null,
  }));
  console.log('SUMMARY:', JSON.stringify(summary, null, 2));
  console.log('CONSOLE ERRORS:', errors.length ? errors : 'none');

  await browser.close();
})().catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
