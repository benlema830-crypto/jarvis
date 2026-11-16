/* JARVIS's orb: a hollow hologram shell. Builds on the J object from brain.js; holo.js places it and draws what surrounds it.
   - Two shells of blocks stacked in rings, each ring turning on its own. Every block is an outline of light you can see
     through, and the blocks step in and out with what he is doing: a calm climbing band at rest, ripples from the side
     facing you while he listens, pops and a scan line while he thinks, his voice pushing out from the middle band.
   - Thin arcs of light at different tilts between and around the shells.
   - Tiny electric sparks inside the shell: zaps between the two shells and short tufts of hairs from a wall.
   Nothing is solid, nothing sits in the middle and nothing sticks out of the sphere. He does not bounce or sway.
   Drawn on its own WebGL2 canvas (every piece is one stretched cube) and copied into the page's 2D canvas.
   The mockups this was chosen from are in docs/plans/orb-mockups (spark-orbs.html, version C). */
'use strict';
(() => {
const TAU = Math.PI * 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), clamp01 = v => clamp(v, 0, 1);
const hash = n => { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const AXES = [[1, 0, 0], [0, 1, 0], [0, 0, 1]], IDENTITY = [0, 0, 0, 1];
const rng = seed => () => { seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };

/* ---------- What he is doing right now; holo.js fills this in before every frame ---------- */
// w = how much he is in each state (they blend), level = loudness of whoever is talking, hist = recent levels, newest first.
const sim = { t: 0, dt: 0, level: 0, hist: new Float32Array(90), w: { standby: 1, listening: 0, thinking: 0, speaking: 0 } };
sim.lv = delay => sim.hist[clamp(delay | 0, 0, 89)];   // the level a few frames ago, so a pulse can travel across the sphere

/* ---------- Building a stack of rings ---------- */
function quatFromBasis(x, y, z) {   // rotation whose columns are x, y, z (right-handed)
  const m00 = x[0], m10 = x[1], m20 = x[2], m01 = y[0], m11 = y[1], m21 = y[2], m02 = z[0], m12 = z[1], m22 = z[2], tr = m00 + m11 + m22;
  if (tr > 0) { const s = Math.sqrt(tr + 1) * 2; return [(m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, s / 4]; }
  if (m00 > m11 && m00 > m22) { const s = Math.sqrt(1 + m00 - m11 - m22) * 2; return [s / 4, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s]; }
  if (m11 > m22) { const s = Math.sqrt(1 + m11 - m00 - m22) * 2; return [(m01 + m10) / s, s / 4, (m12 + m21) / s, (m02 - m20) / s]; }
  const s = Math.sqrt(1 + m22 - m00 - m11) * 2; return [(m02 + m20) / s, (m12 + m21) / s, s / 4, (m10 - m01) / s];
}
// One piece = 14 numbers: centre xyz, rotation xyzw, size xyz, glow, kind, heat (colour to white-hot), brightness of a piece of light.
// Kinds: 3 a piece of light (arc piece or part of a spark), 4 a block drawn as an outline of light.
const PIECE = 14;
function put(out, i, cx, cy, cz, q, sx, sy, sz, glow, kind, heat, bright) {
  const o = i * PIECE;
  out[o] = cx; out[o + 1] = cy; out[o + 2] = cz; out[o + 3] = q[0]; out[o + 4] = q[1]; out[o + 5] = q[2]; out[o + 6] = q[3];
  out[o + 7] = sx; out[o + 8] = sy; out[o + 9] = sz; out[o + 10] = glow; out[o + 11] = kind; out[o + 12] = heat; out[o + 13] = bright;
}
// Leaves a window of `open` blocks out of every five or six, so each ring becomes a string of short arcs you can see between.
const GAPS = open => (r, b) => (b + r.j * 3) % (5 + r.j % 2) < open;
// o: rings for each block size (M), blocks per ring (factor), how much of its slot a block fills sideways (wf) and
// upwards (hf), rings left off at each pole (trim) and replaced by one hub pin, the resting radius and which blocks to skip.
function buildRings(density, o) {
  const M = o.M[density], step = Math.PI / M, rings = [], blocks = [], unit = [.1, .075, .06][density] * (o.steps || 1);
  for (let j = o.trim; j < M - o.trim; j++) {
    const lat = ((j + .5) / M - .5) * Math.PI, rest = o.rest || .8, count = Math.max(6, Math.round(o.factor * M * Math.cos(lat)));
    const r = { j, lat, count, rest, dir: j % 2 ? 1 : -1, angle: hash(j) * TAU, snap: 0, shown: 0, timer: hash(j) * 1.5,
      wide: TAU * Math.cos(lat) * rest / count * o.wf, tall: step * rest * o.hf, lobes: 3 + Math.floor(hash(j + 9) * 4), phase: hash(j + 4) * TAU };
    rings.push(r);
    for (let b = 0; b < count; b++) {
      if (o.skip(r, b)) continue;
      blocks.push({ r, b, d: [0, 0, 0], lon: 0, lat, r1: hash(blocks.length), r2: hash(blocks.length + .5), h: rest });
    }
  }
  if (o.trim) for (const s of [1, -1]) {       // one square pin closes each pole
    const r = { j: s > 0 ? M : -1, lat: s * Math.PI / 2, rest: .8, dir: 1, lobes: 0, phase: 0 };
    blocks.push({ r, hub: s, d: [0, s, 0], lon: 0, lat: r.lat, r1: hash(s + 31), r2: hash(s + 41), h: .8,
      width: .8 * Math.sin(o.trim * step) * 1.25, q: s > 0 ? quatFromBasis(AXES[2], AXES[0], AXES[1]) : quatFromBasis(AXES[0], AXES[2], [0, -1, 0]) });
  }
  // Blocks move in whole steps of `unit`; the amounts below say how far each state pushes them.
  const k = o.steps || 1;
  return { unit, rings, blocks, amp: { S: .8 * unit, L: 1.6 * unit, T: 1.6 * unit, V: Math.max(.22 * k, 2.6 * unit) } };
}
// Each ring drifts its own way at `rate`; while thinking it also clicks round like a combination lock.
function spin(rings, rate) {
  const dt = sim.dt;
  for (const r of rings) {
    r.angle += r.dir * dt * rate;
    r.timer -= dt * sim.w.thinking;
    if (r.timer < 0) { r.timer = .3 + hash(r.snap * 3.7 + r.lat) * .9; r.snap += r.dir * TAU / r.count * (1 + Math.floor(hash(r.snap + r.lat * 5) * 3)); }
    r.shown += (r.snap - r.shown) * (1 - Math.exp(-dt * 12));
  }
}
function aim(c) {                    // where a ring block points this frame, and its rotation
  if (c.hub) return c.q;
  const r = c.r, th = c.b / r.count * TAU + r.angle + r.shown, cl = Math.cos(r.lat), sl = Math.sin(r.lat), ct = Math.cos(th), st = Math.sin(th), d = c.d;
  d[0] = cl * ct; d[1] = sl; d[2] = cl * st; c.lon = th;
  return quatFromBasis([-sl * ct, cl, -sl * st], [-st, 0, ct], d);
}
// How far a block sits out: one pattern per state, blended by how much he is in each.
function ringOffset(c, front, a) {
  const t = sim.t, w = sim.w, r = c.r; let off = 0;
  if (w.standby > .01) {            // calm: one band of light climbing from the bottom to the top, then a pause
    const dl = c.lat - (((t * .2) % 1.35 - .175) * Math.PI - Math.PI / 2);
    off += w.standby * a.S * 1.5 * Math.exp(-dl * dl * 14);
  }
  if (w.listening > .01) {          // ripples spreading from the point facing you, stronger as you talk
    const ang = Math.acos(clamp(dot(c.d, front), -1, 1));
    off += w.listening * a.L * (.55 + 2.2 * sim.level) * Math.sin(ang * 7 - t * 5.5) * Math.exp(-ang * .8);
  }
  if (w.thinking > .01) {           // pops at random, and a scan line sweeping round
    const slot = Math.floor(t * 2.4 + c.r1 * 5), val = hash(c.r2 * 91.7 + slot * 7.13);
    let dl = ((c.lon - t * 1.9) % TAU + TAU) % TAU; if (dl > Math.PI) dl -= TAU;
    off += w.thinking * a.T * ((val > .78 ? (val - .78) / .22 : 0) * 1.3 + Math.exp(-dl * dl * 10) * Math.cos(c.lat) * 1.1 - .25);
  }
  if (w.speaking > .01) {           // his voice pushes out from the middle band towards the poles
    off += w.speaking * a.V * sim.lv(Math.abs(c.lat) * 14) * (.15 + 1.05 * Math.pow(.5 + .5 * Math.sin(c.lon * r.lobes + t * 2.4 * r.dir + r.phase), 2));
  }
  return off;
}
// o: inner = where the blocks' inner ends sit (or thick = how deep each block is), and the resting glow.
function putShell(out, at, set, front, o) {
  const { blocks, amp, unit } = set, ease = 1 - Math.exp(-sim.dt * 11);
  for (let i = 0; i < blocks.length; i++) {
    const c = blocks[i], quat = aim(c), rest = c.r.rest;
    c.h += (rest + unit * Math.round(ringOffset(c, front, amp) / unit) - c.h) * ease;   // the target is always a whole number of steps
    const lo = o.inner != null ? o.inner : rest - o.thick, mid = (c.h + lo) / 2, d = c.d;
    const glow = ((c.hub ? .4 : o.glow) + .9 * clamp01((c.h - rest) / (amp.V * .8))) * .6;
    put(out, at + i, d[0] * mid, d[1] * mid, d[2] * mid, quat, c.hub ? c.width : c.r.tall, c.hub ? c.width : c.r.wide, c.h - lo, glow, 4, glow * .42, 0);
  }
  return at + blocks.length;
}

/* ---------- Thin arcs of light ---------- */
// Each arc: radius, tilt of its plane, direction of the tilt, start angle, length (radians), pieces, width, thickness, turn speed,
// fill (below 1 = dashes) and brightness (1 if left out).
function makeArcs(list) {
  return list.map(([R, tilt, az, start, span, n, width, thick, speed, fill, bright = 1]) => {
    const C = [Math.sin(tilt) * Math.cos(az), Math.cos(tilt), Math.sin(tilt) * Math.sin(az)];
    const A = norm(cross(C, Math.abs(C[1]) > .95 ? AXES[0] : AXES[1])), B = cross(C, A);
    return { R, A, B, C, start, span, n, width, thick, speed, fill, bright, angle: 0 };
  });
}
function putArcs(out, at, arcs) {
  const w = sim.w, voice = w.speaking + w.listening;
  for (const s of arcs) {
    s.angle += sim.dt * s.speed * (1 + 1.6 * w.thinking + 1.2 * sim.level);
    const len = s.R * s.span / s.n * s.fill, { A, B, R } = s;
    for (let i = 0; i < s.n; i++) {
      const th = s.start + (i + .5) / s.n * s.span + s.angle, ct = Math.cos(th), st = Math.sin(th);
      const d = [A[0] * ct + B[0] * st, A[1] * ct + B[1] * st, A[2] * ct + B[2] * st], T = [B[0] * ct - A[0] * st, B[1] * ct - A[1] * st, B[2] * ct - A[2] * st];
      const glow = .22 + .78 * sim.lv(i % 16 * 2) * voice + .2 * w.thinking;     // his voice runs along the arc
      put(out, at++, d[0] * R, d[1] * R, d[2] * R, quatFromBasis(T, s.C, d), len, s.width, s.thick, glow, 3, glow * .5, s.bright);
    }
  }
  return at;
}

/* ---------- Tiny electric sparks inside the shell: short-lived hair-thin jagged lines ---------- */
// Everything stays between the inner shell and the inside face of the outer blocks, so nothing sticks out of the sphere.
function makeSparks(seed) {
  const rnd = rng(seed), live = [], POOL = 720, WALL = .66, INNER = .54, DEEP = .34;
  let waitZap = .2, waitTuft = .5;
  const onSphere = R => { const u = rnd() * 2 - 1, th = rnd() * TAU, s = Math.sqrt(1 - u * u); return [s * Math.cos(th) * R, u * R, s * Math.sin(th) * R]; };
  const toRadius = (p, R) => { const n = norm(p); return [n[0] * R, n[1] * R, n[2] * R]; };
  const gap = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  // A jagged line from a to b: split in half again and again, pushing each midpoint sideways by less each time.
  function jagged(a, b, n, sway, R) {
    const pts = new Array(n + 1); pts[0] = a; pts[n] = b;
    const split = (i, j, amp) => {
      if (j - i < 2) return;
      const m = (i + j) >> 1, A = pts[i], B = pts[j];
      let p = [(A[0] + B[0]) / 2 + (rnd() - .5) * amp, (A[1] + B[1]) / 2 + (rnd() - .5) * amp, (A[2] + B[2]) / 2 + (rnd() - .5) * amp];
      if (R) p = toRadius(p, R * (1 + (rnd() - .5) * .04));        // a zap keeps to its own depth
      pts[m] = p; split(i, m, amp * .55); split(m, j, amp * .55);
    };
    split(0, n, sway); return pts;
  }
  function zap() {                  // about one block long, over in a tenth of a second
    const R = INNER + .02 + (WALL - INNER - .04) * rnd(), a = onSphere(R), o = onSphere(.1 + .12 * rnd()), b = toRadius([a[0] + o[0], a[1] + o[1], a[2] + o[2]], R), span = gap(a, b);
    live.push({ life: .07 + .09 * rnd(), age: 0, redraw: 0, power: .7 + .5 * rnd(), thick: .008, build: () => [[jagged(a, b, 4, span * .5, R), 1]] });
  }
  function tuft() {                 // three to five hairs from one spot, each re-forming as it lives so the tuft dances
    // It starts on the inside face of the outer blocks and reaches inwards, or on the inner shell and reaches out to the blocks.
    const inward = rnd() < .5, a = onSphere(inward ? WALL : INNER), n = norm(a), tips = [];
    for (let i = 3 + Math.floor(rnd() * 3); i > 0; i--) {
      const out = inward ? -(.1 + .14 * rnd()) : .04 + .07 * rnd(), o = onSphere(.05 + .08 * rnd()), tip = [a[0] + n[0] * out + o[0], a[1] + n[1] * out + o[1], a[2] + n[2] * out + o[2]];
      tips.push(toRadius(tip, clamp(Math.hypot(tip[0], tip[1], tip[2]), DEEP, WALL)));   // never past the blocks, never into the very middle
    }
    live.push({ life: .25 + .2 * rnd(), age: 0, redraw: 0, power: .7 + .5 * rnd(), thick: .007, build() {
      const lines = [];
      for (const tip of tips) {
        const main = jagged(a, tip, 4, gap(a, tip) * .4, 0); lines.push([main, 1]);
        if (rnd() < .6) {           // a shorter side hair
          const from = main[2], o = onSphere(.03 + .04 * rnd());
          lines.push([jagged(from, [from[0] + (tip[0] - from[0]) * .6 + o[0], from[1] + (tip[1] - from[1]) * .6 + o[1], from[2] + (tip[2] - from[2]) * .6 + o[2]], 2, .02, 0), .6]);
        }
      }
      return lines;
    } });
  }
  return { POOL, put(out, at) {
    const w = sim.w, level = sim.level;
    // How often they fire: a few at rest, busy while thinking, in time with the voice while speaking or listening.
    waitZap -= sim.dt * .6 * (5 * w.standby + (6 + 40 * level) * w.listening + 26 * w.thinking + (6 + 50 * level) * w.speaking);
    while (waitZap <= 0) { waitZap += .5 + rnd(); if (live.length < 70) zap(); }
    waitTuft -= sim.dt * .6 * (1.5 * w.standby + (2 + 10 * level) * w.listening + 7 * w.thinking + (1.5 + 14 * level) * w.speaking);
    while (waitTuft <= 0) { waitTuft += .5 + rnd(); if (live.length < 70) tuft(); }
    let used = 0;
    for (let k = live.length - 1; k >= 0; k--) {
      const sp = live[k]; sp.age += sim.dt;
      if (sp.age > sp.life) { live.splice(k, 1); continue; }
      sp.redraw -= sim.dt; if (sp.redraw <= 0 || !sp.lines) { sp.redraw = .035; sp.lines = sp.build(); sp.flick = .55 + .45 * rnd(); }
      const fade = Math.sqrt(1 - sp.age / sp.life) * sp.flick * sp.power;
      for (const [pts, weight] of sp.lines) for (let i = 0; i + 1 < pts.length && used + 2 <= POOL; i++) {
        const p = pts[i], q = pts[i + 1], len = gap(p, q); if (len < 1e-4) continue;
        const z = [(q[0] - p[0]) / len, (q[1] - p[1]) / len, (q[2] - p[2]) / len], x = norm(cross(z, Math.abs(z[1]) < .9 ? AXES[1] : AXES[0])), quat = quatFromBasis(x, cross(z, x), z);
        const cx = (p[0] + q[0]) / 2, cy = (p[1] + q[1]) / 2, cz = (p[2] + q[2]) / 2, thick = sp.thick * weight;
        put(out, at + used++, cx, cy, cz, quat, thick, thick, len + thick, 1, 3, 1, 3 * fade * weight);                   // white-hot hair
        put(out, at + used++, cx, cy, cz, quat, thick * 3.2, thick * 3.2, len + thick, .2, 3, .2, .34 * fade * weight);   // faint coloured haze round it
      }
    }
    for (let i = used; i < POOL; i++) put(out, at + i, 0, 0, 0, IDENTITY, 0, 0, 0, 0, 3, 0, 0);
  } };
}

/* ---------- The whole orb for one block size (0 big blocks, 1 medium, 2 small) ---------- */
function buildOrb(density) {
  const outer = buildRings(density, { M: [9, 11, 13], factor: 2.6, wf: .88, hf: .85, trim: 1, skip: GAPS(1) });
  const inner = buildRings(density, { M: [7, 9, 11], factor: 2.4, wf: .86, hf: .8, trim: 0, rest: .52, steps: .6, skip: GAPS(2) });
  const arcs = makeArcs([
    [.62, .5, 0, 0, 4.2, 56, .007, .004, .35, .96], [.62, 1.2, 2, 1, 2.6, 36, .007, .004, -.5, .96], [.4, .9, 4, 3, 5, 48, .005, .004, .4, .5],
    [.42, .3, 2, 0, 3.4, 36, .006, .004, -.6, .96], [.86, .25, 1, 0, 2.4, 40, .01, .004, .18, .97], [.88, .85, 3, 2, 1.7, 28, .006, .004, -.22, .97],
    [.84, 1.35, 5, 4, 3.2, 48, .005, .004, .3, .45],
    [.85, .55, 0, .3, 2.2, 44, .045, .004, .12, .97, .3], [.85, .55, 0, 3.3, 1.5, 30, .045, .004, .12, .97, .3], [.885, .55, 0, 0, TAU, 90, .02, .004, .12, .16, .7]]);
  const sparks = makeSparks(37), count = outer.blocks.length + inner.blocks.length + arcs.reduce((sum, s) => sum + s.n, 0) + sparks.POOL;
  return { count, data: new Float32Array(count * PIECE), update(front) {
    const drift = .05 * (sim.w.standby + sim.w.listening) + .04 * sim.w.speaking;
    spin(outer.rings, drift); spin(inner.rings, -2.5 * drift - .05);
    let at = putShell(this.data, 0, outer, front, { inner: .68, glow: .25 });
    at = putShell(this.data, at, inner, front, { thick: .035, glow: .2 });
    at = putArcs(this.data, at, arcs); sparks.put(this.data, at);
  } };
}

/* ---------- Drawing: every piece is the same cube, placed and stretched on the graphics card; all of it is added light ---------- */
const VERT = `#version 300 es
layout(location=0) in vec3 aPos;layout(location=1) in vec3 aNormal;
layout(location=2) in vec3 iCenter;layout(location=3) in vec4 iQuat;layout(location=4) in vec3 iScale;layout(location=5) in vec4 iFx;
uniform mat3 uRot;uniform float uView;
out vec3 vLocal,vScale,vN0,vWorld;out vec4 vFx;
vec3 qrot(vec4 q,vec3 v){return v+2.*cross(q.xyz,cross(q.xyz,v)+q.w*v);}
void main(){
  vec3 w=uRot*(iCenter+qrot(iQuat,aPos*iScale));
  vLocal=aPos;vScale=iScale;vN0=aNormal;vFx=iFx;vWorld=w;
  float cam=4.6,cw=cam-w.z;
  gl_Position=vec4(w.xy*cam*uView,0.,cw);
}`;
const FRAG = `#version 300 es
precision highp float;
in vec3 vLocal,vScale,vN0,vWorld;in vec4 vFx;out vec4 frag;
uniform vec3 uTint,uHot;uniform float uEdge;
void main(){
  vec3 a=abs(vN0),d=(.5-abs(vLocal))*vScale+a*1e3;
  float e=min(d.x,min(d.y,d.z)),aa=fwidth(e)+1e-5;
  float line=1.-smoothstep(uEdge-aa,uEdge+aa,e),bevel=1.-smoothstep(0.,uEdge*5.,e);   // sharp edge line and a soft glow beside it
  float side=1.-a.z,cap=step(.5,vN0.z),glow=vFx.x;
  vec3 emit=mix(uTint,uHot,vFx.z),col;
  float back=mix(.22,1.,smoothstep(-.5,.6,vWorld.z));            // dimmer at the back, so the near side reads as near
  if(vFx.y<3.5)col=emit*(.5+.9*glow)*back*vFx.w;                 // arc piece or a piece of a spark
  else col=emit*(line*(.34+1.1*glow)+bevel*.06+side*.015+cap*(.03+.2*glow))*back;   // block drawn as an outline
  frag=vec4(col,max(col.r,max(col.g,col.b)));
}`;
const EXTENT = 1.15;                 // half the width of the picture, in orb units (the blocks rest at .8 and reach about 1.06)
const canvas = document.createElement('canvas'), glowCanvas = document.createElement('canvas'), glow2d = glowCanvas.getContext('2d');
let gl = null, U = null, failed = false, lost = false, size = 0, loaded = -1;
const models = [];
function setup() {
  gl = canvas.getContext('webgl2', { antialias: true, alpha: true, depth: false, premultipliedAlpha: true });
  if (!gl) throw Error('WebGL2 is not available');
  const program = gl.createProgram();
  for (const [type, code] of [[gl.VERTEX_SHADER, VERT], [gl.FRAGMENT_SHADER, FRAG]]) {
    const s = gl.createShader(type); gl.shaderSource(s, code); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(s));
    gl.attachShader(program, s);
  }
  gl.linkProgram(program); if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
  gl.useProgram(program);
  U = {}; for (const name of ['uRot', 'uView', 'uTint', 'uHot', 'uEdge']) U[name] = gl.getUniformLocation(program, name);
  const cube = [];
  for (let a = 0; a < 3; a++) for (const s of [1, -1]) {
    const n = AXES[a].map(x => x * s), eu = AXES[(a + 1) % 3], ev = AXES[(a + 2) % 3];
    for (const [cu, cv] of [[-1, -1], [1, -1], [1, 1], [-1, -1], [1, 1], [-1, 1]]) cube.push(n[0] * .5 + eu[0] * cu * .5 + ev[0] * cv * .5, n[1] * .5 + eu[1] * cu * .5 + ev[1] * cv * .5, n[2] * .5 + eu[2] * cu * .5 + ev[2] * cv * .5, ...n);
  }
  gl.bindVertexArray(gl.createVertexArray());
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(cube), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 24, 0);
  gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 24, 12);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  for (const [loc, count, offset] of [[2, 3, 0], [3, 4, 12], [4, 3, 28], [5, 4, 40]]) {
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, count, gl.FLOAT, false, PIECE * 4, offset); gl.vertexAttribDivisor(loc, 1);
  }
  gl.disable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);
  loaded = -1; lost = false;
}
canvas.addEventListener('webglcontextlost', e => { e.preventDefault(); lost = true; });
canvas.addEventListener('webglcontextrestored', () => { try { setup(); } catch (e) { failed = true; console.warn('Orb could not be restored:', e); } });

