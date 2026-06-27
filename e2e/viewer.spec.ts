import { test, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

const htmlPath = path.resolve(__dirname, '..', 'examples', 'viewer_demo.html');
const fileUrl = 'file://' + htmlPath;
const outDir = path.resolve(__dirname, '..', 'test-results');

test.beforeAll(() => {
  if (!fs.existsSync(htmlPath)) {
    throw new Error('examples/viewer_demo.html missing — generate it from Python first');
  }
  fs.mkdirSync(outDir, { recursive: true });
});

test('CTG viewer renders grid + curve and reacts to toggles', async ({ page }) => {
  await page.goto(fileUrl);

  // host signals readiness
  await page.waitForSelector('#fhr-host[data-ready="1"]', { timeout: 30000 });
  const canvas = page.locator('canvas.background-canvas');
  await expect(canvas).toBeVisible();

  // canvas must have non-trivial size
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThan(200);
  expect(box!.height).toBeGreaterThan(100);

  // the canvas should contain the CTG green grid and a (red) FHR curve:
  // sample pixels and assert we see grid-green and curve-red.
  const colors = await page.evaluate(() => {
    const c = document.querySelector('canvas.background-canvas') as HTMLCanvasElement;
    const ctx = c.getContext('2d')!;
    const img = ctx.getImageData(0, 0, c.width, c.height).data;
    let green = 0;
    let red = 0;
    let nonBg = 0;
    for (let i = 0; i < img.length; i += 4) {
      const r = img[i], g = img[i + 1], b = img[i + 2];
      // CTG grid green ~ #AAFFAA / background #EEFFEE
      if (g > 180 && r < 220 && b < 220 && g > r && g > b) green++;
      // red FHR curve
      if (r > 150 && g < 100 && b < 100) red++;
      if (!(r > 230 && g > 230 && b > 230)) nonBg++;
    }
    return { green, red, nonBg, total: img.length / 4 };
  });
  expect(colors.green).toBeGreaterThan(500); // grid present
  expect(colors.red).toBeGreaterThan(50);    // FHR curve present
  await page.screenshot({ path: path.join(outDir, 'viewer-default.png') });

  // toggle baseline + acc/dec zones off then on
  await page.click('.btn-baseline');
  await page.waitForTimeout(150);
  await page.click('.btn-baseline');
  await page.waitForTimeout(150);

  // toggle MHR off
  await page.click('.btn-mhr');
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(outDir, 'viewer-mhr-off.png') });

  // switch to 3cm/min
  await page.click('.btn-scale');
  await page.waitForTimeout(200);
  const is3cm = await page.evaluate(() => (window as any).fhrViewer.graph.is3cm);
  expect(is3cm).toBe(1);
  await page.screenshot({ path: path.join(outDir, 'viewer-3cm.png') });

  // interpolate gaps
  await page.click('.btn-interpolate');
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(outDir, 'viewer-interpolate.png') });

  // paging keeps time valid (record may fit on one screen -> clamped, not NaN)
  const t0 = await page.evaluate(() => (window as any).fhrViewer.graph.time);
  await page.click('.btn-nextpage');
  await page.waitForTimeout(150);
  const t1 = await page.evaluate(() => (window as any).fhrViewer.graph.time);
  expect(Number.isNaN(t1)).toBe(false);
  expect(t1).toBeGreaterThanOrEqual(t0);

  // scrollTo (fraction) is wired and keeps time finite
  await page.evaluate(() => (window as any).fhrViewer.scrollTo(0.5));
  await page.waitForTimeout(100);
  const t2 = await page.evaluate(() => (window as any).fhrViewer.graph.time);
  expect(Number.isFinite(t2)).toBe(true);
});

test('can add an event marker by clicking the trace (edit box opens)', async ({ page }) => {
  await page.goto(fileUrl);
  await page.waitForSelector('#fhr-host[data-ready="1"]', { timeout: 30000 });
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  const n0 = await page.evaluate(() => (window as any).fhrViewer.getMarkers().length);
  await page.click('.btn-addevent');
  const box = await page.evaluate(() => {
    const g = document.querySelector('.fhr-viewer .graph') as HTMLElement;
    const r = g.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  await page.mouse.click(box.x + box.w * 0.4, box.y + box.h * 0.4);
  // the edit textarea must become visible (regression: a stale addquestion ref threw here)
  const editVisible = await page.evaluate(() => {
    const t = document.querySelector('.eventTextEdit') as HTMLElement;
    return !!t && getComputedStyle(t).display !== 'none';
  });
  expect(editVisible).toBe(true);
  await page.evaluate(() => { (document.querySelector('.eventTextEdit') as HTMLTextAreaElement).value = 'e2e mark'; });
  await page.mouse.click(box.x + box.w * 0.85, box.y + box.h * 0.85);  // validate
  const marks = await page.evaluate(() => (window as any).fhrViewer.getMarkers());
  expect(marks.length).toBe(n0 + 1);
  expect(marks.some((m: any[]) => String(m[1]).includes('e2e mark'))).toBe(true);
  expect(errors).toEqual([]);
});
