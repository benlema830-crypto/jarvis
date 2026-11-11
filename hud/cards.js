/* Cards: the few things that want you, each with its answer one click away. They show in both views:
   beside the 3D model, and at the top of the Console's side rail.

     ask    Jarvis is waiting for a yes or no        Yes · No · Read it
     held   updates he kept back while you were out  Hear them
     job    an away job that finished                What changed? · Hear the summary · Dismiss
     agent  an agent session that finished           Hear the report · Dismiss

   Yes and No send your own word, exactly as if you had typed it; nothing here approves anything by itself.
   A job's proof line is the test result Jarvis re-ran, kept apart from what the agent says about its work.
   Everything is drawn with textContent. Dismissing only hides a card on this PC; nothing is deleted. */
'use strict';
(() => {
  const el = id => document.getElementById(id);
  const stack = el('cards');
  const state = { question: '', held: [], jobs: [], sessions: [], answered: '' };
  let dismissed = store.get('dismissedCards', []), showAll = false;
  const RECENT_HOURS = 18, SHOWN = 3;
  const short = (text, n) => { const s = String(text ?? '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
  const hide = id => { dismissed = [...dismissed.filter(d => d !== id), id].slice(-200); store.set('dismissedCards', dismissed); render(); };

  function button(label, action, cls) {
    const b = make('button', label, cls); b.type = 'button';
    b.onclick = async () => { b.disabled = true; try { await action(); } finally { b.disabled = false; } };
    return b;
  }
  function card(id, kind, kicker, title, body, proof, actions) {
    const box = make('article', null, 'card-item ' + kind); box.dataset.card = id;
    box.append(make('small', kicker, 'card-kicker'), make('h3', title));
    if (body) box.append(make('p', body, 'card-body'));
    if (proof) box.append(make('p', proof[0], 'card-proof ' + proof[1]));
    const row = make('div', null, 'card-actions'); row.append(...actions); box.append(row);
    return box;
  }

  function build() {
    const cards = [];
    if (state.question && state.question !== state.answered) {
      const q = state.question, long = q.length > 180;
      const text = make('p', long ? short(q, 180) : q, 'card-body');
      const item = card('ask', 'ask', 'Needs a yes or no', long ? 'Jarvis is asking to go ahead.' : q, '', null, [
        button('Yes', () => { state.answered = q; render(); return J.send('yes'); }, 'primary'),
        button('No', () => { state.answered = q; render(); return J.send('no'); }),
        ...(long ? [button('Read it', () => { text.textContent = q; text.classList.add('open'); })] : []),
      ]);
      if (long) item.querySelector('h3').after(text);
      cards.push(item);
    }
    if (state.held.length) {
      const n = state.held.length;
      cards.push(card('held', 'held', 'Held for later', `${n} update${n === 1 ? '' : 's'} came in while you were away or busy.`,
        state.held.slice(-4).map(h => h.label).join(' · '), null, [button('Hear them', () => J.send('What did I miss?'), 'primary')]));
    }
    for (const j of state.jobs) {
      const id = 'job:' + j.id;
      if (!['done', 'partial', 'blocked', 'failed'].includes(j.status) || dismissed.includes(id)) continue;
      const good = j.status === 'done';
      cards.push(card(id, 'job ' + j.status, `${j.label} · away ${j.kind}`, short(j.what, 120), j.branch ? 'Waiting on branch ' + j.branch + '. Nothing was merged.' : '',
        j.check ? [(good ? '✓ ' : '! ') + j.check, good ? 'ok' : 'warn'] : ['? Jarvis has no check of his own for this one.', 'warn'], [
          ...(j.branch ? [button('What changed?', () => J.send(`Summarize what changed on the branch ${j.branch} compared to main. Look at the diff yourself.`), 'primary')] : []),
          button('Hear the summary', () => J.send(`Tell me about away job ${j.id}: what was done, and what you checked yourself.`), j.branch ? '' : 'primary'),
          button('Dismiss', () => hide(id), 'quiet'),
        ]));
    }
    for (const s of state.sessions) {
      const when = s.updated_at || 0, id = `agent:${s.name}:${Math.round(when)}`;
      if (!['completed', 'failed'].includes(s.status) || !s.report || Date.now() / 1000 - when > RECENT_HOURS * 3600 || dismissed.includes(id)) continue;
      const good = s.status === 'completed';
      cards.push(card(id, 'agent ' + (good ? 'done' : 'failed'), good ? 'Agent finished' : "Agent didn't finish", String(s.name || 'Agent'),
        'It reports: ' + short(s.report, 170), ['This is the agent’s own account, not something Jarvis checked.', 'note'], [
          button('Hear the report', () => J.send(`What did the ${s.name} agent report? Say what it claims and what you can confirm.`), 'primary'),
          button('Dismiss', () => hide(id), 'quiet'),
        ]));
    }
    return cards;
  }

  function render() {
    const cards = build(), shown = showAll ? cards : cards.slice(0, SHOWN);
    stack.replaceChildren(...shown);
    if (cards.length > shown.length) stack.append(button(`${cards.length - shown.length} more`, () => { showAll = true; render(); }, 'link more'));
    else if (showAll && cards.length > SHOWN) stack.append(button('show fewer', () => { showAll = false; render(); }, 'link more'));
    stack.hidden = !cards.length;
    el('viewConsole').classList.toggle('alert', !!state.question && state.question !== state.answered);
    J.emit('cards', cards.length);
  }

  /* ---------- Keeping up to date ---------- */
  const live = () => !document.hidden && J.online !== false && !document.body.classList.contains('compact-orb');
  async function pollAttention() {
    if (!live()) return;
    try {
      const data = await J.api('/attention', undefined, { timeout: 4000 });
      state.question = String(data.question || ''); state.held = Array.isArray(data.held) ? data.held : [];
      if (!state.question) state.answered = '';
      render();
    } catch {}
  }
  async function pollWork() {
    if (!live()) return;
    try { state.jobs = (await J.api('/jobs', undefined, { timeout: 5000 })).jobs || []; } catch {}
    try { state.sessions = (await J.api('/sessions', undefined, { timeout: 5000 })).sessions || []; } catch {}
    render();
  }
  J.on('event', ev => {
    if (ev.replay) return;
    const text = ev.type === 'event' ? String(ev.text || '') : '';
    if (text.startsWith('Approval needed: ') || text.startsWith('Held for later: ')) pollAttention();
    else if (/ (finished|didn't finish|got blocked|didn't work|only partly finished)$/.test(text) || text === 'Away work') pollWork();
    else if (ev.type === 'you') setTimeout(pollAttention, 600);  // an answer just went in
  });
  setInterval(pollAttention, 3000); setInterval(pollWork, 15000);
  document.addEventListener('visibilitychange', () => { pollAttention(); pollWork(); });

  /* ---------- One stack, two homes: beside the model, or at the top of the Console's rail ---------- */
  const home = stack.parentElement, rail = document.querySelector('.console-rail');
  J.on('view', name => { if (name === 'console') rail.prepend(stack); else home.insertBefore(stack, el('console')); });
  if (document.body.classList.contains('view-console')) rail.prepend(stack);
  J.cards = { state, render, poll() { return Promise.all([pollAttention(), pollWork()]); } };
  render(); pollAttention(); pollWork();
})();
