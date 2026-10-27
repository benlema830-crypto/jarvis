/* JARVIS hologram: the sphere and what surrounds it. Builds on the J object from brain.js.
   - Sphere: dotted globe that assembles on load, bulges with his speech, ripples inward while listening,
     and can be grabbed and spun (mouse or HOLO hand tracking) when he is the main view.
   - Thought beams: when he reads vault notes, beams run from the sphere to those notes in the graph.
   - Main view only: status gauges (CPU/GPU/memory/network) and moons for agent tasks, the next
     calendar events and the Spotify track; clicking a moon opens its card.
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
let theme = 'cyan';
function setTheme(name) {
  theme = THEMES[name] ? name : 'cyan';
  Object.assign(J.stateColors, THEMES[theme].states); Object.assign(J.linkColors, THEMES[theme].links);
  document.body.dataset.theme = theme; store.set('theme', theme);
  for (const b of themeRow.children) { b.classList.toggle('on', b.dataset.theme === theme); b.setAttribute('aria-pressed', b.dataset.theme === theme); }
}
setTheme(store.get('theme', 'cyan'));

/* ---------- Live data, polled only while it is shown ---------- */
const data = { status: null, sessions: [], events: [], track: null, trackAt: 0, mic: 0 };
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
poll('/sessions', 5000, main, s => { data.sessions = Array.isArray(s?.sessions) ? s.sessions : []; });
poll('/orbit', 5000, main, o => {
  data.events = Array.isArray(o?.events) ? o.events : [];
  data.track = o?.track && typeof o.track === 'object' ? o.track : null; data.trackAt = performance.now();
});
poll('/voice-health', 350, () => J.view.state === 'listening', h => { data.mic = clamp01((Number(h?.input_level) || 0) * 3); });
J.on('stage', jarvisMain => { if (jarvisMain) refreshers.forEach(refresh => refresh()); });  // gauges and moons appear at once

/* ---------- Sphere ---------- */
const bootAt = performance.now();
const HISTORY = 48;
const speech = new Float32Array(HISTORY);  // recent loudness of his voice, newest first: bulges travel from equator to poles
const spinner = { yaw: 0, pitch: 0, vy: 0, vp: 0, held: false, samples: [] };
const points = {};
function unitSphere(count) {  // Fibonacci lattice, plus a scattered start position for the boot assembly
  if (!points[count]) {
    points[count] = Array.from({ length: count }, (_, i) => {
      const y = 1 - (i + .5) / count * 2, r = Math.sqrt(1 - y * y), a = i * 2.39996;
      const rnd = k => { const s = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453; return s - Math.floor(s); };
      const th = rnd(1) * 6.283, ph = Math.acos(rnd(2) * 2 - 1), far = 2.2 + rnd(3) * 2.4;
      return { x: Math.cos(a) * r, y, z: Math.sin(a) * r, lon: a,
               sx: Math.sin(ph) * Math.cos(th) * far, sy: Math.cos(ph) * far, sz: Math.sin(ph) * Math.sin(th) * far };
    });
  }
  return points[count];
}
const images = new Map();
function image(url) {
  if (!url || !url.startsWith('https://i.scdn.co/')) return null;
  if (!images.has(url)) { const img = new Image(); img.referrerPolicy = 'no-referrer'; img.src = url; images.set(url, img); }
  return images.get(url);
}
let moonHits = [];

