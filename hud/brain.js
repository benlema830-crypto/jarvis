/* JARVIS Brain core: knowledge graph, inspector, reactor, conversation and live status.
   panels.js (dialogs) and modes.js (Eyes/Watch/Holo/Focus) build on the J object below.
   All remote text is rendered with textContent; nothing here uses innerHTML. */
'use strict';
const $ = id => document.getElementById(id);
const make = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
const store = {
  get(key, fallback) { try { const v = JSON.parse(localStorage.getItem('jarvis.' + key)); return v ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem('jarvis.' + key, JSON.stringify(value)); } catch {} },
};

/* ---------- Shared API used by panels.js and modes.js ---------- */
const J = window.J = {
  listeners: {},
  on(type, fn) { (this.listeners[type] ??= []).push(fn); },
  emit(type, data) { for (const fn of this.listeners[type] || []) { try { fn(data); } catch (e) { console.error(e); } } },
  async api(path, payload, options = {}) {
    const init = payload === undefined ? { cache: 'no-store' } :
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) };
    const response = await fetch(path, { ...init, signal: options.signal ?? AbortSignal.timeout(options.timeout ?? 15000) });
    let data = null;
    try { data = await response.json(); } catch {}
    if (!response.ok) throw Error(data?.error || (response.status === 503 ? 'JARVIS is offline. Open the JARVIS Brain shortcut to start him.' : 'Request failed (' + response.status + ').'));
    return data;
  },
  notice(text) { $('hint').textContent = text || ''; },
  prepare(text) { $('prompt').value = text; $('prompt').focus(); },
  async send(text) {
    if (!text.trim()) return;
    try { await J.api('/command', { text }); J.notice('Sent to JARVIS…'); }
    catch (e) { J.notice(e.message); }
  },
  online: false, health: null, mode: 'wake',
};

/* ---------- Graph data ---------- */
const FIXED_COLORS = { JARVIS: '#e8f4ef', Memory: '#3ddc97', Conversation: '#5b8def', Tool: '#a78bfa' };
const PALETTE = ['#f5b83d', '#2dd4bf', '#f472b6', '#fb923c', '#a3e635', '#38bdf8', '#e879f9', '#facc15', '#f87171', '#c084fc'];
const groupColors = new Map();
const G = {
  nodes: [], links: [], byId: new Map(), adj: new Map(), groups: [],
  hidden: new Set(store.get('hiddenGroups', ['Tool'])),
  selected: null, focus: new Set(), depth: 1, path: null, hover: null, matches: null,
  alpha: 1, is3d: true, orbit: false,
  cam: { yaw: .35, pitch: .22, zoom: 1, panX: 0, panY: 0, target: { x: 0, y: 0, z: 0 }, goal: null },
};
J.graph = G;
function colorOf(group) {
  if (FIXED_COLORS[group]) return FIXED_COLORS[group];
  if (!groupColors.has(group)) groupColors.set(group, PALETTE[groupColors.size % PALETTE.length]);
  return groupColors.get(group);
}
function radiusOf(n) { return n.id === 'root' ? 9 : 2.6 + Math.sqrt(n.degree || 0) * 1.9; }
function visible(n) { return !G.hidden.has(n.group); }

async function load(keepView) {
  try {
    const data = await J.api('/brain-data');
    const old = new Map(G.nodes.map(n => [n.id, n]));
    G.nodes = data.nodes; G.links = data.links.filter(l => l.source !== l.target);
    G.byId = new Map(G.nodes.map(n => [n.id, n]));
    G.adj = new Map(G.nodes.map(n => [n.id, new Set()]));
    for (const l of G.links) { G.adj.get(l.source)?.add(l.target); G.adj.get(l.target)?.add(l.source); }
    const groups = [...new Set(G.nodes.map(n => n.group))];
    G.groups = groups;
    groups.filter(g => !FIXED_COLORS[g]).sort().forEach(colorOf);  // stable folder colors
    groups.forEach((g, i) => {  // seed each group around a sphere so clusters form quickly
      const phi = Math.acos(1 - 2 * (i + .5) / groups.length), theta = Math.PI * (1 + Math.sqrt(5)) * i;
      G.nodes.filter(n => n.group === g).forEach((n, j) => {
        const prev = old.get(n.id);
        if (prev) { Object.assign(n, { x: prev.x, y: prev.y, z: prev.z, vx: 0, vy: 0, vz: 0 }); return; }
        const r = 140 + (j % 7) * 6, jitter = () => (Math.random() - .5) * 60;
        n.x = n.id === 'root' ? 0 : Math.sin(phi) * Math.cos(theta) * r + jitter();
        n.y = n.id === 'root' ? 0 : Math.cos(phi) * r + jitter();
        n.z = n.id === 'root' ? 0 : Math.sin(phi) * Math.sin(theta) * r + jitter();
        n.vx = n.vy = n.vz = 0;
      });
    });
    G.nodes.forEach(n => { n.color = colorOf(n.group); n.r = radiusOf(n); });
    G.alpha = keepView ? .5 : 1;
    const v = data.vault || {};
    $('vaultName').textContent = (v.name || 'Second brain');
    $('counts').textContent = `${v.notes ?? 0} notes · ${G.links.filter(l => l.kind === 'note-link').length} note links · ${G.nodes.length} nodes` +
      (v.unresolved ? ` · ${v.unresolved} unresolved` : '');
    renderFilters(); renderHubs(); search();
    if (G.selected) { const again = G.byId.get(G.selected.id); again ? select(again, { keepCamera: true }) : clearSelection(); }
    else renderInspector();
    if (!keepView) settling = performance.now();
    J.emit('graph-loaded');
  } catch (e) { J.notice(e.message); }
}

