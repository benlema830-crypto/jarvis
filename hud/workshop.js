/* The workshop: a third main view where JARVIS builds things in 3D and changes them by voice (workshop.py).
   This file draws the bench around the 3D stage: the title, the build list, the picture, the buttons. The stage
   itself is workshop-frame.html in a sandboxed frame, because it runs scene code a model wrote; the two talk
   only through messages. Everything here is drawn with textContent. */
'use strict';
(() => {
  const el = id => document.getElementById(id);
  const box = el('workshop'), frame = el('workshopFrame'), stage = frame.contentWindow;
  const MODELS = { fable: 'Claude Fable 5.2', qwen: 'Qwen3.5 (local)' };
  const visible = () => document.body.classList.contains('view-workshop');
  let ready = false, queue = [], scene = null, setup = '', busy = '', startedAt = 0, clock = 0, tokens = 0, exploded = false;
  let errors = 0, renderUrl = '', view = 'model', before = 'model', benchStamp = 0;
  let partList = [], selected = [], isolate = false;
  let motionList = [], moving = [], measuring = false, cutNow = null, variantList = [], refs = [], photoKey = '', photoData = [];

  const send = message => { if (ready) stage.postMessage(message, '*'); else queue.push(message); };
  const report = payload => J.api('/workshop', payload).catch(e => J.notice(e.message));

  /* ---------- Parts of the bench ---------- */
  function button(label, title, action, cls) { const b = make('button', label, cls); b.type = 'button'; if (title) b.title = title; b.onclick = action; return b; }
  const title = make('h2', 'The workshop'), meta = make('small', '', 'ws-meta');
  const head = make('header', null, 'ws-head'); head.append(title, meta);
  const modelPick = make('select'); modelPick.setAttribute('aria-label', 'Workshop model');
  for (const [value, label] of Object.entries(MODELS)) {
    const option = make('option', label); option.value = value; modelPick.append(option);
  }
  modelPick.onchange = async () => {
    modelPick.disabled = true;
    try { await J.api('/workshop', { action: 'model', model: modelPick.value }); }
    catch (e) { J.notice(e.message); }
    finally { await sync(false); }
  };
  head.append(modelPick);
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
  /* More tools: a second row. Each also has a spoken form; the buttons tell Jarvis what was done so he keeps up. */
  const detailBtn = button('More detail', 'Compare it with the real thing and add detail (a minute or two)', () => report({ action: 'detail', request: '' }));
  const measureBtn = button('Measure', 'Show its real size; click two points to measure between them', () => setMeasuring(!measuring, true));
  const cutBtn = button('Cut open', 'Slice it open to see inside', () => setCut(cutNow ? null : { axis: 'x', at: .5 }, true));
  const fileBtn = button('Save file', 'STL for 3D printing or Fusion (Shift-click for a coloured GLB)', e => { note('Saving the file…'); report({ action: 'export', request: e.shiftKey ? 'glb' : 'stl' }); });
  const clipBtn = button('Clip', 'Record it turning once (saved in Documents, Jarvis Workshop)', () => report({ action: 'video', request: '' }));
  const tools = make('div', null, 'ws-tools'); tools.append(detailBtn, measureBtn, cutBtn, fileBtn, clipBtn);
  const cutBar = make('div', null, 'ws-cutbar'), cutSlide = make('input'); cutSlide.type = 'range'; cutSlide.min = 2; cutSlide.max = 98; cutSlide.value = 50;
  cutSlide.setAttribute('aria-label', 'Where the cut is');
  cutSlide.oninput = () => { if (cutNow) setCut({ axis: cutNow.axis, at: cutSlide.value / 100 }, false); };
  cutSlide.onchange = () => { if (cutNow) report({ action: 'cut', on: true, axis: cutNow.axis, at: cutNow.at }); };
  const axisButtons = [['x', 'Side'], ['y', 'Top'], ['z', 'Front']].map(([axis, label]) => button(label, 'Cut from the ' + label.toLowerCase(), () => setCut({ axis, at: cutNow ? cutNow.at : .5 }, true)));
  cutBar.append(make('small', 'CUT'), ...axisButtons, cutSlide); cutBar.hidden = true;
  const photos = make('figure', null, 'ws-picture ws-photos'), photoRow = make('div', null, 'ws-photo-row');
  photos.append(make('figcaption', 'THE REAL THING'), photoRow); photos.hidden = true;
  const moves = make('div', null, 'ws-moves');
  function setMeasuring(on, tell) {
    measuring = !!on; send({ t: 'measure', on: measuring, scale: 'auto' });
    if (tell) report({ action: 'measure', on: measuring });
    draw();
  }
  function setCut(value, tell) {
    cutNow = value && { axis: value.axis, at: Math.max(.02, Math.min(.98, +value.at || .5)) };
    send({ t: 'cut', on: !!cutNow, axis: cutNow?.axis, at: cutNow?.at });
    if (cutNow) cutSlide.value = Math.round(cutNow.at * 100);
    if (tell) report({ action: 'cut', on: !!cutNow, axis: cutNow?.axis, at: cutNow?.at });
    draw();
  }
  function setMotion(name, on, tell) {
    moving = on ? [...new Set([...moving, name])] : moving.filter(n => n !== name);
    send({ t: 'motion', name, on: !!on });
    if (tell) report({ action: 'motion', name, on: !!on });
    drawMoves();
  }
  function drawMoves() {
    moves.replaceChildren();
    if (!motionList.length) return;
    moves.append(make('small', 'MOVES'));
    for (const name of motionList) moves.append(button(name, 'Play or reset this motion', () => setMotion(name, !moving.includes(name), true), 'chip' + (moving.includes(name) ? ' on' : '')));
  }
  /* Photographs of the real thing: shown, and handed to the stage so the model can wear them (api.photo). */
  async function loadPhotos() {
    const key = scene?.id && refs.length ? scene.id + ':' + refs.map(r => r.name).join(',') : '';
    if (key !== photoKey) {
      photoKey = key; photoData = []; photoRow.replaceChildren();
      for (const ref of refs.slice(0, 4)) {
        const url = `/workshop/file?scene=${encodeURIComponent(scene.id)}&name=${encodeURIComponent(ref.name)}`;
        try {
          const blob = await (await fetch(url, { cache: 'no-store' })).blob();
          photoData.push(await new Promise((done, fail) => { const reader = new FileReader(); reader.onload = () => done(reader.result); reader.onerror = fail; reader.readAsDataURL(blob); }));
        } catch { photoData.push(''); }
        const thumb = make('img'); thumb.src = url; thumb.alt = thumb.title = String(ref.about || 'A photograph of the real thing'); thumb.draggable = false; photoRow.append(thumb);
      }
    }
    send({ t: 'photos', list: photoData });
  }
  const picture = make('figure', null, 'ws-picture'), pictureImg = make('img'); pictureImg.alt = 'The picture this was built from';
  picture.append(make('figcaption', 'YOUR PICTURE'), pictureImg); picture.hidden = true;
  const rendered = make('img', null, 'ws-render'); rendered.alt = 'Realistic render of the model'; rendered.hidden = true;

  const panel = make('section', null, 'ws-panel card'), panelHead = make('div', null, 'ws-panel-head'), panelTitle = make('b', 'BUILT');
  const panelBody = make('div', null, 'ws-panel-body'), thought = make('div', null, 'ws-thought'), thoughtHead = make('small', ''), thoughtText = make('p', '');
  const steps = make('ol', null, 'ws-steps');
  let panelAuto = true, leftNow = 0;   // the build list folds away by itself once a job is done, unless the owner set it
  const hide = button('Hide', null, () => { panelAuto = false; const off = !panelBody.hidden; panelBody.hidden = off; hide.textContent = off ? 'Show' : 'Hide'; draw(); }, 'link');
  panelHead.append(panelTitle, hide); thought.append(thoughtHead, thoughtText); panelBody.append(thought, steps); panel.append(panelHead, panelBody); panel.hidden = true;

  /* Parts: click one in the list or on the model to look at it alone; Ctrl-click adds another. */
  const partsPanel = make('section', null, 'ws-parts card'), partsHead = make('div', null, 'ws-panel-head');
  const showAll = button('Show all', 'Back to the whole model', () => pickParts([], false), 'link');
  const partsBody = make('div', null, 'ws-parts-list'), partAbout = make('div', null, 'ws-part-about');
  const only = button('Only this', 'Hide everything else', () => pickParts(selected, !isolate), 'link');
  partsHead.append(make('b', 'PARTS'), showAll); partsPanel.append(partsHead, partsBody, partAbout, moves); partsPanel.hidden = true;
  function drawParts() {
    partsBody.replaceChildren();
    for (const part of partList) {
      const row = button(part.name, part.description, e => pickParts(e.ctrlKey || e.shiftKey ? toggle(part.name) : (selected.length === 1 && selected[0] === part.name ? [] : [part.name]), isolate), selected.includes(part.name) ? 'on' : '');
      partsBody.append(row);
    }
    showAll.hidden = !selected.length;
    partAbout.replaceChildren();
    const chosen = partList.filter(p => selected.includes(p.name));
    if (chosen.length === 1) partAbout.append(make('p', chosen[0].description || 'No description.'));
    else if (chosen.length > 1) partAbout.append(make('p', chosen.length + ' parts selected.'));
    if (chosen.length) { only.textContent = isolate ? 'Show the rest faintly' : 'Only ' + (chosen.length === 1 ? 'this' : 'these'); partAbout.append(only, make('small', 'Say "make it red", "remove it" or ask about it.')); }
  }
  const toggle = name => selected.includes(name) ? selected.filter(n => n !== name) : [...selected, name];
  function applySelection(names, alone) {
    const known = new Set(partList.map(p => p.name));
    selected = (names || []).filter(n => known.has(n)); isolate = !!alone && selected.length > 0;
    send({ t: 'select', names: selected, isolate });
    drawParts(); draw();
  }
  function pickParts(names, alone) {   // the owner chose on the page: show it, and let Jarvis know what "this" is
    applySelection(names, alone);
    report({ action: 'select', parts: selected, isolate });
  }
  const bench = make('section', null, 'ws-bench card');
  const pick = make('input'); pick.type = 'file'; pick.accept = 'image/*'; pick.hidden = true;
  const choose = button('Choose a picture', null, () => pick.click(), 'primary');
  const benchRow = make('div', null, 'ws-bench-row'); benchRow.append(choose, make('span', 'or drop one here, paste it, or say "Jarvis, build what\'s on my screen"'));
  const saved = make('div', null, 'ws-saved');
  bench.append(make('h3', 'The workshop'), make('p', 'Put a picture on the bench and I will build it in 3D, ready to pull apart: a floor plan, a product, a sketch, a logo. Or just tell me what to build.'), benchRow, saved, pick);
  const status = make('div', '', 'ws-status'); status.setAttribute('role', 'status');
  box.append(rendered, head, hint, tabs, actions, tools, cutBar, picture, photos, partsPanel, panel, bench, status);
  // Dragging the render (or any picture already on the page) is not "putting a picture on the bench".
  rendered.draggable = false; pictureImg.draggable = false;

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
    modelPick.disabled = !!busy;
    const has = !!(scene && scene.steps.length);
    title.textContent = scene?.title || (busy === 'build' ? 'Designing…' : 'The workshop');
    bench.hidden = has || !!busy;
    panel.hidden = !(has || busy) || view === 'render';
    panelTitle.textContent = busy === 'build' ? 'BUILDING' : busy === 'change' ? 'CHANGING' : busy === 'check' ? 'CHECKING AND DETAILING' : busy === 'variants' ? 'MAKING VARIANTS' : 'BUILT';
    const comparing = variantList.length > 0;
    hint.textContent = view === 'render' || !has || busy ? '' : comparing ? 'Click the one to keep, or say "the second one".'
      : measuring ? 'Its real size. Click two points on it to measure between them.'
      : selected.length ? 'Click empty space, or "Show all", for the whole model again.'
      : exploded ? 'Every part, labelled. Click one to look at it alone.' : 'Drag to turn it. Click a part to select it. Say "Jarvis, pull it apart."';
    partsPanel.hidden = !has || busy === 'build' || view === 'render' || !partList.length || comparing;
    tools.hidden = !has || view === 'render' || comparing || busy === 'build';
    for (const b of [detailBtn, fileBtn, clipBtn]) b.disabled = !!busy;
    measureBtn.classList.toggle('on', measuring); cutBtn.classList.toggle('on', !!cutNow);
    cutBtn.textContent = cutNow ? 'Close it up' : 'Cut open';
    cutBar.hidden = !cutNow || !has || view === 'render' || comparing;
    axisButtons.forEach((b, i) => b.classList.toggle('on', !!cutNow && cutNow.axis === 'xyz'[i]));
    photos.hidden = !refs.length || !has || view === 'render';
    apart.textContent = exploded ? 'Put together' : 'Pull apart';
    for (const b of [apart, renderBtn]) b.hidden = !has || view === 'render' || comparing;
    apart.disabled = renderBtn.disabled = !!busy;
    undoBtn.hidden = !has || !scene.versions || !!busy || view === 'render';
    fresh.hidden = !has || !!busy;
    tabs.hidden = !renderUrl;
    tabModel.classList.toggle('on', view === 'model'); tabRender.classList.toggle('on', view === 'render');
    rendered.hidden = view !== 'render' || !renderUrl; frame.style.visibility = view === 'render' && renderUrl ? 'hidden' : 'visible';
    picture.hidden = !(scene?.picture) || view === 'render';
    status.textContent = busy === 'render' ? 'Rendering a realistic picture… about a minute' : status.dataset.keep || status.dataset.job || '';
    if (panelAuto) { panelBody.hidden = !busy || busy === 'render'; hide.textContent = panelBody.hidden ? 'Show' : 'Hide'; }
    box.classList.toggle('ws-compact', panelBody.hidden);
    const edge = !partsPanel.hidden ? partsPanel : !panel.hidden ? panel : null, left = edge ? Math.round(edge.getBoundingClientRect().right + 10) : 0;
    if (left !== leftNow) { leftNow = left; insets(); }
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
  async function replay() {
    await loadPhotos();
    if (variantList.length) { send({ t: 'variants', list: variantList }); return; }
    send({ t: 'reset' });
    for (const step of scene?.steps || []) send({ t: 'run', name: step.name, code: step.code, setup, quiet: true });
    if (exploded) send({ t: 'explode', on: true });
    if (selected.length) send({ t: 'select', names: selected, isolate });
    if (measuring) send({ t: 'measure', on: true, scale: 'auto' });
    if (cutNow) send({ t: 'cut', on: true, axis: cutNow.axis, at: cutNow.at });
    for (const name of moving) send({ t: 'motion', name, on: true });
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
    const comparing = JSON.stringify((data.variants || []).map(v => v.name));
    const same = scene && data.scene && JSON.stringify(scene.steps) === JSON.stringify(data.scene.steps) && setup === data.scene.setup
      && comparing === JSON.stringify(variantList.map(v => v.name)) && JSON.stringify(data.refs || []) === JSON.stringify(refs);
    scene = data.scene; setup = data.scene?.setup || ''; busy = data.busy || ''; modelName = data.model || 'fable';
    modelPick.value = data.selected_model || 'fable'; modelPick.disabled = !!busy;
    tokens = data.tokens || 0; exploded = !!data.exploded; errors = 0;
    startedAt = Date.now() / 1000 - Math.max(0, (data.now || 0) - (data.started || 0)); clock = data.seconds || 0;
    steps.replaceChildren(); for (const name of (data.notes?.length ? data.notes : (scene?.steps || []).map(s => s.name))) addStep(name);
    thoughtText.textContent = data.thinking ? data.thinking.slice(-320) : '';
    if (busy && busy !== 'render') thoughtHead.textContent = modelName.toUpperCase() + ' IS THINKING'; else if (!thoughtHead.textContent.startsWith('THOUGHT')) thoughtHead.textContent = '';
    thought.hidden = !thoughtText.textContent;
    if (scene?.picture) pictureImg.src = `/workshop/file?scene=${encodeURIComponent(scene.id)}&name=picture.jpg`;
    setRender(data.render); view = data.view === 'render' && data.render ? 'render' : 'model';
    drawSaved(data.recent);
    selected = Array.isArray(data.selected) ? data.selected : []; isolate = !!data.isolate && selected.length > 0;
    variantList = Array.isArray(data.variants) ? data.variants : []; refs = Array.isArray(data.refs) ? data.refs : [];
    measuring = !!data.measuring; cutNow = data.cut || null; moving = Array.isArray(data.moving) ? data.moving : [];
    if (cutNow) cutSlide.value = Math.round(cutNow.at * 100);
    if (!scene) { partList = []; motionList = []; }
    if (!same) await replay(); else { send({ t: 'explode', on: exploded }); send({ t: 'select', names: selected, isolate }); }
    drawParts(); drawMoves();
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
    else if (p === 'settings') { modelPick.value = ev.model; }
    else if (p === 'close') leave();
    else if (p === 'start') {
      busy = ev.mode; startedAt = Date.now() / 1000; tokens = 0; errors = 0; modelName = ev.model || modelName; view = 'model';
      thoughtText.textContent = ''; thoughtHead.textContent = modelName.toUpperCase() + ' IS THINKING'; thought.hidden = false; steps.replaceChildren();
      status.dataset.keep = '';
      if (ev.mode === 'build') {
        scene = { id: '', title: '', steps: [], picture: !!ev.picture, versions: 0 }; setup = ''; exploded = false; setRender('');
        partList = []; selected = []; isolate = false; motionList = []; moving = []; measuring = false; cutNow = null; variantList = []; refs = [];
        photoKey = ''; photoData = []; photoRow.replaceChildren(); drawParts(); drawMoves();
        send({ t: 'photos', list: [] }); send({ t: 'reset' });
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
    else if (p === 'done') {   // the build is in; with `checking` Jarvis goes straight on to compare and improve it
      clock = ev.seconds || 0; tokens = ev.tokens || tokens;
      if (!ev.checking) { busy = ''; sync(); setTimeout(repairIfBroken, 900); }
    }
    else if (p === 'ready') { clock = ev.seconds || clock; busy = ''; status.dataset.job = ''; sync(); }
    else if (p === 'status') { status.dataset.job = ev.text || ''; draw(); }
    else if (p === 'refs') { refs = Array.isArray(ev.refs) ? ev.refs : []; if (scene) scene.id = ev.scene || scene.id; loadPhotos().then(draw); }
    else if (p === 'motion') { setMotion(String(ev.name), !!ev.on, false); enter(); }
    else if (p === 'measure') { measuring = !!ev.on; send({ t: 'measure', on: measuring, scale: ev.scale || 'auto' }); draw(); enter(); }
    else if (p === 'cut') { setCut(ev.on ? { axis: ev.axis, at: ev.at } : null, false); enter(); }
    else if (p === 'export') { pendingFiles.add(ev.nonce); send({ t: 'export', format: ev.format, nonce: ev.nonce }); }
    else if (p === 'record') { pendingFiles.add(ev.nonce); note('Recording a turntable clip…'); send({ t: 'record', nonce: ev.nonce, seconds: ev.seconds }); enter(); }
    else if (p === 'variants') { busy = ''; sync(true); }
    else if (p === 'patch') { clock = ev.seconds || 0; tokens = ev.tokens || tokens; busy = ''; sync().then(() => setTimeout(repairIfBroken, 900)); }
    else if (p === 'note-status') { status.dataset.job = ev.text || ''; draw(); }
    else if (p === 'error') { busy = ''; note(ev.message ? 'It didn\'t finish: ' + ev.message : ''); sync(); }
    else if (p === 'explode') { setExploded(ev.on); view = 'model'; draw(); enter(); }
    else if (p === 'snapshot') {   // if the workshop only just came on screen, give the stage a moment to size itself
      pendingSnapshot = ev.nonce; enter();
      setTimeout(() => send({ t: 'snapshot', nonce: ev.nonce, mode: ev.mode || 'view' }), Math.max(0, 1600 - (Date.now() - enteredAt)));
    }
    else if (p === 'rendering') { busy = 'render'; draw(); enter(); }
    else if (p === 'render') { busy = ''; setRender(ev.url + '&at=' + Date.now()); view = 'render'; draw(); enter(); }
    else if (p === 'render-error') { busy = ''; note('The render didn\'t come out: ' + (ev.message || 'unknown')); }
    else if (p === 'view') { show(ev.view); enter(); }
    else if (p === 'select') { view = 'model'; applySelection(ev.parts, ev.isolate); enter(); }
  });
  function repairIfBroken() { if (errors && !busy) { errors = 0; report({ action: 'repair' }); } }

  /* ---------- What the stage sends back ---------- */
  let pendingSnapshot = '', sizesTimer = 0;
  const pendingFiles = new Set();
  async function upload(m) {   // a file the stage made (a model or a clip) goes to Jarvis, who puts it in Documents
    if (!pendingFiles.delete(m.nonce)) return;
    if (m.failed || !(m.data instanceof ArrayBuffer)) return note('That didn\'t come out: ' + (m.failed || 'no data'));
    try {
      const text = await new Promise((done, fail) => { const reader = new FileReader(); reader.onload = () => done(String(reader.result)); reader.onerror = fail; reader.readAsDataURL(new Blob([m.data])); });
      await J.api('/workshop/upload', { nonce: m.nonce, kind: m.kind, data: text.slice(text.indexOf(',') + 1) }, { timeout: 120000 });
      note(m.kind === 'webm' ? 'Clip recorded.' : 'Saved in Documents, Jarvis Workshop.');
    } catch (e) { note('Couldn\'t save it: ' + e.message); }
  }
  addEventListener('message', event => {
    if (event.source !== stage || !event.data || typeof event.data !== 'object') return;
    const m = event.data;
    if (m.t === 'parts' && Array.isArray(m.parts)) {
      const names = m.parts.map(p => p.name).join('|');
      if (names !== partList.map(p => p.name).join('|')) { partList = m.parts.map(p => ({ name: String(p.name), description: String(p.description || '') })); drawParts(); draw(); }
      const able = (Array.isArray(m.motions) ? m.motions : []).map(String);
      if (able.join('|') !== motionList.join('|')) { motionList = able; moving = moving.filter(n => able.includes(n)); drawMoves(); }
    } else if (m.t === 'sizes') {
      clearTimeout(sizesTimer);
      sizesTimer = setTimeout(() => J.api('/workshop', { action: 'sizes', whole: m.whole, parts: m.parts, ruler: m.ruler }).catch(() => {}), 150);
    } else if (m.t === 'file') upload(m);
    else if (m.t === 'variant') report({ action: 'variant', name: String(m.name || '') });
    else if (m.t === 'pick') {
      if (busy || view === 'render') return;
      pickParts(m.name ? (m.add ? toggle(m.name) : (selected.length === 1 && selected[0] === m.name ? [] : [m.name])) : [], m.name ? isolate : false);
    } else if (m.t === 'ready' && !ready) { ready = true; for (const item of queue.splice(0)) stage.postMessage(item, '*'); insets(); }
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
    send({ t: 'insets', right: side ? Math.max(0, innerWidth - side.left + 8) : 0, bottom: Math.max(0, innerHeight - dock.top + 8), top: 96, left: visible() ? leftNow : 0 });
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
  box.addEventListener('dragover', e => { e.preventDefault(); if (!ownDrag) box.classList.add('dropping'); });
  box.addEventListener('dragleave', () => box.classList.remove('dropping'));
  let ownDrag = false;   // a drag that began on this page (the render, a button) never counts as a picture for the bench
  addEventListener('dragstart', () => { ownDrag = true; }, true);
  addEventListener('dragend', () => { ownDrag = false; }, true);
  box.addEventListener('drop', e => {
    e.preventDefault(); box.classList.remove('dropping');
    if (ownDrag) { ownDrag = false; return; }
    const file = [...e.dataTransfer.files].find(f => f.type.startsWith('image/'));
    if (file) putOnBench(file);
  });
  addEventListener('paste', e => {
    if (!visible()) return;
    const file = [...(e.clipboardData?.files || [])].find(f => f.type.startsWith('image/'));
    if (file) { e.preventDefault(); putOnBench(file); }
  });
  // A drag over the frame never reaches this page, so the frame stops taking the mouse while something is dragged in.
  addEventListener('dragenter', () => { if (visible()) frame.style.pointerEvents = 'none'; });
  for (const type of ['drop', 'dragend', 'mouseup']) addEventListener(type, () => { frame.style.pointerEvents = ''; }, true);
  addEventListener('dragleave', e => { if (!e.relatedTarget) frame.style.pointerEvents = ''; });

  /* ---------- Hands (HOLO): the same gestures that turn the graph turn the model while the workshop is up ----------
     Pinch and move turns it, a quick pinch picks the part under your hand, an open palm frames it again, and two
     pinching hands zoom it; pulled far enough apart, the model itself comes apart, and squeezed together it
     goes back. The gesture code in modes.js is unchanged: these wrap what it calls. */
  if (J.camera && J.camera.hand) {
    const cam = J.camera, hand = cam.hand, was = { move: hand.move, zoomBy: cam.zoomBy, rotate: cam.rotate, fit: cam.fit, hit: J.hit, select: J.select, clear: J.clearSelection };
    let spread = 1, spreadAt = 0;
    hand.move = (dx, dy, now) => visible() ? send({ t: 'orbit', dx, dy }) : was.move(dx, dy, now);
    cam.rotate = (yaw, pitch) => visible() ? send({ t: 'orbit', dx: yaw * 60, dy: pitch * 60 }) : was.rotate.call(cam, yaw, pitch);
    cam.fit = () => visible() ? send({ t: 'fit' }) : was.fit();
    cam.zoomBy = factor => {
      if (!visible()) return was.zoomBy.call(cam, factor);
      const now = performance.now(); if (now - spreadAt > 700) spread = 1;
      spreadAt = now; spread *= factor; send({ t: 'zoom', f: factor });
      if (!busy && !variantList.length && ((spread > 1.8 && !exploded) || (spread < .55 && exploded))) {
        setExploded(spread > 1); report({ action: 'explode', on: exploded }); spread = 1;
      }
    };
    J.hit = (x, y) => visible() ? { workshop: true, x, y } : was.hit(x, y);
    J.select = target => target && target.workshop ? send({ t: 'pickAt', x: target.x, y: target.y }) : was.select(target);
    J.clearSelection = () => visible() ? pickParts([], false) : was.clear();
  }

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
