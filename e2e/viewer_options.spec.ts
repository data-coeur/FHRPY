import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

/*
 * Browser checks of the viewer options ported from OpenCTG (issues #14, #15,
 * #21, #22, #23, #24). Unlike viewer.spec.ts, the page is built here from the
 * CURRENT fhrviewer.js / .css and a bundled recording, so these specs never
 * depend on the generated examples/viewer_demo.html.
 */
const root = path.resolve(__dirname, '..');
const web = path.join(root, 'fhrpy', 'viewer', 'web');
const outDir = path.join(root, 'test-results');

function buildPage(name: string, dataFile: string, ext: string, options: Record<string, unknown>, markers: unknown[] = []): string {
  const js = fs.readFileSync(path.join(web, 'fhrviewer.js'), 'utf8')
    .replace('export class FHRViewer', 'class FHRViewer')
    .replace('export function upgradeAll', 'function upgradeAll')
    .replace('export { Signals };', '')
    .replace('export default FHRViewer;', '');
  const css = fs.readFileSync(path.join(web, 'fhrviewer.css'), 'utf8');
  const tpl = fs.readFileSync(path.join(web, 'standalone.html'), 'utf8');
  const b64 = fs.readFileSync(path.join(root, 'examples', dataFile)).toString('base64');
  // function replacements: the sources contain `$'`-like sequences that a replacement string would expand
  const html = tpl
    .replace('/*__CSS__*/', () => css)
    .replace('/*__JS__*/', () => js)
    .replace('{{DATA_B64}}', () => b64)
    .replace('{{EXT}}', () => ext)
    .replace('{{TITLE}}', () => name)
    .replace('{{MARKERS}}', () => JSON.stringify(markers))
    .replace('{{OPTIONS_JSON}}', () => JSON.stringify(options));
  fs.mkdirSync(outDir, { recursive: true });
  const file = path.join(outDir, `viewer-options-${name}.html`);
  fs.writeFileSync(file, html);
  return 'file://' + file;
}

async function open(page: Page, url: string): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(url);
  await page.waitForSelector('#fhr-host[data-ready="1"]', { timeout: 30000 });
  return errors;
}

async function pixels(page: Page) {
  return page.evaluate(() => {
    const c = document.querySelector('canvas.background-canvas') as HTMLCanvasElement;
    const d = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    let white = 0, lightGreen = 0, red = 0, lightGreenRun = 0, run = 0;
    for (let i = 0; i < d.length; i += 4) {
      const r = d[i], g = d[i + 1], b = d[i + 2];
      if (r === 255 && g === 255 && b === 255) white++;
      if (r > 150 && g < 100 && b < 100) red++;                 // the FHR1 curve
      // The former light-green paper. A few isolated pixels of that exact tone
      // remain where a green grid line (#AAFFAA) is anti-aliased over white at
      // ~20% coverage — 255 - 0.2*85 = 238 — so what tells a fill from a line
      // is the length of the horizontal run, not the count.
      if (r === 238 && g === 255 && b === 238) {
        lightGreen++;
        run++;
        if (run > lightGreenRun) lightGreenRun = run;
      } else run = 0;
      if ((i / 4 + 1) % c.width === 0) run = 0;                 // rows do not wrap
    }
    return { white, lightGreen, lightGreenRun, red, total: d.length / 4 };
  });
}

test('a 4-byte-header .fhr (the bundled FHRMA recording) is decoded from the right offset and draws the FHR curve (#14)', async ({ page }) => {
  const errors = await open(page, buildPage('fhr4', 'example_recording.fhr', 'fhr', { height: 400 }));
  const info = await page.evaluate(() => {
    const s = (window as any).fhrViewer.graph.signals;
    return { start: s.start, n: s.RCF1.length, bps: s.bytesBySample };
  });
  expect(info).toEqual({ start: 0, n: 14007, bps: 6 });
  expect((await pixels(page)).red).toBeGreaterThan(50);
  expect(errors).toEqual([]);
});