/* ---------- Force simulation (3D, cools down and stops) ---------- */
function forces() {
  const repel = 15 + Number($('repel').value) * 1.3, length = 20 + Number($('linkLength').value) * 1.2;
  return { repel, length };
}
function simulate() {
  if (G.alpha < .004) return;
  // Hidden groups sit still: otherwise 55 invisible tool nodes shove the visible graph into a long thin streak.
  const ns = G.nodes.filter(visible), n = ns.length, { repel, length } = forces(), a = G.alpha;
  for (let i = 0; i < n; i++) {
    const p = ns[i];
    for (let j = i + 1; j < n; j++) {
      const q = ns[j];
      let dx = p.x - q.x, dy = p.y - q.y, dz = G.is3d ? p.z - q.z : 0;
      let d2 = dx * dx + dy * dy + dz * dz;
      if (d2 > 160000) continue;
      if (d2 < .01) { dx = Math.random() - .5; dy = Math.random() - .5; d2 = .5; }
      const f = repel * a / d2;
      p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f;
      if (G.is3d) { p.vz += dz * f; q.vz -= dz * f; }
    }
  }
  for (const l of G.links) {
    const p = G.byId.get(l.source), q = G.byId.get(l.target);
    if (!p || !q || !visible(p) || !visible(q)) continue;
    const dx = q.x - p.x, dy = q.y - p.y, dz = G.is3d ? q.z - p.z : 0;
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
    const want = l.kind === 'note-link' ? length * 1.1 : length;
    const k = (l.kind === 'note-link' ? .09 : .05) * a * (d - want) / d;
    p.vx += dx * k; p.vy += dy * k; q.vx -= dx * k; q.vy -= dy * k;
    if (G.is3d) { p.vz += dz * k; q.vz -= dz * k; }
  }
  for (const p of ns) {
    p.vx -= p.x * .004 * a; p.vy -= p.y * .004 * a; p.vz -= p.z * .004 * a;
    if (p.id === 'root') { p.x *= .9; p.y *= .9; p.z *= .9; }
    p.vx *= .62; p.vy *= .62; p.vz *= .62;
    p.x += p.vx; p.y += p.vy; p.z = G.is3d ? p.z + p.vz : p.z * .85;
  }
  G.alpha *= .988;
}
function reheat(value = .4) { G.alpha = Math.max(G.alpha, value); }
['repel', 'linkLength'].forEach(id => $(id).addEventListener('input', () => { reheat(.5); store.set(id, $(id).value); }));
['repel', 'linkLength'].forEach(id => { const v = store.get(id, null); if (v != null) $(id).value = v; });

/* ---------- Camera and projection ---------- */
const canvas = $('graph'), ctx = canvas.getContext('2d');
let W = 0, H = 0, DPR = 1;
const FOCAL = 620;
function resize() {
  W = innerWidth; H = innerHeight; DPR = Math.min(devicePixelRatio || 1, 2);
  canvas.width = W * DPR; canvas.height = H * DPR; ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
}
addEventListener('resize', resize); resize();
function centerX() { return (W + ($('left').hidden ? 0 : 230) - 190) / 2; }
function project(n) {
  const c = G.cam, t = c.target;
  let x = n.x - t.x, y = n.y - t.y, z = G.is3d ? n.z - t.z : 0;
  const cy = Math.cos(c.yaw), sy = Math.sin(c.yaw), cp = Math.cos(c.pitch), sp = Math.sin(c.pitch);
  if (G.is3d) {
    const x1 = x * cy - z * sy, z1 = x * sy + z * cy;
    const y1 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;
    x = x1; y = y1; z = z2;
  }
  // Stronger perspective than before (was 900) so near nodes read as near; clamped so nothing explodes past the lens.
  const scale = Math.min(W, H) / 820 * c.zoom, persp = G.is3d ? FOCAL / (FOCAL + Math.max(z, -FOCAL * .6)) : 1;
  n.sx = centerX() + c.panX + x * scale * persp;
  n.sy = H * .46 + c.panY + y * scale * persp;  // a little above centre: the dock covers the bottom
  n.sz = z; n.sr = Math.max(1.2, n.r * scale * persp * 1.15); n.persp = persp;
}
let settling = 0;  // keep re-fitting while the first layout settles, until the user takes over
function fit(subset) {
  const shown = Array.isArray(subset) ? subset : G.nodes.filter(visible);
  if (!shown.length) return;
  const c = G.cam;
  c.follow = null;
  const cx = shown.reduce((s, n) => s + n.x, 0) / shown.length, cy = shown.reduce((s, n) => s + n.y, 0) / shown.length,
        cz = shown.reduce((s, n) => s + n.z, 0) / shown.length;
  const spread = shown.map(n => Math.hypot(n.x - cx, n.y - cy, G.is3d ? n.z - cz : 0)).sort((a, b) => a - b);
  const radius = Math.max(60, spread[Math.floor(spread.length * .92)] * 1.08);  // ignore a few far outliers
  c.goal = { x: cx, y: cy, z: G.is3d ? cz : 0, panX: 0, panY: 0, zoom: Math.min(2.6, Math.max(.3, 285 / radius)) };  // margin for perspective: near nodes project larger
}
function stepCamera() {
  const c = G.cam, g = c.goal;
  if (g && c.follow) { g.x = c.follow.x; g.y = c.follow.y; g.z = G.is3d ? c.follow.z : 0; }  // track a node that is still settling
  if (g) {
    const k = .12;
    c.target.x += (g.x - c.target.x) * k; c.target.y += (g.y - c.target.y) * k; c.target.z += (g.z - c.target.z) * k;
    if (g.panX != null) { c.panX += (g.panX - c.panX) * k; c.panY += (g.panY - c.panY) * k; }
    if (g.zoom != null) c.zoom += (g.zoom - c.zoom) * k;
    if (Math.abs(g.x - c.target.x) + Math.abs(g.y - c.target.y) + Math.abs(g.z - c.target.z) < .5 &&
        (g.zoom == null || Math.abs(g.zoom - c.zoom) < .01) && (!c.follow || G.alpha < .01)) c.goal = c.follow = null;
  }
  if (G.orbit && !reduced.matches && !drag && !G.hover) c.yaw += .0016;  // pauses under the pointer so clicks land
  if (settling && (performance.now() - settling > 12000 || drag || G.alpha < .03)) settling = 0;
  if (settling && Math.round(performance.now() / 16) % 20 === 0) fit();
}
J.camera = { fit, rotate(dYaw, dPitch) { G.cam.yaw += dYaw; G.cam.pitch = Math.max(-1.45, Math.min(1.45, G.cam.pitch + dPitch)); },
  zoomBy(f) { G.cam.goal = null; G.cam.zoom = Math.max(.2, Math.min(6, G.cam.zoom * f)); },
  pan(dx, dy) { G.cam.panX += dx; G.cam.panY += dy; } };