function drawSphere(rx, S, t, col, pulse, spin, big) {
  const now = performance.now(), D = J.view.dpr || 1;
  const build = reduced.matches ? 1 : ease(clamp01((now - bootAt - 250) / 2200));
  speech.copyWithin(1, 0); speech[0] = pulse;
  const listening = J.view.state === 'listening', mic = data.mic;
  const R = S * .27 * (1 + pulse * .05), yaw = t * .35 * spin + spinner.yaw, tilt = .38 + Math.sin(t * .21) * .08 + spinner.pitch;
  const cy = Math.cos(yaw), sy = Math.sin(yaw), ct = Math.cos(tilt), st = Math.sin(tilt);
  const turn = (x, y, z) => {  // spin about the vertical axis, then tilt toward the viewer
    const x1 = x * cy - z * sy, z1 = x * sy + z * cy;
    return [x1, y * ct - z1 * st, y * st + z1 * ct];
  };
  const lens = z => 3.2 / (3.2 - z);
  const onOrbit = (radius, inc, u) => {
    const [x, y, z] = turn(Math.cos(u) * radius, Math.sin(u) * radius * Math.sin(inc), Math.sin(u) * radius * Math.cos(inc));
    const p = lens(z / radius);
    return [x * R * p, y * R * p, z];
  };
  // halo and core
  let g = rx.createRadialGradient(0, 0, R * .2, 0, 0, R * 1.7);
  g.addColorStop(0, hex(col, (.16 + pulse * .2) * build)); g.addColorStop(.55, hex(col, .05 * build)); g.addColorStop(1, hex(col, 0));
  rx.fillStyle = g; rx.beginPath(); rx.arc(0, 0, R * 1.7, 0, 6.283); rx.fill();
  rx.globalCompositeOperation = 'lighter';
  const core = R * (.32 + pulse * .2 + Math.sin(t * 2.2) * .02 + (listening ? mic * .08 : 0)) * build;
  if (core > 0) {
    g = rx.createRadialGradient(0, 0, 0, 0, 0, core);
    g.addColorStop(0, hex('#ffffff', .9)); g.addColorStop(.25, hex(col, .7)); g.addColorStop(1, hex(col, 0));
    rx.fillStyle = g; rx.beginPath(); rx.arc(0, 0, core, 0, 6.283); rx.fill();
  }
  // wireframe: meridians and parallels, the far side fainter
  const back = new Path2D(), front = new Path2D(), steps = 48;
  const line = point => {
    let prev = null;
    for (let k = 0; k <= steps; k++) {
      const [x, y, z] = turn(...point(k / steps * 6.283)), p = lens(z), cur = [x * R * p, y * R * p, z];
      if (prev) { const path = prev[2] + cur[2] > 0 ? front : back; path.moveTo(prev[0], prev[1]); path.lineTo(cur[0], cur[1]); }
      prev = cur;
    }
  };
  for (let m = 0; m < 8; m++) { const a = m / 8 * Math.PI; line(u => [Math.cos(u) * Math.cos(a), Math.sin(u), Math.cos(u) * Math.sin(a)]); }
  for (const lat of [-.66, -.33, 0, .33, .66]) { const r = Math.sqrt(1 - lat * lat); line(u => [Math.cos(u) * r, lat, Math.sin(u) * r]); }
  rx.lineWidth = Math.max(1, S * .0025);
  rx.strokeStyle = hex(col, .07 * build); rx.stroke(back);
  rx.strokeStyle = hex(col, .26 * build); rx.stroke(front);
  // the dotted shell: a scan band sweeps it; his voice pushes bulges out from the equator,
  // and while he listens the surface ripples inward from the poles
  const scan = Math.sin(t * .8 * spin), dot = S * (big ? .0032 : .0062);
  rx.fillStyle = col;
  unitSphere(big ? 1400 : 420).forEach((p, i) => {
    const lat = Math.abs(p.y);
    let shape = 1 + speech[Math.min(HISTORY - 1, lat * (HISTORY - 1) | 0)] * .17 * (.7 + .3 * Math.sin(p.lon * 4 + t * 3))
                  + .012 * Math.sin(t * 1.7 + i);
    if (listening) shape -= (.025 + mic * .11) * Math.max(0, Math.sin(lat * 10 + t * 7));
    let ux = p.x * shape, uy = p.y * shape, uz = p.z * shape;
    if (build < 1) { ux = p.sx + (ux - p.sx) * build; uy = p.sy + (uy - p.sy) * build; uz = p.sz + (uz - p.sz) * build; }
    const [x, y, z] = turn(ux, uy, uz), pz = lens(Math.max(-2.5, Math.min(2.5, z))), near = clamp01((z + 1) / 2);
    const band = Math.max(0, 1 - Math.abs(p.y - scan) / .09);
    rx.globalAlpha = Math.min(1, .12 + near * .6 + band * .6) * (.35 + .65 * build);
    const r = dot * (.55 + near * .7 + band * .6);
    rx.fillRect(x * R * pz - r / 2, y * R * pz - r / 2, r, r);
  });
  rx.globalAlpha = 1;
  // orbit rings; in the main view they carry moons, otherwise a satellite each
  const moons = big ? buildMoons(col) : [];
  const rings = [{ radius: 1.42, inc: .9, rate: .6, phase: 0, kind: 'agent' }, { radius: 1.6, inc: -1.1, rate: -.42, phase: 2, kind: 'event' }];
  for (const ring of rings) {
    const orbit = new Path2D(), far = new Path2D();
    let prev = null;
    for (let k = 0; k <= 72; k++) {
      const cur = onOrbit(ring.radius, ring.inc, k / 72 * 6.283);
      if (prev) { const path = cur[2] > 0 ? orbit : far; path.moveTo(prev[0], prev[1]); path.lineTo(cur[0], cur[1]); }
      prev = cur;
    }
    rx.lineWidth = Math.max(1, S * .003);
    rx.strokeStyle = hex(col, .1 * build); rx.stroke(far);
    rx.strokeStyle = hex(col, .4 * build); rx.stroke(orbit);
    if (moons.some(m => m.kind === ring.kind)) continue;
    const sat = onOrbit(ring.radius, ring.inc, t * ring.rate * spin + ring.phase), sr = S * .009 * (sat[2] > 0 ? 1.2 : .7);
    g = rx.createRadialGradient(sat[0], sat[1], 0, sat[0], sat[1], sr * 4);
    g.addColorStop(0, hex('#ffffff', (sat[2] > 0 ? .95 : .4) * build)); g.addColorStop(.3, hex(col, .6 * build)); g.addColorStop(1, hex(col, 0));
    rx.fillStyle = g; rx.beginPath(); rx.arc(sat[0], sat[1], sr * 4, 0, 6.283); rx.fill();
  }
  rx.globalCompositeOperation = 'source-over';
  // a slowly turning tick ring frames it
  for (let i = 0; i < 96; i++) {
    const a = i / 96 * 6.283 + t * .05, long = i % 8 === 0;
    rx.strokeStyle = hex(col, (long ? .7 : .28) * build); rx.lineWidth = long ? Math.max(1.5, S * .006) : Math.max(1, S * .003);
    const r1 = S * .455, r2 = S * (long ? .425 : .44);
    rx.beginPath(); rx.moveTo(Math.cos(a) * r1, Math.sin(a) * r1); rx.lineTo(Math.cos(a) * r2, Math.sin(a) * r2); rx.stroke();
  }
  moonHits = [];
  if (!big) return;
  drawGauges(rx, S, col, build);
  const centre = J.view.sphere;
  moons.forEach((m, i) => {
    const same = moons.filter(o => o.kind === m.kind), k = same.indexOf(m);
    const ring = m.kind === 'track' ? { radius: 1.9, inc: .22, rate: .12 } : rings[m.kind === 'agent' ? 0 : 1];
    const radius = m.kind === 'event' ? m.orbit : ring.radius;
    const [X, Y, z] = onOrbit(radius, ring.inc, t * ring.rate * .5 + k / same.length * 6.283 + (m.kind === 'event' ? 1.3 : 0));
    const r = S * (m.kind === 'track' ? .034 : .022);
    drawMoon(rx, m, X, Y, z, r, S, t, build);
    if (centre) moonHits.push({ x: centre.x + X / D, y: centre.y + Y / D, r: r / D, z, m, X, Y });
  });
  for (const h of moonHits) drawMoonLabel(rx, h.m, h.X, h.Y, h.z, h.r * D, S, build);  // labels above every moon body
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
    rx.lineWidth = S * .009; rx.strokeStyle = hex(col, .13 * build);
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

/* ---------- Moons: agent tasks, upcoming events, the current song ---------- */
function until(iso) {
  const minutes = Math.round((Date.parse(iso) - Date.now()) / 60000);
  if (!Number.isFinite(minutes)) return '';
  if (minutes <= 0) return 'now';
  return minutes < 60 ? `in ${minutes}m` : `in ${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
function buildMoons(col) {
  const moons = [];
  const sessions = [...data.sessions].sort((a, b) => (b.status === 'running') - (a.status === 'running')).slice(0, 4);
  for (const s of sessions) {
    const status = String(s.status || 'idle');
    moons.push({ kind: 'agent', data: s, label: String(s.name || 'Agent').slice(0, 24), sub: status,
                 color: status === 'running' ? '#f5b83d' : status === 'failed' ? '#f87171' : col, spinning: status === 'running', glyph: '⚙' });
  }
  for (const e of data.events.slice(0, 3)) {
    const minutes = (Date.parse(e.start) - Date.now()) / 60000;
    moons.push({ kind: 'event', data: e, label: String(e.title || 'Event').slice(0, 26), sub: e.all_day ? 'today' : until(e.start),
                 color: '#c4b5fd', glyph: '◷', orbit: 1.3 + .45 * clamp01((Number.isFinite(minutes) ? minutes : 720) / 720) });
  }
  const tr = data.track;
  if (tr && tr.name) {
    const elapsed = tr.playing ? performance.now() - data.trackAt : 0;
    const progress = tr.duration_ms ? clamp01((tr.progress_ms + elapsed) / tr.duration_ms) : 0;
    moons.push({ kind: 'track', data: tr, label: String(tr.name).slice(0, 26), sub: (tr.artists || []).join(', ').slice(0, 30),
                 color: '#1ed760', glyph: '♫', progress, playing: tr.playing, img: image(tr.art) });
  }
  return moons;
}
function drawMoon(rx, m, X, Y, z, r, S, t, build) {
  rx.save();
  rx.globalAlpha = (z > 0 ? 1 : .42) * build;
  let g = rx.createRadialGradient(X, Y, r * .5, X, Y, r * 2.6);
  g.addColorStop(0, hex(m.color, .35)); g.addColorStop(1, hex(m.color, 0));
  rx.fillStyle = g; rx.beginPath(); rx.arc(X, Y, r * 2.6, 0, 6.283); rx.fill();
  rx.fillStyle = '#04090c'; rx.beginPath(); rx.arc(X, Y, r, 0, 6.283); rx.fill();
  if (m.img?.complete && m.img.naturalWidth) {
    rx.save(); rx.beginPath(); rx.arc(X, Y, r * .9, 0, 6.283); rx.clip();
    rx.translate(X, Y); rx.rotate(m.playing && !reduced.matches ? t * .6 : 0); rx.drawImage(m.img, -r, -r, r * 2, r * 2); rx.restore();
  } else {
    rx.fillStyle = m.color; rx.font = `${r * 1.05}px "Segoe UI Symbol", sans-serif`; rx.textAlign = 'center'; rx.textBaseline = 'middle';
    rx.fillText(m.glyph, X, Y + r * .05);
  }
  rx.lineWidth = Math.max(1.5, S * .0035); rx.strokeStyle = hex(m.color, .9);
  if (m.spinning) {
    rx.beginPath(); rx.arc(X, Y, r, 0, 6.283); rx.strokeStyle = hex(m.color, .35); rx.stroke();
    rx.strokeStyle = hex(m.color, .95); rx.beginPath(); rx.arc(X, Y, r * 1.3, t * 3, t * 3 + 1.7); rx.stroke();
  } else if (m.progress != null) {
    rx.strokeStyle = hex(m.color, .25); rx.beginPath(); rx.arc(X, Y, r * 1.18, 0, 6.283); rx.stroke();
    rx.strokeStyle = hex(m.color, .95); rx.beginPath(); rx.arc(X, Y, r * 1.18, -Math.PI / 2, -Math.PI / 2 + 6.283 * m.progress); rx.stroke();
  } else { rx.beginPath(); rx.arc(X, Y, r, 0, 6.283); rx.stroke(); }
  rx.restore();
}
function drawMoonLabel(rx, m, X, Y, z, r, S, build) {
  rx.save(); rx.globalAlpha = build;
  if (z > -.2) {
    rx.textAlign = 'left'; rx.textBaseline = 'middle';
    rx.fillStyle = '#e8fffb'; rx.font = `600 ${px(S * .019, 12)}px Consolas, monospace`; rx.fillText(m.label, X + r * 1.7, Y - S * .011);
    rx.fillStyle = hex(m.color, .9); rx.font = `500 ${px(S * .016, 11)}px Consolas, monospace`; rx.fillText(m.sub, X + r * 1.7, Y + S * .014);
  }
  rx.restore();
}

/* ---------- Moon cards ---------- */
const card = make('div', null, 'card moon-card'); card.hidden = true; card.setAttribute('role', 'dialog'); document.body.append(card);
function showCard(hit) {
  const m = hit.m, d = m.data; card.replaceChildren();
  const actions = make('div', null, 'moon-actions');
  const action = (text, fn) => { const b = make('button', text); b.type = 'button'; b.onclick = fn; actions.append(b); };
  if (m.kind === 'agent') {
    card.append(make('h4', String(d.name || 'Agent session')), make('small', `${d.project || ''} · ${d.provider || 'codex'} · ${d.status || 'idle'}`));
    if (d.task) card.append(make('p', String(d.task).slice(0, 220) + (String(d.task).length > 220 ? '…' : '')));
    if (d.report) card.append(make('p', 'Last report: ' + String(d.report).slice(0, 220), 'muted'));
    action('Open tasks & agents', () => { hideCard(); $('agentsBtn').click(); });
  } else if (m.kind === 'event') {
    const when = new Date(d.start);
    card.append(make('h4', String(d.title || 'Event')),
      make('small', d.all_day ? 'All day' : when.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' }) + ' · ' + until(d.start)));
    if (d.location) card.append(make('p', String(d.location)));
  } else {
    card.append(make('h4', String(d.name || 'Spotify')), make('small', (d.artists || []).join(', ')));
    if (d.album) card.append(make('p', String(d.album), 'muted'));
    action(d.playing ? 'Pause' : 'Play', () => { hideCard(); J.send(d.playing ? 'pause the music' : 'resume the music'); });
    action('Next song', () => { hideCard(); J.send('next song'); });
  }
  const close = make('button', '×', 'moon-close'); close.type = 'button'; close.setAttribute('aria-label', 'Close'); close.onclick = hideCard;
  card.prepend(close);
  if (actions.children.length) card.append(actions);
  card.hidden = false;
  const box = card.getBoundingClientRect();
  card.style.left = Math.max(12, Math.min(innerWidth - box.width - 12, hit.x + hit.r + 14)) + 'px';
  card.style.top = Math.max(12, Math.min(innerHeight - box.height - 12, hit.y - box.height / 2)) + 'px';
}
function hideCard() { card.hidden = true; }
J.on('escape', hideCard); J.on('stage', hideCard);
document.addEventListener('pointerdown', e => { if (!card.hidden && !card.contains(e.target) && e.target !== $('reactor')) hideCard(); });

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
const moonAt = (x, y) => moonHits.filter(h => Math.hypot(h.x - x, h.y - y) < h.r * 1.8).sort((a, b) => b.z - a.z)[0];
rc.addEventListener('pointerdown', e => {
  if (!main() || e.button !== 0) return;
  grab = { id: e.pointerId, x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, moved: false };
  rc.setPointerCapture(e.pointerId);
});
rc.addEventListener('pointermove', e => {
  if (!main()) return;
  if (!grab) { rc.style.cursor = moonAt(e.clientX, e.clientY) ? 'pointer' : 'grab'; return; }
  if (!grab.moved && Math.hypot(e.clientX - grab.sx, e.clientY - grab.sy) > 4) { grab.moved = true; hand.begin(performance.now()); rc.style.cursor = 'grabbing'; }
  if (grab.moved) hand.move(e.clientX - grab.x, e.clientY - grab.y, performance.now());
  grab.x = e.clientX; grab.y = e.clientY;
});
rc.addEventListener('pointerup', e => {
  if (!grab) return;
  if (grab.moved) hand.end(performance.now());
  else { const hit = moonAt(e.clientX, e.clientY); if (hit) showCard(hit); else hideCard(); }
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
  if (!n || J.graph.hidden?.has(n.group) || !Number.isFinite(n.sx)) return null;
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
    const pool = J.graph.nodes.filter(n => !J.graph.hidden?.has(n.group));
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

J.holo = { drawSphere, hand, setTheme, showCard, themes: Object.keys(THEMES),
  get moons() { return moonHits; }, get beams() { return beams; } };
})();