test('the paper is pure white and the 160 label chip is white above the band edge, grey below (#24)', async ({ page }) => {
  await open(page, buildPage('paper', 'sample.rcfm', 'rcfm', { height: 400 }));
  const px = await pixels(page);
  // no light-green FILL any more: the tone only survives as anti-aliasing of a
  // vertical grid line over white paper, never as a run across the page
  expect(px.lightGreenRun).toBeLessThan(3);
  expect(px.white).toBeGreaterThan(px.total * 0.4);
  const probe = await page.evaluate(() => {
    const g = (window as any).fhrViewer.graph, s = g.signals;
    const ctx = (g.canvas as HTMLCanvasElement).getContext('2d')!;
    const yA = g.BorderTop + ((s.maxRCF - s.safeMax) / (s.maxRCF - s.minRCF)) * g.RCFHeight;   // the 160 line
    const x = g.BorderLeft + ((600 - (g.time % 600)) / g.winlength) * g.graphWidth;         // first label column
    ctx.font = '18px Arial';
    const half = (ctx.measureText('160').width + 4) / 2;
    const at = (px: number, py: number) => Array.from(ctx.getImageData(Math.round(px), Math.round(py), 1, 1).data.slice(0, 3));
    return { above: at(x - half + 1.5, yA - 6), below: at(x - half + 1.5, yA + 6), inView: x < g.graphWidth };
  });
  expect(probe.inView).toBe(true);
  expect(probe.above).toEqual([255, 255, 255]);
  expect(probe.below).toEqual([240, 240, 240]);
});

test('the follow-live control sits at the right end of the scrollbar and locks the view on the end (#22)', async ({ page }) => {
  await open(page, buildPage('follow', 'example_recording.fhr', 'fhr', { height: 400 }));
  const btn = page.locator('.btn-follow');
  await expect(btn).toBeVisible();
  const row = (await page.locator('.fhr-viewer-scrollbar').boundingBox())!;
  const track = (await page.locator('.scrollbarTrack').boundingBox())!;
  const box = (await btn.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(track.x + track.width);
  expect(Math.abs(box.x + box.width - (row.x + row.width))).toBeLessThan(2);
  expect(box.height).toBeLessThanOrEqual(row.height + 1);
  expect(await page.evaluate(() => (window as any).fhrViewer.getFollow())).toBe(false);
  const t0 = await page.evaluate(() => (window as any).fhrViewer.graph.time);
  await btn.click();
  const st = await page.evaluate(() => {
    const v = (window as any).fhrViewer;
    return { on: v.getFollow(), time: v.graph.time, end: v._liveEnd(), active: v._btn.follow.classList.contains('active') };
  });
  expect(st.on).toBe(true);
  expect(st.time).toBe(st.end);
  expect(st.time).toBeGreaterThan(t0);
  expect(st.active).toBe(true);
  await page.click('.btn-previouspage');
  expect(await page.evaluate(() => (window as any).fhrViewer.getFollow())).toBe(false);
  await page.screenshot({ path: path.join(outDir, 'viewer-options-follow.png') });
});

test('the MHR toggle is drawn in the MHR colour with a −/+ prefix (#23)', async ({ page }) => {
  await open(page, buildPage('mhr', 'sample.rcfm', 'rcfm', { height: 400 }));
  const btn = page.locator('.btn-mhr');
  expect(await btn.evaluate((b) => getComputedStyle(b).color)).toBe('rgb(255, 0, 255)');
  expect(await btn.textContent()).toBe('− MHR');
  await btn.click();
  expect(await btn.textContent()).toBe('+ MHR');
  expect(await page.evaluate(() => (window as any).fhrViewer.channelVisible.MHR)).toBe(false);
});

test('the resize bar is a visible handle set apart from the buttons (#21)', async ({ page }) => {
  await open(page, buildPage('resize', 'sample.rcfm', 'rcfm', { height: 400 }));
  const buttons = (await page.locator('.controller-icons').boundingBox())!;
  const bar = page.locator('.resizebar');
  const box = (await bar.boundingBox())!;
  expect(box.y - (buttons.y + buttons.height)).toBeGreaterThanOrEqual(5);
  expect(box.height).toBeGreaterThanOrEqual(11);
  const bg = await bar.evaluate((b) => getComputedStyle(b).backgroundColor);
  expect(bg).toBe('rgb(233, 237, 236)');
});

test('opts.labels translates the tooltips (#15)', async ({ page }) => {
  await open(page, buildPage('labels', 'sample.rcfm', 'rcfm', {
    height: 400, labels: { previouspage: 'Page précédente', follow: 'Suivre le direct', 'mhr.text': 'RCM' },
  }));
  expect(await page.locator('.btn-previouspage').getAttribute('title')).toBe('Page précédente');
  expect(await page.locator('.btn-follow').getAttribute('title')).toBe('Suivre le direct');
  expect(await page.locator('.btn-mhr').textContent()).toBe('− RCM');
});
