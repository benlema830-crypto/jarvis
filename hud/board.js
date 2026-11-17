/* The agent board. Reads /agents (agent_board.py) and the live event stream; it shows, it never controls.
   Everything an agent wrote goes in as text, never as markup. */
(() => {
  const $ = id => document.getElementById(id);
  const make = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
  const STATE_WORDS = { listening: 'Jarvis is listening', standby: 'Jarvis is standing by', thinking: 'Jarvis is thinking',
    speaking: 'Jarvis is speaking', offline: 'Jarvis is offline', connecting: 'Connecting to Jarvis', lost: "Can't reach Jarvis. Trying again." };
  const STATUS_WORDS = { running: 'Working', waiting: 'Waiting', paused: 'Paused', interrupted: 'Interrupted by a restart',
    completed: 'Finished', failed: "Didn't finish", ready: 'Ready', idle: 'Idle' };
  const MODE_WORDS = { research: 'Looks only', work: 'Changes files' };
  const LEAD_WORDS = {
    planning: () => 'Planning the split. The agents start when its plan is ready.',
    working: job => `Waiting for round ${job.round}'s agents. It checks their reports next.`,
    merging: () => 'Reading the reports. It either sends agents out again or writes the answer.' };
  const QUIET_AFTER = 120;  // seconds without a new step before a working agent is called quiet

  // Inside the phone app (phone_bridge.py marks the page) the phone key goes with each request, as in the chat page.
  const PHONE = 'phone' in document.body.dataset;
  let key = ''; if (PHONE) { try { key = localStorage.getItem('jarvis-key') || ''; } catch (error) { /* no key */ } }
  const get = path => fetch(path, { cache: 'no-store', headers: key ? { Authorization: 'Bearer ' + key } : {} });
  const signIn = () => location.replace(PHONE ? '/' : '/login');  // the chat page asks for the phone key

  let board = null, fetchedAt = 0, timer = 0;
  const open = new Set();   // which "brief" / report folds the reader opened, kept across refreshes

  // The server's clock, carried forward: the laptop's own clock may be minutes off.
  const serverNow = () => board ? board.now + (performance.now() - fetchedAt) / 1000 : Date.now() / 1000;

  function span(seconds) {  // 75 -> 1:15, 3700 -> 1:01:40
    seconds = Math.max(0, Math.floor(seconds));
    const h = Math.floor(seconds / 3600), m = Math.floor(seconds % 3600 / 60), s = String(seconds % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
  }
  function ago(seconds) {
    seconds = Math.max(0, seconds);
    if (seconds < 60) return `${Math.floor(seconds)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
    return `${Math.floor(seconds / 86400)} d`;
  }
  const letter = name => name.replace(/^Parallel\s+/, '');

  function mark(status) {
    const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 18 18'); svg.setAttribute('class', 'mark'); svg.dataset.status = status;
    svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', STATUS_WORDS[status] || status);
    const shapes = {
      running: '<circle class="halo" cx="9" cy="9" r="7.5" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="9" cy="9" r="3.5" fill="currentColor"/>',
      completed: '<path d="M3.5 9.5l3.6 3.6 7.4-8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
      failed: '<path d="M4.5 4.5l9 9m0-9l-9 9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
      paused: '<path d="M6.5 4v10m5-10v10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
      waiting: '<circle cx="9" cy="9" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 5v4.5l2.8 1.8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    };
    svg.innerHTML = shapes[status] || shapes[status === 'interrupted' ? 'paused' : ''] || '<circle cx="9" cy="9" r="6" fill="none" stroke="currentColor" stroke-width="2"/>';
    return svg;
  }

  function fold(key, label, text) {  // a closed-by-default "show me more" that stays as the reader left it
    const details = make('details'), summary = make('summary', label);
    details.open = open.has(key);
    details.addEventListener('toggle', () => details.open ? open.add(key) : open.delete(key));
    details.append(summary, make('p', text));
    return details;
  }

  function card(agent) {
    const el = make('article', null, 'agent');
    el.dataset.live = agent.live; el.dataset.name = agent.name;
    const head = make('header'), clock = make('span', span(agent.seconds), 'clock num');
    if (agent.live) clock.dataset.since = agent.seconds;
    clock.title = agent.live ? 'Time working' : 'Time it took';
    head.append(mark(agent.status), make('h3', agent.name), clock);
    const meta = [agent.model, MODE_WORDS[agent.mode], agent.folder].filter(Boolean).join(' · ');
    el.append(head, make('p', meta, 'meta'));
    el.append(make('p', agent.doing || (agent.live ? 'Starting' : STATUS_WORDS[agent.status] || agent.status), 'doing'));
    if (agent.live && agent.quiet > QUIET_AFTER)
      el.append(make('p', `No new step for ${ago(agent.quiet)}. It may be on one long command.`, 'quiet'));
    if (agent.live && agent.steps.length) {
      const steps = make('ol', null, 'steps'); steps.setAttribute('aria-label', 'Latest steps');
      for (const step of agent.steps) {
        const row = make('li'), when = make('time', step.at ? ago(serverNow() - step.at) : '');
        row.dataset.state = step.state; row.append(make('span', step.text), when); row.title = step.text;
        steps.append(row);
      }
      el.append(steps);
    }
    if (!agent.live && agent.report && agent.report !== agent.doing) el.append(fold('report:' + agent.name, 'Its report', agent.report));
    if (agent.task) el.append(fold('brief:' + agent.name, 'Its brief', agent.task));
    const foot = [agent.evidence, agent.files ? `${agent.files} file${agent.files === 1 ? '' : 's'} changed` : ''].filter(Boolean).join(' ');
    if (foot) el.append(make('p', foot, 'foot'));
    return el;
  }

  function leadBar(agent, job) {
    const bar = $('lead');
    bar.replaceChildren();
    const running = agent && agent.live, phase = job.lead.phase;
    bar.append(mark(running ? 'running' : phase === 'working' ? 'waiting' : agent ? agent.status : 'waiting'),
      make('span', 'Lead', 'who'), make('span', job.lead.model, 'model'),
      make('span', (LEAD_WORDS[phase] || (() => ''))(job), 'saying'));
    if (running) { const clock = make('span', span(agent.seconds), 'clock num'); clock.dataset.since = agent.seconds; bar.append(clock); }
    bar.hidden = false;
  }

  function stages(job) {
    const list = $('stages');
    list.replaceChildren();
    let round = 0;
    for (const stage of job.stages) {
      const item = make('li', stage.label, 'stage');
      item.dataset.state = stage.state;
      if (stage.state === 'now') item.setAttribute('aria-current', 'step');
      if (/^(Round|Agents)/.test(stage.label)) {  // each agent of that round, coloured by how it ended
        const parts = (job.rounds[round++] || {}).parts || [];
        if (parts.length) {
          const small = make('small');
          for (const part of parts) {
            const tag = make('span', letter(part.name));
            tag.dataset.outcome = part.outcome; tag.title = `${part.name}: ${part.outcome || 'working'}`;
            small.append(tag);
          }
          item.append(small);
        }
      }
      list.append(item);
    }
  }

  function earlierRow(agent) {
    const item = make('li'), details = make('details'), summary = make('summary');
    const key = 'earlier:' + agent.name;
    details.open = open.has(key);
    details.addEventListener('toggle', () => details.open ? open.add(key) : open.delete(key));
    const when = agent.updated_at ? `${ago(serverNow() - agent.updated_at)} ago` + (agent.seconds ? ` · took ${span(agent.seconds)}` : '') : '';
    summary.append(mark(agent.status), make('span', agent.name, 'name'),
      make('span', agent.doing || STATUS_WORDS[agent.status] || agent.status, 'line'), make('span', when, 'when num'));
    const more = make('div', null, 'more');
    const meta = [agent.model, MODE_WORDS[agent.mode], agent.project, agent.evidence].filter(Boolean).join(' · ');
    if (meta) more.append(make('p', meta, 'label'));
    if (agent.report || agent.doing) more.append(make('p', agent.report || agent.doing));
    if (agent.task) { const brief = make('p'); brief.append(make('span', 'Its brief: ', 'label'), agent.task); more.append(brief); }
    details.append(summary, more); item.append(details);
    return item;
  }

  function render() {
    const { job, agents, counts } = board;
    const inJob = agents.filter(a => a.role !== 'solo'), solo = agents.filter(a => a.role === 'solo');
    const working = solo.filter(a => a.live), earlier = solo.filter(a => !a.live);

    $('headset').hidden = PHONE || !(board.room && board.room.headset);  // it is about the laptop's microphone
    const tally = $('tally'); tally.replaceChildren();
    if (counts.working) {
      tally.append(make('b', String(counts.working)), ` agent${counts.working === 1 ? '' : 's'} working`);
      if (job) tally.append(` · round ${job.round} of at most ${job.max_rounds}`);
    } else tally.append(job ? 'Between rounds' : 'No agents working');

    $('job').hidden = !job;
    if (job) {
      $('jobGoal').textContent = job.goal;
      const facts = $('jobFacts'), clock = make('span', span(job.seconds), 'num'); clock.dataset.since = job.seconds;
      facts.replaceChildren(MODE_WORDS[job.mode] ? MODE_WORDS[job.mode] + ' · ' : '', clock);
      stages(job);
      $('jobNote').textContent = job.note; $('jobNote').hidden = !job.note;
      if (job.lead) leadBar(inJob.find(a => a.role === 'lead'), job); else $('lead').hidden = true;
      $('jobCards').replaceChildren(...inJob.filter(a => a.role === 'part').map(card));
    }
    $('soloSection').hidden = !working.length;
    $('soloTitle').textContent = job ? 'Also working' : 'Working now';
    $('soloCards').replaceChildren(...working.map(card));
    $('idle').hidden = !!job || working.length > 0;
    $('earlierSection').hidden = !earlier.length;
    $('earlier').replaceChildren(...earlier.map(earlierRow));
    // One beat for every pulsing mark, so a refresh doesn't restart them out of step
    document.documentElement.style.setProperty('--beat', `-${Date.now() % 1600}ms`);
  }

  function tick() {
    const now = new Date();
    $('clock').textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    $('clock').dateTime = now.toISOString();
    if (!board) return;
    const passed = (performance.now() - fetchedAt) / 1000;
    for (const clock of document.querySelectorAll('[data-since]')) clock.textContent = span(Number(clock.dataset.since) + passed);
  }

  async function refresh() {
    clearTimeout(timer);
    try {
      const response = await get('/agents');
      if (response.status === 401) return signIn();  // the key went: sign in again
      if (!response.ok) throw new Error(response.status);
      board = await response.json(); fetchedAt = performance.now();
      if (document.body.dataset.state === 'lost') setState(lastState);
      render();
    } catch (error) {
      setState('lost', true);
    }
    timer = setTimeout(refresh, board && (board.job || board.counts.working) ? 3000 : 10000);
  }

  async function queue() {
    try {
      const data = await (await get('/jobs')).json(), jobs = (data.jobs || []).slice(0, 5);
      $('queueSection').hidden = !jobs.length;
      $('queue').replaceChildren(...jobs.map(job => { const li = make('li'); li.append(make('b', job.label), make('span', job.what)); return li; }));
    } catch (error) { /* the board works without it */ }
  }

  /* ---------- Jarvis, live ---------- */
  let lastState = 'connecting';
  function setState(state, passing) {
    if (!passing) lastState = state;
    document.body.dataset.state = state;
    $('jarvisWords').textContent = STATE_WORDS[state] || 'Jarvis: ' + state;
  }
  function feedLine(event, fresh) {
    const words = event.type === 'tool' ? 'Using ' + String(event.name || 'a tool').replace(/_/g, ' ')
      : event.type === 'you' ? 'You: ' + event.text : event.text;
    if (!words || !['you', 'jarvis', 'event', 'tool', 'error'].includes(event.type)) return;
    const row = make('li', null, fresh ? 'new' : ''), when = make('time', new Date(event.t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).replace(/\s?[AP]M$/i, ''));
    row.dataset.kind = event.type; row.append(when, make('p', String(words).slice(0, 600)));
    const feed = $('feed');
    feed.prepend(row);
    while (feed.children.length > 60) feed.lastChild.remove();
    $('feedEmpty').hidden = true;
  }
  function onEvent(data) {
    let event; try { event = JSON.parse(data); } catch (error) { return; }
    if (event.type === 'hello') {
      setState(event.state || 'standby'); $('feed').replaceChildren();
      for (const past of (event.history || []).slice(-40)) feedLine(past, false);
      refresh();
    } else if (event.type === 'state') setState(event.state);
    else if (event.type === 'sessions') { clearTimeout(timer); timer = setTimeout(refresh, 250); }
    else feedLine(event, true);
  }
  function listen() {
    const stream = new EventSource('/events');
    stream.onmessage = message => onEvent(message.data);
    stream.onerror = () => setState('lost', true);  // EventSource reconnects by itself
  }
  // An EventSource can't carry the phone key, so the phone app reads the same stream itself and reconnects itself.
  async function listenWithKey() {
    for (;;) {
      try {
        const response = await get('/events');
        if (response.status === 401) return signIn();
        if (!response.ok || !response.body) throw new Error(response.status);
        const reader = response.body.getReader(), decoder = new TextDecoder();
        let text = '';
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          text += decoder.decode(value, { stream: true });
          const blocks = text.split('\n\n'); text = blocks.pop();
          for (const block of blocks) for (const line of block.split('\n')) if (line.startsWith('data: ')) onEvent(line.slice(6));
        }
      } catch (error) { /* the phone slept or the PC went away: try again below */ }
      setState('lost', true);
      await new Promise(done => setTimeout(done, 3000));
    }
  }

  if (PHONE) {
    const back = document.querySelector('.quiet-link'); back.textContent = 'Chat'; back.setAttribute('aria-label', 'Back to the chat');
    if (!key) return signIn();
  }
  tick(); setInterval(tick, 1000);
  refresh(); queue(); setInterval(queue, 30000);
  if (PHONE) listenWithKey(); else listen();
})();