/* ---------- Rendering ---------- */
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const stars = Array.from({ length: 220 }, (_, i) => ({ x: ((i * 127.31 + 17) % 997) / 997, y: ((i * 213.73 + 31) % 991) / 991, r: i % 11 === 0 ? 1.1 : .5, p: i * 1.7 }));
function hex(color, alpha) { const a = Math.round(Math.max(0, Math.min(1, alpha)) * 255).toString(16).padStart(2, '0'); return color + a; }
function draw(now) {
  const t = reduced.matches ? 0 : now / 1000;
  simulate(); stepCamera();
  ctx.fillStyle = '#030608'; ctx.fillRect(0, 0, W, H);
  if ($('showStars').checked) {
    const glow = ctx.createRadialGradient(centerX(), H * .5, 10, centerX(), H * .5, Math.max(W, H) * .6);
    glow.addColorStop(0, '#0c2a2a40'); glow.addColorStop(1, '#03060800'); ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H);
    for (const s of stars) { ctx.fillStyle = `rgba(150,200,205,${.25 + Math.sin(t * .4 + s.p) * .15})`; ctx.fillRect(s.x * W, s.y * H, s.r * 1.6, s.r * 1.6); }
  }
  for (const n of G.nodes) project(n);
  const lit = G.focus.size ? G.focus : null, onPath = G.path ? new Set(G.path) : null;
  const pathEdge = (a, b) => onPath && onPath.has(a) && onPath.has(b) && Math.abs(G.path.indexOf(a) - G.path.indexOf(b)) === 1;
  // links (far ones dimmer, a depth cue), then the travelling "electrons" on top of them
  const flow = $('showFlow').checked && !reduced.matches, sparks = [];
  const speed = uiState === 'thinking' || uiState === 'speaking' ? 2.2 : 1;  // the brain visibly busies itself
  G.links.forEach((l, i) => {
    const a = G.byId.get(l.source), b = G.byId.get(l.target);
    if (!a || !b || !visible(a) || !visible(b)) return;
    const isPath = pathEdge(a.id, b.id), isLit = lit ? lit.has(a.id) && lit.has(b.id) : false, note = l.kind === 'note-link';
    let alpha = note ? .55 : .16;
    if (lit || onPath) alpha = isPath ? 1 : isLit ? (note ? .85 : .45) : .03;
    if (G.matches && !(G.matches.has(a.id) || G.matches.has(b.id))) alpha *= .3;
    const depth = G.is3d ? Math.max(.3, Math.min(1, (a.persp + b.persp) / 2)) : 1;
    ctx.strokeStyle = isPath ? hex('#f5b83d', alpha * depth) : note ? hex('#5eead4', alpha * depth) : hex('#6fb3a6', alpha * depth);
    ctx.lineWidth = (isPath ? 2.2 : note ? 1.2 : .6) * Math.min(1.5, depth + .2);
    ctx.beginPath(); ctx.moveTo(a.sx, a.sy); ctx.lineTo(b.sx, b.sy); ctx.stroke();
    if (!flow || ((lit || onPath) && !isPath && !isLit)) return;
    // Phase seeded by link index (not screen position) so electrons glide smoothly while the camera orbits.
    const count = isPath ? 3 : note ? 2 : 1, rate = (isPath ? .55 : note ? .32 : .2) * speed;
    for (let k = 0; k < count; k++) {
      const phase = (t * rate + ((i * .618) % 1) + k / count) % 1;
      sparks.push({ x: a.sx + (b.sx - a.sx) * phase, y: a.sy + (b.sy - a.sy) * phase, dx: b.sx - a.sx, dy: b.sy - a.sy,
                    r: (isPath ? 2.4 : note ? 1.9 : 1.2) * depth * Math.min(1.6, Math.max(.8, G.cam.zoom)),
                    color: isPath ? '#ffd27a' : note ? '#a7f3e4' : '#7fd8c8', alpha: Math.max(alpha, note || isPath ? .9 : .5) * depth });
    }
  });
  ctx.globalCompositeOperation = 'lighter';  // additive, so overlapping electrons glow
  for (const s of sparks) {
    const halo = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.r * 4.5);
    halo.addColorStop(0, hex(s.color, s.alpha * .55)); halo.addColorStop(1, hex(s.color, 0));
    ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(s.x, s.y, s.r * 4.5, 0, 6.283); ctx.fill();
    const len = Math.hypot(s.dx, s.dy) || 1, tail = Math.min(14, len * .12);  // short comet tail behind it
    ctx.strokeStyle = hex(s.color, s.alpha * .5); ctx.lineWidth = s.r;
    ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(s.x - s.dx / len * tail, s.y - s.dy / len * tail); ctx.stroke();
    ctx.fillStyle = hex('#ffffff', s.alpha); ctx.beginPath(); ctx.arc(s.x, s.y, s.r * .8, 0, 6.283); ctx.fill();
  }
  ctx.globalCompositeOperation = 'source-over';
  // nodes, far to near
  const order = G.nodes.filter(visible).sort((a, b) => b.sz - a.sz);
  const labelled = new Set(hubIds.slice(0, 10)), labels = [];
  for (const n of order) {
    let alpha = 1;
    if (lit || onPath) alpha = (onPath && onPath.has(n.id)) || (lit && lit.has(n.id)) ? 1 : .07;
    if (G.matches) alpha *= G.matches.has(n.id) ? 1 : .15;
    if (G.is3d) alpha *= Math.max(.35, Math.min(1, n.persp * 1.05));
    ctx.globalAlpha = alpha;
    const r = n.sr * (n === G.selected ? 1.25 : 1);
    const grad = ctx.createRadialGradient(n.sx - r * .35, n.sy - r * .4, r * .1, n.sx, n.sy, r);
    grad.addColorStop(0, '#ffffff'); grad.addColorStop(.25, n.color); grad.addColorStop(1, hex(n.color, .55));
    ctx.fillStyle = grad;
    if (n === G.selected || n === G.hover) { ctx.shadowBlur = 18; ctx.shadowColor = n.color; }
    ctx.beginPath(); ctx.arc(n.sx, n.sy, r, 0, 6.283); ctx.fill(); ctx.shadowBlur = 0;
    if (n === G.selected) { ctx.strokeStyle = hex(n.color, .8); ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(n.sx, n.sy, r + 4 + Math.sin(t * 3) * 1.5, 0, 6.283); ctx.stroke(); }
    const showLabel = $('showLabels').checked && alpha > .3 && (labelled.has(n.id) || n === G.selected || n === G.hover ||
      (lit && lit.has(n.id)) || (onPath && onPath.has(n.id)) || (G.matches && G.matches.has(n.id)) || G.cam.zoom > 1.7 || G.nodes.length < 60);
    if (showLabel) {
      const rank = n === G.selected ? 0 : n === G.hover ? 1 : onPath?.has(n.id) ? 2 : labelled.has(n.id) ? 3 : 4;
      labels.push({ n, r, alpha, rank });
    }
  }
  // Labels last, most important first; skip any that would overlap one already drawn.
  const placed = [];
  ctx.textAlign = 'center';
  for (const { n, r, alpha, rank } of labels.sort((a, b) => a.rank - b.rank || (b.n.degree || 0) - (a.n.degree || 0))) {
    const big = rank <= 3;
    ctx.font = `${big ? 600 : 400} ${big ? 11.5 : 10}px "Segoe UI", sans-serif`;
    const text = n.label.length > 34 ? n.label.slice(0, 32) + '…' : n.label, w = ctx.measureText(text).width;
    const box = { x: n.sx - w / 2 - 2, y: n.sy + r + 2, w: w + 4, h: 13 };
    if (rank > 1 && placed.some(b => box.x < b.x + b.w && b.x < box.x + box.w && box.y < b.y + b.h && b.y < box.y + box.h)) continue;
    placed.push(box);
    ctx.globalAlpha = alpha; ctx.fillStyle = big ? '#eef6f4' : '#a8bbb7';
    ctx.fillText(text, n.sx, n.sy + r + 12);
  }
  ctx.globalAlpha = 1;
  drawReactor(t);
  requestAnimationFrame(draw);
}

