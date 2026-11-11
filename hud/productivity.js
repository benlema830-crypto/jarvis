/* Project memory, handoffs and vault search. Opening the panel changes nothing. */
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
  for (const name of ['Jarvis', 'Rocket Frontier', "Don't Wake the Giant", 'KnightShow']) project.append(make('option', name));
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
  d.append(output);
  J.menuItem('projects', 'Project memory & search', () => d.showModal(), 'projectToolsBtn');
})();
