/* Browser proof for the standalone presentation. Requires Playwright + Edge.
 * Usage: node scripts/verify-agent-loop.cjs [http://127.0.0.1:8893] [output-dir]
 * Measures rendered geometry, transfers, framing and playback; does not claim
 * these checks establish audience comprehension or cinematic quality.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const base = process.argv[2] || 'http://127.0.0.1:8893';
  const output = path.resolve(process.argv[3] || 'work/agent-loop-validation');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [], external = [], checks = [], layouts = [], states = [], motionSamples = [];
  const motionMetrics = {};
  const origin = new URL(base).origin;
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, reducedMotion: 'reduce' });
  context.on('page', opened => opened.on('pageerror', error => errors.push(error.message)));
  context.on('request', request => {
    const url = request.url();
    if (!url.startsWith('data:') && !url.startsWith('blob:') && new URL(url).origin !== origin) external.push(url);
  });
  const page = await context.newPage();
  const frame = target => target.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const ready = async target => {
    await target.waitForFunction(() => document.body.dataset.ready === 'true');
    await target.waitForLoadState('networkidle'); await frame(target);
  };
  const renderedFrame = async target => {
    const value = await target.locator('#viewport').getAttribute('data-frame');
    assert.ok(value, 'rendered frame diagnostics must exist for a working 3D scene');
    return JSON.parse(value);
  };
  const step = async (index, target = page) => {
    await target.locator('#scrubber').fill(String(index));
    await target.waitForFunction(i => document.body.dataset.step === String(i), index); await frame(target);
  };
  const capture = (name, target = page) => target.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
  const visiblePhotos = async (target = page) => target.locator('#photo-stage-overlay .shot-photo:visible').evaluateAll(elements => elements.map(el => ({
    id: Number(el.dataset.photoId), role: el.dataset.role || '', verdict: el.dataset.verdict || '', text: el.innerText,
  })));
  const visibleLabels = target => target.locator('#scene-labels [data-marker]:visible').evaluateAll(elements => elements
    .filter(el => Number(getComputedStyle(el).opacity) > 0).map(el => el.dataset.marker));
  const overlaySnapshot = target => target.locator('#photo-stage-overlay .shot-photo:visible, #payload:visible, #scene-labels [data-marker]:visible').evaluateAll(elements => elements
    .filter(el => Number(getComputedStyle(el).opacity) > 0).map(el => {
      const r = el.getBoundingClientRect(), style = getComputedStyle(el);
      return { key: el.dataset.photoId || el.dataset.marker || el.id, x: r.x, y: r.y, width: r.width, height: r.height, transform: style.transform, opacity: style.opacity };
    }));
  const assertFraming = async (target, width, index) => {
    const layout = await target.evaluate(() => {
      const stage = document.querySelector('.stage').getBoundingClientRect();
      const visible = el => !el.hidden && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden' && Number(getComputedStyle(el).opacity) > 0;
      const measure = el => {
        const r = el.getBoundingClientRect();
        return { name: el.dataset.photoId || el.dataset.marker || el.id, width: r.width, height: r.height,
          fits: r.left >= stage.left - 1 && r.right <= stage.right + 1 && r.top >= stage.top - 1 && r.bottom <= stage.bottom + 1 };
      };
      const captions = [...document.querySelectorAll('#photo-stage-overlay .shot-photo')].filter(visible);
      const rendered = JSON.parse(document.querySelector('#viewport').dataset.frame);
      const viewport = document.querySelector('#viewport').getBoundingClientRect();
      return {
        noOverflow: document.documentElement.scrollWidth <= innerWidth,
        labels: [...document.querySelectorAll('#scene-labels [data-marker]')].filter(visible).map(measure),
        captionBoxes: captions.map(measure), title: measure(document.querySelector('#action-title')),
        cards: rendered.cards.filter(card => card.active).map(card => ({
          id: card.id, depth: card.depth, ...card.bounds,
          fits: card.bounds.left >= -1 && card.bounds.top >= -1 && card.bounds.right <= viewport.width + 1 && card.bounds.bottom <= viewport.height + 1,
        })),
        captions: captions.flatMap(photo => [...photo.querySelectorAll('figcaption, .photo-caption, [data-caption]')])
          .filter(visible).map(el => ({ text: el.textContent.trim(), size: parseFloat(getComputedStyle(el).fontSize) })),
      };
    });
    layouts.push({ width, step: index, ...layout });
    assert.ok(layout.noOverflow, `horizontal overflow at ${width}px, step ${index}`);
    assert.ok(layout.title.fits, `action title clipped at ${width}px, step ${index}`);
    assert.ok(layout.labels.every(item => item.fits), `agent label clipped at ${width}px, step ${index}: ${JSON.stringify(layout.labels)}`);
    assert.ok(layout.captionBoxes.every(item => item.fits), `photo caption clipped at ${width}px, step ${index}: ${JSON.stringify(layout.captionBoxes)}`);
    assert.ok(layout.cards.every(item => item.fits && item.width > 0 && item.height > 0), `active mesh clipped or empty at ${width}px, step ${index}: ${JSON.stringify(layout.cards)}`);
    assert.ok(layout.cards.every(item => item.depth > 0), 'rendered photo cards have nonzero thickness');
    assert.deepEqual(layout.cards.map(item => item.id).sort(), layout.captionBoxes.map(item => Number(item.name)).sort(), 'active card geometry and visible photo captions match');
    if (width >= 1024 && [7, 16].includes(index)) {
      assert.ok(layout.cards.length >= 2, `comparison needs original and candidate at ${width}px`);
      assert.ok(layout.cards.every(item => item.width >= 190), `projected comparison mesh below 190px at ${width}px: ${JSON.stringify(layout.cards)}`);
      assert.ok(layout.captions.length >= layout.cards.length, 'each comparison photo needs a visible caption');
      assert.ok(layout.captions.every(item => item.size >= 12 && item.text), `comparison caption below 12px or empty: ${JSON.stringify(layout.captions)}`);
    }
  };
  const writeEvidence = (status, error) => {
    const evidence = { status, date: new Date().toISOString(), checks, states, layouts, motionMetrics, motionSamples, browser: browser.version(), screenshots: output,
      ...(error ? { failure: error.message, errors, external } : {}) };
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(evidence, null, 2)); return evidence;
  };
  try {
    await page.goto(base); await ready(page);
    assert.equal(await page.locator('#fallback').isVisible(), false);
    assert.equal(await page.locator('#viewport canvas').count(), 1);
    assert.equal(await page.locator('body').getAttribute('data-playing'), 'false');
    await capture('desktop-opening'); checks.push('WebGL renders; reduced-motion opening remains paused');

    await page.locator('#next').click();
    assert.equal(await page.locator('body').getAttribute('data-phase'), 'tool');
    await page.locator('#previous').click();
    assert.equal(await page.locator('body').getAttribute('data-step'), '0');
    await page.locator('h1').click(); await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('body').getAttribute('data-step'), '1');
    await page.keyboard.press('Home');
    assert.equal(await page.locator('body').getAttribute('data-step'), '0');
    checks.push('Previous/next, arrow keys and Home seek the matching state');

    const shots = ['decide', 'search', 'return', 'decide', 'inspect', 'return', 'submit', 'review', 'feedback', 'decide', 'search', 'return', 'decide', 'inspect', 'return', 'submit', 'review', 'organize', 'done'];
    const directionValues = ['outbound', 'return', 'feedback', 'handoff', 'none'];
    for (let index = 0; index < shots.length; index++) {
      await step(index);
      const shot = await page.locator('.stage').getAttribute('data-shot');
      assert.equal(shot, shots[index], `shot at step ${index}`);
      // Transfers follow the receiving Explorer/Reviewer; other shots label
      // the acting agent. This measures visual focus, not message authorship.
      const agent = [6, 7, 15, 16].includes(index) ? 'reviewer' : index >= 17 ? 'organizer' : 'explorer';
      const labels = await visibleLabels(page);
      assert.ok(labels.includes(agent), `required focused agent label visible at step ${index}: ${labels.join(', ')}`);
      assert.ok((await page.locator('#action-title').innerText()).trim(), `missing action at step ${index}`);
      assert.equal(await page.locator('.demo-label').isVisible(), true, `fixture label at step ${index}`);
      const direction = await page.locator('#payload').getAttribute('data-direction');
      assert.ok(directionValues.includes(direction), `unknown payload direction ${direction}`);
      const payloadTitle = await page.locator('#payload-title').innerText();
      const payloadDetail = await page.locator('#payload-detail').innerText();
      if (direction !== 'none') {
        assert.equal(await page.locator('#payload-title').isVisible(), true);
        assert.equal(await page.locator('#payload-detail').isVisible(), true);
        assert.ok(payloadTitle.trim() && payloadDetail.trim(), `anonymous transfer at step ${index}`);
      }
      if ([2, 5, 11, 14].includes(index)) assert.equal(direction, 'return', `observation returns at step ${index}`);
      if (index === 8) assert.equal(direction, 'feedback');
      if ([6, 15].includes(index)) assert.equal(direction, 'handoff');
      const photos = await visiblePhotos();
      const rendered = await renderedFrame(page);
      assert.deepEqual(rendered.cards.filter(card => card.active).map(card => card.id).sort(), photos.map(photo => photo.id).sort(), `rendered card identities match captions at step ${index}`);
      assert.ok(photos.every(photo => photo.id !== 0 || photo.role === 'original'), 'source is never relabeled as a candidate');
      if (index < 16) assert.ok(photos.every(photo => photo.verdict !== 'supported'), `premature accepted photo at step ${index}`);
      states.push({ step: index, shot, agent, labels, direction, payloadTitle, payloadDetail, photos, camera: rendered.camera, cards: rendered.cards.filter(card => card.active) });
    }
    checks.push('All 19 shots label the focused agent and name the action and directed payload; fixture badge stays visible');

    for (const [observationIndex, decisionIndex] of [[2, 3], [11, 12]]) {
      await step(observationIndex);
      const observation = (await page.locator('#observation').innerText()).trim();
      assert.ok(observation, `observation at step ${observationIndex}`);
      await step(decisionIndex);
      assert.equal((await page.locator('#observation').innerText()).trim(), observation, 'returned observation persists into next decision');
      assert.match(await page.locator('#request-text').innerText(), /inspect_photos|사진.*확인|이미지.*확인/);
    }
    await step(0); const initialRequest = await page.locator('#request-text').innerText();
    await step(8);
    assert.ok((await page.locator('#payload-detail').innerText()).trim().length > 6, 'feedback carries a specific clue');
    await capture('review-feedback'); await step(9);
    assert.notEqual(await page.locator('#request-text').innerText(), initialRequest, 'feedback changes next search request');
    assert.ok((await page.locator('#observation').innerText()).trim(), 'feedback observation available for new decision');
    assert.deepEqual((await visiblePhotos()).map(photo => photo.id), [0], 'revised search decision shows source, not future search results');
    await capture('refined-search');
    await step(10);
    assert.deepEqual((await visiblePhotos()).map(photo => photo.id).sort(), [1, 2], 'revised search reveals new candidates only when the search tool executes');
    checks.push('Four tool-result returns differ from one reviewer feedback; observations persist and next request changes');
    checks.push('New candidates appear after the revised search request, never before its tool execution');

    await step(7);
    assert.deepEqual((await visiblePhotos()).filter(photo => photo.role !== 'original').map(photo => [photo.id, photo.verdict]).sort(), [[3, 'rejected'], [4, 'rejected']]);
    await capture('rejected-comparison'); await step(16);
    assert.deepEqual((await visiblePhotos()).filter(photo => photo.role !== 'original').map(photo => [photo.id, photo.verdict]).sort(), [[1, 'supported'], [2, 'supported']]);
    await capture('supported-comparison'); await step(18);
    assert.deepEqual((await visiblePhotos()).map(photo => photo.id).sort(), [1, 2]);
    assert.equal(await page.locator('#next').isDisabled(), true);
    assert.equal(await page.locator('body').getAttribute('data-playing'), 'false');
    await capture('completed');
    checks.push('Rejected candidates stay excluded; final photos are exactly supported IDs 1 and 2, excluding source 0');

    await page.locator('#play').click();
    assert.equal(await page.locator('body').getAttribute('data-step'), '0');
    await page.locator('#play').click();
    await step(16); const seekA = await overlaySnapshot(page); const seekFrameA = await renderedFrame(page);
    await step(4); await step(16); const seekB = await overlaySnapshot(page); const seekFrameB = await renderedFrame(page);
    assert.deepEqual(seekA, seekB, 'reduced-motion seek gives same composed overlay regardless of history');
    assert.deepEqual(seekFrameA, seekFrameB, 'reduced-motion seek gives same camera, card and gripper transforms regardless of history');
    checks.push('Replay resets to zero; manual/reduced-motion seeks give stable rendered geometry and captions');

    await page.locator('#notes-toggle').click();
    assert.equal(await page.locator('#presenter-notes').isVisible(), true);
    await page.locator('#notes-toggle').click();
    for (const width of [1440, 1024, 760, 600, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const index of [4, 7, 8, 16, 18]) {
        await step(index); await assertFraming(page, width, index);
      }
      if ([1440, 1024, 600, 320].includes(width)) {
        await step(16); await capture(`comparison-width-${width}`);
      }
    }
    checks.push('Notes work; active mesh bounds and captions fit at six widths including 600px; desktop comparison meshes are >=190px and captions >=12px');

    const fallback = await context.newPage();
    await fallback.route('**/scene.js*', route => route.abort());
    await fallback.goto(base); await ready(fallback);
    assert.equal(await fallback.locator('#fallback').isVisible(), true);
    await fallback.locator('#next').click();
    assert.equal(await fallback.locator('body').getAttribute('data-step'), '1');
    assert.ok((await fallback.locator('#action-title').innerText()).trim());
    await capture('module-failure-fallback', fallback); await fallback.close();
    checks.push('Unavailable 3D module displays fallback with readable action and working step controls');

    const moving = await context.newPage();
    await moving.emulateMedia({ reducedMotion: 'no-preference' });
    await moving.goto(base); await ready(moving);
    assert.equal(await moving.locator('body').getAttribute('data-playing'), 'true');
    // Seeking lands in a completed readable composition. Enter feedback
    // through normal playback to exercise its actual camera/payload transfer.
    await step(7, moving); await moving.locator('#play').click();
    await moving.waitForFunction(() => document.body.dataset.step === '8', null, { timeout: 10000 });
    await moving.waitForTimeout(200);
    const animatedCanvasA = await moving.locator('#viewport canvas').screenshot();
    const animatedOverlayA = await overlaySnapshot(moving);
    await moving.waitForTimeout(300);
    const animatedCanvasB = await moving.locator('#viewport canvas').screenshot();
    const animatedOverlayB = await overlaySnapshot(moving);
    assert.notEqual(Buffer.compare(animatedCanvasA, animatedCanvasB), 0, 'canvas changes during motion');
    assert.notDeepEqual(animatedOverlayA, animatedOverlayB, 'visible photo/payload/agent-label positions change during feedback');
    await moving.locator('#play').click(); await frame(moving);
    const pausedCanvasA = await moving.locator('#viewport canvas').screenshot();
    const pausedOverlayA = await overlaySnapshot(moving);
    const pausedFrameA = await renderedFrame(moving);
    const pausedStep = await moving.locator('body').getAttribute('data-step');
    await moving.waitForTimeout(500);
    const pausedCanvasB = await moving.locator('#viewport canvas').screenshot();
    const pausedOverlayB = await overlaySnapshot(moving);
    assert.equal(Buffer.compare(pausedCanvasA, pausedCanvasB), 0, 'pause freezes rendered camera and agents');
    assert.deepEqual(pausedOverlayA, pausedOverlayB, 'pause freezes photo, label and payload bounding boxes');
    assert.deepEqual(pausedFrameA, await renderedFrame(moving), 'pause freezes camera, card, agent, gripper and token transforms');
    assert.equal(await moving.locator('body').getAttribute('data-step'), pausedStep);
    await capture('paused-feedback-motion', moving);
    checks.push('Canvas and visible overlay positions change while playing; rendered camera, cards, agents, grips and token freeze exactly on pause');

    await moving.locator('#restart').click(); await moving.locator('#speed').selectOption('2');
    await moving.evaluate(() => {
      window.observedSteps = [0];
      new MutationObserver(() => {
        const index = Number(document.body.dataset.step);
        if (window.observedSteps.at(-1) !== index) window.observedSteps.push(index);
      }).observe(document.body, { attributes: true, attributeFilter: ['data-step'] });
      // Read diagnostics from frames already rendered during the same playback;
      // never advance or mutate the scene to manufacture a motion sample.
      window.sampledFrames = [];
      window.samplingFrames = true;
      let lastStep = -1, lastProgress = -1;
      const sample = () => {
        if (!window.samplingFrames) return;
        const raw = document.querySelector('#viewport').dataset.frame;
        if (raw) {
          const value = JSON.parse(raw), index = Number(document.body.dataset.step);
          if (index !== lastStep || value.progress - lastProgress >= .045 || value.progress === 1 && lastProgress !== 1) {
            window.sampledFrames.push({ step: index, ...value });
            lastStep = index; lastProgress = value.progress;
          }
        }
        requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    });
    await moving.locator('#play').click();
    await moving.waitForFunction(() => document.body.dataset.step === '18' && JSON.parse(document.querySelector('#viewport').dataset.frame).progress > .2, null, { timeout: 60000 });
    await moving.locator('#play').click();
    assert.equal(await moving.locator('body').getAttribute('data-playing'), 'false');
    assert.equal(await moving.locator('#play').getAttribute('aria-label'), '시연 재생', 'pausing an unfinished final shot offers resume, not restart');
    await moving.locator('#play').click();
    assert.equal(await moving.locator('body').getAttribute('data-step'), '18', 'resuming the unfinished final shot stays on step 18');
    assert.equal(await moving.locator('body').getAttribute('data-playing'), 'true');
    await moving.waitForFunction(() => document.body.dataset.step === '18' && document.body.dataset.playing === 'false', null, { timeout: 10000 });
    assert.equal(await moving.locator('body').getAttribute('data-playing'), 'false');
    assert.deepEqual(await moving.evaluate(() => window.observedSteps), Array.from({ length: 19 }, (_, i) => i));
    await frame(moving);
    motionSamples.push(...await moving.evaluate(() => { window.samplingFrames = false; return window.sampledFrames; }));
    const distance = (a, b) => Math.hypot(...a.map((value, i) => value - b[i]));
    const actionPhases = new Set(['anticipate', 'reach', 'carry', 'release', 'hold']);
    assert.ok(motionSamples.every(sample => actionPhases.has(sample.actionPhase)), 'all sampled motion states name their action phase');
    const attached = motionSamples.flatMap(sample => sample.grips.filter(grip => grip.attached).map(grip => ({ sample, grip })));
    assert.ok(attached.length >= 2, 'playback must contain measured attached gripper frames');
    const gapValues = attached.map(({ grip }) => distance(grip.tip, grip.contact));
    motionMetrics.maximumGripContactGap = Math.max(...gapValues);
    assert.ok(motionMetrics.maximumGripContactGap <= .04, `rendered gripper tip separates from card contact: ${motionMetrics.maximumGripContactGap}`);
    const coupledSteps = [...new Set(attached.map(item => item.sample.step))];
    const movedWhileAttached = [];
    for (const index of coupledSteps) {
      const samples = motionSamples.filter(sample => sample.step === index);
      const carry = samples.filter(sample => sample.progress >= .35 && sample.progress <= .72 && sample.grips.some(grip => grip.attached));
      const settled = samples.filter(sample => sample.progress >= .85);
      assert.ok(settled.length > 0, `missing release/hold samples for coupled step ${index}`);
      assert.ok(settled.every(sample => sample.grips.every(grip => !grip.attached)), `gripper remains attached after release at step ${index}`);
      if (carry.length >= 2) {
        for (const grip of carry[0].grips.filter(item => item.attached)) {
          const sameGrip = carry.filter(sample => sample.grips.some(item => item.attached && item.agent === grip.agent && item.card === grip.card));
          if (sameGrip.length < 2) continue;
          const first = sameGrip[0], last = sameGrip.at(-1);
          const cardA = first.cards.find(card => card.id === grip.card), cardB = last.cards.find(card => card.id === grip.card);
          assert.ok(cardA && cardB && cardA.active && cardB.active, 'attached gripper references an active visible card');
          const travel = distance(cardA.position, cardB.position);
          if (travel > .05) movedWhileAttached.push({ step: index, agent: grip.agent, card: grip.card, travel });
        }
      }
    }
    motionMetrics.coupledSteps = coupledSteps;
    motionMetrics.cardTravelWhileAttached = movedWhileAttached;
    assert.ok(movedWhileAttached.length > 0, 'card world position must change while its gripper stays in contact');
    assert.ok(coupledSteps.some(index => [2, 5, 11, 14].includes(index)), 'a tool-return shot demonstrates card/gripper coupling');
    assert.ok(coupledSteps.some(index => [6, 15].includes(index)), 'a submission shot demonstrates card/gripper coupling');
    assert.ok(coupledSteps.includes(17), 'organization demonstrates card/gripper coupling');
    const cameraPositions = motionSamples.map(sample => sample.camera.position);
    const cameraHeights = cameraPositions.map(position => position[1]);
    motionMetrics.cameraHeightRange = Math.max(...cameraHeights) - Math.min(...cameraHeights);
    motionMetrics.maximumCameraTravelFromFirst = Math.max(...cameraPositions.map(position => distance(position, cameraPositions[0])));
    assert.ok(motionMetrics.cameraHeightRange > .1, 'camera shots have distinct physical heights');
    assert.ok(motionMetrics.maximumCameraTravelFromFirst > 1, 'camera changes physical position across shots');
    const finalShot = motionSamples.filter(sample => sample.step === 18);
    assert.ok(finalShot.some(sample => sample.progress < .85), 'final shot is played before its completed hold');
    const finalHold = finalShot.at(-1);
    assert.ok(finalHold && Math.abs(finalHold.progress - 1) <= 1e-6 && finalHold.actionPhase === 'hold', 'final shot reaches progress 1 and its reading hold before stopping');
    const cameraDistance = sample => distance(sample.camera.position, sample.camera.look);
    motionMetrics.finalShotPullback = cameraDistance(finalHold) - cameraDistance(finalShot[0]);
    motionMetrics.finalShotCameraTravel = distance(finalHold.camera.position, finalShot[0].camera.position);
    assert.ok(motionMetrics.finalShotCameraTravel > .05, 'camera physically moves during the final shot');
    assert.ok(motionMetrics.finalShotPullback > .05, 'final-shot camera moves farther from its look target');
    checks.push('Rendered gripper tips remain within 0.04 world units of card contacts; cards move while coupled and detach before their reading hold');
    checks.push('Tool return, submission and organization each include coupling; rendered camera changes position and height across the sequence');
    checks.push('Final shot plays its camera pullback and reaches progress 1 hold before playback stops');
    checks.push('Pause/resume during the final shot continues step 18 and only offers restart after completion');
    const completedCanvas = await moving.locator('#viewport canvas').screenshot();
    const completedOverlay = await overlaySnapshot(moving);
    await moving.waitForTimeout(400);
    assert.equal(Buffer.compare(completedCanvas, await moving.locator('#viewport canvas').screenshot()), 0);
    assert.deepEqual(completedOverlay, await overlaySnapshot(moving));
    checks.push('Continuous 2x playback visits all 19 steps in order, stops, and holds final result');

    // Lifecycle simulation checks the page handler; it is not an OS-window test.
    await moving.locator('#play').click();
    await moving.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    assert.equal(await moving.locator('body').getAttribute('data-playing'), 'false');
    await moving.evaluate(() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); });
    assert.equal(await moving.locator('body').getAttribute('data-playing'), 'false');
    await moving.locator('#play').click(); await moving.emulateMedia({ reducedMotion: 'reduce' });
    await moving.waitForFunction(() => document.body.dataset.playing === 'false');
    checks.push('Simulated hide/show and live reduced-motion change pause without silent restart');
    await moving.close();
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    checks.push('No uncaught browser errors or external runtime requests');
    const evidence = writeEvidence('PASS');
    console.log(JSON.stringify({ status: evidence.status, checks: evidence.checks, browser: evidence.browser }, null, 2));
  } catch (error) {
    await capture('failure').catch(() => {}); writeEvidence('FAIL', error); throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
