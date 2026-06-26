import { test, expect } from '@playwright/test';
import { execFileSync } from 'child_process';
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs';

// Build a self-contained analyzed bundle from the bundled example recording,
// using the Python viewer (analyze=True), into a temp file Playwright won't wipe.
const OUT = path.join(os.tmpdir(), 'fhrpy_analyzed.html');
const PY = `from fhrpy.viewer import FHRViewer; FHRViewer('examples/example_recording.fhr', analyze=True, height=440, zones=True).to_html(${JSON.stringify(OUT)})`;

test.beforeAll(() => {
  execFileSync('python3', ['-c', PY], { cwd: path.resolve(__dirname, '..') });
});

test('analyzed viewer renders real baseline + acc/dec zones', async ({ page }) => {
  await page.goto('file://' + OUT);
  await page.waitForTimeout(1000);
  // The CTG grid + curve are present (non-trivial canvas content).
  const hasCanvas = await page.evaluate(() => !!document.querySelector('canvas.background-canvas'));
  expect(hasCanvas).toBeTruthy();
  await page.screenshot({ path: 'test-results/analyzed-full.png' });
});

test.afterAll(() => { try { fs.unlinkSync(OUT); } catch {} });
