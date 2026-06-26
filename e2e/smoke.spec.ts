import { test, expect } from '@playwright/test';

// Minimal smoke test: confirms Playwright can render a page and screenshot it.
// Replaced by real viewer tests once the FHR viewer is built (Étape 1).
test('playwright smoke: render + screenshot', async ({ page }) => {
  await page.setContent(`
    <html><body style="margin:0;background:#AAFFAA;font-family:sans-serif">
      <canvas id="c" width="400" height="120"></canvas>
      <div style="padding:8px">FHRPY Playwright smoke OK</div>
      <script>
        const ctx = document.getElementById('c').getContext('2d');
        ctx.strokeStyle = '#2a7';
        for (let x = 0; x < 400; x += 20) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,120); ctx.stroke(); }
        ctx.strokeStyle = '#c00'; ctx.beginPath();
        for (let x = 0; x < 400; x++) ctx.lineTo(x, 60 + 40*Math.sin(x/15));
        ctx.stroke();
      </script>
    </body></html>`);
  await expect(page.locator('text=FHRPY Playwright smoke OK')).toBeVisible();
  await page.screenshot({ path: 'test-results/smoke.png' });
});
