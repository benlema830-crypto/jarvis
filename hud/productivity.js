/* Local project tools. Reading a panel never runs a routine. */
'use strict';
(() => {
  const d = make('dialog'); d.id = 'projectToolsDialog';
  const head = make('div', null, 'dialog-head'), close = make('button', 'Close');
  close.onclick = () => d.close(); head.append(make('h2', 'Project tools'), close); d.append(head);
  document.body.append(d);
  const button = (label, fn) => { const b = make('button', label); b.type = 'button'; b.onclick = async () => {
    b.disabled = true; try { await fn(); } catch (e) { output.textContent = e.message; } finally { b.disabled = false; }
  }; return b; };
  const output = make('pre'); output.id = 'projectToolResult'; output.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere;max-height:45vh;overflow:auto';
  const project = make('select'); project.setAttribute('aria-label', 'Project');
  for (const name of ['Jarvis', 'Rocket Frontier']) project.append(make('option', name));
  const post = (path, body) => J.api(path, body, {timeout: path === '/knowledge-search' ? 180000 : 60000});
  function projectText(data) {
    let text = `${data.project} · checked ${data.checked_at || data.created_at}\n`;
    if (data.claims) text += Object.entries(data.claims).filter(([,v]) => v).map(([k,v]) => `${k.replaceAll('_',' ')}: ${v}`).join('\n') + '\n';
    const evidence = data.evidence || data;
    for (const item of evidence.verified || []) text += `\n${item.source}\n${item.text || 'Clean working tree.'}\n`;
    if (data.last_handoff) text += '\nLast handoff\n' + projectText(data.last_handoff);
    for (const note of evidence.reference_notes || []) text += `\nReference: ${note.source} · ${new Date(note.modified*1000).toLocaleString()}\n${note.text}\n`;
    for (const report of evidence.agent_reports || []) text += `\nAgent report (not independently verified): ${report.name}\n${report.report}\n`;
    return text + '\n' + (evidence.interpretation || '');
  }
  const show = data => { output.textContent = typeof data === 'string' ? data : data.project && (data.verified || data.evidence) ? projectText(data) : JSON.stringify(data, null, 2); };
  d.append(make('h3', 'Project memory'), project, button('Where did we leave off?', async () => show(await post('/project-memory', {project: project.value}))));
  const fields = {};
  for (const [key, label] of [['summary', 'Progress this session'], ['unresolved', 'Unresolved problems'], ['next_action', 'Next action'], ['files', 'Relevant files']]) {
    const input = make('textarea'); input.placeholder = label; input.setAttribute('aria-label', label); input.maxLength = 6000;
    input.style.cssText = 'display:block;width:100%;margin:6px 0'; fields[key] = input; d.append(input);
  }
  d.append(button('Save handoff', async () => {
    show(await post('/project-memory', {action:'handoff', project: project.value, ...Object.fromEntries(Object.entries(fields).map(([k,v]) => [k,v.value]))}));
  }));
  const query = make('input'); query.placeholder = 'Find notes by meaning…'; query.maxLength = 2000; query.setAttribute('aria-label', 'Search vault by meaning');
  d.append(make('h3', 'Vault search'), query, button('Search notes', async () => {
    show('Searching local notes…'); const data = await post('/knowledge-search', {query:query.value});
    output.replaceChildren(make('p', ['hybrid', 'semantic'].includes(data.mode) ? 'Meaning + exact words · local embeddings' : 'Keyword only · local embeddings unavailable'));
    for (const note of data.results) {
      const link = make('a', note.path); if (note.uri.startsWith('obsidian://')) link.href = note.uri;
      output.append(link, make('p', note.excerpt));
    }
  }));
  const select = make('select'); select.id = 'routineSelect'; select.setAttribute('aria-label', 'Named routine');
  const name = make('input'); name.placeholder = 'Routine name'; name.setAttribute('aria-label', 'Routine name'); name.maxLength = 60;
  const routineProject = make('select'); routineProject.setAttribute('aria-label', 'Routine project');
  for (const value of ['Jarvis', 'Rocket Frontier']) routineProject.append(make('option', value));
  const editor = make('div'); editor.setAttribute('aria-label', 'Routine steps');
  const labels = {open_project:'Open project folder', project_status:'Read project status', tasks:'Show unfinished tasks', focus:'Start Focus', handoff:'Save session handoff'};
  let draftSteps = [];
  function renderSteps() {
    editor.replaceChildren();
    draftSteps.forEach((step, i) => {
      const row = make('div'); row.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;margin:8px 0;align-items:center';
      const action = make('select'); action.setAttribute('aria-label', `Step ${i+1}`);
      for (const [value,label] of Object.entries(labels)) { const option = make('option',label); option.value=value; action.append(option); }
      action.value = step.action;
      action.onchange = () => { invalidate(); draftSteps[i] = action.value === 'focus' ? {action:'focus',app:'Code.exe',minutes:30} : {action:action.value}; renderSteps(); };
      row.append(make('span',`${i+1}.`), action);
      if (step.action === 'focus') {
        const app = make('input'); app.value = step.app; app.placeholder = 'Code.exe'; app.setAttribute('aria-label','Focus app'); app.style.width = '180px';
        const minutes = make('input'); minutes.type='number'; minutes.min=1; minutes.max=120; minutes.value=step.minutes; minutes.style.width='65px'; minutes.setAttribute('aria-label','Focus minutes');
        app.oninput = () => { invalidate(); step.app=app.value; }; minutes.oninput = () => { invalidate(); step.minutes=Number(minutes.value); };
        row.append(app,minutes,make('span','minutes'));
      }
      const up = button('↑', async () => { if (i) { invalidate(); [draftSteps[i-1],draftSteps[i]]=[draftSteps[i],draftSteps[i-1]]; renderSteps(); } }); up.setAttribute('aria-label',`Move step ${i+1} up`);
      row.append(up,button('Remove',async () => { invalidate(); draftSteps.splice(i,1); renderSteps(); })); editor.append(row);
    });
  }
  let definitions = {}, review = null;
  const approve = button('Approve and run once', async () => {
    if (!review) return;
    const token = review.token; review = null; approve.hidden = true;
    show(await post('/routines', {action:'run',token}));
  }); approve.hidden = true;
  const invalidate = () => { review = null; approve.hidden = true; };
  const choose = () => { invalidate(); name.value = select.value; routineProject.value = definitions[select.value].project; draftSteps=structuredClone(definitions[select.value].steps); renderSteps(); };
  select.onchange = choose; routineProject.onchange = invalidate; name.oninput = invalidate;
  async function load() {
    definitions = (await J.api('/routines')).routines; select.replaceChildren();
    for (const key of Object.keys(definitions)) select.append(make('option', key)); choose();
  }
  d.addEventListener('close', invalidate);
  d.append(make('h3', 'Named routines'), make('p', 'Choose a routine, adjust its steps, and save. Review the saved steps before each run. Change the name to save a new routine.'), select, name, routineProject, editor,
    button('Add step',async () => { invalidate(); if (draftSteps.length<8) { draftSteps.push({action:'tasks'}); renderSteps(); } }),
    button('Save routine', async () => { invalidate(); const savedName=name.value; show(await post('/routines', {action:'save', name:savedName, definition:{project:routineProject.value,steps:draftSteps}})); await load(); select.value=savedName; choose(); }),
    button('Review saved steps', async () => {
      invalidate(); review = await post('/routines', {action:'preview',name:select.value});
      show(`${review.name} — ${review.project}\n\n${review.descriptions.map((s,i) => `${i+1}. ${s}`).join('\n')}\n\n${review.notice}`);
      approve.hidden = false;
    }), approve, button('Stop routine', async () => { invalidate(); show(await post('/routines',{action:'cancel'})); }), output);
  const menu = document.getElementById('moreMenu');
  const entry = button('Project tools', async () => { menu.hidden = true; d.showModal(); await load(); });
  entry.id = 'projectToolsBtn'; entry.setAttribute('role','menuitem'); menu.prepend(entry);
})();
