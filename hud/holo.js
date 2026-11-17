/* JARVIS hologram: the sphere and what surrounds it. Builds on the J object from brain.js.
   - Sphere: the hollow hologram shell drawn by shell-orb.js. This file places it, feeds it what he is doing,
     and lets it be grabbed and spun (mouse or HOLO hand tracking) when he is the main view.
   - Thought beams: when he reads vault notes, beams run from the sphere to those notes in the graph.
   - Main view only: status gauges (CPU/GPU/memory/network). Nothing else floats around him.
   - Holographic replies, a boot sequence and colour themes.
   All remote text is rendered with textContent; nothing here uses innerHTML. */
'use strict';
(() => {
const $ = id => document.getElementById(id);
const make = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
const store = {
  get(key, fallback) { try { const v = JSON.parse(localStorage.getItem('jarvis.' + key)); return v ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem('jarvis.' + key, JSON.stringify(value)); } catch {} },
};
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const clamp01 = v => Math.max(0, Math.min(1, v));
const ease = v => 1 - (1 - v) ** 3;
const px = (size, minimum) => Math.max(size, minimum * (J.view.dpr || 1));  // canvas text never smaller than `minimum` CSS px
function hex(color, alpha) { return color + Math.round(clamp01(alpha) * 255).toString(16).padStart(2, '0'); }

/* ---------- Colour themes ---------- */
const THEMES = {
  violet: { label: 'Holographic violet', swatch: '#b18aff',
    states: { standby: '#8938ff', listening: '#a05aff', speaking: '#b178ff', thinking: '#7025ef' },
    links: { note: '#b18aff', folder: '#8870ad', noteSpark: '#e4d5ff', folderSpark: '#bba0ef' } },
  cyan: { label: 'Classic cyan', swatch: '#5eead4',
    states: { standby: '#5eead4', listening: '#22d3ee', speaking: '#7dd3fc', thinking: '#f5b83d' },
    links: { note: '#5eead4', folder: '#6fb3a6', noteSpark: '#a7f3e4', folderSpark: '#7fd8c8' } },
  mark42: { label: 'Mark 42 red and gold', swatch: '#f59e0b',
    states: { standby: '#f59e0b', listening: '#fcd34d', speaking: '#fb7185', thinking: '#ef4444' },
    links: { note: '#f59e0b', folder: '#b45309', noteSpark: '#fde68a', folderSpark: '#fb923c' } },
  stealth: { label: 'Stealth white', swatch: '#e2e8f0',
    states: { standby: '#cbd5e1', listening: '#f8fafc', speaking: '#e2e8f0', thinking: '#94a3b8' },
    links: { note: '#cbd5e1', folder: '#64748b', noteSpark: '#f8fafc', folderSpark: '#cbd5e1' } },
  emerald: { label: 'Emerald', swatch: '#34d399',
    states: { standby: '#34d399', listening: '#6ee7b7', speaking: '#a7f3d0', thinking: '#fbbf24' },
    links: { note: '#34d399', folder: '#059669', noteSpark: '#a7f3d0', folderSpark: '#6ee7b7' } },
};
const themeRow = make('div', null, 'themes'); themeRow.setAttribute('role', 'group'); themeRow.setAttribute('aria-label', 'Colour theme');
for (const [name, def] of Object.entries(THEMES)) {
  const b = make('button'); b.type = 'button'; b.dataset.theme = name; b.title = def.label; b.setAttribute('aria-label', def.label);
  b.style.setProperty('--swatch', def.swatch); b.onclick = () => setTheme(name);
  themeRow.append(b);
}
document.querySelector('.appearance').after(themeRow);
const graphicsRow = make('label', 'Quality ', 'graphics-quality'), graphicsChoice = make('select');
graphicsChoice.setAttribute('aria-label', 'Graphics quality');
for (const [value,label] of [['auto','Automatic'],['cinematic','Cinematic'],['balanced','Balanced'],['economy','Economy']]) {
  const option=make('option',label);option.value=value;graphicsChoice.append(option);
}
graphicsChoice.value=J.graphics.quality;graphicsChoice.onchange=()=>J.graphics.setQuality(graphicsChoice.value);
graphicsRow.append(graphicsChoice);themeRow.after(graphicsRow);
let theme = 'cyan';
function setTheme(name) {
  theme = THEMES[name] ? name : 'cyan';
  Object.assign(J.stateColors, THEMES[theme].states); Object.assign(J.linkColors, THEMES[theme].links);
  document.body.dataset.theme = theme; store.set('theme', theme);
  for (const b of themeRow.children) { b.classList.toggle('on', b.dataset.theme === theme); b.setAttribute('aria-pressed', b.dataset.theme === theme); }
}
// The shell orb replaced the three older sphere models on 2026-11-16. It starts in cyan once; colour choices after that persist.
if (store.get('orbLook', null) !== 'shell') { store.set('theme', 'cyan'); store.set('orbLook', 'shell'); }
setTheme(store.get('theme', 'cyan'));

/* ---------- Live data, polled only while it is shown ---------- */
const data = { status: null };
const refreshers = [];
function poll(path, every, when, take) {
  let timer = 0;
  const tick = async () => {
    clearTimeout(timer);
    if (when() && !document.hidden && J.online !== false) { try { take(await J.api(path, undefined, { timeout: 4000 })); } catch {} }
    timer = setTimeout(tick, every);
  };
  refreshers.push(tick); tick();
}
const main = () => J.view.jarvisMain;
poll('/status', 2000, main, s => { data.status = s; });
poll('/sessions', 5000, main, s => J.emit('sessions', s));  // the agents dialog and the panel list listen for this
J.on('stage', jarvisMain => { if (jarvisMain) refreshers.forEach(refresh => refresh()); });  // gauges appear at once

/* ---------- Sphere ---------- */
const bootAt = performance.now();
const spinner = { yaw: 0, pitch: 0, vy: 0, vp: 0, held: false, samples: [] };
/* What he is doing, blended over time so the orb never jumps: how much he is listening, thinking or speaking, and how loud
   the microphone and his own voice are. Nothing here moves or resizes him; the orb's blocks do the moving (shell-orb.js). */
const coreMotion = { at: 0, dt: 0, phase: 0, listening: 0, thinking: 0, speaking: 0, energy: 0, input: 0, output: 0, color: [94, 234, 212] };
function advanceCore(now, pulse, color) {
  const m = coreMotion, dt = m.at ? Math.min(.05, Math.max(0, (now-m.at)/1000)) : 0; m.at = now; m.dt = dt;
  const blend = 1-Math.exp(-dt/.45);
  for (const state of ['listening','thinking','speaking']) m[state] += ((J.view.state===state ? 1 : 0)-m[state])*blend;
  const audio=J.audio, fresh=audio?.separated && now-audio.at<350 && J.online;
  const compress=(v,floor,gain)=>1-Math.exp(-Math.max(0,v-floor)*gain);
  const input=fresh ? compress(audio.input,.004,28) : !audio?.separated && J.view.state==='listening' ? pulse : 0;
  const output=fresh ? compress(audio.output,.001,18) : !audio?.separated && J.view.state==='speaking' ? pulse : 0;
  for(const [key,target] of [['input',input],['output',output]])
    m[key]+=(target-m[key])*(1-Math.exp(-dt/(target>m[key]?.045:.24)));
  m.energy += (Math.max(m.input,m.output)-m.energy)*(1-Math.exp(-dt/.055));
  for (let i=0;i<3;i++) m.color[i] += (parseInt(color.slice(1+i*2,3+i*2),16)-m.color[i])*blend;
  if (!reduced.matches) m.phase += dt;   // a steady clock: his slow turn never speeds up or slows down
  return m;
}

function drawSphere(rx, S, t, col, pulse, spin, big) {
  const D = J.view.dpr || 1, TAU = Math.PI * 2;
  const build = reduced.matches ? 1 : ease(clamp01((performance.now() - bootAt - 250) / 2200));
  const motion = advanceCore(performance.now(), pulse, col);
  t = motion.phase;
  col = '#' + motion.color.map(v => Math.round(v).toString(16).padStart(2,'0')).join('');
  // He stays in one spot at one size, with nothing floating around him. R is the yardstick the gauges and his name are placed by.
  const R = S * .255, yaw = t * .12 + spinner.yaw;

  rx.save();
  rx.globalCompositeOperation = 'lighter';
  // A faint wash of his colour behind the orb. It has no bright centre: nothing sits in the middle.
  const halo = rx.createRadialGradient(0, 0, 0, 0, 0, R * 1.9);
  halo.addColorStop(0, hex(col, (.09 + motion.energy * .05) * build)); halo.addColorStop(.6, hex(col, .04 * build)); halo.addColorStop(1, hex(col, 0));
  rx.fillStyle = halo; rx.beginPath(); rx.arc(0, 0, R * 1.9, 0, TAU); rx.fill();
  // The orb itself. Its yaw and pitch follow the same grab-and-spin as before; the signs differ because its "up" is up.
  const compact = document.body.classList.contains('compact-orb');
  const drawn = J.shellOrb?.draw(rx, compact ? S * .38 : R * 1.4, { dt: motion.dt, listening: motion.listening, thinking: motion.thinking, speaking: motion.speaking,
    level: Math.max(motion.input, motion.output), color: motion.color, yaw: -yaw, pitch: .3 - spinner.pitch,
    density: compact || J.graphics.quality === 'economy' ? 0 : 1, alpha: build, still: reduced.matches });
  if (!drawn) {  // no WebGL2: a plain stack of rings in his colour
    rx.strokeStyle = hex(col, .55 * build); rx.lineWidth = Math.max(D, S * .002);
    for (let i = -3; i <= 3; i++) {
      const y = i / 4 * R, half = Math.sqrt(R * R - y * y);
      rx.beginPath(); rx.ellipse(0, y, half, half * .28, 0, 0, TAU); rx.stroke();
    }
  }
  rx.restore();

  if (!big) return;
  if (!compact) drawGauges(rx, S, col, build);
  rx.fillStyle = '#e8fffb'; rx.font = `700 ${S * .032}px Consolas, monospace`; rx.textAlign = 'center'; rx.textBaseline = 'middle';
  rx.globalAlpha = build; rx.fillText('J.A.R.V.I.S.', 0, S * .52);
  rx.fillStyle = hex(col, .85); rx.font = `600 ${S * .019}px Consolas, monospace`;
  rx.fillText(String(J.view.state).toUpperCase(), 0, S * .56); rx.globalAlpha = 1;
}

/* ---------- Status gauges (main view) ---------- */
const shown = { cpu: 0, gpu: 0, mem: 0, net: 0 };
function rate(bytes) { return bytes >= 1e6 ? (bytes / 1e6).toFixed(1) + ' MB/s' : bytes >= 1e3 ? Math.round(bytes / 1e3) + ' KB/s' : Math.round(bytes || 0) + ' B/s'; }
function uptime(seconds) { const d = Math.floor(seconds / 86400), h = Math.floor(seconds % 86400 / 3600), m = Math.floor(seconds % 3600 / 60); return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`; }
function drawGauges(rx, S, col, build) {
  const s = data.status || {}, gpu = s.gpu && typeof s.gpu === 'object' ? s.gpu : null;
  const net = (Number(s.net_down) || 0) + (Number(s.net_up) || 0);
  const target = { cpu: (Number(s.cpu) || 0) / 100, gpu: gpu ? (Number(gpu.util) || 0) / 100 : 0, mem: (Number(s.mem) || 0) / 100,
                   net: net > 0 ? clamp01(Math.log10(net) / 8) : 0 };  // 100 MB/s fills the network gauge
  for (const k in shown) shown[k] += (target[k] - shown[k]) * .08;
  const has = s.cpu != null;
  const gauges = [
    ['CPU', shown.cpu, has ? `${Math.round(s.cpu)}%` : '—', -150, ''],
    ['GPU', shown.gpu, gpu ? `${Math.round(gpu.util)}%` : '—', -30, gpu?.temp != null ? `${Math.round(gpu.temp)}°C` : ''],
    ['MEM', shown.mem, has ? `${Math.round(s.mem)}%` : '—', 150, ''],
    ['NET', shown.net, has ? `↓ ${rate(s.net_down)}` : '—', 30, has ? `↑ ${rate(s.net_up)} · up ${uptime(s.uptime || 0)}` : ''],
  ];
  const r = S * .5, span = 52 * Math.PI / 180;
  rx.save(); rx.lineCap = 'butt';
  for (const [label, value, text, centre, sub] of gauges) {
    const mid = centre * Math.PI / 180, a0 = mid - span / 2, a1 = mid + span / 2;
    rx.lineWidth = S * .0045; rx.strokeStyle = hex(col, .13 * build);
    rx.beginPath(); rx.arc(0, 0, r, a0, a1); rx.stroke();
    const warm = value > .85 ? '#f87171' : value > .65 ? '#f5b83d' : col;
    rx.strokeStyle = hex(warm, .85 * build); rx.shadowBlur = S * .012; rx.shadowColor = warm;
    rx.beginPath(); rx.arc(0, 0, r, a0, a0 + span * clamp01(value)); rx.stroke(); rx.shadowBlur = 0;
    rx.lineWidth = Math.max(1, S * .002); rx.strokeStyle = hex(col, .5 * build);
    for (let i = 0; i <= 10; i++) {
      const a = a0 + span * i / 10, len = i % 5 ? .012 : .022;
      rx.beginPath(); rx.moveTo(Math.cos(a) * (r + S * .008), Math.sin(a) * (r + S * .008));
      rx.lineTo(Math.cos(a) * (r + S * (.008 + len)), Math.sin(a) * (r + S * (.008 + len))); rx.stroke();
    }
    const lx = Math.cos(mid) * r * 1.1, ly = Math.sin(mid) * r * 1.1;
    rx.textAlign = Math.cos(mid) < 0 ? 'right' : 'left'; rx.textBaseline = 'middle'; rx.globalAlpha = build;
    rx.fillStyle = hex(col, .75); rx.font = `600 ${px(S * .019, 11)}px Consolas, monospace`; rx.fillText(label, lx, ly - S * .026);
    rx.fillStyle = '#e8fffb'; rx.font = `700 ${px(S * .028, 15)}px Consolas, monospace`; rx.fillText(text, lx, ly + S * .004);
    if (sub) { rx.fillStyle = hex(col, .7); rx.font = `500 ${px(S * .018, 11)}px Consolas, monospace`; rx.fillText(sub, lx, ly + S * .036); }
    rx.globalAlpha = 1;
  }
  rx.restore();
}

/* ---------- Grab to spin: mouse in the main view, or a HOLO hand ---------- */
const hand = {
  begin(now) { spinner.held = true; spinner.vy = spinner.vp = 0; spinner.samples = [{ at: now, yaw: spinner.yaw, pitch: spinner.pitch }]; },
  move(dx, dy, now) {
    if (!spinner.held) { hand.begin(now); return; }
    spinner.yaw += dx * .008; spinner.pitch = Math.max(-1, Math.min(1, spinner.pitch + dy * .006));
    const s = spinner.samples; s.push({ at: now, yaw: spinner.yaw, pitch: spinner.pitch });
    while (s.length > 2 && now - s[0].at > 120) s.shift();
  },
  end(now, tap = false) {
    if (!spinner.held) return;
    spinner.held = false;
    const s = spinner.samples, first = s[0], last = s[s.length - 1];
    if (tap || reduced.matches || s.length < 2 || last.at - first.at < 16) return;
    const seconds = (last.at - first.at) / 1000;
    spinner.vy = Math.max(-6, Math.min(6, (last.yaw - first.yaw) / seconds));
    spinner.vp = Math.max(-3, Math.min(3, (last.pitch - first.pitch) / seconds));
  },
  cancel() { spinner.held = false; spinner.vy = spinner.vp = 0; },
};
const rc = $('reactor');
let grab = null;
rc.addEventListener('pointerdown', e => {
  if (!main() || e.button !== 0) return;
  grab = { id: e.pointerId, x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, moved: false };
  rc.setPointerCapture(e.pointerId);
});
rc.addEventListener('pointermove', e => {
  if (!main()) return;
  if (!grab) { rc.style.cursor = 'grab'; return; }
  if (!grab.moved && Math.hypot(e.clientX - grab.sx, e.clientY - grab.sy) > 4) { grab.moved = true; hand.begin(performance.now()); rc.style.cursor = 'grabbing'; }
  if (grab.moved) hand.move(e.clientX - grab.x, e.clientY - grab.y, performance.now());
  grab.x = e.clientX; grab.y = e.clientY;
});
rc.addEventListener('pointerup', e => {
  if (!grab) return;
  if (grab.moved) hand.end(performance.now());
  grab = null; rc.style.cursor = '';
});
rc.addEventListener('pointercancel', () => { if (grab?.moved) hand.cancel(); grab = null; });

/* ---------- Thought beams (drawn over everything else, never catching clicks) ---------- */
const fx = make('canvas'); fx.id = 'fx'; fx.setAttribute('aria-hidden', 'true'); document.body.append(fx);
const fctx = fx.getContext('2d');
let fxScale = 1;
function sizeFx() {
  fxScale = Math.min(devicePixelRatio || 1, 2);
  fx.width = innerWidth * fxScale; fx.height = innerHeight * fxScale; fctx.setTransform(fxScale, 0, 0, fxScale, 0, 0);
}
addEventListener('resize', sizeFx); sizeFx();
let beams = [], lastProbe = 0;
J.on('event', ev => {
  if (ev.type !== 'knowledge' || ev.replay || !Array.isArray(ev.sources)) return;
  const now = performance.now();
  ev.sources.slice(0, 8).forEach((s, i) => beams.push({ id: 'note:' + s.path, start: now + i * 140, life: 7000, strong: true }));
});
function nodeOnScreen(n, box, mini) {
  if (!n || !J.isNodeVisible(n) || !Number.isFinite(n.sx)) return null;
  const x = box.left + n.sx, y = box.top + n.sy;
  if (mini ? Math.hypot(x - (box.left + box.width / 2), y - (box.top + box.height / 2)) > box.width / 2 - 2
           : x < 0 || y < 0 || x > innerWidth || y > innerHeight) return null;
  return [x, y];
}
function drawBeams(now) {
  fctx.clearRect(0, 0, innerWidth, innerHeight);
  const origin = J.view.sphere;
  if (!origin || reduced.matches) { beams = []; return; }
  // while he thinks, faint probes search the graph
  if (J.view.state === 'thinking' && now - lastProbe > 380 && J.graph.nodes.length) {
    lastProbe = now;
    const pool = J.graph.nodes.filter(J.isNodeVisible);
    if (pool.length) beams.push({ id: pool[Math.random() * pool.length | 0].id, start: now, life: 1300, strong: false });
  }
  beams = beams.filter(b => now - b.start < b.life);
  if (!beams.length) return;
  const box = $('graph').getBoundingClientRect(), mini = J.view.jarvisMain, links = THEMES[theme].links;
  fctx.globalCompositeOperation = 'lighter'; fctx.lineCap = 'round';
  for (const b of beams) {
    const age = now - b.start; if (age < 0) continue;
    const end = nodeOnScreen(J.graph.byId.get(b.id), box, mini); if (!end) continue;
    const [x0, y0] = [origin.x, origin.y], [x1, y1] = end, len = Math.hypot(x1 - x0, y1 - y0) || 1;
    let bend = 0; for (const c of b.id) bend = (bend * 31 + c.charCodeAt(0)) % 997;
    const side = bend % 2 ? 1 : -1, cx = (x0 + x1) / 2 - (y1 - y0) / len * len * .18 * side, cy = (y0 + y1) / 2 + (x1 - x0) / len * len * .18 * side;
    const grow = ease(clamp01(age / 480)), fade = Math.min(1, (b.life - age) / 1100), alpha = (b.strong ? 1 : .35) * fade;
    const at = u => [(1 - u) ** 2 * x0 + 2 * (1 - u) * u * cx + u * u * x1, (1 - u) ** 2 * y0 + 2 * (1 - u) * u * cy + u * u * y1];
    const path = new Path2D(); path.moveTo(x0, y0);
    for (let k = 1; k <= 28; k++) { const [x, y] = at(k / 28 * grow); path.lineTo(x, y); }
    fctx.strokeStyle = hex(links.note, .16 * alpha); fctx.lineWidth = b.strong ? 7 : 4; fctx.stroke(path);
    fctx.strokeStyle = hex(links.noteSpark, .85 * alpha); fctx.lineWidth = b.strong ? 1.6 : 1; fctx.stroke(path);
    if (grow < 1) continue;
    for (let k = 0; k < (b.strong ? 3 : 1); k++) {  // pulses travelling to the note
      const [x, y] = at((age / 900 + k / 3) % 1), g = fctx.createRadialGradient(x, y, 0, x, y, 7);
      g.addColorStop(0, hex('#ffffff', .9 * alpha)); g.addColorStop(1, hex(links.noteSpark, 0));
      fctx.fillStyle = g; fctx.beginPath(); fctx.arc(x, y, 7, 0, 6.283); fctx.fill();
    }
    const ring = (age % 900) / 900, g = fctx.createRadialGradient(x1, y1, 0, x1, y1, 16);  // the note flares as it is read
    g.addColorStop(0, hex('#ffffff', .8 * alpha)); g.addColorStop(.4, hex(links.note, .45 * alpha)); g.addColorStop(1, hex(links.note, 0));
    fctx.fillStyle = g; fctx.beginPath(); fctx.arc(x1, y1, 16, 0, 6.283); fctx.fill();
    fctx.strokeStyle = hex(links.noteSpark, (1 - ring) * .8 * alpha); fctx.lineWidth = 1.5;
    fctx.beginPath(); fctx.arc(x1, y1, 6 + ring * 22, 0, 6.283); fctx.stroke();
  }
  fctx.globalCompositeOperation = 'source-over';
}

/* ---------- Holographic replies (main view) ---------- */
const reply = make('div', null, 'holo-reply'); reply.hidden = true; reply.setAttribute('aria-hidden', 'true'); document.body.append(reply);
const turn = { parts: [], text: '', typed: 0, quietSince: 0 };
J.on('event', ev => {
  if (ev.replay) return;
  if (ev.type === 'you') { turn.parts = []; turn.text = ''; turn.typed = 0; reply.hidden = true; }
  else if (ev.type === 'jarvis' && ev.text) { turn.parts.push(String(ev.text)); turn.text = turn.parts.join(' '); turn.quietSince = 0; reply.classList.remove('fade'); }
});
let replyAt = 0;
function drawReply(now) {
  const sphere = J.view.sphere, elapsed = (now - (replyAt || now)) / 1000; replyAt = now;
  if (!main() || !turn.text || !sphere) { reply.hidden = true; return; }
  // typed at 60 characters a second of real time, however often frames arrive
  turn.typed = reduced.matches ? turn.text.length : Math.min(turn.text.length, turn.typed + elapsed * 60);
  const typing = turn.typed < turn.text.length, busy = ['speaking', 'thinking'].includes(J.view.state);
  if (typing || busy) turn.quietSince = 0; else if (!turn.quietSince) turn.quietSince = now;
  if (turn.quietSince && now - turn.quietSince > 7000) reply.classList.add('fade');  // drifts down into the chat history
  if (turn.quietSince && now - turn.quietSince > 8400) { turn.text = ''; reply.hidden = true; return; }
  const visible = turn.text.slice(0, Math.floor(turn.typed));
  const tail = visible.length > 320 ? '…' + visible.slice(-320).replace(/^\S*\s/, '') : visible;
  if (reply.textContent !== tail) reply.textContent = tail;
  reply.classList.toggle('typing', typing);
  const top = sphere.y + sphere.size * .6, bottom = $('dock').getBoundingClientRect().top - 14;
  reply.style.left = J.view.stageX + 'px'; reply.style.top = top + 'px';
  reply.style.width = Math.max(240, Math.min(680, J.view.stageWidth - 48)) + 'px';
  reply.style.maxHeight = Math.max(40, bottom - top) + 'px';
  reply.hidden = false;
  reply.classList.toggle('overflow', reply.scrollHeight > reply.clientHeight + 2);  // fade the top only when text runs past it
}

/* ---------- Per frame ---------- */
let lastAt = performance.now();
J.on('frame', () => {
  const now = performance.now(), dt = Math.min(.05, (now - lastAt) / 1000); lastAt = now;
  if (!spinner.held) {
    spinner.yaw += spinner.vy * dt; spinner.pitch = Math.max(-1, Math.min(1, spinner.pitch + spinner.vp * dt));
    const decay = Math.exp(-2.5 * dt); spinner.vy *= decay; spinner.vp *= decay;
    spinner.pitch *= Math.exp(-.6 * dt);  // settles back to its resting tilt
  }
  drawBeams(now);
  drawReply(now);
});

/* ---------- Boot sequence ---------- */
function boot() {
  if (reduced.matches) return;
  document.body.classList.add('booting');
  const scan = make('div', null, 'boot-scan'), log = make('div', null, 'boot-log');
  log.append(make('div', 'J.A.R.V.I.S. // SYSTEMS CHECK', 'boot-title'));
  let calendar = null;
  J.api('/settings', undefined, { timeout: 2500 }).then(s => { calendar = s?.calendar_connected ? 'CONNECTED' : 'NOT CONNECTED'; }).catch(() => { calendar = 'OFFLINE'; });
  const checks = [
    ['VAULT', () => J.graph.nodes.length ? `${J.graph.nodes.length} NODES` : null],
    ['BRAIN', () => { const m = $('modelName').textContent; return m && m !== '—' ? m.toUpperCase() : null; }],
    ['MICROPHONE', () => J.health ? (J.health.microphone_active ? 'ONLINE' : 'OFF') : null],
    ['VOICE', () => J.health ? (J.health.output_active ? 'ONLINE' : 'OFF') : null],
    ['CALENDAR', () => calendar],
  ];
  const rows = checks.map(([name], i) => {
    const row = make('div', null, 'boot-row'), value = make('b', '…');
    row.append(make('span', name), value); row.style.animationDelay = (300 + i * 260) + 'ms'; log.append(row);
    return value;
  });
  document.body.append(scan, log);
  const place = () => { const s = J.view.sphere; log.style.left = J.view.stageX + 'px'; log.style.top = (main() && s ? s.y : innerHeight * .42) + 'px'; };
  place();
  const started = performance.now();
  const tick = () => {
    const age = performance.now() - started;
    let pending = 0;
    checks.forEach(([, read], i) => {
      if (age < 300 + i * 260 + 200) { pending++; return; }
      const v = read() ?? (age > 3600 ? (J.online === false ? 'OFFLINE' : 'STANDBY') : null);
      if (v == null) pending++; else if (rows[i].textContent === '…') { rows[i].textContent = v; rows[i].parentElement.classList.add('ok'); }
    });
    if (!pending && age > 2200 || age > 4200) {
      log.classList.add('done'); document.body.classList.remove('booting');
      setTimeout(() => { log.remove(); scan.remove(); }, 700);
      return;
    }
    place(); setTimeout(tick, 120);
  };
  tick();
}
boot();

J.holo = { drawSphere, hand, setTheme, themes: Object.keys(THEMES),
  get renderer() { return J.shellOrb?.ready ? 'webgl2' : 'canvas2d'; },
  get motion() { return { ...coreMotion, color: [...coreMotion.color] }; },
  get beams() { return beams; } };
})();