/* ---------- Pointer interaction ---------- */
let drag = null;
function hit(x, y) {
  let best = null, bestD = Infinity;
  for (const n of G.nodes) {
    if (!visible(n) || n.sx == null) continue;
    const d = Math.hypot(n.sx - x, n.sy - y);
    if (d < Math.max(9, n.sr + 5) && d < bestD) { best = n; bestD = d; }
  }
  return best;
}
J.hit = hit;
canvas.addEventListener('contextmenu', e => e.preventDefault());
canvas.addEventListener('pointerdown', e => {
  drag = { x: e.clientX, y: e.clientY, moved: false, pan: e.button === 2 || e.button === 1 || !G.is3d || e.ctrlKey };
  if (drag.pan) { G.cam.goal = G.cam.follow = null; }
  canvas.setPointerCapture(e.pointerId); canvas.classList.add('dragging');
});
canvas.addEventListener('pointermove', e => {
  if (!drag) {
    const n = hit(e.clientX, e.clientY);
    G.hover = n;
    const tip = $('tooltip');
    if (n) { tip.replaceChildren(make('div', n.label), make('small', n.group + ' · ' + (n.degree || 0) + ' connections')); tip.style.left = e.clientX + 'px'; tip.style.top = e.clientY + 'px'; tip.hidden = false; canvas.style.cursor = 'pointer'; }
    else { tip.hidden = true; canvas.style.cursor = ''; }
    return;
  }
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
  if (drag.pan) J.camera.pan(dx, dy); else J.camera.rotate(dx * .006, dy * .005);
  drag.x = e.clientX; drag.y = e.clientY;
});
canvas.addEventListener('pointerup', e => {
  canvas.classList.remove('dragging');
  if (drag && !drag.moved && e.button === 2) { const n = hit(e.clientX, e.clientY); if (n) { select(n, { keepCamera: true }); J.emit('read', n); } }
  if (drag && !drag.moved && e.button === 0) {
    const n = hit(e.clientX, e.clientY);
    if (n && e.shiftKey && G.selected && n !== G.selected) tracePath(G.selected, n);
    else if (n) select(n);
    else clearSelection();
  }
  drag = null;
});
canvas.addEventListener('pointercancel', () => { drag = null; canvas.classList.remove('dragging'); });
canvas.addEventListener('dblclick', e => { const n = hit(e.clientX, e.clientY); if (n) J.emit('read', n); });
canvas.addEventListener('wheel', e => { e.preventDefault(); J.camera.zoomBy(Math.exp(-e.deltaY * .0012)); }, { passive: false });
addEventListener('keydown', e => {
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) || document.querySelector('dialog[open]');
  if (e.key === 'Escape' && !typing) { clearSelection(); J.emit('escape'); }
  if (typing) return;
  if (e.key === '/') { e.preventDefault(); $('search').focus(); }
  else if (e.key.toLowerCase() === 'f') fit();
});

