/* The Console: one stream of what you asked, what JARVIS did and what the tools proved, with a side rail of
   running work, things waiting on you and the house. It is a second main view beside the 3D model; the
   switch in the top bar (or Ctrl+.) moves between them. Everything is drawn with textContent.
   Proof chips come from the tools' own receipts (truth_guard.py), never from how the reply is worded. */
'use strict';
(() => {
  const el = id => document.getElementById(id);
  const stream = el('consoleStream');
  const PROOF = {
    confirmed: ['✓', 'confirmed', 'ok'], sent: ['→', 'sent, not read back', 'sent'],
    waiting: ['…', 'waiting for your OK', 'wait'], unknown: ['?', 'could not confirm', 'warn'], failed: ['✗', 'failed', 'bad'],
  };
  const SOURCES = [['(Telegram voice) ', 'Telegram voice'], ['(Telegram) ', 'Telegram'], ['(Phone) ', 'Phone'], ['(Terminal) ', 'Terminal']];
  let turn = null;

  /* ---------- Turns ---------- */
  function atBottom() { return stream.scrollHeight - stream.scrollTop - stream.clientHeight < 60; }
  function startTurn(text, kind, at) {
    const follow = atBottom();
    const box = make('article', null, 'turn ' + (kind || 'you'));
    const head = make('div', null, 'turn-head');
    let label = '';
    for (const [prefix, name] of SOURCES) if (text.startsWith(prefix)) { text = text.slice(prefix.length); label = name; }
    head.append(make('span', kind === 'system' ? '•' : '›', 'caret'), make('span', text, 'turn-text'));
    if (label) head.append(make('small', label, 'via'));
    const time = make('time', new Date((at || Date.now() / 1000) * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }));
    head.append(time);
    turn = { box, work: make('div', null, 'turn-work'), say: make('div', null, 'turn-say'), proof: make('div', null, 'turn-proof'), tools: [] };
    box.append(head, turn.work, turn.say, turn.proof);
    el('consoleEmpty')?.remove();
    stream.append(box);
    while (stream.children.length > 200) stream.firstElementChild.remove();
    if (follow) stream.scrollTop = stream.scrollHeight;
    return turn;
  }
  const current = at => turn || startTurn('Jarvis', 'system', at);
  function keepInView(follow) { if (follow) stream.scrollTop = stream.scrollHeight; }

  /* ---------- Tool rows ---------- */
  function clip(value, n = 140) { const s = String(value ?? '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  function describe(name, input) {
    const a = input && typeof input === 'object' ? input : {};
    if (name === 'run_command') return ['$', clip(a.command, 400), true];
    if (name === 'read_file') return ['read', clip(a.path)];
    if (name === 'search_text') return ['search', clip(a.pattern) + (a.folder ? '  in ' + clip(a.folder, 60) : '')];
    if (name === 'find_files') return ['find', clip(a.query)];
    if (name === 'write_file') return ['write', clip(a.path)];
    if (name === 'edit_file') return ['edit', clip(a.path)];
    if (name === 'home_control') return ['home', clip([a.device, String(a.action || '').replaceAll('_', ' '), a.value].filter(Boolean).join(' · '))];
    const first = Object.values(a).find(v => typeof v === 'string' && v.trim());
    return [name.replaceAll('_', ' '), first ? clip(first) : ''];
  }
  function diffCard(input) {
    const card = make('div', null, 'diff'), body = make('pre');
    const lines = (text, cls, mark) => String(text ?? '').split('\n').slice(0, 60).forEach(l => body.append(make('span', mark + ' ' + l + '\n', cls)));
    lines(input.old_text, 'del', '-'); lines(input.new_text, 'add', '+');
    card.append(body); return card;
  }
  function addTool(ev) {
    const t = current(ev.t), follow = atBottom();
    const [verb, detail, mono] = describe(String(ev.name || 'tool'), ev.input);
    const row = make('div', null, 'tool');
    const line = make('div', null, 'tool-line');
    line.append(make('b', verb), make(mono ? 'code' : 'span', detail));
    row.append(line);
    if (ev.name === 'edit_file' && ev.input && typeof ev.input.new_text === 'string') row.append(diffCard(ev.input));
    t.work.append(row); t.tools.push({ name: ev.name, row, done: false });
    keepInView(follow);
  }
  function addResult(ev) {
    if (!turn) return;
    const entry = turn.tools.find(x => x.name === ev.name && !x.done); if (!entry) return;
    entry.done = true;
    const follow = atBottom(), text = String(ev.text || '').trimEnd();
    if (!ev.ok) entry.row.classList.add('failed');
    if (!text || (ev.name === 'edit_file' && ev.ok)) return;
    const out = make('pre', null, 'out'), all = text.split('\n');
    out.textContent = all.slice(0, 14).join('\n');
    entry.row.append(out);
    if (all.length > 14) {
      const more = make('button', `show all ${all.length} lines`, 'link'); more.type = 'button';
      more.onclick = () => { out.textContent = text; out.classList.add('open'); more.remove(); };
      entry.row.append(more);
    }
    keepInView(follow);
  }
  function addReceipt(ev) {
    const t = current(ev.t), follow = atBottom();
    const [icon, words, cls] = PROOF[ev.status] || ['•', String(ev.status || ''), 'sent'];
    const chip = make('span', `${icon} ${clip(ev.about, 40)} · ${words}`, 'chip-proof ' + cls);
    chip.title = String(ev.tool || '').replaceAll('_', ' ') + ': what the tool itself reported';
    t.proof.append(chip);
    keepInView(follow);
  }
  function addNote(text, cls, at) {
    const t = current(at), follow = atBottom();
    t.work.append(make('div', text, 'note ' + (cls || '')));
    keepInView(follow);
  }

  /* ---------- The event stream ---------- */
  // 'reset' comes just before the server replays this session's history to a page that has (re)connected.
  J.on('reset', () => { stream.replaceChildren(empty()); turn = null; });
  function empty() {
    const e = make('div', null, 'console-empty'); e.id = 'consoleEmpty';
    e.append(make('p', 'Nothing yet this session.'), make('small', 'Type below, or say “Jarvis…”. Commands he runs, files he changes and what each tool proved show up here.'));
    return e;
  }
  J.on('event', ev => {
    if (ev.type === 'you') startTurn(String(ev.text || ''), 'you', ev.t);
    else if (ev.type === 'jarvis') {
      const t = current(ev.t), follow = atBottom();
      t.say.textContent = (t.say.textContent ? t.say.textContent + ' ' : '') + String(ev.text || '');
      keepInView(follow);
    }
    else if (ev.type === 'tool') addTool(ev);
    else if (ev.type === 'result') addResult(ev);
    else if (ev.type === 'receipt') addReceipt(ev);
    else if (ev.type === 'error') addNote(String(ev.text || 'Something failed.'), 'error', ev.t);
    else if (ev.type === 'event') {
      const text = String(ev.text || '');
      const asked = text.startsWith('Approval needed: ') ? text.slice(17) : '';
      if (asked) addNote('Waiting for your OK: ' + asked, 'wait', ev.t);  // the card with Yes and No is cards.js
      else if (text === 'Interrupted') addNote('You cut in.', '', ev.t);
      else if (/ (finished|didn't finish|got blocked|didn't work|was stopped|only partly finished)$/.test(text) || /^(Reminder|Timer|Telegram message|Phone message|Daily review|Briefing|Morning wake-up|Welcome back)/.test(text)) {
        startTurn(text, 'system', ev.t);
      } else addNote(text.split('\n')[0].slice(0, 300), '', ev.t);
    }
  });
  stream.append(empty());

  /* ---------- Side rail ---------- */
  const ago = seconds => seconds < 90 ? Math.max(1, Math.round(seconds)) + ' s' : seconds < 5400 ? Math.round(seconds / 60) + ' min' : Math.round(seconds / 3600) + ' h';
  async function refreshWork() {
    const box = el('railWork');
    try {
      const data = await J.api('/sessions', undefined, { timeout: 4000 });
      const busy = (data.sessions || []).filter(s => ['running', 'pausing', 'paused'].includes(s.status));
      box.replaceChildren();
      for (const s of busy) {
        const card = make('div', null, 'rail-card'), top = make('div', null, 'rail-top');
        const last = (s.timeline || []).at(-1);
        top.append(make('b', String(s.name || 'Agent')), make('small', last?.status === 'running' && last.started_at ? 'step: ' + ago(Date.now() / 1000 - last.started_at) : s.status));
        card.append(top, make('p', clip(last?.label || s.task || s.status, 110)));
        if (s.status === 'running') {
          const stop = make('button', 'Stop', 'link'); stop.type = 'button';
          stop.onclick = async () => { try { await J.api('/session-control', { action: 'cancel', name: s.name }); refreshWork(); } catch (e) { J.notice(e.message); } };
          card.append(stop);
        }
        box.append(card);
      }
      let jobs = [];
      // Working lists what is still going; a finished job becomes a card (cards.js) with its buttons.
      try { jobs = ((await J.api('/jobs', undefined, { timeout: 4000 })).jobs || []).filter(j => ['queued', 'running'].includes(j.status)); } catch {}
      for (const j of jobs) {
        const card = make('div', null, 'rail-card job ' + String(j.status)), top = make('div', null, 'rail-top');
        top.append(make('b', 'Away ' + String(j.kind)), make('small', String(j.label) + (j.attempt ? ' · attempt ' + j.attempt : '')));
        card.append(top, make('p', String(j.what)));
        if (j.check) card.append(make('small', String(j.check), 'job-check'));
        if (j.branch) card.append(make('small', 'Branch to review: ' + String(j.branch), 'job-check'));
        box.append(card);
      }
      if (!busy.length && !jobs.length) box.append(make('p', 'Nothing running.', 'rail-note'));
    } catch { box.replaceChildren(make('p', J.online ? 'Could not read the agents.' : 'Jarvis is offline.', 'rail-note')); }
  }
  async function refreshHome() {
    const box = el('railHome');
    try {
      const data = await J.api('/home', undefined, { timeout: 6000 });
      box.replaceChildren();
      if (data.error) { box.append(make('p', data.error, 'rail-note')); return; }
      // Whatever is on comes first, so a full house never hides the thing that's running.
      const live = d => ['on', 'playing'].includes(d.state) ? 0 : 1;
      const shown = (data.devices || []).filter(d => ['light', 'switch', 'fan', 'media_player', 'climate'].includes(d.domain))
        .sort((a, b) => live(a) - live(b)).slice(0, 12);
      for (const d of shown) {
        const known = ['on', 'off', 'playing', 'paused', 'idle', 'standby', 'heat', 'cool'].includes(d.state);
        const tile = make('button', null, 'home-tile' + (['on', 'playing'].includes(d.state) ? ' on' : '') + (known ? '' : ' unknown')); tile.type = 'button';
        tile.append(make('b', known ? d.state : 'unknown'), make('span', d.name));
        tile.title = 'Read from Home Assistant ' + ago(Date.now() / 1000 - (data.read_at || 0)) + ' ago. Click to prepare a command.';
        tile.onclick = () => J.prepare(`Turn ${d.state === 'on' || d.state === 'playing' ? 'off' : 'on'} the ${d.name}`);
        box.append(tile);
      }
      if (!shown.length) box.append(make('p', 'No devices found.', 'rail-note'));
    } catch { box.replaceChildren(make('p', J.online ? 'Could not read the house.' : 'Jarvis is offline.', 'rail-note')); }
  }
  async function refreshToday() {
    const box = el('railToday');
    try {
      const data = await J.api('/intel', undefined, { timeout: 8000 });
      box.replaceChildren(make('p', clip(data.schedule || 'No calendar connected.', 260)), make('p', clip(data.weather || '', 160), 'muted'));
    } catch { box.replaceChildren(make('p', J.online ? 'Could not read today.' : 'Jarvis is offline.')); }
  }
  el('railHomeRefresh').onclick = refreshHome;
  const visible = () => document.body.classList.contains('view-console') && !document.hidden;
  setInterval(() => { if (visible()) refreshWork(); }, 4000);
  setInterval(() => { if (visible()) refreshHome(); }, 20000);
  setInterval(() => { if (visible()) refreshToday(); }, 300000);
  J.on('receipt', ev => { if (ev.tool === 'home_control' && visible()) setTimeout(refreshHome, 9000); });  // after the server's short cache

  /* ---------- Switching views ---------- */
  let restoreStage = false;
  function setView(name, focus = true) {
    const consoleOn = name === 'console', workshopOn = name === 'workshop' && !!el('workshop');
    if ((consoleOn || workshopOn) && J.view.jarvisMain) { restoreStage = true; J.setStage(false, false, false); }
    document.body.classList.toggle('view-console', consoleOn);
    document.body.classList.toggle('view-workshop', workshopOn);   // the 3D workshop (workshop.js)
    el('console').hidden = !consoleOn;
    if (el('workshop')) el('workshop').hidden = !workshopOn;
    for (const [id, on] of [['viewConsole', consoleOn], ['viewWorkshop', workshopOn], ['viewModel', !consoleOn && !workshopOn]]) {
      if (!el(id)) continue;
      el(id).classList.toggle('on', on); el(id).setAttribute('aria-pressed', String(on));
    }
    if (!consoleOn && !workshopOn && restoreStage) { restoreStage = false; J.setStage(true, false, false); }
    if (!workshopOn) store.set('view', consoleOn ? 'console' : 'model');   // the workshop is opened on purpose, never by default
    dispatchEvent(new Event('resize'));
    if (consoleOn) { refreshWork(); refreshHome(); refreshToday(); stream.scrollTop = stream.scrollHeight; if (focus) el('prompt').focus(); }
    J.emit('view', consoleOn ? 'console' : workshopOn ? 'workshop' : 'model');
  }
  J.setView = setView;
  el('viewConsole').onclick = () => setView('console');
  el('viewModel').onclick = () => setView('model');
  addEventListener('keydown', e => {
    if (e.ctrlKey && !e.altKey && !e.shiftKey && e.key === '.') { e.preventDefault(); setView(document.body.classList.contains('view-console') ? 'model' : 'console'); }
  });

  /* ---------- A terminal's habit: Up and Down recall what you typed ---------- */
  const typed = store.get('typed', []); let at = typed.length, draft = '';
  el('command').addEventListener('submit', () => {
    const text = el('prompt').value.trim(); if (!text) return;
    if (typed.at(-1) !== text) { typed.push(text); while (typed.length > 50) typed.shift(); store.set('typed', typed); }
    at = typed.length; draft = '';
  }, true);
  el('prompt').addEventListener('keydown', e => {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    if (e.key === 'ArrowUp' && at > 0) { if (at === typed.length) draft = el('prompt').value; at--; }
    else if (e.key === 'ArrowDown' && at < typed.length) at++;
    else return;
    e.preventDefault(); el('prompt').value = at === typed.length ? draft : typed[at];
  });

  if (store.get('view', 'model') === 'console' && !document.body.classList.contains('compact-orb')
      && new URLSearchParams(location.search).get('compact') !== '1') setView('console', false);
})();
