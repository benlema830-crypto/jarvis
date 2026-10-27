/* JARVIS Brain dialogs: armory, activity, tasks & agents, model, voice health, reader, workspace.
   Opening a dialog never connects an account, runs a tool or starts capture. */
'use strict';
(() => {
  const el = id => document.getElementById(id);
  function dialog(id, title, sub, narrow) {
    const d = make('dialog'); d.id = id; if (narrow) d.className = 'narrow';
    const head = make('div', null, 'dialog-head'), h = make('h2', title), close = make('button', '✕ close', 'close');
    close.type = 'button'; close.onclick = () => d.close();
    head.append(h, close); d.append(head);
    if (sub) d.append(make('p', sub, 'dialog-sub'));
    const body = make('div'); d.append(body); document.body.append(d);
    d.head = h; d.body = body;
    return d;
  }
  function tile({ icon, name, text, chip, chipClass, onClick, extra }) {
    const t = make(onClick ? 'button' : 'div', null, 'tile'); if (onClick) { t.type = 'button'; t.onclick = onClick; }
    const i = make('div', icon || '•', 'icon'), body = make('div', null, 'body');
    body.append(make('b', name), make('p', text));
    if (extra) body.append(...extra);
    t.append(i, body);
    if (chip) t.append(make('span', chip, 'chip ' + (chipClass || '')));
    return t;
  }

  /* ---------- Activity ---------- */
  const activity = dialog('activityDialog', 'Activity', 'What JARVIS did this session: tools used, errors and system events.', true);
  let unseen = 0;
  const seenTypes = new Set(['tool', 'error', 'event']);
  const TOOL_WORDS = { web_search: 'Searched the web', search_knowledge: 'Searched your vault', read_knowledge_note: 'Read a note' };
  J.on('event', ev => {
    if (!seenTypes.has(ev.type)) return;
    const row = make('div', null, 'activity-row' + (ev.type === 'error' ? ' error' : ''));
    row.append(make('small', new Date((ev.t || Date.now() / 1000) * 1000).toLocaleTimeString() + ' · ' + ev.type),
      make('span', ev.type === 'tool' ? (TOOL_WORDS[ev.name] || String(ev.name || '').replaceAll('_', ' ')) : String(ev.text || '')));
    activity.body.prepend(row);
    while (activity.body.children.length > 150) activity.body.lastChild.remove();
    if (ev.type === 'error' && !ev.replay) J.notice(ev.text);
    if (!ev.replay && !activity.open) { unseen++; el('activityCount').textContent = unseen; el('activityCount').hidden = false; }
  });
  el('activityBtn').onclick = () => {
    unseen = 0; el('activityCount').hidden = true;
    if (!activity.body.children.length) activity.body.append(make('p', 'Nothing yet this session.', 'muted'));
    activity.showModal();
  };

  /* ---------- Tasks & agents ---------- */
  const agents = dialog('agentsDialog', 'Tasks & agents', 'Your to-do list lives in Tasks.md in your vault. Agent sessions are Codex workers JARVIS manages.');
  const taskBox = make('div'), sessionBox = make('div', null, 'grid');
  agents.body.append(make('div', 'To-do (Tasks.md)', 'section-label'), taskBox, make('div', 'Agent sessions', 'section-label'), sessionBox);
  async function showAgents() {
    try {
      const data = await J.api('/tasks'); taskBox.replaceChildren();
      if (!data.tasks.length) taskBox.append(make('p', 'No tasks yet. Say "Jarvis, add a task: …".', 'muted'));
      for (const task of data.tasks.slice(0, 80)) {
        const row = make('div', null, 'task' + (task.done ? ' done' : ''));
        row.append(make('span', task.done ? '☑' : '☐'), make('span', task.text));
        taskBox.append(row);
      }
    } catch (e) { taskBox.replaceChildren(make('p', e.message, 'muted')); }
    try {
      const data = await J.api('/sessions'); sessionBox.replaceChildren();
      const sessions = data.sessions || [];
      if (!sessions.length) sessionBox.append(make('p', 'No agent sessions yet. Say "Open an agent session in Rocket Frontier".', 'muted'));
      for (const s of sessions) {
        const details = make('details'); details.append(make('summary', 'Last report'), make('p', s.report || 'No report yet.'));
        const status = String(s.status || 'idle');
        sessionBox.append(tile({ icon: '🤖', name: s.name, text: (s.project || '') + ' · ' + (s.provider || 'codex') + (s.task ? ' — ' + s.task : ''),
          chip: status, chipClass: status === 'running' ? 'warn' : status === 'failed' ? 'bad' : 'ok', extra: s.report ? [details] : [] }));
      }
    } catch (e) { sessionBox.replaceChildren(make('p', e.message, 'muted')); }
  }
  el('agentsBtn').onclick = () => { agents.showModal(); showAgents(); };
  setInterval(() => { if (agents.open) showAgents(); }, 5000);

  /* ---------- Tool armory ---------- */
  const armory = dialog('armoryDialog', 'Tool armory', 'Everything JARVIS can reach. Built-in tools are always on; connect apps through MCP and he uses them mid-conversation (asking you first).');
  const armorySearch = make('input'); armorySearch.placeholder = 'Filter tools…'; armorySearch.style.width = '100%';
  const builtIn = make('div', null, 'grid'), connect = make('div', null, 'grid'), mine = make('div', null, 'grid');
  const armoryNotice = make('p', '', 'muted'); armoryNotice.setAttribute('role', 'status');
  armory.body.append(armorySearch, make('div', 'Built in', 'section-label'), builtIn, make('div', 'Connect', 'section-label'), connect,
    make('div', 'Your MCP connections', 'section-label'), mine, armoryNotice);
  const BUILT_IN = [
    ['🔎', 'Web research', 'Live web search with the sources shown in the Brain.', 'What is the latest news on '],
    ['🧠', 'Second brain', 'Search, read and add notes in your Obsidian vault.', 'What do my notes say about '],
    ['✅', 'Tasks', 'A to-do list kept in Tasks.md in your vault.', 'Add a task: '],
    ['📝', 'Documents', 'Writes Word documents using your notes and context.', 'Write a document: '],
    ['🗂', 'Files & folders', 'Find, open, list, copy and rename your personal files.', 'Find the file called '],
    ['🪟', 'Apps & windows', 'Open apps; move, snap, minimize or close windows.', 'Put Chrome on my second monitor'],
    ['🎵', 'Media & volume', 'Play/pause, skip, per-app volume and speaker choice.', 'Turn Spotify down to 30 percent'],
    ['📅', 'Calendar', 'Reads your published calendar; adds Outlook events.', "What's on my calendar tomorrow?"],
    ['⏰', 'Reminders & timers', 'Spoken reminders that survive restarts.', 'Remind me in 20 minutes to '],
    ['👁', 'Screen & camera', 'Looks at your screen, or through the camera while EYES is on.', 'What am I looking at?'],
    ['🎯', 'Focus coach', 'Timed focus on one app; JARVIS calls out drift.', 'Start a 30 minute focus session on '],
    ['🤖', 'Agent sessions', 'Codex project agents for coding and research.', 'Open an agent session in Rocket Frontier'],
    ['💾', 'Memory', 'Remembers facts about you between sessions.', 'Remember that '],
    ['🖐', 'Hand control', 'Steer this graph with your hands through the webcam (HOLO switch).', 'Turn on hand control'],
  ];
  let integrations = [], connections = [];
  function renderArmory() {
    const q = armorySearch.value.toLowerCase();
    const match = (...words) => !q || words.join(' ').toLowerCase().includes(q);
    builtIn.replaceChildren(...BUILT_IN.filter(b => match(b[1], b[2])).map(([icon, name, text, prompt]) =>
      tile({ icon, name, text, chip: 'ready', chipClass: 'ok', onClick: () => { armory.close(); J.prepare(prompt); } })));
    connect.replaceChildren();
    for (const item of integrations.filter(i => match(i.name, i.detail))) {
      const chipClass = { connected: 'ok', running: 'ok', paired: 'ok', installed: 'warn', configured: 'warn', setup: 'warn', paused: 'warn', 'needs OAuth': 'warn', unavailable: 'bad', 'refresh failed': 'bad' }[item.state] || '';
      const t = tile({ icon: item.icon, name: item.name, text: item.detail, chip: item.state === 'available' ? '+' : item.state,
        chipClass: item.state === 'available' ? 'add' : chipClass, onClick: () => act(item) });
      t.title = item.setup || '';
      connect.append(t);
    }
    const add = make('button', '+  Add your own tool  (any MCP URL)', 'tile dashed'); add.type = 'button'; add.onclick = () => openMcp();
    connect.append(add);
    mine.replaceChildren();
    if (!connections.length) mine.append(make('p', 'No custom connections yet.', 'muted'));
    for (const c of connections) {
      const checked = new Date(c.checked_at * 1000);
      const details = make('details'); details.append(make('summary', c.tools.length + ' discovered tools'));
      for (const tool of c.tools) { const b = make('button', tool.name); b.type = 'button'; b.title = tool.description || ''; b.disabled = !c.enabled; b.onclick = () => { armory.close(); J.prepare(`Use the ${c.name} tool ${tool.name} to `); }; details.append(b); }
      const actions = make('div', null, 'actions');
      for (const [action, label] of [['refresh', 'Refresh'], ['toggle', c.enabled ? 'Pause' : 'Enable'], ['remove', 'Remove']]) {
        const b = make('button', label); b.type = 'button';
        b.onclick = async () => { b.disabled = true; armoryNotice.textContent = 'Updating…'; try { const r = await J.api('/mcp', { action, id: c.id }, { timeout: 90000 }); armoryNotice.textContent = r.message || 'Updated.'; } catch (e) { armoryNotice.textContent = e.message; } loadArmory(); };
        actions.append(b);
      }
      const state = c.discovery_state === 'refresh_failed' ? ['refresh failed', 'bad'] : c.enabled ? ['configured', 'warn'] : ['paused', 'warn'];
      mine.append(tile({ icon: '🔌', name: c.name, text: c.host + ' · last discovery ' + (Number.isFinite(checked.getTime()) ? checked.toLocaleString() : 'unknown'),
        chip: state[0], chipClass: state[1], extra: [details, actions] }));
    }
    armory.head.replaceChildren(document.createTextNode('Tool armory'), make('small', connections.length + ' saved MCP connections'));
  }
  function act(item) {
    const a = item.action || {};
    if (a.type === 'mcp') openMcp(a.name, a.hint, item.setup);
    else if (a.type === 'model') { armory.close(); J.emit('open-model'); }
    else if (a.type === 'command') { armory.close(); J.prepare(a.text); }
    else armoryNotice.textContent = item.setup || item.detail;
  }
  async function loadArmory() {
    try { integrations = (await J.api('/integration-status')).integrations || []; } catch (e) { integrations = []; armoryNotice.textContent = e.message; }
    try { connections = (await J.api('/mcp')).connections || []; } catch { connections = []; }
    renderArmory();
  }
  armorySearch.oninput = renderArmory;
  el('armoryBtn').onclick = () => { armory.showModal(); renderArmory(); loadArmory(); };

  const mcp = dialog('mcpDialog', 'Add a tool', "Paste the server's MCP endpoint (Streamable HTTP). Connecting only discovers tools; JARVIS asks you before each call.", true);
  const form = make('form', null, 'form');
  const authMethod = make('select'); authMethod.id = 'mcp_auth';
  for (const [value, text] of [['bearer', 'Bearer token / endpoint URL'], ['oauth', 'Sign in with OAuth']]) {
    const o = make('option', text); o.value = value; authMethod.append(o);
  }
  form.append(make('label', 'Connection method'), authMethod);
  const fields = {};
  for (const [key, label, type, placeholder] of [['name', 'Connection name', 'text', 'My tools'], ['url', 'MCP endpoint URL', 'url', 'https://your-server.example/mcp'], ['token', 'Bearer token (optional)', 'password', 'Leave blank for token-in-URL endpoints']]) {
    const l = make('label', label), i = make('input'); i.type = type; i.placeholder = placeholder; i.autocomplete = 'off'; i.maxLength = key === 'token' ? 8192 : 4096; i.required = key !== 'token';
    l.htmlFor = i.id = 'mcp_' + key; fields[key] = i; form.append(l, i);
  }
  const mcpHelp = make('p', '', 'muted'), connectBtn = make('button', 'Test & connect', 'primary'), mcpResult = make('p', '', 'muted');
  connectBtn.type = 'submit'; mcpResult.setAttribute('role', 'status');
  const oauthOptions = make('details'), oauthClient = make('input'), oauthScope = make('input'), oauthPort = make('input');
  oauthOptions.append(make('summary', 'OAuth options (usually leave blank)'));
  oauthClient.id = 'mcp_client_id'; oauthClient.placeholder = 'Pre-registered public client ID';
  oauthScope.id = 'mcp_scope'; oauthScope.placeholder = 'Scopes requested by the server';
  oauthPort.id = 'mcp_callback_port'; oauthPort.type = 'number'; oauthPort.min = '1024'; oauthPort.max = '65535'; oauthPort.placeholder = 'Automatic loopback port';
  for (const [label, input] of [['Client ID', oauthClient], ['Scopes', oauthScope], ['Callback port', oauthPort]]) {
    input.autocomplete = 'off'; oauthOptions.append(make('label', label), input);
  }
  oauthOptions.append(make('p', 'For a pre-registered client, register http://127.0.0.1:PORT/callback with the service and enter that port here. Otherwise JARVIS tries dynamic public-client registration.', 'muted'));
  const oauthLink = make('a', 'Continue to service sign-in'); oauthLink.id = 'mcp_oauth_link'; oauthLink.target = '_blank'; oauthLink.rel = 'noopener noreferrer'; oauthLink.hidden = true;
  const oauthCancel = make('button', 'Cancel sign-in'); oauthCancel.type = 'button'; oauthCancel.hidden = true;
  let oauthId = '', oauthTimer = null, oauthEpoch = 0;
  function authFields() {
    const oauth = authMethod.value === 'oauth';
    fields.token.hidden = oauth;
    document.querySelector('label[for="mcp_token"]').hidden = oauth;
    oauthOptions.hidden = !oauth; connectBtn.textContent = oauth ? 'Prepare sign-in' : 'Test & connect';
  }
  authMethod.onchange = authFields;
  form.append(make('p', 'Credentials are encrypted for your Windows account. OAuth supports public clients with PKCE. Some services require a pre-registered client ID; account approval happens on the service website.', 'muted'), oauthOptions, mcpHelp, connectBtn, oauthLink, oauthCancel, mcpResult);
  mcp.body.append(form);
  authFields();
  async function cancelOAuth() {
    ++oauthEpoch; clearTimeout(oauthTimer);
    const id = oauthId; oauthId = ''; oauthLink.hidden = oauthCancel.hidden = true; oauthLink.removeAttribute('href');
    connectBtn.disabled = false; authMethod.disabled = false;
    if (id) { try { await J.api('/mcp/oauth', { action: 'cancel', id }); } catch {} }
  }
  oauthCancel.onclick = async () => { await cancelOAuth(); mcpResult.textContent = 'Sign-in cancelled.'; };
  async function pollOAuth(epoch) {
    if (!oauthId || epoch !== oauthEpoch || !mcp.open) return;
    try {
      const r = await J.api('/mcp/oauth', { action: 'status', id: oauthId });
      if (epoch !== oauthEpoch) return;
      if (r.state === 'complete') { oauthId = ''; mcp.close(); armoryNotice.textContent = r.message; loadArmory(); return; }
      if (['failed', 'cancelled'].includes(r.state)) { await cancelOAuth(); mcpResult.textContent = r.message; return; }
      mcpResult.textContent = r.state === 'exchanging' ? 'Finishing sign-in and discovering tools…' : 'Complete sign-in in the service tab. This request expires in five minutes.';
      oauthTimer = setTimeout(() => pollOAuth(epoch), 1000);
    } catch (e) { if (epoch === oauthEpoch) { await cancelOAuth(); mcpResult.textContent = e.message; } }
  }
  function openMcp(name = '', hint = '', help = '') {
    const fixedUrl = /^https:\/\/[^\s…]+$/.test(hint) ? hint : '';  // known servers have one public endpoint
    fields.name.value = name; fields.url.value = fixedUrl; fields.url.placeholder = hint || 'https://your-server.example/mcp'; fields.token.value = '';
    authMethod.value = 'bearer'; oauthClient.value = oauthScope.value = oauthPort.value = ''; authFields();
    mcpHelp.textContent = help; mcpResult.textContent = ''; mcp.showModal(); (fixedUrl ? fields.token : name ? fields.url : fields.name).focus();
  }
  function clearMcp() { cancelOAuth(); fields.token.value = ''; fields.url.value = ''; }
  const nativeMcpClose = mcp.close.bind(mcp);
  mcp.close = (...args) => { clearMcp(); nativeMcpClose(...args); };
  mcp.addEventListener('cancel', clearMcp);
  // Native close events can arrive after a rapid reopen; do not cancel a new flow.
  mcp.addEventListener('close', () => { if (!mcp.open) clearMcp(); });
  form.onsubmit = async e => {
    e.preventDefault(); connectBtn.disabled = true; mcpResult.textContent = 'Testing connection and discovering tools…';
    if (authMethod.value === 'oauth') {
      const epoch = ++oauthEpoch; authMethod.disabled = true;
      mcpResult.textContent = 'Discovering authorization settings…';
      try {
        const r = await J.api('/mcp/oauth', { action: 'start', name: fields.name.value, url: fields.url.value,
          client_id: oauthClient.value.trim(), scope: oauthScope.value.trim(), callback_port: Number(oauthPort.value || 0) }, { timeout: 120000 });
        if (epoch !== oauthEpoch || !mcp.open) { await J.api('/mcp/oauth', { action: 'cancel', id: r.id }); return; }
        oauthId = r.id; oauthLink.href = r.authorization_url; oauthLink.hidden = oauthCancel.hidden = false;
        mcpResult.textContent = 'Click Continue to service sign-in to review and approve access.';
        oauthTimer = setTimeout(() => pollOAuth(epoch), 1000);
      } catch (err) { if (epoch === oauthEpoch) { mcpResult.textContent = err.message; connectBtn.disabled = authMethod.disabled = false; } }
      return;
    }
    const payload = { action: 'connect', name: fields.name.value, url: fields.url.value, token: fields.token.value };
    fields.token.value = '';
    try { const r = await J.api('/mcp', payload, { timeout: 60000 }); mcp.close(); armoryNotice.textContent = `Saved ${r.name}: discovered ${r.tools.length} tools.`; loadArmory(); }
    catch (err) { mcpResult.textContent = err.message; }
    finally { payload.token = ''; connectBtn.disabled = false; }
  };

  /* ---------- Model ---------- */
  const model = dialog('modelDialog', "JARVIS's brain", 'Pick the conversation model. Codex uses your ChatGPT sign-in and plan limits — no API key. Changes are validated with a short test and apply after the current turn. You can also say "Jarvis, switch your brain to …".', true);
  const modelStatus = make('p', '', 'muted'), provider = make('select'), choice = make('select'), apply = make('button', 'Validate and apply', 'primary');
  modelStatus.setAttribute('role', 'status'); apply.type = 'button';
  for (const [id, label] of [['codex', 'Codex / ChatGPT subscription'], ['ollama', 'Ollama / local models'], ['anthropic', 'Anthropic / Claude API'], ['openai', 'OpenAI API']]) { const o = make('option', label); o.value = id; provider.append(o); }
  const modelForm = make('div', null, 'form'); modelForm.append(make('label', 'Provider'), provider, make('label', 'Model'), choice, apply, modelStatus);
  model.body.append(modelForm);
  let modelData = null, modelBusy = false;
  // API cost per conversation, relative to Haiku (published prices, with prompt caching)
  const CLAUDE_LABELS = {
    'claude-haiku-5-5': 'Haiku 5.5 · fastest, cheapest',
    'claude-sonnet-5-5': 'Sonnet 5.5 · smarter · ~20× Haiku cost',
    'claude-opus-5-5': 'Opus 5.5 · smartest everyday · ~35× Haiku cost',
    'claude-fable-5-1': 'Fable 5.1 · most capable, slowest · ~85× Haiku cost',
  };
  function choices() {
    const previous = choice.value; choice.replaceChildren();
    for (const id of modelData?.models?.[provider.value] || []) { const o = make('option', CLAUDE_LABELS[id] || id); o.value = id; choice.append(o); }
    if ([...choice.options].some(o => o.value === previous)) choice.value = previous;
    apply.disabled = !modelData?.ready || !!modelData?.pending || modelData?.validating || !choice.value || modelBusy;
  }
  function renderModel(value, first) {
    modelData = value;
    for (const o of provider.options) o.disabled = !!value.subscription_only && !['codex', 'ollama'].includes(o.value);
    if (first) { provider.value = value.active.provider; choices(); choice.value = value.active.model; } else choices();
    const pending = value.pending ? ` Pending: ${value.pending.model}${value.validating ? ' (validating…)' : ' (after this turn)'}.` : '';
    modelStatus.textContent = `Active: ${value.active.provider} / ${value.active.model}.${pending} ${value.error || ''}` + (value.subscription_only ? ' Paid API providers are off.' : '') + (provider.value === 'ollama' ? ' Local models require Ollama and JARVIS_OLLAMA_ENABLED=1. Models must be installed and support tools. No automatic fallback.' : '');
    el('modelName').textContent = value.active.model;
  }
  async function refreshModel(first) {
    try { renderModel(await J.api('/models', undefined, { timeout: 20000 }), first); }
    catch { modelData = null; apply.disabled = true; modelStatus.textContent = 'Model controls unavailable while JARVIS is offline.'; }
  }
  provider.onchange = choices;
  apply.onclick = async () => {
    modelBusy = true; apply.disabled = true;
    try { renderModel(await J.api('/models', { provider: provider.value, model: choice.value }, { timeout: 30000 })); }
    catch (e) { modelStatus.textContent = e.message; } finally { modelBusy = false; choices(); }
  };
  J.on('open-model', () => { model.showModal(); refreshModel(true); });
  setInterval(() => { if (model.open) refreshModel(false); }, 2000);

  /* ---------- Voice health ---------- */
  const health = dialog('healthDialog', 'Voice health', 'Live diagnostics from the assistant. No transcripts or audio are shown.', true);
  const healthList = make('dl', null, 'kv'), meter = make('meter'); meter.min = 0; meter.max = 1;
  health.body.append(healthList, make('label', 'Microphone input level'), meter,
    make('p', 'Device activity does not prove speech can be recognized. AI status reflects the last request only.', 'muted'));
  const REC = { none: 'No phrase yet', voice_not_matched: 'Voice not matched', recognized: 'Speech recognized', no_speech: 'No usable speech', recognition_error: 'Recognition failed', wake_word_required: 'Wake word required', accepted: 'Command accepted', interruption_rejected: 'Interruption not accepted' };
  const AI = { not_checked: 'Not checked', requesting: 'Request in progress', responded: 'Last request responded', interrupted: 'Last request interrupted', error: 'Last request failed' };
  function renderHealth() {
    const h = J.health, yes = v => v ? 'Active' : 'Inactive';
    const rows = !h ? [['Assistant', J.online ? 'Connected; diagnostics unavailable' : 'Offline']] : [
      ['Startup', h.startup], ['Microphone', h.microphone || 'Unknown'],
      ['Mic stream / input / processing', [h.microphone_active, h.microphone_receiving, h.processing].map(yes).join(' / ')],
      ['Command listener', h.listener_alive ? 'Running' : 'Not running'], ['Output device', h.output || 'Windows default'],
      ['Output stream', yes(h.output_active)], ['Listening mode', h.listening_mode],
      ['Voice lock', h.voice_lock === true ? 'Enabled' : h.voice_lock === false ? 'Disabled' : 'Unknown'],
      ['AI service', AI[h.ai_service] || 'Unknown'],
      ['Recent recognition', h.recognition ? (REC[h.recognition.reason] || h.recognition.reason) + (h.recognition.at ? ' at ' + new Date(h.recognition.at * 1000).toLocaleTimeString() : '') : 'Unknown'],
      ['Playback error this session', h.output_error ? 'Yes — playback or synthesis failed' : 'None reported']];
    healthList.replaceChildren(...rows.flatMap(([k, v]) => [make('dt', k), make('dd', String(v))]));
    meter.value = h?.input_level || 0;
  }
  J.on('status', () => { if (health.open) renderHealth(); });

  /* ---------- Reader ---------- */
  const reader = dialog('readerDialog', '', '', false);
  const readerPath = make('div', null, 'reader-path'), readerBody = make('div', null, 'reader-body'), readerActions = make('div', null, 'actions');
  reader.body.append(readerPath, readerBody, readerActions);
  J.on('read', n => {
    reader.head.textContent = n.label; readerPath.textContent = n.source || n.group; readerBody.textContent = n.body || '';
    readerActions.replaceChildren();
    const ask = make('button', 'Ask JARVIS about this'); ask.type = 'button';
    ask.onclick = () => { reader.close(); J.prepare(n.source ? `Read my note "${n.source}" and ` : `About "${n.label}": `); };
    readerActions.append(ask);
    if (n.uri && /^obsidian:/.test(n.uri)) { const a = make('a', 'Open in Obsidian ↗'); a.href = n.uri; a.style.marginLeft = '12px'; readerActions.append(a); }
    reader.showModal();
  });

  /* ---------- Workspace ---------- */
  const workspace = dialog('workspaceDialog', 'Workspace', 'Your JARVIS folders. Click to open in File Explorer.');
  const wsGrid = make('div', null, 'grid'), wsNote = make('p', '', 'muted'); workspace.body.append(wsGrid, wsNote);
  async function showWorkspace() {
    workspace.showModal(); wsNote.textContent = '';
    try {
      const data = await J.api('/workspace');
      wsGrid.replaceChildren(...data.folders.map((f, i) => {
        const t = tile({ icon: String(i).padStart(2, '0'), name: f.name, text: f.description, chip: f.available ? '' : 'missing', chipClass: 'bad',
          onClick: async () => { try { await J.api('/workspace/open', { id: f.id }); wsNote.textContent = 'Opened ' + f.name + '.'; } catch (e) { wsNote.textContent = e.message; } } });
        t.disabled = !f.available; return t;
      }));
    } catch (e) { wsNote.textContent = e.message; }
  }

  /* ---------- Next steps (build plan) ---------- */
  const plan = dialog('planDialog', 'Next steps', 'The current build brief for JARVIS. Prepare fills the command bar; nothing starts until you send it.');
  const planText = make('pre', '', 'plan'), prepare = make('button', 'Prepare build task', 'primary'); prepare.type = 'button';
  plan.body.append(planText, prepare);
  prepare.onclick = () => { plan.close(); J.prepare('Open a Codex agent session named Jarvis Builder in the Jarvis project, then have Jarvis Builder implement the task in docs/plans/NIGHT-BUILD-PROMPT.txt in work mode. Start only that task.'); };
  async function showPlan() { plan.showModal(); try { planText.textContent = (await J.api('/build-plan')).text || 'No build brief saved.'; } catch (e) { planText.textContent = e.message; } }

  /* ---------- More menu ---------- */
  const menu = el('moreMenu');
  const items = [
    ['Voice health', () => { health.showModal(); renderHealth(); }], ['Change model…', () => J.emit('open-model')],
    ['Workspace folders', showWorkspace], ['Next steps', showPlan], null,
    ['Keyboard: / search · F fit · Esc clear', null],
  ];
  for (const item of items) {
    if (!item) { menu.append(make('hr')); continue; }
    const b = make('button', item[0]); b.type = 'button'; b.setAttribute('role', 'menuitem');
    if (item[1]) b.onclick = () => { menu.hidden = true; item[1](); }; else b.disabled = true;
    menu.append(b);
  }
  el('moreBtn').onclick = e => {
    e.stopPropagation(); menu.hidden = !menu.hidden;
    const r = el('moreBtn').getBoundingClientRect();
    menu.style.left = Math.min(r.left, innerWidth - 210) + 'px'; menu.style.bottom = (innerHeight - r.top + 8) + 'px';
  };
  document.addEventListener('click', e => { if (!menu.hidden && !menu.contains(e.target)) menu.hidden = true; });
})();