/* ---------- Selection, depth focus and path tracing ---------- */
function neighborhood(id, depth) {
  const seen = new Set([id]); let frontier = [id];
  for (let d = 0; d < depth; d++) {
    const next = [];
    for (const v of frontier) for (const w of G.adj.get(v) || []) if (!seen.has(w) && visible(G.byId.get(w))) { seen.add(w); next.push(w); }
    frontier = next;
  }
  return seen;
}
function select(n, options = {}) {
  G.selected = n; G.path = null; settling = 0;
  if (!visible(n)) { G.hidden.delete(n.group); store.set('hiddenGroups', [...G.hidden]); renderFilters(); }
  G.focus = neighborhood(n.id, G.depth);
  if (!options.keepCamera) { G.cam.follow = n; G.cam.goal = { x: n.x, y: n.y, z: G.is3d ? n.z : 0, panX: 0, panY: 0, zoom: Math.max(G.cam.zoom, 1.25) }; }
  renderInspector(); renderHubs();
  J.emit('selected', n);
}
function clearSelection() {
  G.selected = null; G.focus = new Set(); G.path = null;
  renderInspector(); renderHubs(); J.emit('selected', null);
}
function tracePath(from, to) {
  const prev = new Map([[from.id, null]]), queue = [from.id];
  while (queue.length) {
    const v = queue.shift();
    if (v === to.id) break;
    for (const w of G.adj.get(v) || []) if (!prev.has(w)) { prev.set(w, v); queue.push(w); }
  }
  if (!prev.has(to.id)) { J.notice('No connection between those two.'); return; }
  const path = []; for (let v = to.id; v; v = prev.get(v)) path.unshift(v);
  G.path = path; G.focus = new Set(path);
  fit(path.map(id => G.byId.get(id)));
  renderInspector();
}
J.select = select; J.clearSelection = clearSelection;
J.selectById = id => { const n = G.byId.get(id); if (n) select(n); return n; };

