/* The workshop: a third main view where JARVIS builds things in 3D and changes them by voice (workshop.py).
   This file draws the bench around the 3D stage: the title, the build list, the picture, the buttons. The stage
   itself is workshop-frame.html in a sandboxed frame, because it runs scene code a model wrote; the two talk
   only through messages. Everything here is drawn with textContent. */
'use strict';
(() => {
  const el = id => document.getElementById(id);
  const box = el('workshop'), frame = el('workshopFrame'), stage = frame.contentWindow;
  const MODELS = { fable: 'Claude Fable 5.2', opus: 'Claude Opus 5.5', sonnet: 'Claude Sonnet 5.5', haiku: 'Claude Haiku 5.5' };
  const visible = () => document.body.classList.contains('view-workshop');
  let ready = false, queue = [], scene = null, setup = '', busy = '', startedAt = 0, clock = 0, tokens = 0, exploded = false;
  let errors = 0, renderUrl = '', view = 'model', before = 'model', benchStamp = 0;

  const send = message => { if (ready) stage.postMessage(message, '*'); else queue.push(message); };
  const report = payload => J.api('/workshop', payload).catch(e => J.notice(e.message));

  /* ---------- Parts of the bench ---------- */
  function button(label, title, action, cls) { const b = make('button', label, cls); b.type = 'button'; if (title) b.title = title; b.onclick = action; return b; }
  const title = make('h2', 'The workshop'), meta = make('small', '', 'ws-meta');
  const head = make('header', null, 'ws-head'); head.append(title, meta);
  const hint = make('div', '', 'ws-hint');
  const tabs = make('div', null, 'ws-tabs'); tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', 'What to show');
  const tabModel = button('3D model', null, () => show('model', true)), tabRender = button('Render', null, () => show('render', true));
  const save = make('a', 'Save picture', 'ws-save'); save.setAttribute('role', 'button');
  tabs.append(tabModel, tabRender, save);
  const apart = button('Pull apart', 'Show every part, labelled', () => { setExploded(!exploded); report({ action: 'explode', on: exploded }); });
  const renderBtn = button('Render', 'A realistic picture of this view, in about a minute', () => report({ action: 'render' }));
  const undoBtn = button('Undo', 'Take back the last change', () => report({ action: 'undo' }));
  const fresh = button('New', 'Clear the bench', () => report({ action: 'clear' }));
  const close = button('Close', 'Back to the last view', () => { report({ action: 'close' }); leave(); }, 'ws-close');
  const actions = make('div', null, 'ws-actions'); actions.append(apart, renderBtn, undoBtn, fresh, close);
  const picture = make('figure', null, 'ws-picture'), pictureImg = make('img'); pictureImg.alt = 'The picture this was built from';
  picture.append(make('figcaption', 'YOUR PICTURE'), pictureImg); picture.hidden = true;
  const rendered = make('img', null, 'ws-render'); rendered.alt = 'Realistic render of the model'; rendered.hidden = true;

  const panel = make('section', null, 'ws-panel card'), panelHead = make('div', null, 'ws-panel-head'), panelTitle = make('b', 'BUILT');
  const panelBody = make('div', null, 'ws-panel-body'), thought = make('div', null, 'ws-thought'), thoughtHead = make('small', ''), thoughtText = make('p', '');
  const steps = make('ol', null, 'ws-steps');
  const hide = button('Hide', null, () => { const off = !panelBody.hidden; panelBody.hidden = off; hide.textContent = off ? 'Show' : 'Hide'; }, 'link');
  panelHead.append(panelTitle, hide); thought.append(thoughtHead, thoughtText); panelBody.append(thought, steps); panel.append(panelHead, panelBody); panel.hidden = true;

  const bench = make('section', null, 'ws-bench card');
  const pick = make('input'); pick.type = 'file'; pick.accept = 'image/*'; pick.hidden = true;
  const choose = button('Choose a picture', null, () => pick.click(), 'primary');
  const benchRow = make('div', null, 'ws-bench-row'); benchRow.append(choose, make('span', 'or drop one here, paste it, or say "Jarvis, build what\'s on my screen"'));
  const saved = make('div', null, 'ws-saved');
  bench.append(make('h3', 'The workshop'), make('p', 'Put a picture on the bench and I will build it in 3D, ready to pull apart: a floor plan, a product, a sketch, a logo. Or just tell me what to build.'), benchRow, saved, pick);
  const status = make('div', '', 'ws-status'); status.setAttribute('role', 'status');
  box.append(rendered, head, hint, tabs, actions, picture, panel, bench, status);

  /* ---------- Drawing ---------- */
  const clockText = s => Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');
  const tokenText = n => n >= 1000 ? (n / 1000).toFixed(1) + 'K tokens' : n + ' tokens';
  let modelName = 'fable';
  function drawMeta() {
    const seconds = busy && busy !== 'render' ? (Date.now() / 1000 - startedAt) : clock;
    meta.textContent = scene || busy ? `${MODELS[modelName] || modelName} · ${clockText(Math.max(0, seconds))} · ${tokenText(tokens)}` : '';
  }
  setInterval(() => { if (busy && visible()) drawMeta(); }, 500);
  function addStep(name, state = 'ok') {
    const row = make('li', name, state); row.dataset.name = name; steps.append(row);
    panelBody.scrollTop = panelBody.scrollHeight; return row;
  }
  function draw() {
    const has = !!(scene && scene.steps.length);
    title.textContent = scene?.title || (busy === 'build' ? 'Designing…' : 'The workshop');
    bench.hidden = has || !!busy;
    panel.hidden = !(has || busy) || view === 'render';
    panelTitle.textContent = busy === 'build' ? 'BUILDING' : busy === 'change' ? 'CHANGING' : 'BUILT';
    hint.textContent = view === 'render' || !has || busy ? '' : exploded ? 'Every part, labelled. Say "Jarvis, put it back together."' : 'Drag to turn it. Say "Jarvis, pull it apart."';
    apart.textContent = exploded ? 'Put together' : 'Pull apart';
    for (const b of [apart, renderBtn]) b.hidden = !has || view === 'render';
    apart.disabled = renderBtn.disabled = !!busy;
    undoBtn.hidden = !has || !scene.versions || !!busy || view === 'render';
    fresh.hidden = !has || !!busy;
    tabs.hidden = !renderUrl;
    tabModel.classList.toggle('on', view === 'model'); tabRender.classList.toggle('on', view === 'render');
    rendered.hidden = view !== 'render' || !renderUrl; frame.style.visibility = view === 'render' && renderUrl ? 'hidden' : 'visible';
    picture.hidden = !(scene?.picture) || view === 'render';
    status.textContent = busy === 'render' ? 'Rendering a realistic picture… about a minute' : status.dataset.keep || '';
    drawMeta();
  }
  function note(text) { status.dataset.keep = text || ''; draw(); if (text) setTimeout(() => { if (status.dataset.keep === text) { status.dataset.keep = ''; draw(); } }, 9000); }
  function setExploded(on) { exploded = !!on; send({ t: 'explode', on: exploded }); draw(); }
  function show(which, tell) {
    view = which === 'render' && renderUrl ? 'render' : 'model';
    if (tell) report({ action: 'view', view });
    draw();
  }
  function setRender(url) {
    renderUrl = url || '';
    if (renderUrl) { rendered.src = renderUrl; save.href = renderUrl; save.download = (scene?.title || 'workshop').replace(/[^\w -]+/g, '') + '.png'; }
  }
  function replay() {
    send({ t: 'reset' });
    for (const step of scene?.steps || []) send({ t: 'run', name: step.name, code: step.code, setup, quiet: true });
    if (exploded) send({ t: 'explode', on: true });
  }
  function drawSaved(list) {
    saved.replaceChildren();
    if (!list?.length) return;
    saved.append(make('small', 'Saved:'));
    for (const item of list.slice(0, 6)) saved.append(button(String(item.title).slice(0, 40), 'Open this model', () => report({ action: 'open', scene: item.id }), 'chip'));
  }

  /* ---------- Matching what Jarvis has (GET /workshop) ---------- */
  async function sync(open) {
    let data;
    try { data = await J.api('/workshop'); } catch { return; }
    const same = scene && data.scene && JSON.stringify(scene.steps) === JSON.stringify(data.scene.steps) && setup === data.scene.setup;
    scene = data.scene; setup = data.scene?.setup || ''; busy = data.busy || ''; modelName = data.model || 'fable';
    tokens = data.tokens || 0; exploded = !!data.exploded; errors = 0;
    startedAt = Date.now() / 1000 - Math.max(0, (data.now || 0) - (data.started || 0)); clock = data.seconds || 0;
    steps.replaceChildren(); for (const name of (data.notes?.length ? data.notes : (scene?.steps || []).map(s => s.name))) addStep(name);
    thoughtText.textContent = data.thinking ? data.thinking.slice(-320) : '';
    if (busy && busy !== 'render') thoughtHead.textContent = modelName.toUpperCase() + ' IS THINKING'; else if (!thoughtHead.textContent.startsWith('THOUGHT')) thoughtHead.textContent = '';
    thought.hidden = !thoughtText.textContent;
    if (scene?.picture) pictureImg.src = `/workshop/file?scene=${encodeURIComponent(scene.id)}&name=picture.jpg`;
    setRender(data.render); view = data.view === 'render' && data.render ? 'render' : 'model';
    drawSaved(data.recent);
    if (!same) replay(); else send({ t: 'explode', on: exploded });
    if (data.error) note(data.error);
    draw();
    if ((open === null ? data.open && data.busy : open) && !visible()) enter();
  }
  let enteredAt = 0;
  function enter() { if (!visible()) { before = document.body.classList.contains('view-console') ? 'console' : 'model'; enteredAt = Date.now(); J.setView('workshop'); } }
  function leave() { if (visible()) J.setView(before); }

  /* ---------- What Jarvis sends while he works ---------- */
  J.on('workshop', ev => {
    const p = ev.phase;
    if (p === 'open') sync(true);
    else if (p === 'close') leave();
    else if (p === 'start') {
      busy = ev.mode; startedAt = Date.now() / 1000; tokens = 0; errors = 0; modelName = ev.model || modelName; view = 'model';
      thoughtText.textContent = ''; thoughtHead.textContent = modelName.toUpperCase() + ' IS THINKING'; thought.hidden = false; steps.replaceChildren();
      status.dataset.keep = '';
      if (ev.mode === 'build') {
        scene = { id: '', title: '', steps: [], picture: !!ev.picture, versions: 0 }; setup = ''; exploded = false; setRender('');
        send({ t: 'reset' });
        if (ev.picture) pictureImg.src = '/workshop/file?scene=bench&name=bench.jpg&at=' + Date.now();
      }
      draw(); enter();
    } else if (p === 'thinking') {
      tokens = ev.tokens || tokens;
      if (ev.text) { thoughtText.textContent = (thoughtText.textContent + ev.text).slice(-320); thought.hidden = false; }
      if (ev.thought) thoughtHead.textContent = `THOUGHT IT THROUGH IN ${ev.thought} S`;
      drawMeta();
    } else if (p === 'title' && scene) { scene.title = ev.value; draw(); }
    else if (p === 'setup') setup = ev.value || '';
    else if (p === 'step' && scene) {
      scene.steps.push(ev.value); addStep(ev.value.name);
      send({ t: 'run', name: ev.value.name, code: ev.value.code, setup }); draw();
    } else if (p === 'note') addStep(ev.value);
    else if (p === 'done') { clock = ev.seconds || 0; tokens = ev.tokens || tokens; busy = ''; sync(); setTimeout(repairIfBroken, 900); }
    else if (p === 'patch') { clock = ev.seconds || 0; tokens = ev.tokens || tokens; busy = ''; sync().then(() => setTimeout(repairIfBroken, 900)); }
    else if (p === 'error') { busy = ''; note(ev.message ? 'It didn\'t finish: ' + ev.message : ''); sync(); }
    else if (p === 'explode') { setExploded(ev.on); view = 'model'; draw(); enter(); }
    else if (p === 'snapshot') {   // if the workshop only just came on screen, give the stage a moment to size itself
      pendingSnapshot = ev.nonce; enter();
      setTimeout(() => send({ t: 'snapshot', nonce: ev.nonce }), Math.max(0, 1600 - (Date.now() - enteredAt)));
    }
    else if (p === 'rendering') { busy = 'render'; draw(); enter(); }
    else if (p === 'render') { busy = ''; setRender(ev.url + '&at=' + Date.now()); view = 'render'; draw(); enter(); }
    else if (p === 'render-error') { busy = ''; note('The render didn\'t come out: ' + (ev.message || 'unknown')); }
    else if (p === 'view') { show(ev.view); enter(); }
  });
  function repairIfBroken() { if (errors && !busy) { errors = 0; report({ action: 'repair' }); } }

  /* ---------- What the stage sends back ---------- */
  let pendingSnapshot = '';
  addEventListener('message', event => {
    if (event.source !== stage || !event.data || typeof event.data !== 'object') return;
    const m = event.data;
    if (m.t === 'ready' && !ready) { ready = true; for (const item of queue.splice(0)) stage.postMessage(item, '*'); insets(); }
    else if (m.t === 'error') {
      errors++;
      const row = [...steps.children].find(r => r.dataset.name === m.step); if (row) { row.className = 'bad'; row.title = String(m.message); }
      report({ action: 'error', step: String(m.step || ''), message: String(m.message || '') });
    } else if (m.t === 'snapshot' && m.nonce === pendingSnapshot && typeof m.data === 'string' && m.data.startsWith('data:image/jpeg;base64,')) {
      pendingSnapshot = '';
      J.api('/workshop/snapshot', { nonce: m.nonce, data: m.data.slice(23) }, { timeout: 20000 }).catch(e => note(e.message));
    }
  });
  // The stage fills the window; tell it what floats on top so it frames the model in the clear part.
  function insets() {
    const side = document.querySelector('.right')?.getBoundingClientRect(), dock = el('dock').getBoundingClientRect();
    send({ t: 'insets', right: side ? Math.max(0, innerWidth - side.left + 8) : 0, bottom: Math.max(0, innerHeight - dock.top + 8), top: 96 });
  }
  addEventListener('resize', insets);
  let insetTimer = 0;
  new ResizeObserver(() => { clearTimeout(insetTimer); insetTimer = setTimeout(insets, 250); }).observe(el('dock'));   // the reply box grows
  J.on('view', name => { if (name === 'workshop') setTimeout(insets, 60); });
  J.on('level', v => { if (visible() && v > .02) send({ t: 'level', v: Math.min(1, v * 3) }); });

  /* ---------- A picture on the bench: choose, drop or paste ---------- */
  async function putOnBench(file) {
    if (!file || !file.type.startsWith('image/')) return note('That isn\'t a picture.');
    if (busy) return note('I\'m still on the last job.');
    try {
      const bitmap = await createImageBitmap(file), scale = Math.min(1, 1800 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas'); canvas.width = Math.round(bitmap.width * scale); canvas.height = Math.round(bitmap.height * scale);
      const g = canvas.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, canvas.width, canvas.height); g.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const data = canvas.toDataURL('image/jpeg', .9).slice(23);
      await J.api('/workshop/picture', { data }, { timeout: 20000 });
      benchStamp = Date.now(); pictureImg.src = '/workshop/file?scene=bench&name=bench.jpg&at=' + benchStamp; picture.hidden = false;
      note('Picture on the bench.');
      J.send('I just put a picture on the workshop bench. Build it in 3D.');
    } catch (e) { note('Couldn\'t use that picture: ' + e.message); }
  }
  pick.onchange = () => { putOnBench(pick.files[0]); pick.value = ''; };
  box.addEventListener('dragover', e => { e.preventDefault(); box.classList.add('dropping'); });
  box.addEventListener('dragleave', () => box.classList.remove('dropping'));
  box.addEventListener('drop', e => { e.preventDefault(); box.classList.remove('dropping'); putOnBench([...e.dataTransfer.files].find(f => f.type.startsWith('image/'))); });
  addEventListener('paste', e => {
    if (!visible()) return;
    const file = [...(e.clipboardData?.files || [])].find(f => f.type.startsWith('image/'));
    if (file) { e.preventDefault(); putOnBench(file); }
  });
  // A drag over the frame never reaches this page, so the frame stops taking the mouse while something is dragged in.
  addEventListener('dragenter', () => { if (visible()) frame.style.pointerEvents = 'none'; });
  for (const type of ['drop', 'dragend', 'mouseup']) addEventListener(type, () => { frame.style.pointerEvents = ''; }, true);
  addEventListener('dragleave', e => { if (!e.relatedTarget) frame.style.pointerEvents = ''; });

  el('viewWorkshop').onclick = () => { enteredAt = Date.now(); J.setView('workshop'); };
  J.on('view', name => { if (name === 'workshop') sync(false); });
  J.menuItem('view', 'Workshop (build in 3D)', () => { enter(); sync(false); });
  // Jarvis only says the workshop is on screen when a page tells him so (workshop.py, on_screen).
  const seen = () => J.api('/workshop', { action: 'seen', visible: visible() && !document.hidden }).catch(() => {});
  setInterval(seen, 6000); J.on('view', seen); document.addEventListener('visibilitychange', seen); seen();
  J.workshop = { sync, enter, leave };
  // The frame may have said it's ready before this script was listening; asking makes it say so again.
  stage.postMessage({ t: 'hello' }, '*'); frame.addEventListener('load', () => stage.postMessage({ t: 'hello' }, '*'));
  // If the stage never answers (its 3D library didn't load, say while Jarvis was restarting), load it again.
  let reloads = 0;
  setInterval(() => { if (!ready && visible() && reloads < 6) { reloads++; frame.src = '/workshop-frame.html?try=' + reloads; } }, 5000);
  sync(new URLSearchParams(location.search).has('workshop') ? true : null);   // opened by Jarvis to show the workshop
})();