/* Draws the orb centred on the 2D context's origin. unit = canvas pixels for one orb unit (the blocks rest at .8 of it).
   m: seconds since the last frame (dt), weights for listening/thinking/speaking (0..1), level (0..1), colour [r,g,b] 0..255,
   yaw and pitch of the whole orb, block size (density 0..2), alpha, and still (no movement, for reduced motion).
   Returns false when it cannot draw (no WebGL2), so the caller can draw something simpler. */
function draw(rx, unit, m) {
  if (failed) return false;
  try {
    if (!gl) setup();
    if (lost) return false;
    const density = clamp(m.density | 0, 0, 2), model = models[density] || (models[density] = buildOrb(density));
    const budget = J.graphics.budget(), side = 2 * EXTENT * unit;
    const n = Math.ceil(clamp(side * Math.min(budget.scale, 1.25), 160, budget.max) / 2) * 2;
    if (n !== size) { size = n; canvas.width = canvas.height = n; glowCanvas.width = glowCanvas.height = Math.ceil(n / 3); }
    // What he is doing, handed to the patterns above.
    const w = sim.w; w.listening = clamp01(m.listening); w.thinking = clamp01(m.thinking); w.speaking = clamp01(m.speaking);
    w.standby = clamp01(1 - Math.max(w.listening, w.thinking, w.speaking));
    sim.dt = Math.min(.05, Math.max(0, m.dt)); if (!m.still) sim.t += sim.dt;
    sim.level = clamp01(m.level); sim.hist.copyWithin(1, 0); sim.hist[0] = sim.level;
    if (m.still) { w.thinking = 0; w.standby = clamp01(1 - Math.max(w.listening, w.speaking)); }   // no pops, clicks or busy sparks
    const cy = Math.cos(m.yaw), sy = Math.sin(m.yaw), cp = Math.cos(m.pitch), sp = Math.sin(m.pitch);
    model.update([-cp * sy, sp, cp * cy]);
    if (loaded !== density) { gl.bufferData(gl.ARRAY_BUFFER, model.data.byteLength, gl.DYNAMIC_DRAW); loaded = density; }
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, model.data);
    gl.viewport(0, 0, n, n); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    const tint = m.color.map(v => v / 255);
    gl.uniformMatrix3fv(U.uRot, false, [cy, sp * sy, -cp * sy, 0, cp, sp, sy, -sp * cy, cp * cy]);
    gl.uniform1f(U.uView, 1 / EXTENT);
    gl.uniform3f(U.uTint, tint[0], tint[1], tint[2]);
    gl.uniform3f(U.uHot, tint[0] * .5 + .5, tint[1] * .5 + .5, tint[2] * .5 + .5);
    gl.uniform1f(U.uEdge, Math.max(.004, .75 * 2 * EXTENT / n));   // edge lines never thinner than about a pixel
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 36, model.count);
    // Soft glow: blurred copies of the bright parts, one tight and one wide.
    const small = glowCanvas.width;
    glow2d.globalCompositeOperation = 'source-over'; glow2d.clearRect(0, 0, small, small);
    for (const [radius, alpha] of [[.012, .5], [.045, .4]]) {
      glow2d.filter = `contrast(2.6) blur(${Math.max(1.5, small * radius)}px)`; glow2d.globalAlpha = alpha;
      glow2d.drawImage(canvas, 0, 0, small, small);
    }
    rx.save(); rx.globalCompositeOperation = 'lighter'; rx.globalAlpha = clamp01(m.alpha ?? 1);
    rx.drawImage(canvas, -side / 2, -side / 2, side, side);
    rx.drawImage(glowCanvas, -side / 2, -side / 2, side, side);
    rx.restore();
    return true;
  } catch (e) { failed = true; console.warn('Orb unavailable; drawing the simple one.', e); return false; }
}

J.shellOrb = { draw, extent: EXTENT, get ready() { return !!gl && !failed && !lost; } };
})();