function renderInspector() {
  const box = $('inspector'); box.replaceChildren();
  const n = G.selected;
  if (!n) {
    box.append(make('p', 'Click a node to focus it — only that node and its connections light up, and you can read the note here. Shift-click a second node to trace the path.', 'placeholder'));
    return;
  }
  const title = make('div', null, 'title'); const dot = make('i', null, 'dot'); dot.style.background = n.color;
  title.append(dot, make('span', n.label)); box.append(title);
  box.append(make('div', `${n.group} · ${n.degree || 0} connections`, 'meta'));
  if (G.path) {
    box.append(make('div', 'Path (' + (G.path.length - 1) + ' hops): ' + G.path.map(id => G.byId.get(id)?.label || id).join(' → '), 'path'));
  }
  // A plain-text preview: drop the title line and Markdown heading/link punctuation.
  const plain = (n.body || '').replace(/^#.*\n+/, '').replace(/^#{1,6}\s+/gm, '').replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, a, b) => b || a).trim();
  const excerpt = make('div', plain.slice(0, 420), 'excerpt'); box.append(excerpt);
  const row = make('div', null, 'row');
  if (plain.length > 420) {
    const more = make('button', 'Read full note ▾', 'link'); more.type = 'button';
    more.onclick = () => { const full = excerpt.classList.toggle('full'); excerpt.textContent = full ? plain : plain.slice(0, 420); more.textContent = full ? 'Show less ▴' : 'Read full note ▾'; };
    row.append(more);
  }
  if (n.uri && /^obsidian:/.test(n.uri)) { const a = make('a', 'Open in Obsidian ↗'); a.href = n.uri; row.append(a); }
  const ask = make('button', 'Ask JARVIS', 'link'); ask.type = 'button';
  ask.onclick = () => J.prepare(n.source ? `Read my note "${n.source}" and ` : `About "${n.label}": `);
  row.append(ask); box.append(row);
  const depth = make('div', 'Depth', 'depth');
  for (const d of [1, 2, 3]) {
    const b = make('button', String(d)); b.type = 'button'; b.classList.toggle('on', G.depth === d);
    b.onclick = () => { G.depth = d; G.focus = neighborhood(n.id, d); G.path = null; renderInspector(); };
    depth.append(b);
  }
  box.append(depth);
  const list = make('div', null, 'list neighbors');
  [...(G.adj.get(n.id) || [])].map(id => G.byId.get(id)).filter(m => m && visible(m))
    .sort((a, b) => (b.degree || 0) - (a.degree || 0)).slice(0, 40)
    .forEach(m => list.append(nodeButton(m)));
  box.append(list);
}
function nodeButton(n) {
  const b = make('button'); b.type = 'button';
  const dot = make('i', null, 'dot'); dot.style.background = n.color;
  b.append(dot, make('span', n.label), make('em', String(n.degree || 0)));
  b.onclick = () => select(n); b.title = n.group;
  return b;
}
let hubIds = [];
function renderHubs() {
  const hubs = G.nodes.filter(n => visible(n) && n.id !== 'root').sort((a, b) => (b.degree || 0) - (a.degree || 0)).slice(0, 8);
  hubIds = hubs.map(n => n.id);
  $('hubs').replaceChildren(...hubs.map(nodeButton));
  if (!hubs.length) $('hubs').append(make('p', 'Nothing visible. Turn a group on in Filter.', 'muted'));
}
function renderFilters() {
  const box = $('filters'); box.replaceChildren();
  for (const g of G.groups) {
    const count = G.nodes.filter(n => n.group === g).length;
    const b = make('button'); b.type = 'button'; b.classList.toggle('off', G.hidden.has(g));
    const dot = make('i', null, 'dot'); dot.style.background = colorOf(g);
    b.append(dot, make('span', g), make('em', String(count)));
    b.setAttribute('aria-pressed', String(!G.hidden.has(g)));
    b.onclick = () => { G.hidden.has(g) ? G.hidden.delete(g) : G.hidden.add(g); store.set('hiddenGroups', [...G.hidden]); renderFilters(); renderHubs(); if (G.selected && !visible(G.selected)) clearSelection(); reheat(.3); };
    box.append(b);
  }
  const vaultOnly = G.groups.every(g => G.hidden.has(g) === ['Memory', 'Conversation', 'Tool', 'JARVIS'].includes(g));
  $('scopeVault').classList.toggle('on', vaultOnly); $('scopeAll').classList.toggle('on', G.hidden.size === 0);
}
$('scopeVault').onclick = () => { G.hidden = new Set(['Memory', 'Conversation', 'Tool', 'JARVIS']); store.set('hiddenGroups', [...G.hidden]); clearSelection(); renderFilters(); renderHubs(); fit(); };
$('scopeAll').onclick = () => { G.hidden = new Set(); store.set('hiddenGroups', []); renderFilters(); renderHubs(); fit(); };

function search() {
  const q = $('search').value.toLowerCase().trim(), box = $('searchResults');
  box.replaceChildren();
  if (!q) { G.matches = null; return; }
  const found = G.nodes.filter(n => (n.label + ' ' + (n.body || '')).toLowerCase().includes(q))
    .sort((a, b) => (b.label.toLowerCase().includes(q) - a.label.toLowerCase().includes(q)) || (b.degree || 0) - (a.degree || 0));
  G.matches = new Set(found.map(n => n.id));
  found.slice(0, 25).forEach(n => box.append(nodeButton(n)));
  if (!found.length) box.append(make('p', 'No matching knowledge.', 'muted'));
}
$('search').addEventListener('input', search);
$('search').addEventListener('keydown', e => {
  if (e.key === 'Enter') { const first = $('searchResults').querySelector('button'); first?.click(); }
  if (e.key === 'Escape') { $('search').value = ''; search(); $('search').blur(); }
});

/* ---------- Toolbar and panel chrome ---------- */
$('fit').onclick = () => { clearSelection(); $('search').value = ''; search(); fit(); };
$('dimension').onclick = () => {
  G.is3d = !G.is3d; $('dimension').textContent = G.is3d ? '3D' : '2D';
  if (!G.is3d) { G.cam.yaw = 0; G.cam.pitch = 0; }
  else {  // 2D flattened every z to 0, and nothing pushes a perfectly flat sheet back out: re-seed the depth
    for (const n of G.nodes) { n.z = n.id === 'root' ? 0 : (Math.random() - .5) * 220; n.vz = 0; }
    G.cam.yaw = .35; G.cam.pitch = .22;
  }
  reheat(G.is3d ? .9 : .6); setTimeout(fit, 400);
};
G.orbit = store.get('orbit', true);
$('orbit').setAttribute('aria-pressed', String(G.orbit));
$('orbit').onclick = () => { G.orbit = !G.orbit; store.set('orbit', G.orbit); $('orbit').setAttribute('aria-pressed', String(G.orbit)); };
$('refresh').onclick = () => load(true);
function setLeft(open) { $('left').hidden = !open; $('expandLeft').hidden = open; store.set('leftOpen', open); }
$('collapseLeft').onclick = () => setLeft(false); $('expandLeft').onclick = () => setLeft(true);
setLeft(store.get('leftOpen', true));
for (const id of ['showLabels', 'showFlow', 'showStars']) {
  $(id).checked = store.get(id, true); $(id).addEventListener('change', () => store.set(id, $(id).checked));
}

/* ---------- Reactor: ring / cube / face ---------- */
const rc = $('reactor'), rx = rc.getContext('2d');
let look = store.get('look', 'ring'), level = 0, levelAt = 0, uiState = 'connecting';
const STATE_COLORS = { listening: '#22d3ee', standby: '#5eead4', thinking: '#f5b83d', speaking: '#7dd3fc', offline: '#64748b', connecting: '#64748b', booting: '#64748b' };
document.querySelectorAll('[data-look]').forEach(b => {
  b.classList.toggle('on', b.dataset.look === look);
  b.onclick = () => { look = b.dataset.look; store.set('look', look); document.querySelectorAll('[data-look]').forEach(x => x.classList.toggle('on', x === b)); };
});
J.on('level', v => { level = Math.max(level, Math.min(1, v * 4)); levelAt = performance.now(); });
function drawReactor(t) {
  const S = rc.width, c = S / 2, col = STATE_COLORS[uiState] || '#5eead4';
  rx.clearRect(0, 0, S, S);
  if (performance.now() - levelAt > 200) level *= .9;  // decays to rest when no real audio level arrives
  const pulse = level, spin = uiState === 'thinking' ? 2.4 : 1;
  rx.save(); rx.translate(c, c); rx.lineCap = 'round';
  if (look === 'ring') {
    for (let i = 0; i < 72; i++) {
      const a = i / 72 * 6.283, long = i % 6 === 0;
      rx.strokeStyle = hex(col, long ? .9 : .45); rx.lineWidth = long ? 3 : 2;
      rx.beginPath(); rx.moveTo(Math.cos(a) * (S * .44), Math.sin(a) * (S * .44)); rx.lineTo(Math.cos(a) * (S * (long ? .405 : .42)), Math.sin(a) * (S * (long ? .405 : .42))); rx.stroke();
    }
    const arcs = [[.37, 1.1, 2.2, .9], [.33, -.7, 1.3, .6], [.29, .5, 3.6, .35]];
    for (const [r, speed, len, alpha] of arcs) {
      const start = t * speed * spin; rx.strokeStyle = hex(col, alpha); rx.lineWidth = S * .018;
      rx.beginPath(); rx.arc(0, 0, S * r, start, start + len); rx.stroke();
      rx.beginPath(); rx.arc(0, 0, S * r, start + Math.PI, start + Math.PI + len * .4); rx.stroke();
    }
    const inner = S * (.2 + pulse * .05);
    const g = rx.createRadialGradient(0, 0, 2, 0, 0, inner * 1.4);
    g.addColorStop(0, hex(col, .55 + pulse * .4)); g.addColorStop(.6, hex(col, .12)); g.addColorStop(1, hex(col, 0));
    rx.fillStyle = g; rx.beginPath(); rx.arc(0, 0, inner * 1.4, 0, 6.283); rx.fill();
    rx.strokeStyle = hex(col, .8); rx.lineWidth = 2; rx.beginPath(); rx.arc(0, 0, inner, 0, 6.283); rx.stroke();
    rx.fillStyle = '#e8fffb'; rx.font = `700 ${S * .046}px Consolas, monospace`; rx.textAlign = 'center'; rx.textBaseline = 'middle';
    rx.fillText('J.A.R.V.I.S.', 0, 0);
  } else if (look === 'cube') {
    const s = S * (.2 + pulse * .04), a = t * .7 * spin, b = t * .45;
    const pts = [-1, 1].flatMap(x => [-1, 1].flatMap(y => [-1, 1].map(z => [x, y, z])));
    const proj = pts.map(([x, y, z]) => {
      let x1 = x * Math.cos(a) - z * Math.sin(a), z1 = x * Math.sin(a) + z * Math.cos(a);
      let y1 = y * Math.cos(b) - z1 * Math.sin(b), z2 = y * Math.sin(b) + z1 * Math.cos(b);
      const p = 3 / (3 + z2); return [x1 * s * p, y1 * s * p];
    });
    rx.strokeStyle = hex(col, .9); rx.lineWidth = 2;
    pts.forEach((p, i) => pts.forEach((q, j) => { if (j > i && p.filter((v, k) => v !== q[k]).length === 1) { rx.beginPath(); rx.moveTo(...proj[i]); rx.lineTo(...proj[j]); rx.stroke(); } }));
    rx.strokeStyle = hex(col, .25); rx.beginPath(); rx.arc(0, 0, S * .42, 0, 6.283); rx.stroke();
    rx.fillStyle = hex(col, .9); rx.font = `600 ${S * .05}px Consolas, monospace`; rx.textAlign = 'center'; rx.fillText('J.A.R.V.I.S.', 0, S * .4);
  } else {
    // Face: decorative eyes/blink; the mouth only opens with real audio level events.
    rx.strokeStyle = hex(col, .35); rx.lineWidth = 1.5;
    for (let i = 0; i < 9; i++) { const y = -S * .32 + i * S * .08, w = Math.sqrt(Math.max(0, 1 - (y / (S * .4)) ** 2)) * S * .3; rx.beginPath(); rx.ellipse(0, y, w, S * .012, 0, 0, 6.283); rx.stroke(); }
    rx.strokeStyle = hex(col, .85); rx.lineWidth = 2.2; rx.beginPath(); rx.ellipse(0, 0, S * .3, S * .4, 0, 0, 6.283); rx.stroke();
    const blink = (t % 4.2) < .12 ? .15 : 1;
    rx.fillStyle = hex(col, .95); rx.shadowBlur = 14; rx.shadowColor = col;
    for (const x of [-1, 1]) { rx.beginPath(); rx.ellipse(x * S * .11, -S * .06, S * .045, S * .03 * blink, 0, 0, 6.283); rx.fill(); }
    rx.shadowBlur = 0; rx.strokeStyle = hex(col, .95); rx.lineWidth = 2.5;
    const open = S * (.008 + pulse * .07);
    rx.beginPath(); rx.ellipse(0, S * .16, S * .09, open, 0, 0, 6.283); rx.stroke();
  }
  rx.restore();
}

/* ---------- Conversation dock ---------- */
const chat = { turn: [], history: [] };
function addMessage(ev) {
  if (!['you', 'jarvis'].includes(ev.type) || !ev.text) return;
  const log = $('chatLog'), follow = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  const row = make('div', null, 'msg ' + ev.type);
  row.append(make('small', ev.type === 'you' ? 'YOU' : 'JARVIS'), make('div', ev.text));
  log.append(row); while (log.children.length > 120) log.firstElementChild.remove();
  if (follow) log.scrollTop = log.scrollHeight;
  if (ev.type === 'you') { chat.turn = []; $('replyWho').textContent = 'YOU'; $('replyText').textContent = ev.text; }
  else { chat.turn.push(ev.text); $('replyWho').textContent = 'JARVIS'; $('replyText').textContent = chat.turn.join(' '); $('replyText').scrollTop = 1e9; }
  $('reply').hidden = false;
}
$('historyToggle').onclick = () => { const log = $('chatLog'); log.hidden = !log.hidden; $('historyToggle').textContent = log.hidden ? 'history' : 'hide'; log.scrollTop = 1e9; };
$('command').onsubmit = e => { e.preventDefault(); const text = $('prompt').value.trim(); if (!text) return; if (!J.online) { J.notice('JARVIS is offline. Open the JARVIS Brain shortcut to start him.'); return; } $('prompt').value = ''; J.send(text); };
$('stop').onclick = async () => { try { await J.api('/stop', {}); J.notice('Stopped.'); } catch (e) { J.notice(e.message); } J.emit('stop'); };
$('screenBtn').onclick = () => J.prepare('Look at my screen and tell me what you see.');
$('micBtn').onclick = async () => {
  try { const s = await J.api('/settings', { listening_mode: J.mode === 'wake' ? 'continuous' : 'wake' }); settings(s); }
  catch (e) { J.notice(e.message); }
};
function settings(s) { if (s?.listening_mode) J.mode = s.listening_mode; renderStatus(); }

/* ---------- Live status ---------- */
function healthLabel() {
  const h = J.health;
  if (!J.online) return ['offline', 'JARVIS offline'];
  if (!h) return ['standby', 'Connected'];
  if (h.startup !== 'ready') return ['booting', 'Booting · ' + String(h.startup).replaceAll('_', ' ')];
  if (h.text_mode) return [uiState, 'Keyboard only'];
  if (!h.microphone_active || !h.microphone_receiving || !h.listener_alive) return [uiState, 'Mic unavailable'];
  if (!h.output_active) return [uiState, 'Speaker unavailable'];
  if (h.ai_service === 'error') return [uiState, 'Last request failed'];
  const words = { speaking: 'Speaking', thinking: 'Thinking', listening: 'Listening' };
  return [uiState, words[uiState] || (J.mode === 'continuous' ? 'Listening continuously' : 'Say "Jarvis…"')];
}
function renderStatus() {
  const [state, label] = healthLabel();
  document.body.dataset.online = String(J.online); document.body.dataset.state = state;
  $('online').lastElementChild.textContent = J.online ? 'ONLINE' : 'OFFLINE';
  $('stateText').textContent = label;
  const mic = $('micBtn'); mic.classList.toggle('on', J.online && J.mode === 'continuous');
  mic.title = J.mode === 'continuous' ? 'Continuous listening (click for wake word)' : 'Wake word "Jarvis" (click for continuous)';
  J.emit('status');
}
J.renderStatus = renderStatus;
async function pollHealth() {
  try { const h = await J.api('/voice-health', undefined, { timeout: 3000 }); J.health = h?.startup ? h : null; if (J.health) J.mode = J.health.listening_mode || J.mode; J.online = true; }
  catch { J.health = null; }
  renderStatus();
}
async function pollModel() {
  try { const s = await J.api('/status', undefined, { timeout: 5000 }); $('modelName').textContent = s.info?.model || '—'; J.online = true; uiState = s.state || uiState; }
  catch { $('modelName').textContent = '—'; }
  renderStatus();
}
$('modelPill').onclick = () => J.emit('open-model');

/* ---------- Event stream from the assistant ---------- */
const stream = new EventSource('/events');
J.stream = stream;
stream.onopen = () => { J.online = true; J.api('/settings').then(settings).catch(() => {}); pollHealth(); pollModel(); };
stream.onerror = () => { J.online = false; uiState = 'offline'; J.health = null; renderStatus(); };
stream.onmessage = e => {
  let ev; try { ev = JSON.parse(e.data); } catch { return; }
  if (ev.type === 'hello') {
    $('chatLog').replaceChildren(); chat.turn = [];
    uiState = ev.state || uiState;
    for (const h of ev.history || []) { addMessage(h); J.emit('event', { ...h, replay: true }); }
    J.emit('hello', ev);
  } else if (ev.type === 'state') { uiState = ev.state; renderStatus(); }
  else if (ev.type === 'settings') settings(ev);
  else if (ev.type === 'level') J.emit('level', ev.v || 0);
  else { addMessage(ev); J.emit('event', ev); J.emit(ev.type, ev); }
};

/* ---------- Assistant sources (vault retrieval and web research) ---------- */
function safeUrl(value, schemes) { try { const u = new URL(value); return schemes.includes(u.protocol) ? u.href : null; } catch { return null; } }
J.safeUrl = safeUrl;
function showSources(ev) {
  const list = $('sourcesList'); list.replaceChildren(); $('sourcesBox').hidden = false;
  if (ev.type === 'knowledge') {
    const sources = Array.isArray(ev.sources) ? ev.sources.slice(0, 8) : [];
    $('sourcesStatus').textContent = ev.status === 'unavailable' ? 'Knowledge source unavailable.' :
      sources.length ? (ev.via === 'holo' ? 'Picked up in HOLO.' : 'Retrieved from your vault.') : 'No matching vault notes.';
    for (const s of sources) {
      const row = make('article'), pick = make('button', String(s.title || s.path || 'Source').slice(0, 200)); pick.type = 'button';
      pick.onclick = () => J.selectById('note:' + s.path);
      row.append(pick, make('small', String(s.path || '').slice(0, 300)), make('p', String(s.excerpt || '').replace(/^#.*\n+/, '').slice(0, 220)));
      const uri = safeUrl(s.uri, ['obsidian:']); if (uri) { const a = make('a', 'Open in Obsidian ↗'); a.href = uri; row.append(a); }
      list.append(row);
    }
    if (sources[0] && !ev.replay) J.selectById('note:' + sources[0].path);
  } else {
    $('sourcesStatus').textContent = 'Research sources';
    for (const s of (Array.isArray(ev.sources) ? ev.sources : []).slice(0, 12)) {
      const url = safeUrl(s.url, ['https:', 'http:']); if (!url) continue;
      const a = make('a', String(s.title || new URL(url).hostname).slice(0, 200)); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      list.append(a);
    }
    if (!list.children.length) $('sourcesStatus').textContent = 'No usable research links.';
  }
}
J.on('event', ev => {
  if ((ev.type === 'knowledge' || ev.type === 'sources') && !ev.replay) showSources(ev);
  else if (ev.type === 'you' && !ev.replay) $('sourcesBox').hidden = true;
});
$('clearSources').onclick = () => { $('sourcesBox').hidden = true; $('sourcesList').replaceChildren(); clearSelection(); };

setInterval(pollHealth, 2000); setInterval(pollModel, 15000);
pollHealth(); pollModel();
load(false);
requestAnimationFrame(draw);
