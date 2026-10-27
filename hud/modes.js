/* EYES · WATCH · HOLO · FOCUS. Each mode starts only from an explicit click here or a spoken
   request JARVIS forwards to this page; nothing starts when the page loads.
   EYES:  camera frames go to this PC's Brain server (newest frame only, memory only).
   WATCH: masked desktop preview every 5 s, memory only, needs this page visible.
   HOLO:  hand tracking runs in this page (MediaPipe); landmarks never leave the browser.
   FOCUS: foreground app names only; JARVIS calls out drift if you let him. */
'use strict';
(() => {
  const el = id => document.getElementById(id);
  const panel = el('modePanel');
  const toggles = Object.fromEntries([...document.querySelectorAll('.mode')].map(b => [b.dataset.mode, b]));
  const sections = {};
  let openMode = null;
  const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  function setToggle(mode, text, cls) {
    const b = toggles[mode]; b.querySelector('em').textContent = text;
    b.classList.remove('on', 'busy', 'error'); if (cls) b.classList.add(cls);
    b.setAttribute('aria-pressed', String(cls === 'on'));
  }
  function section(mode, title) {
    const s = make('div'), h = make('h3'), close = make('button', '✕', 'link'); close.type = 'button';
    close.onclick = () => { panel.hidden = true; openMode = null; };
    h.append(make('span', title), close); s.append(h); sections[mode] = s; return s;
  }
  function button(text, fn, cls) { const b = make('button', text, cls); b.type = 'button'; b.onclick = fn; return b; }
  function openPanel(mode) {
    if (openMode === mode && !panel.hidden) { panel.hidden = true; openMode = null; return; }
    openMode = mode; panel.replaceChildren(sections[mode]); panel.hidden = false;
    const r = toggles[mode].getBoundingClientRect();
    panel.style.top = Math.max(10, Math.min(r.top - 60, innerHeight - panel.offsetHeight - 10)) + 'px'; panel.style.bottom = 'auto';
    J.emit('mode-panel', mode);
  }
  for (const [mode, b] of Object.entries(toggles)) b.onclick = () => openPanel(mode);
  J.on('escape', () => { panel.hidden = true; openMode = null; });

  /* ---------- Shared camera ---------- */
  const cam = { stream: null, users: new Set(), video: make('video') };
  cam.video.muted = true; cam.video.playsInline = true;
  function cameraError(e) {
    return { NotAllowedError: 'Camera permission was denied. Allow it from the camera icon in the address bar.',
      NotFoundError: 'No camera was found.', NotReadableError: 'The camera is in use by another app.',
      OverconstrainedError: 'The camera does not support the requested size.' }[e?.name] || 'Camera unavailable: ' + (e?.message || e);
  }
  async function cameraOn(user) {
    if (!cam.stream) {
      if (!navigator.mediaDevices?.getUserMedia) throw Error('This browser cannot use the camera on this page.');
      try { cam.stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false }); }
      catch (e) { throw Error(cameraError(e)); }
      cam.video.srcObject = cam.stream; await cam.video.play();
    }
    cam.users.add(user); return cam.video;
  }
  function cameraOff(user) {
    cam.users.delete(user);
    if (!cam.users.size && cam.stream) { cam.stream.getTracks().forEach(t => t.stop()); cam.stream = null; cam.video.srcObject = null; }
  }
  // Worker timers keep firing while the Brain tab is in the background (window timers get throttled).
  function ticker(ms, fn) {
    const url = URL.createObjectURL(new Blob([`setInterval(()=>postMessage(0),${ms})`], { type: 'text/javascript' }));
    const worker = new Worker(url); worker.onmessage = fn; URL.revokeObjectURL(url);
    return () => worker.terminate();
  }
  function preview(canvas, overlay) {
    const ctx = canvas.getContext('2d');
    (function paint() {
      if (!canvas.isConnected || panel.hidden) return;
      if (cam.stream && cam.video.videoWidth) {
        canvas.width = 320; canvas.height = Math.round(320 * cam.video.videoHeight / cam.video.videoWidth);
        ctx.drawImage(cam.video, 0, 0, canvas.width, canvas.height); overlay?.(ctx, canvas.width, canvas.height);
      }
      requestAnimationFrame(paint);
    })();
  }

  /* ---------- EYES ---------- */
  const eyes = { on: false, stopTicker: null, stopCoach: null, coach: false, error: '', last: 0 };
  const eyesBox = section('eyes', 'Eyes · camera');
  const eyesStatus = make('div', '', 'status'), eyesCanvas = make('canvas', null, 'cam mirror');
  const eyesBtn = button('Turn on', () => eyes.on ? eyesStop() : eyesStart(), 'primary');
  const coachLabel = make('label', null, 'check'), coach = make('input'); coach.type = 'checkbox';
  coachLabel.append(coach, document.createTextNode('Coach me: every 5 minutes JARVIS glances over and speaks up only about posture, your phone or tiredness.'));
  coach.onchange = () => { eyes.coach = coach.checked; eyes.coach && eyes.on ? startCoach() : stopCoach(); };
  eyesBox.append(make('p', 'Lets JARVIS see you through your webcam. Ask "Jarvis, what do you see?" while this is on. Only the newest frame is kept, in memory on this PC, and it expires 12 seconds after Eyes turn off.'),
    coachLabel, make('div', null, 'actions'), eyesStatus, eyesCanvas);
  eyesBox.querySelector('.actions').append(eyesBtn);
  const grab = make('canvas');
  async function sendFrame() {
    if (!eyes.on || !cam.video.videoWidth) return;
    grab.width = 640; grab.height = Math.round(640 * cam.video.videoHeight / cam.video.videoWidth);
    grab.getContext('2d').drawImage(cam.video, 0, 0, grab.width, grab.height);
    try { await J.api('/eyes', { action: 'frame', jpeg: grab.toDataURL('image/jpeg', .72).split(',')[1] }, { timeout: 5000 }); eyes.last = Date.now(); eyes.error = ''; }
    catch (e) { eyes.error = e.message; }
    updateEyes();
  }
  function startCoach() { stopCoach(); eyes.stopCoach = ticker(300000, () => J.api('/eyes', { action: 'coach' }).catch(() => {})); }
  function stopCoach() { eyes.stopCoach?.(); eyes.stopCoach = null; }
  async function eyesStart() {
    setToggle('eyes', '…', 'busy');
    try { await cameraOn('eyes'); eyes.on = true; eyes.error = ''; await sendFrame(); eyes.stopTicker = ticker(3000, sendFrame); if (eyes.coach) startCoach(); }
    catch (e) { eyes.error = e.message; }
    updateEyes(); if (openMode === 'eyes') preview(eyesCanvas);
  }
  function eyesStop() {
    eyes.on = false; eyes.stopTicker?.(); eyes.stopTicker = null; stopCoach(); cameraOff('eyes');
    J.api('/eyes', { action: 'stop' }).catch(() => {}); updateEyes();
  }
  function updateEyes() {
    eyesBtn.textContent = eyes.on ? 'Turn off' : 'Turn on';
    eyesStatus.textContent = eyes.error || (eyes.on ? `Seeing · last frame ${Math.round((Date.now() - eyes.last) / 1000)}s ago` : 'Off. The camera is not in use.');
    eyesCanvas.hidden = !eyes.on;
    setToggle('eyes', eyes.error && !eyes.on ? 'error' : eyes.on ? 'on' : 'off', eyes.error && !eyes.on ? 'error' : eyes.on ? 'on' : '');
  }
  updateEyes();

  /* ---------- WATCH and FOCUS (shared local visual-mode backend) ---------- */
  let visual = null, visualError = '', polling = false;
  async function vm(payload) { return J.api('/visual-modes', payload, { timeout: 6000 }); }
  async function pollVisual() {
    if (polling) return; polling = true;
    try {
      const active = visual && ['starting', 'running'].includes(visual.state);
      visual = active && visual.needs_heartbeat && visual.session && !document.hidden
        ? await vm({ action: 'heartbeat', session: visual.session }) : await vm();
      visualError = '';
    } catch (e) { visualError = e.message; if (visual) visual = await vm().catch(() => null); }
    finally { polling = false; renderVisual(); }
  }
  async function visualStart(payload) {
    try { visual = await vm({ action: 'start', ...payload }); visualError = ''; } catch (e) { visualError = e.message; }
    renderVisual();
  }
  async function visualStop() { try { visual = await vm({ action: 'stop' }); } catch (e) { visualError = e.message; } renderVisual(); }
  J.on('stop', visualStop);
  document.addEventListener('visibilitychange', () => { if (document.hidden && visual?.mode === 'watch' && ['starting', 'running'].includes(visual.state)) visualStop(); });

  const watchBox = section('watch', 'Watch · screen');
  const watchMinutes = make('input'); watchMinutes.type = 'number'; watchMinutes.min = 1; watchMinutes.max = 30; watchMinutes.value = 15;
  const watchStatus = make('div', '', 'status'), watchImg = make('img'); watchImg.alt = 'Latest masked desktop preview';
  const watchBtn = button('Start', () => active('watch') ? visualStop() : visualStart({ mode: 'watch', minutes: Number(watchMinutes.value) }), 'primary');
  const watchLabel = make('label', 'Minutes (1–30)');
  watchBox.append(make('p', 'Shares a masked desktop preview every 5 seconds, held in memory only. Work apps are blacked out. Keep this page visible; hiding it stops Watch. JARVIS can also look at your screen any time you ask.'),
    watchLabel, watchMinutes, make('div', null, 'actions'), watchStatus, watchImg);
  watchBox.querySelector('.actions').append(watchBtn);

  const focusBox = section('focus', 'Focus lock');
  const focusApp = make('select'), focusOther = make('input'), focusMinutes = make('input');
  focusOther.placeholder = 'or type an app, e.g. Code.exe'; focusOther.maxLength = 84;
  focusMinutes.type = 'number'; focusMinutes.min = 1; focusMinutes.max = 120; focusMinutes.value = 30;
  const callLabel = make('label', null, 'check'), callouts = make('input'); callouts.type = 'checkbox'; callouts.checked = store.get('focusCallouts', true);
  callouts.onchange = () => store.set('focusCallouts', callouts.checked);
  callLabel.append(callouts, document.createTextNode('JARVIS calls me out when I drift'));
  const focusBtn = button('Start focus', () => active('focus') ? visualStop() : visualStart({ mode: 'focus', minutes: Number(focusMinutes.value), target: (focusOther.value.trim() || focusApp.value), callouts: callouts.checked }), 'primary');
  const focusStatus = make('div', '', 'status'), evidence = make('ul');
  focusBox.append(make('p', 'Lock onto one app for a set time. JARVIS watches only which app is in front (no screenshots) and counts a drift when you stay away for 5+ seconds.'),
    make('label', 'App'), focusApp, focusOther, make('label', 'Minutes (1–120)'), focusMinutes, callLabel, make('div', null, 'actions'), focusStatus, evidence);
  focusBox.querySelector('.actions').append(focusBtn);
  J.on('mode-panel', async mode => {
    if (mode === 'eyes' && eyes.on) preview(eyesCanvas);
    if (mode === 'holo') { refreshHoloApp(); if (holo.on) preview(holoCanvas, drawHands); }
    if (mode !== 'focus') return;
    try {
      const { apps } = await J.api('/focus-apps'), previous = focusApp.value || store.get('focusApp', '');
      focusApp.replaceChildren(...apps.map(a => { const o = make('option', a); o.value = a; return o; }));
      if (apps.includes(previous)) focusApp.value = previous;
    } catch (e) { focusStatus.textContent = e.message; }
  });
  focusApp.onchange = () => store.set('focusApp', focusApp.value);

  function active(mode) { return visual?.mode === mode && ['starting', 'running', 'stopping'].includes(visual.state); }
  function renderVisual() {
    const v = visual || {};
    for (const mode of ['watch', 'focus']) {
      if (!active(mode)) { setToggle(mode, v.mode === mode && v.state === 'error' ? 'error' : 'off', v.mode === mode && v.state === 'error' ? 'error' : ''); continue; }
      const label = v.state === 'stopping' ? 'stopping' : fmt(v.remaining_seconds) + (mode === 'focus' ? ' · ' + v.drift_count : '');
      setToggle(mode, label, v.state === 'running' ? 'on' : 'busy');
    }
    const other = mode => visual && active(mode === 'watch' ? 'focus' : 'watch');
    watchBtn.textContent = active('watch') ? 'Stop' : 'Start'; watchBtn.disabled = other('watch');
    focusBtn.textContent = active('focus') ? 'Stop focus' : 'Start focus'; focusBtn.disabled = other('focus');
    const line = mode => !active(mode) ? (visualError || (v.mode === mode ? v.reason + ' ' + (v.error || '') : 'Off.')) :
      `${v.state} · ${fmt(v.remaining_seconds)} left · ${v.observation}` + (mode === 'focus' ? ` · ${v.drift_count} drift${v.drift_count === 1 ? '' : 's'}` : '');
    watchStatus.textContent = line('watch'); focusStatus.textContent = line('focus');
    if (other('watch')) watchStatus.textContent = 'Focus is running; stop it first.';
    if (other('focus')) focusStatus.textContent = 'Watch is running; stop it first.';
    if (active('watch') && v.preview && openMode === 'watch') { watchImg.src = 'data:image/jpeg;base64,' + v.preview; watchImg.hidden = false; }
    else { watchImg.hidden = true; watchImg.removeAttribute('src'); }
    evidence.replaceChildren(...(v.mode === 'focus' ? (v.evidence || []).slice(-6).reverse() : []).map(e => make('li', `${fmt(e.elapsed_seconds)} — switched to ${e.process}`)));
  }
  setInterval(pollVisual, 2000); pollVisual();

  /* ---------- HOLO: hand control for this graph, plus the separate HOLO app ---------- */
  const MP = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1';
  const MODEL = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';
  const holo = { on: false, landmarker: null, error: '', hands: [], last: [] };
  const holoBox = section('holo', 'Holo · hand control');
  const holoStatus = make('div', '', 'status'), holoCanvas = make('canvas', null, 'cam mirror');
  const holoBtn = button('Turn on hand control', () => holo.on ? holoStop() : holoStart(), 'primary');
  const legend = make('ul');
  for (const line of ['Hold pinch, then move — orbit the graph', 'Quick pinch — select; small hand tremors are ignored', 'Two-hand pinch — zoom (spread) and twist (rotate)',
    'Open palm, hold 1 s — fit everything', 'Peace sign, hold — clear selection']) legend.append(make('li', line));
  const appTitle = make('h3', 'HOLO app'), appStatus = make('p', 'Checking…'), appBtn = button('Open HOLO', () => J.send('Open HOLO'));
  holoBox.append(make('p', 'Control this second brain with your hands through the webcam. Tracking runs in this page with Google MediaPipe; the first start downloads the model (about 8 MB).'),
    make('div', null, 'actions'), holoStatus, legend, holoCanvas, appTitle, appStatus, appBtn);
  holoBox.querySelector('.actions').append(holoBtn);
  async function refreshHoloApp() {
    try {
      const s = await J.api('/holo');
      appStatus.textContent = !s.installed ? 'Not installed yet. Run scripts\\setup_holo.ps1 once (it downloads the free MIT-licensed HOLO app), then click Open HOLO or say "Jarvis, open HOLO".'
        : `Installed at ${s.path} · ${s.running ? 'running on port ' + s.port : 'not running'}. Cards you grab in HOLO light up here; squeeze one and JARVIS summarizes it.`;
      appBtn.disabled = !s.installed;
    } catch (e) { appStatus.textContent = e.message; }
  }
  class OneEuro {  // jitter filter for landmarks (minCutoff 1, beta 1 as tuned for hand tracking)
    constructor(minCutoff = 1, beta = 1) { this.minCutoff = minCutoff; this.beta = beta; this.x = null; }
    alpha(cutoff, dt) { const tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); }
    filter(x, t) {
      if (this.x == null) { this.x = x; this.dx = 0; this.t = t; return x; }
      const dt = Math.max(1e-3, (t - this.t) / 1000); this.t = t;
      this.dx += this.alpha(1, dt) * ((x - this.x) / dt - this.dx);
      this.x += this.alpha(this.minCutoff + this.beta * Math.abs(this.dx), dt) * (x - this.x);
      return this.x;
    }
  }
  const tracks = [0, 1].map(() => ({ fx: new OneEuro(), fy: new OneEuro(),
    mx: new OneEuro(1, .35), my: new OneEuro(1, .35),
    pinched: false, dragging: false, blocked: false, since: 0, moved: 0, x: 0, y: 0, palmSince: 0, peaceSince: 0 }));
  let two = null;
  const cursor = el('handCursor');
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const extended = (lm, tip, pip) => dist(lm[tip], lm[0]) > dist(lm[pip], lm[0]) * 1.08;
  function interpret(hands, now) {
    const points = [];
    // Missing tracking is cancellation, not a deliberate throw. Two-hand
    // zoom/twist also takes over immediately from a single-hand coast.
    if (hands.length !== 1) {
      J.camera.hand.cancel();
      for (const t of tracks) if (t.pinched) { t.blocked = true; t.dragging = false; }
    }
    hands.slice(0, 2).forEach((lm, i) => {
      const t = tracks[i], size = dist(lm[0], lm[9]) || .1, pinch = dist(lm[4], lm[8]) / size;
      const x = t.fx.filter(1 - (lm[4].x + lm[8].x) / 2, now) * innerWidth, y = t.fy.filter((lm[4].y + lm[8].y) / 2, now) * innerHeight;
      // Palm movement is stable when the thumb closes: finger motion must not rotate the graph.
      const px = t.mx.filter(1 - (lm[0].x + lm[9].x) / 2, now) * innerWidth;
      const py = t.my.filter((lm[0].y + lm[9].y) / 2, now) * innerHeight;
      const threshold = Math.max(20, Math.min(44, Math.min(innerWidth, innerHeight) * .03));
      const wasPinched = t.pinched;
      t.pinched = wasPinched ? pinch < .5 : pinch < .32;
      if (t.pinched && !wasPinched) {
        t.since = now; t.moved = 0; t.dragging = false; t.blocked = hands.length !== 1;
        t.startX = px; t.startY = py; t.target = J.hit(x, y);
        if (hands.length === 1) J.camera.hand.cancel();
      }
      if (t.pinched && wasPinched && hands.length === 1 && !t.blocked) {
        t.moved = Math.max(t.moved, Math.hypot(px - t.startX, py - t.startY));
        if (!t.dragging && now - t.since >= 180 && t.moved >= threshold) {
          t.dragging = true; J.camera.hand.begin(now); // No catch-up jump from the selection grace period.
        } else if (t.dragging) {
          const dx = Math.max(-35, Math.min(35, (px - t.px) * 1000 / innerWidth));
          const dy = Math.max(-35, Math.min(35, (py - t.py) * 800 / innerHeight));
          J.camera.hand.move(dx * .85, dy * .85, now);
        }
      }
      if (!t.pinched && wasPinched) {
        const tap = !t.dragging && !t.blocked && hands.length === 1 && now - t.since < 450 && t.moved < threshold * 2;
        if (t.dragging && hands.length === 1) J.camera.hand.end(now, false);
        // Select where the pinch began, not where opening the fingers pushes the cursor.
        if (tap) { t.target ? J.select(t.target) : J.clearSelection(); }
        t.dragging = false; t.target = null;
      }
      const fingers = [[8, 6], [12, 10], [16, 14], [20, 18]].map(([a, b]) => extended(lm, a, b));
      const palm = fingers.every(Boolean) && pinch > .6, peace = fingers[0] && fingers[1] && !fingers[2] && !fingers[3];
      t.palmSince = palm ? (t.palmSince || now) : 0; t.peaceSince = peace ? (t.peaceSince || now) : 0;
      if (t.palmSince && now - t.palmSince > 1000) { J.camera.fit(); t.palmSince = now + 2000; }
      if (t.peaceSince && now - t.peaceSince > 700) { J.clearSelection(); t.peaceSince = now + 2000; }
      t.x = x; t.y = y; t.px = px; t.py = py; points.push(t);
    });
    for (let i = hands.length; i < 2; i++) {
      const t = tracks[i]; t.pinched = t.dragging = false; t.target = null;
      t.fx.x = t.fy.x = t.mx.x = t.my.x = null;
    }
    if (points.length === 2 && points[0].pinched && points[1].pinched) {
      const d = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y), a = Math.atan2(points[1].y - points[0].y, points[1].x - points[0].x);
      if (two) { J.camera.zoomBy(d / two.d); J.camera.rotate((a - two.a) * .8, 0); }
      two = { d: Math.max(20, d), a };
    } else two = null;
    const lead = points[0];
    cursor.hidden = !lead;
    if (lead) { cursor.style.left = lead.x + 'px'; cursor.style.top = lead.y + 'px'; cursor.classList.toggle('pinch', lead.pinched); }
  }
  function drawHands(ctx, w, h) {
    ctx.fillStyle = '#5eead4';
    for (const lm of holo.last) for (const p of lm) { ctx.beginPath(); ctx.arc(p.x * w, p.y * h, 2.2, 0, 6.283); ctx.fill(); }
  }
  let lastTime = -1;
  function track() {
    if (!holo.on) return;
    const v = cam.video;
    if (v.readyState >= 2 && v.currentTime !== lastTime) {
      lastTime = v.currentTime;
      try { const now = performance.now(), result = holo.landmarker.detectForVideo(v, now); holo.last = result.landmarks || []; interpret(holo.last, now); }
      catch (e) { holo.error = 'Hand tracking stopped: ' + e.message; holoStop(); return; }
    }
    requestAnimationFrame(track);
  }
  async function holoStart() {
    setToggle('holo', 'loading', 'busy'); holoStatus.textContent = 'Starting camera and loading the hand model…';
    try {
      await cameraOn('holo');
      if (!holo.landmarker) {
        const vision = await import(MP + '/vision_bundle.mjs');
        const files = await vision.FilesetResolver.forVisionTasks(MP + '/wasm');
        const options = delegate => ({ baseOptions: { modelAssetPath: MODEL, delegate }, runningMode: 'VIDEO', numHands: 2 });
        try { holo.landmarker = await vision.HandLandmarker.createFromOptions(files, options('GPU')); }
        catch { holo.landmarker = await vision.HandLandmarker.createFromOptions(files, options('CPU')); }
      }
      holo.on = true; holo.error = ''; track();
      if (openMode === 'holo') preview(holoCanvas, drawHands);
    } catch (e) {
      holo.error = /fetch|import|network/i.test(String(e?.message)) ? 'Could not download MediaPipe. Hand control needs internet the first time.' : (e.message || String(e));
      cameraOff('holo');
    }
    updateHolo();
  }
  function holoStop() {
    J.camera.hand.cancel(); two = null;
    for (const t of tracks) { t.pinched = t.dragging = false; t.target = null; t.fx.x = t.fy.x = t.mx.x = t.my.x = null; }
    holo.on = false; holo.last = []; cursor.hidden = true; cameraOff('holo'); updateHolo();
  }
  function updateHolo() {
    holoBtn.textContent = holo.on ? 'Turn off hand control' : 'Turn on hand control';
    holoStatus.textContent = holo.error || (holo.on ? 'Tracking. Raise a hand in front of the camera.' : 'Off. The camera is not in use.');
    holoCanvas.hidden = !holo.on;
    setToggle('holo', holo.error && !holo.on ? 'error' : holo.on ? 'on' : 'off', holo.error && !holo.on ? 'error' : holo.on ? 'on' : '');
  }
  updateHolo();
  document.addEventListener('visibilitychange', () => { if (document.hidden && holo.on) holoStop(); });

  /* ---------- Spoken control: JARVIS forwards "turn on your eyes" etc. as a ui event ---------- */
  J.on('ui', ev => {
    if (ev.replay || ev.action !== 'mode') return;
    const on = ev.on === true;
    if (ev.mode === 'eyes') on ? (eyes.on || eyesStart()) : (eyes.on && eyesStop());
    else if (ev.mode === 'holo') on ? (holo.on || holoStart()) : (holo.on && holoStop());
    else if (ev.mode === 'watch') on ? (active('watch') || visualStart({ mode: 'watch', minutes: 15 })) : (active('watch') && visualStop());
  });
  addEventListener('pagehide', () => { if (eyes.on) eyesStop(); if (active('watch')) visualStop(); });
})();
