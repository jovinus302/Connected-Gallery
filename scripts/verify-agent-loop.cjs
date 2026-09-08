/* Browser proof for the standalone presentation. Requires Playwright + Edge.
 * Usage: node scripts/verify-agent-loop.cjs [http://127.0.0.1:8891] [output-dir]
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const base = process.argv[2] || 'http://127.0.0.1:8891';
  const output = path.resolve(process.argv[3] || 'work/agent-loop-validation');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [], external = [], checks = [];
  const context = await browser.newContext({viewport:{width:1440,height:1050},reducedMotion:'reduce'});
  context.on('page', opened => opened.on('pageerror', error => errors.push(error.message)));
  context.on('request', request => {
    if (!request.url().startsWith(new URL(base).origin) && !request.url().startsWith('data:')) external.push(request.url());
  });
  const page = await context.newPage();
  const step = async (index) => {
    await page.locator('#scrubber').fill(String(index));
    await page.waitForFunction(i => document.body.dataset.step === String(i), index);
  };
  const capture = name => page.screenshot({path:path.join(output, `${name}.png`),fullPage:true});
  try {
    await page.goto(base);
    await page.waitForFunction(() => document.body.dataset.ready === 'true');
    assert.equal(await page.locator('#fallback').isVisible(), false);
    assert.equal(await page.locator('canvas').count(), 1);
    assert.equal(await page.locator('body').getAttribute('data-playing'), 'false');
    await capture('desktop-opening');
    checks.push('WebGL scene renders; reduced motion does not autoplay');

    await page.locator('#next').click();
    assert.equal(await page.locator('body').getAttribute('data-phase'), 'tool');
    await page.locator('#previous').click();
    assert.equal(await page.locator('body').getAttribute('data-step'), '0');
    await page.locator('h1').click();
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('body').getAttribute('data-step'), '1');
    await page.keyboard.press('Home');
    assert.equal(await page.locator('body').getAttribute('data-step'), '0');
    checks.push('Previous/next and keyboard seek synchronize the displayed step');

    for (const index of [2,5,11,14]) {
      await step(index);
      assert.equal(await page.locator('body').getAttribute('data-phase'), 'observe');
      assert.equal(await page.locator('[data-marker="observe"]').getAttribute('class'), 'orbit-label active');
    }
    await step(5);await capture('observation-loop');
    await step(7);
    assert.equal(await page.locator('.evidence-thumb.rejected').count(), 2);
    await step(8);
    assert.match(await page.locator('#evidence-value').innerText(), /첫 검토/);
    assert.equal(await page.locator('.feedback-label.active').count(), 1);
    await capture('review-feedback');
    await step(16);
    assert.equal(await page.locator('.evidence-thumb.supported').count(), 2);
    assert.equal(await page.locator('.evidence-thumb.photo-0').count(), 0);
    await step(18);
    assert.equal(await page.locator('#next').isDisabled(), true);
    assert.match(await page.locator('#evidence-value').innerText(), /재탐색 1회/);
    await capture('completed');
    checks.push('Four tool-observation returns, one conditional review feedback, two accepted non-source photos, terminal stop');

    await page.locator('#play').click();
    assert.equal(await page.locator('body').getAttribute('data-step'), '0');
    await page.locator('#play').click();
    await page.locator('#speed').selectOption('2');
    await page.locator('#play').click();
    await page.waitForFunction(() => document.body.dataset.step === '1', null, {timeout:7000});
    await page.locator('#play').click();
    const pausedStep = await page.locator('body').getAttribute('data-step');
    await page.waitForTimeout(2300);
    assert.equal(await page.locator('body').getAttribute('data-step'), pausedStep);
    checks.push('Replay starts at zero; 2× playback advances; pause holds state');

    await step(17);await page.locator('#play').click();
    await page.waitForFunction(() => document.body.dataset.step === '18', null, {timeout:7000});
    assert.equal(await page.locator('body').getAttribute('data-playing'), 'false');
    checks.push('Automatic playback stops at completion');

    await page.locator('#notes-toggle').click();
    assert.equal(await page.locator('#presenter-notes').isVisible(), true);
    await page.locator('#notes-toggle').click();
    for (const width of [1024,760,390,360,320]) {
      await page.setViewportSize({width,height:1000});await step(8);
      await page.waitForTimeout(100);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `overflow at ${width}`);
      const labels = await page.locator('#scene-labels [data-marker]').evaluateAll(elements => {
        const stage = document.querySelector('.stage').getBoundingClientRect();
        return elements.filter(el => getComputedStyle(el).opacity !== '0').map(el => {
          const r = el.getBoundingClientRect();
          return {name:el.dataset.marker,fits:r.left>=stage.left&&r.right<=stage.right&&r.top>=stage.top&&r.bottom<=stage.bottom};
        });
      });
      assert.ok(labels.every(label => label.fits), `clipped labels at ${width}: ${JSON.stringify(labels)}`);
      if ([1024,360].includes(width)) await capture(`width-${width}`);
    }
    checks.push('Notes toggle, no horizontal overflow or clipped scene labels at 1440/1024/760/390/360/320');

    const fallback = await context.newPage();
    await fallback.route('**/scene.js', route => route.abort());
    await fallback.goto(base);await fallback.waitForFunction(() => document.body.dataset.ready === 'true');
    assert.equal(await fallback.locator('#fallback').isVisible(), true);
    await fallback.locator('#next').click();
    assert.equal(await fallback.locator('body').getAttribute('data-step'), '1');
    checks.push('3D load failure shows concept fallback and preserves step controls');
    await fallback.close();
    const moving = await context.newPage();
    await moving.emulateMedia({reducedMotion:'no-preference'});
    await moving.goto(base);await moving.waitForFunction(() => document.body.dataset.ready === 'true');
    await moving.locator('#speed').selectOption('2');
    await moving.waitForTimeout(400);
    const movingA = await moving.locator('canvas').screenshot();
    await moving.waitForTimeout(250);
    const movingB = await moving.locator('canvas').screenshot();
    assert.notEqual(Buffer.compare(movingA,movingB),0,'sculptures and loop animate');
    await moving.locator('#play').click();
    const pausedA = await moving.locator('canvas').screenshot();
    await moving.waitForTimeout(200);
    const pausedB = await moving.locator('canvas').screenshot();
    assert.equal(Buffer.compare(pausedA,pausedB),0,'pause freezes the 3D scene');
    checks.push('Animated canvas changes during playback and freezes exactly on pause');

    await moving.locator('#restart').click();
    await moving.evaluate(() => {
      window.observedSteps=[0];
      new MutationObserver(() => {
        const step=Number(document.body.dataset.step);
        if(window.observedSteps.at(-1)!==step)window.observedSteps.push(step);
      }).observe(document.body,{attributes:true,attributeFilter:['data-step']});
    });
    await moving.locator('#play').click();
    await moving.waitForFunction(() => document.body.dataset.step==='18',null,{timeout:60000});
    assert.equal(await moving.locator('body').getAttribute('data-playing'),'false');
    assert.deepEqual(await moving.evaluate(() => window.observedSteps),Array.from({length:19},(_,i)=>i));
    checks.push('Continuous 2× playback traverses all 19 steps in order and stops');

    // Exercise the visibility handler with an explicit browser event; this is
    // lifecycle simulation, not a claim about OS window-switching behavior.
    await moving.locator('#play').click();
    await moving.evaluate(() => {
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
      document.dispatchEvent(new Event('visibilitychange'));
    });
    assert.equal(await moving.locator('body').getAttribute('data-playing'),'false');
    await moving.evaluate(() => {
      delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));
    });
    assert.equal(await moving.locator('body').getAttribute('data-playing'),'false');
    checks.push('Simulated hide/show pauses and does not silently resume');
    await moving.close();
    assert.deepEqual(errors, []);assert.deepEqual(external, []);
    checks.push('No uncaught browser errors; no external runtime requests');
    const evidence={status:'PASS',date:new Date().toISOString(),checks,browser:await browser.version(),screenshots:output};
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(evidence,null,2));
    console.log(JSON.stringify(evidence,null,2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
