/* JARVIS hologram: the sphere and what surrounds it. Builds on the J object from brain.js.
   - Sphere: translucent holographic core with flowing ribbons, responsive to speech and listening,
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
const VISUAL_MODELS = {'holographic-core':{label:'Holographic Core',theme:'violet',shader:0},'jarvis-orbit':{label:'Jarvis Orbit',theme:'cyan',shader:1},'fracture-sphere':{label:'Fracture Sphere',theme:'mark42',shader:2}};
let visualModel = store.get('visualModel','holographic-core');
if(!VISUAL_MODELS[visualModel])visualModel='holographic-core';
const profiles=store.get('visualProfiles',{});
const saveProfile=()=>{profiles[visualModel]={theme,quality:J.graphics.quality};store.set('visualProfiles',profiles);};
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
graphicsChoice.value=J.graphics.quality;graphicsChoice.onchange=()=>{J.graphics.setQuality(graphicsChoice.value);saveProfile();};
graphicsRow.append(graphicsChoice);themeRow.after(graphicsRow);
let theme = 'violet';
function setTheme(name) {
  theme = THEMES[name] ? name : 'violet';
  Object.assign(J.stateColors, THEMES[theme].states); Object.assign(J.linkColors, THEMES[theme].links);
  document.body.dataset.theme = theme; store.set('theme', theme);
  saveProfile();
  for (const b of themeRow.children) { b.classList.toggle('on', b.dataset.theme === theme); b.setAttribute('aria-pressed', b.dataset.theme === theme); }
}
// Apply the concept's palette once; subsequent colour choices still persist.
if (store.get('sphereModel', null) !== 'holographic-core') {
  store.set('theme', 'violet'); store.set('sphereModel', 'holographic-core');
}
const modelRow=make('label','Core ','graphics-quality'),modelChoice=make('select');modelChoice.setAttribute('aria-label','Core model');
for(const [name,def] of Object.entries(VISUAL_MODELS)){const option=make('option',def.label);option.value=name;modelChoice.append(option);}
function setModel(name){
  if(!VISUAL_MODELS[name])return;
  visualModel=name;store.set('visualModel',name);modelChoice.value=name;
  const profile=profiles[name];
  if(profile?.quality)J.graphics.setQuality(profile.quality);
  graphicsChoice.value=J.graphics.quality;setTheme(profile?.theme||VISUAL_MODELS[name].theme);
  document.body.dataset.coreModel=name;
}
modelChoice.onchange=()=>setModel(modelChoice.value);modelRow.append(modelChoice);themeRow.before(modelRow);setModel(visualModel);
J.on('visual-model',event=>setModel(event.model));

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
poll('/sessions', 5000, main, s => { data.sessions = Array.isArray(s?.sessions) ? s.sessions : []; J.emit('sessions',s); });
poll('/orbit', 5000, main, o => {
  data.events = Array.isArray(o?.events) ? o.events : [];
  data.track = o?.track && typeof o.track === 'object' ? o.track : null; data.trackAt = performance.now();
});
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
let moonHits = [], paneHits = [];

// Sparse triangulation is built once, then projected with the shell each frame.
const shellPoints = unitSphere(230);
const shellEdges = [];
shellPoints.forEach((p, i) => {
  const near = shellPoints.map((q, j) => ({ j, d: (p.x-q.x)**2 + (p.y-q.y)**2 + (p.z-q.z)**2 }))
    .filter(q => q.j !== i).sort((a, b) => a.d - b.d).slice(0, 4);
  for (const q of near) if (q.j > i) shellEdges.push([i, q.j]);
});

// Deterministic space layers: paint cloud textures once, move only the stars each frame.
let spaceTextures = null;
let cosmicSeed = 7023;
const cosmicRandom = () => { cosmicSeed = (Math.imul(cosmicSeed, 1664525) + 1013904223) >>> 0; return cosmicSeed / 4294967296; };
const cosmicDust = Array.from({ length: 1100 }, (_, i) => {
  const r = .08 + Math.sqrt(cosmicRandom()) * .88;
  const a = i % 3 * Math.PI * 2 / 3 + r * 5.7 + (cosmicRandom() - .5) * .7;
  return { x: Math.cos(a) * r, y: (cosmicRandom() - .5) * .12, z: Math.sin(a) * r,
    size: .4 + cosmicRandom() * 1.1, phase: cosmicRandom() * Math.PI * 2, warm: i % 13 === 0 };
});
const cosmicStars = Array.from({ length: 150 }, (_, i) => {
  const a = cosmicRandom() * Math.PI * 2, r = .26 + cosmicRandom() * .49;
  return { x: Math.cos(a) * r, y: Math.sin(a) * r * .85, depth: .25 + cosmicRandom() * .75,
    phase: cosmicRandom() * Math.PI * 2, bright: i % 19 === 0 };
});
const orbitalDust = Array.from({ length: 240 }, (_, i) => ({
  radius: 1.16 + cosmicRandom() * .5,
  incline: [-.62, .38, 1.06][i % 3] + (cosmicRandom() - .5) * .16,
  node: [0, .52, -.42][i % 3], phase: cosmicRandom() * Math.PI * 2,
  rate: (.18 + cosmicRandom() * .24) * (i % 3 === 1 ? -1 : 1),
  size: .45 + cosmicRandom() * 1.1, bright: i % 17 === 0,
}));
const shootingStars = Array.from({ length: 5 }, (_, i) => ({
  radius: 1.32 + cosmicRandom() * .28, incline: [-.55, .85, .3, -1.05, .65][i],
  node: i * .72, phase: cosmicRandom() * Math.PI * 2,
  period: 3.8 + cosmicRandom() * 2.2, offset: i * 1.19,
  duration: 1 + cosmicRandom() * .45, rate: (1.7 + cosmicRandom() * .5) * (i % 2 ? -1 : 1),
}));
function drawOrbitalDust(rx, S, t, col, build, big, project, front, energy) {
  if (!$('showStars').checked) return;
  const D = J.view.dpr || 1, still = reduced.matches;
  const position = (p, angle) => {
    const x = Math.cos(angle) * p.radius, y = Math.sin(angle) * p.radius * Math.sin(p.incline);
    return project(x*Math.cos(p.node)-y*Math.sin(p.node), x*Math.sin(p.node)+y*Math.cos(p.node),
      Math.sin(angle) * p.radius * Math.cos(p.incline));
  };
  const halo = (x, y, r, alpha) => {
    const g = rx.createRadialGradient(x,y,0,x,y,r);
    g.addColorStop(0,hex('#f5eaff',alpha*build));g.addColorStop(.16,hex(col,alpha*.85*build));g.addColorStop(1,hex(col,0));
    rx.fillStyle=g;rx.beginPath();rx.arc(x,y,r,0,Math.PI*2);rx.fill();
  };
  rx.save(); rx.globalCompositeOperation='lighter'; rx.lineCap='round';
  for (let i=0;i<orbitalDust.length;i+=big ? 1 : 3) {
    const p=orbitalDust[i], angle=p.phase+t*p.rate, head=position(p,angle);
    if ((head[2]>0)!==front) continue;
    const depth=clamp01((head[2]+1.7)/3.4), alpha=(.2+depth*.5)*build;
    const r=Math.max(D*.4,S*.0013*p.size)*(.65+depth*.5);
    if (!still && p.bright) {
      const tail=position(p,angle-p.rate*.22);
      rx.strokeStyle=hex(col,alpha*.38);rx.lineWidth=r*.8;
      rx.beginPath();rx.moveTo(tail[0],tail[1]);rx.lineTo(head[0],head[1]);rx.stroke();
    }
    rx.fillStyle=hex(p.bright ? '#ead6ff' : col,alpha);
    rx.beginPath();rx.arc(head[0],head[1],r,0,Math.PI*2);rx.fill();
    if (p.bright) halo(head[0],head[1],r*5,.55+energy*.2);
  }
  if (!still) for (let i=0;i<shootingStars.length;i+=big ? 1 : 2) {
    const p=shootingStars[i], clock=t+p.offset, age=clock%p.period;
    if (age>=p.duration) continue;
    const cycle=Math.floor(clock/p.period), fade=Math.sin(age/p.duration*Math.PI)**.7;
    const angle=p.phase+cycle*2.39996+age*p.rate;
    // Each tail follows its orbit; splitting segments by depth lets it pass behind the glass.
    const length=.48+energy*.16, steps=22;
    let prev=position(p,angle-Math.sign(p.rate)*length);
    for (let j=1;j<=steps;j++) {
      const u=j/steps, cur=position(p,angle-Math.sign(p.rate)*length*(1-u));
      if (((prev[2]+cur[2])>0)===front) {
        const alpha=fade*u*u*(front ? .9 : .3)*build;
        rx.beginPath();rx.moveTo(prev[0],prev[1]);rx.lineTo(cur[0],cur[1]);
        rx.strokeStyle=hex(col,alpha*.19);rx.lineWidth=S*.009*u;rx.stroke();
        rx.strokeStyle=hex(u>.83 ? '#e7cfff' : col,alpha);rx.lineWidth=Math.max(D*.45,S*.0021*u);rx.stroke();
      }
      prev=cur;
    }
    const head=position(p,angle);
    if ((head[2]>0)===front) {
      halo(head[0],head[1],S*.019,fade*(front ? .95 : .4));
      rx.fillStyle=hex('#fff4ff',fade*build*(front ? 1 : .4));
      rx.beginPath();rx.arc(head[0],head[1],Math.max(D*.6,S*.0022),0,Math.PI*2);rx.fill();
    }
  }
  rx.restore();
}
function getSpaceTextures() {
  if (spaceTextures) return spaceTextures;
  const paint = inner => {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 768;
    const ctx = canvas.getContext('2d'); ctx.translate(384, 384); ctx.globalCompositeOperation = 'lighter';
    const colors = ['#6752d9', '#3c72ce', '#9d479f', '#514ab9'];
    const clouds = inner ? 100 : 70;
    for (let i = 0; i < clouds; i++) {
      const u = cosmicRandom(), a = i % 3 * Math.PI * 2 / 3 + u * 5.7;
      const x = inner ? Math.cos(a) * u * 280 : (u - .5) * 520;
      const y = inner ? Math.sin(a) * u * 170 : -x * .45 + (cosmicRandom() - .5) * 180;
      const radius = (inner ? 28 : 60) + cosmicRandom() * (inner ? 65 : 105);
      const color = colors[i % colors.length], gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
      gradient.addColorStop(0, hex(color, inner ? .085 : .052));
      gradient.addColorStop(.45, hex(color, inner ? .035 : .022)); gradient.addColorStop(1, hex(color, 0));
      ctx.fillStyle = gradient; ctx.fillRect(x-radius, y-radius, radius*2, radius*2);
    }
    return canvas;
  };
  spaceTextures = { nebula: paint(false), galaxy: paint(true) };
  return spaceTextures;
}

/* GPU optical core. Local shaders, three passes: volume/surface, bloom, composite. */
const coreMotion = { at: 0, phase: 0, speed: 1, listening: 0, thinking: 0, speaking: 0, energy: 0,
  input:0, output:0, swell:0, velocity:0, activity:0, drive:0, expansion:1, sway:0, roll:0,
  lift:0, lean:0, stretch:0, color: [137,56,255] };
function advanceCore(now, pulse, color) {
  const m = coreMotion, dt = m.at ? Math.min(.05, Math.max(0, (now-m.at)/1000)) : 0; m.at = now;
  const blend = 1-Math.exp(-dt/ .7);
  for (const state of ['listening','thinking','speaking']) m[state] += ((J.view.state===state ? 1 : 0)-m[state])*blend;
  const audio=J.audio, fresh=audio?.separated && now-audio.at<350 && J.online;
  const compress=(v,floor,gain)=>1-Math.exp(-Math.max(0,v-floor)*gain);
  const input=fresh ? compress(audio.input,.004,28) : !audio?.separated && J.view.state==='listening' ? pulse : 0;
  const output=fresh ? compress(audio.output,.001,18) : !audio?.separated && J.view.state==='speaking' ? pulse : 0;
  for(const [key,target] of [['input',input],['output',output]])
    m[key]+=(target-m[key])*(1-Math.exp(-dt/(target>m[key]?.045:.24)));
  const target=Math.max(m.input,m.output);
  m.energy += (target-m.energy)*(1-Math.exp(-dt/.055));
  m.speed += ((.65 + m.thinking*2.3 + m.output*3.8 + m.input*2.1)-m.speed)*(1-Math.exp(-dt/.3));
  // A damped spring gives syllables weight without frame-dependent jitter.
  const steps=Math.max(1,Math.ceil(dt/(1/120))),step=dt/steps;
  for(let i=0;i<steps;i++){m.velocity+=((m.energy-m.swell)*100-m.velocity*15)*step;m.swell+=m.velocity*step;}
  m.swell=Math.max(0,Math.min(1.15,m.swell));
  const movement=reduced.matches?0:1;
  // State choreography is separate from measured audio: thinking moves even in silence.
  const activity=Math.max(m.swell,m.thinking*.9,m.listening*.24,m.speaking*.42);
  m.activity+=(activity-m.activity)*(1-Math.exp(-dt/.18));
  const breath=.5+.5*Math.sin(m.phase*2.4), scan=.5+.5*Math.sin(m.phase*1.65);
  m.drive=clamp01(m.energy*.5+m.activity*(.5+breath*.4));
  m.expansion=1+movement*(m.swell*.27+m.activity*breath*.18+m.thinking*scan*.12);
  m.sway=movement*(Math.sin(m.phase*.85)*.038*m.activity + Math.sin(m.phase*1.7)*.014*m.thinking);
  m.lift=movement*(-.047*m.activity + Math.sin(m.phase*1.6)*.038*m.activity);
  m.lean=movement*(Math.sin(m.phase*1.1)*.46*m.activity + m.input*.22-m.output*.16);
  m.roll=movement*(Math.sin(m.phase*.7)*.13*m.activity + Math.sin(m.phase*1.3)*.07*m.thinking);
  m.stretch=movement*Math.max(-.07,Math.min(.09,m.velocity*.025+Math.sin(m.phase*2.4)*m.activity*.035));
  for (let i=0;i<3;i++) m.color[i] += (parseInt(color.slice(1+i*2,3+i*2),16)-m.color[i])*blend;
  if (!reduced.matches) m.phase += dt*m.speed;
  return m;
}
let opticalCore = null, opticalFailed = false;
function createOpticalCore() {
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl2', { alpha:true, antialias:false, depth:false, premultipliedAlpha:true, powerPreference:'high-performance' });
  if (!gl) return null;
  const vertex = `#version 300 es
  out vec2 uv;
  void main(){ vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);uv=p;gl_Position=vec4(p*2.-1.,0.,1.); }`;
  const scene = `#version 300 es
  precision highp float;
  in vec2 uv; out vec4 frag;
  uniform float phase, energy, listening, thinking, speaking, yaw, pitch;
  uniform vec3 tint;
  uniform int model;
  const float PI=3.14159265;
  mat2 rot(float a){return mat2(cos(a),-sin(a),sin(a),cos(a));}
  float hash(vec3 p){p=fract(p*.3183099+vec3(.1,.2,.3));p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
  float noise(vec3 p){vec3 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
    return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
    mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
  float crystal(vec3 p){
    vec3 cell=floor(p),f=fract(p);float nearest=10.,second=10.;
    for(int z=-1;z<=1;z++)for(int y=-1;y<=1;y++)for(int x=-1;x<=1;x++){
      vec3 offset=vec3(x,y,z),seed=cell+offset;
      vec3 point=offset+vec3(hash(seed),hash(seed+19.7),hash(seed+47.3))*.65+.175-f;
      float d=dot(point,point);if(d<nearest){second=nearest;nearest=d;}else second=min(second,d);
    }
    float opening=model==2 ? energy*.075 : 0.;
    return 1.-smoothstep(.006+opening*.3,.035+opening,second-nearest);
  }
  vec3 turn(vec3 p){p.yz=rot(pitch)*p.yz;p.xz=rot(yaw)*p.xz;return p;}
  vec2 hit(vec3 ro,vec3 rd,float r){float b=dot(ro,rd),h=b*b-dot(ro,ro)+r*r;return h<0.?vec2(-1.):vec2(-b-sqrt(h),-b+sqrt(h));}
  // Two flowing bands, each with several fine filaments and a transparent membrane.
  vec3 ribbon(vec3 p){
    float r=length(p), y=p.y/max(r,.001), a=atan(p.z,p.x);
    float winding=a-y*(3.1+thinking*.95+speaking*.55)-phase*(.28+thinking*.12) + (.42+energy*.18)*sin(y*4.5+phase*.12)+.18*sin(a*2.+phase*.17);
    float d=abs(sin(winding*1.5));
    float radial=exp(-pow((r-(1.012+energy*.026))/.018,2.));
    float edge=exp(-pow((d-.065)/.022,2.)) + .7*exp(-pow((d-.18)/.018,2.));
    float film=exp(-pow((d-.12)/.085,2.))*.24;
    float strands=pow(.5+.5*sin(d*170.+y*9.),18.)*exp(-pow((d-.12)/.15,2.))*.5;
    float fade=1.-smoothstep(.82,1.,abs(y));
    return vec3((edge+strands)*radial*fade,film*radial*fade,exp(-pow((r-1.02)/.07,2.))*exp(-pow(d/.22,2.))*fade);
  }
  void main(){
    vec2 screen=(uv*2.-1.); vec3 ro=vec3(0,0,4.5), rd=normalize(vec3(screen*1.95,-4.5));
    vec2 bounds=hit(ro,rd,1.12); vec3 light=vec3(0);float opacity=0.;
    vec3 purple=normalize(max(tint,vec3(.001)))*vec3(.8,.44,1.25);
    if(model>0){
      vec2 surface=hit(ro,rd,1.);vec3 color=vec3(0);float alpha=0.;
      vec3 accent=normalize(max(tint,vec3(.001)));
      if(surface.x>0.){
        vec3 pos=ro+rd*surface.x,n=normalize(pos),p=turn(pos),reflected=reflect(rd,n);
        float edge=pow(1.-max(0.,dot(n,-rd)),3.);
        float spec=pow(max(0.,dot(reflected,normalize(vec3(.6,.7,1.)))),35.);
        float strip=exp(-pow((reflected.x-.6)/.16,2.))*exp(-pow((reflected.y-.3)/.55,2.))*smoothstep(0.,.4,reflected.z);
        float grain=noise(p*95.)*.016;
        color=vec3(.012,.018,.026)+grain+vec3(.65,.72,.82)*(spec*.8+strip*.55)+accent*edge*.35;
        if(model==1){
          float longitude=atan(p.z,p.x),latitude=asin(clamp(p.y,-1.,1.));
          float seams=max(1.-smoothstep(.015,.04,abs(sin(longitude*9.))),1.-smoothstep(.018,.045,abs(sin(latitude*8.))));
          color*=1.-seams*.8;color+=accent*seams*.12;
          float d=length(screen)*1.95;
          float aperture=.24+energy*.10+listening*.035;
          float ring=exp(-pow((d-aperture)/.014,2.))+exp(-pow((d-aperture-.10)/.008,2.))*.7+exp(-pow((d-aperture-.16)/.005,2.))*.5;
          float blades=pow(.5+.5*cos(atan(screen.y,screen.x)*12.-phase*2.),12.)*exp(-pow((d-.46-energy*.04)/.025,2.));
          color+=accent*(ring*(2.+energy*2.)+blades*(.5+energy*2.)+exp(-d*23.)*10.);color+=vec3(.7,.9,1.)*exp(-d*70.)*5.;
        }else{
          float seams=crystal(p*3.6+noise(p*7.)*.09),inner=crystal(p*7.);
          color*=1.-seams*.75;color+=accent*(seams*(3.+energy*5.)+inner*.035);
          color+=vec3(1.,.7,.18)*pow(seams,4.)*.8;
        }
        alpha=1.;
      }
      color=1.-exp(-color*1.25);frag=vec4(color,alpha);return;
    }
    if(bounds.x>0.){
      float stepSize=(bounds.y-bounds.x)/96.;
      for(int i=0;i<96;i++){
        vec3 world=ro+rd*(bounds.x+(float(i)+.5)*stepSize),p=turn(world);float r=length(p);
        vec3 band=ribbon(p);
        float facing=.6+.4*smoothstep(-1.,1.,world.z);
        light+=(purple*(band.x*24.+band.y*14.+band.z*1.8)+vec3(.58,.34,.95)*band.x*8.)*stepSize*facing;
        float cloud=noise(p*4.+vec3(0,phase*.04,0))*.65+noise(p*11.)*.35;
        float mist=pow(cloud,4.)*exp(-r*r*2.4)*.8;
        light+=purple*mist*stepSize;
        float nucleus=exp(-r*25.)*(24.+energy*18.);
        light+=vec3(.9,.65,1.)*nucleus*stepSize;
        float coreShell=exp(-pow((r-(.235+energy*.035))/.009,2.));
        float latitude=pow(abs(sin(p.y*48.)),22.);
        light+=purple*coreShell*(.6+latitude*2.)*stepSize*2.;
        float wave=exp(-pow((r-(.92-fract(phase*.55)*.62))/.024,2.))*listening;
        light+=purple*wave*.3*stepSize;
        // Sparse points suspended inside the crystal, kept behind the bright shell.
        vec3 cell=floor(p*49.);float star=step(.9975,hash(cell));
        float point=exp(-dot(fract(p*49.)-.5,fract(p*49.)-.5)*80.);
        light+=vec3(.6,.38,1.)*star*point*stepSize*10.*(1.-smoothstep(.6,1.,r));
      }
      // Analytic surface intersections keep the luminous ribbon edges crisp over their volume glow.
      vec2 ribbonHit=hit(ro,rd,1.012+energy*.026);
      if(ribbonHit.x>0.){
        vec3 frontBand=ribbon(turn(ro+rd*ribbonHit.x)),backBand=ribbon(turn(ro+rd*ribbonHit.y));
        light+=vec3(.66,.36,1.)*(frontBand.x*1.4+backBand.x*.32)+purple*(frontBand.y*.9+backBand.y*.25);
        light+=vec3(.7,.5,.85)*pow(frontBand.x,3.)*.45;
      }
      vec2 glassHit=hit(ro,rd,1.);
      if(glassHit.x>0.){
        vec3 pos=ro+rd*glassHit.x,normal=normalize(pos),p=turn(pos);
        float fresnel=pow(1.-max(0.,dot(normal,-rd)),3.);
        vec3 refl=reflect(rd,normal);
        // Soft studio strips reflected in the glass, like the concept's upper-right highlight.
        float strip=pow(max(0.,dot(refl,normalize(vec3(.65,.8,1.)))),65.);
        float fill=pow(max(0.,dot(refl,normalize(vec3(-.8,.25,.8)))),100.);
        float streak=exp(-pow((refl.x-.65)/.12,2.))*exp(-pow((refl.y-.42)/.45,2.))*smoothstep(0.,.2,refl.z);
        light+=vec3(.65,.52,.9)*(strip*.55+streak*.7)+purple*(fresnel*.42+fill*.3);
        float grid=crystal(p*8.);
        light+=purple*grid*.34*(.5+fresnel);
        opacity=.08+fresnel*.22+strip*.2;
      }
    }
    float d=length(screen), flare=exp(-d*30.)*.65;
    float spikes=exp(-abs(screen.x)*700.)*exp(-abs(screen.y)*11.)+exp(-abs(screen.y)*700.)*exp(-abs(screen.x)*11.);
    float coreRadius=.235+energy*.035;
    float rings=exp(-pow((d*1.95-coreRadius)/.004,2.))*.6+exp(-pow((d*1.95-coreRadius*1.16)/.002,2.))*.3;
    vec2 q=rot(.4)*screen;float optic=exp(-pow((length(vec2(q.x,q.y*2.8))*1.95-coreRadius)/.004,2.))*.35;
    light+=purple*(rings+optic)+vec3(.8,.58,1.)*(flare+spikes*.65);
    light+=vec3(.9,.72,1.)*exp(-d*75.)*2.;
    vec3 color=1.-exp(-light*1.05);
    frag=vec4(color,max(opacity,max(color.r,max(color.g,color.b))));
  }`;
  const bloom = `#version 300 es
  precision highp float;in vec2 uv;out vec4 frag;uniform sampler2D source;uniform vec2 pixel;
  void main(){vec4 sum=vec4(0);for(int i=-6;i<=6;i++){float w=exp(-float(i*i)/14.);vec4 c=texture(source,uv+vec2(float(i)*pixel.x*2.,0));sum+=c*w;}frag=sum/6.608;}`;
  const composite = `#version 300 es
  precision highp float;in vec2 uv;out vec4 frag;uniform sampler2D source,blur;uniform vec2 pixel;
  void main(){vec4 glow=vec4(0);for(int i=-6;i<=6;i++){float w=exp(-float(i*i)/14.);glow+=texture(blur,uv+vec2(0,float(i)*pixel.y*2.))*w;}glow/=6.608;
    vec4 base=texture(source,uv);vec3 color=base.rgb+glow.rgb*.3; color=min(color,vec3(1.));frag=vec4(color,max(base.a,max(color.r,max(color.g,color.b))));}`;
  const program = source => {
    const p=gl.createProgram();
    for (const [type,code] of [[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,source]]) {
      const s=gl.createShader(type);gl.shaderSource(s,code);gl.compileShader(s);
      if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)) {const message=gl.getShaderInfoLog(s);gl.deleteShader(s);gl.deleteProgram(p);throw Error(message);}
      gl.attachShader(p,s);gl.deleteShader(s);
    }
    gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(p));
    const uniforms={}; for(let i=0;i<gl.getProgramParameter(p,gl.ACTIVE_UNIFORMS);i++){const name=gl.getActiveUniform(p,i).name;uniforms[name]=gl.getUniformLocation(p,name);}
    return { p, uniforms };
  };
  let programs, targets=[], size=0, lost=false;
  const init=()=>{programs=[program(scene),program(bloom),program(composite)];size=0;targets=[];lost=false;};
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();lost=true;});
  canvas.addEventListener('webglcontextrestored',()=>{try{init();}catch(e){lost=true;console.warn('Optical core restore:',e);}});
  init();
  const resize=n=>{
    if(n===size)return;size=n;canvas.width=canvas.height=n;
    for(const target of targets){gl.deleteTexture(target.texture);gl.deleteFramebuffer(target.fbo);}targets=[];
    for(let i=0;i<2;i++){
      const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      const width=i ? n/2 : n;gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,width,width,0,gl.RGBA,gl.UNSIGNED_BYTE,null);
      const fbo=gl.createFramebuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,fbo);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,texture,0);
      if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('Optical framebuffer unavailable');
      targets.push({texture,fbo,width});
    }
  };
  return { canvas, gl, get ready(){return !lost;}, render(S,m){
    if(lost)return false;
    const budget=J.graphics.budget();
    resize(Math.max(256,Math.min(budget.max,Math.ceil(S*budget.scale/2)*2)));
    const scenePass=programs[0];gl.useProgram(scenePass.p);const u=scenePass.uniforms;
    for(const [name,value] of Object.entries({phase:m.phase,energy:m.drive,listening:m.listening,thinking:m.thinking,speaking:m.speaking,yaw:-spinner.yaw-m.phase*.08+m.lean,pitch:spinner.pitch+.12+m.lean*.7}))gl.uniform1f(u[name],value);
    const tint=visualModel==='jarvis-orbit' && theme==='cyan' ? [.03,.4,1] : visualModel==='fracture-sphere' && theme==='mark42' ? [1,.28,.015] : m.color.map(v=>v/255);
    gl.uniform3f(u.tint,...tint);
    gl.uniform1i(u.model,VISUAL_MODELS[visualModel].shader);
    gl.bindFramebuffer(gl.FRAMEBUFFER,targets[0].fbo);gl.viewport(0,0,size,size);gl.drawArrays(gl.TRIANGLES,0,3);
    gl.useProgram(programs[1].p);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,targets[0].texture);
    gl.uniform1i(programs[1].uniforms.source,0);gl.uniform2f(programs[1].uniforms.pixel,1/size,1/size);
    gl.bindFramebuffer(gl.FRAMEBUFFER,targets[1].fbo);gl.viewport(0,0,size/2,size/2);gl.drawArrays(gl.TRIANGLES,0,3);
    gl.useProgram(programs[2].p);gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,targets[1].texture);
    gl.uniform1i(programs[2].uniforms.source,0);gl.uniform1i(programs[2].uniforms.blur,1);gl.uniform2f(programs[2].uniforms.pixel,2/size,2/size);
    gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.viewport(0,0,size,size);gl.drawArrays(gl.TRIANGLES,0,3);
    return true;
  }};
}
function drawOpticalCore(rx,S,m,build) {
  if(opticalFailed)return false;
  try {
    if(!opticalCore){opticalCore=createOpticalCore();if(!opticalCore){opticalFailed=true;return false;}}
    if(!opticalCore.render(S,m))return false;
    rx.save();rx.globalCompositeOperation='source-over';rx.globalAlpha=build;
    rx.drawImage(opticalCore.canvas,-S*.49,-S*.49,S*.98,S*.98);rx.restore();return true;
  }catch(e){opticalFailed=true;console.warn('Optical core unavailable; using canvas renderer.',e);return false;}
}

function drawMetalFallback(rx,S,col,build,project) {
  if(visualModel==='holographic-core')return false;
  const R=S*.255;rx.save();rx.globalAlpha=build;
  const surface=rx.createRadialGradient(R*.4,-R*.45,R*.05,0,0,R*1.2);
  surface.addColorStop(0,'#aab8cc');surface.addColorStop(.22,'#344050');surface.addColorStop(.55,'#080e17');surface.addColorStop(1,'#202538');
  rx.fillStyle=surface;rx.beginPath();rx.arc(0,0,R,0,Math.PI*2);rx.fill();rx.clip();
  const pts=shellPoints.map(p=>project(p.x,p.y,p.z));rx.strokeStyle=col;
  rx.lineWidth=S*(visualModel==='fracture-sphere'?.003:.001);rx.shadowColor=col;rx.shadowBlur=visualModel==='fracture-sphere'?S*.012:0;
  for(const [i,j] of shellEdges){const a=pts[i],b=pts[j];if(a[2]+b[2]<0)continue;rx.beginPath();rx.moveTo(a[0],a[1]);rx.lineTo(b[0],b[1]);rx.stroke();}
  if(visualModel==='jarvis-orbit'){
    rx.shadowBlur=S*.018;rx.lineWidth=S*.004;
    for(const r of [.06,.085,.1]){rx.beginPath();rx.arc(0,0,S*r,0,Math.PI*2);rx.stroke();}
    const core=rx.createRadialGradient(0,0,0,0,0,S*.07);core.addColorStop(0,'#fff');core.addColorStop(.2,col);core.addColorStop(1,hex(col,0));
    rx.fillStyle=core;rx.fillRect(-S*.07,-S*.07,S*.14,S*.14);
  }
  rx.restore();return true;
}

function drawSphere(rx, S, t, col, pulse, spin, big) {
  const D = J.view.dpr || 1, TAU = Math.PI * 2;
  const build = reduced.matches ? 1 : ease(clamp01((performance.now() - bootAt - 250) / 2200));
  const motion = advanceCore(performance.now(), pulse, col);
  t = motion.phase; spin = 1; pulse = motion.drive;
  col = '#' + motion.color.map(v => Math.round(v).toString(16).padStart(2,'0')).join('');
  speech.copyWithin(1, 0); speech[0] = pulse;
  const listening = motion.listening, mic = motion.input;
  const R = S * .255 * (1 + pulse * .045), yaw = t * .12 * spin + spinner.yaw;
  const tilt = .18 + spinner.pitch + motion.lean*.5, cy = Math.cos(yaw), sy = Math.sin(yaw), ct = Math.cos(tilt), st = Math.sin(tilt);
  const turn = (x, y, z) => {
    const x1 = x * cy - z * sy, z1 = x * sy + z * cy;
    return [x1, y * ct - z1 * st, y * st + z1 * ct];
  };
  const project = (x, y, z) => {
    const v = turn(x, y, z), p = 4.5 / (4.5 - v[2]);
    return [v[0] * R * p, v[1] * R * p, v[2]];
  };
  const onOrbit = (radius, inc, u) => {
    const v = turn(Math.cos(u) * radius, Math.sin(u) * radius * Math.sin(inc), Math.sin(u) * radius * Math.cos(inc));
    const p = 4.5 / (4.5 - v[2] / radius);
    return [v[0] * R * p, v[1] * R * p, v[2]];
  };
  const stroke = (path, color, alpha, width) => {
    rx.strokeStyle = hex(color, alpha * build); rx.lineWidth = Math.max(.5 * D, width); rx.stroke(path);
  };
  const glow = (x, y, radius, strength) => {
    const g = rx.createRadialGradient(x, y, 0, x, y, radius);
    g.addColorStop(0, hex('#f8efff', strength * build));
    g.addColorStop(.1, hex(col, strength * .85 * build));
    g.addColorStop(.4, hex(col, strength * .24 * build)); g.addColorStop(1, hex(col, 0));
    rx.fillStyle = g; rx.beginPath(); rx.arc(x, y, radius, 0, TAU); rx.fill();
  };

  rx.save();
  const space = getSpaceTextures();
  // A broad blue/violet nebula gives the hologram a patch of deep space to float in.
  rx.save(); rx.globalCompositeOperation = 'lighter'; rx.globalAlpha = build * (big ? .28 : .18);
  const drift = Math.sin(t * .035) * .035;
  rx.translate(-S * .03, -S * .05); rx.rotate(-.12 + drift);
  rx.drawImage(space.nebula, -S * .82, -S * .65, S * 1.64, S * 1.3); rx.restore();
  if ($('showStars').checked) {
    rx.save(); rx.globalCompositeOperation = 'lighter';
    for (let i = 0; i < cosmicStars.length; i += big ? 1 : 3) {
      const p = cosmicStars[i], twinkle = .7 + Math.sin(t * .5 + p.phase) * .3;
      const x = S * (p.x + Math.sin(t*.024+p.phase)*.012*p.depth);
      const y = S * (p.y + Math.cos(t*.019+p.phase)*.009*p.depth);
      const size = Math.max(D * .45, S * .0013 * p.depth);
      rx.fillStyle = hex(i % 4 ? '#c6d5ff' : '#edc6ff', (.25+p.depth*.5)*twinkle*build);
      rx.fillRect(x, y, size, size);
      if (p.bright) {
        glow(x, y, S * .009, .55 * twinkle);
        rx.strokeStyle = hex('#dbddff', .45 * twinkle * build); rx.lineWidth = D * .6;
        rx.beginPath(); rx.moveTo(x-S*.004,y); rx.lineTo(x+S*.004,y);
        rx.moveTo(x,y-S*.005); rx.lineTo(x,y+S*.005); rx.stroke();
      }
    }
    rx.restore();
  }
  // Projector: a low, glassy plinth with concentric etched rings and reflected light.
  const baseY = S * .408;
  rx.save(); rx.translate(0, baseY); rx.scale(1, .17);
  glow(0, S * .09, S * .37, .3);
  rx.fillStyle = '#0b0918'; rx.strokeStyle = hex(col, .3 * build); rx.lineWidth = D;
  rx.beginPath(); rx.ellipse(0, S * .1, S * .272, S * .242, 0, 0, TAU); rx.fill(); rx.stroke();
  const plate = rx.createRadialGradient(0, 0, 0, 0, 0, S * .27);
  plate.addColorStop(0, hex(col, .2 * build)); plate.addColorStop(.7, '#101021'); plate.addColorStop(1, '#161329');
  rx.fillStyle = plate; rx.beginPath(); rx.arc(0, 0, S * .27, 0, TAU); rx.fill();
  rx.globalCompositeOperation = 'lighter';
  for (const [r, a] of [[.32,.2],[.268,.7],[.238,.35],[.195,.65],[.153,.3],[.085,.75]]) {
    rx.strokeStyle = hex(col, a * build); rx.lineWidth = S * .0018;
    rx.beginPath(); rx.arc(0, 0, S * r, 0, TAU); rx.stroke();
  }
  for (let i=0;i<3;i++) {
    rx.strokeStyle=hex(i ? '#cbb8ff' : col,(i ? .75 : .9)*build);rx.lineWidth=S*.003;
    rx.shadowColor=col;rx.shadowBlur=S*.012;
    rx.beginPath();rx.arc(0,0,S*(.268-i*.037),.15+i*1.9,1.1+i*1.9);rx.stroke();
  }
  rx.shadowBlur=0;
  for (let i = 0; i < 36; i++) {
    const a = i / 36 * TAU, r = S * .222;
    rx.strokeStyle = hex('#e9dfff', .5 * build); rx.lineWidth = S * .002;
    rx.beginPath(); rx.moveTo(Math.cos(a)*r, Math.sin(a)*r); rx.lineTo(Math.cos(a)*(r+S*.008), Math.sin(a)*(r+S*.008)); rx.stroke();
  }
  glow(0, 0, S * .14, .95); rx.restore();
  const beam = rx.createLinearGradient(0, R * .55, 0, baseY);
  beam.addColorStop(0, hex(col, 0)); beam.addColorStop(1, hex(col, .06 * build));
  rx.fillStyle = beam; rx.beginPath(); rx.moveTo(-R*.6, R*.55); rx.lineTo(R*.6, R*.55);
  rx.lineTo(S*.09, baseY); rx.lineTo(-S*.09, baseY); rx.closePath(); rx.fill();

  rx.globalCompositeOperation = 'lighter';
  glow(0, 0, R * 1.65, .23 + pulse * .1);
  const moons = big ? buildMoons(col) : [];
  const rings = [{ radius: 1.48, inc: .57, rate: .22, phase: 0, kind: 'agent' },
                 { radius: 1.65, inc: -.65, rate: -.16, phase: 2, kind: 'event' }];
  const orbitPaths = [new Path2D(), new Path2D()];
  for (const ring of rings) {
    let prev = null;
    for (let k = 0; k <= 100; k++) {
      const cur = onOrbit(ring.radius, ring.inc, k / 100 * TAU);
      if (prev) { const p = orbitPaths[cur[2] > 0 ? 1 : 0]; p.moveTo(prev[0], prev[1]); p.lineTo(cur[0], cur[1]); }
      prev = cur;
    }
  }
  stroke(orbitPaths[0], col, .18, S * .0012);
  drawOrbitalDust(rx, S, t, col, build, big, project, false, pulse);

  // Real document panes follow the audio-driven orbital tilt; hit regions use the same transform.
  paneHits = [];
  const content = J.panes?.visible || [];
  const panels = content.slice(0, big ? 7 : 4).map((pane, i, all) => {
    const a = i / all.length * TAU + t * .055 + .35;
    const radius=1.6 + motion.output*.32 - motion.input*.16 + motion.thinking*.14*Math.sin(t*.8+i);
    const [x, y, z] = onOrbit(radius, .72+motion.thinking*.23*Math.sin(t*.5), a);
    return { x, y: y*.72 - S*.055, z, i, a, pane };
  });
  const drawPanel = p => {
    rx.save(); rx.globalCompositeOperation = 'source-over';
    rx.translate(p.x, p.y); rx.rotate(Math.sin(p.a) * .19);
    rx.transform(.78 + .18 * Math.abs(Math.cos(p.a)), .16 * Math.cos(p.a), 0, 1, 0, 0);
    const w = S * (.122 + motion.speaking*.012), h = S * (p.i % 2 ? .139 : .104), x = -w/2, y = -h/2;
    rx.globalAlpha = (p.z > 0 ? .85 : .4) * build;
    const glass = rx.createLinearGradient(x, y, x+w, y+h);
    glass.addColorStop(0, hex(col, .21)); glass.addColorStop(.5, '#111022b0'); glass.addColorStop(1, hex(col, .08));
    rx.fillStyle = glass; rx.strokeStyle = hex(col, .8); rx.lineWidth = S * .0015;
    rx.shadowColor = col; rx.shadowBlur = S * .01; rx.fillRect(x, y, w, h); rx.strokeRect(x, y, w, h); rx.shadowBlur = 0;
    J.panes.paint(rx, p.pane, w, h);
    if (big) {
      const matrix = rx.getTransform(), box = $('reactor').getBoundingClientRect();
      const corners = [[x,y],[x+w,y],[x+w,y+h],[x,y+h]].map(([cx,cy]) => {
        const point = matrix.transformPoint({x:cx,y:cy});
        return {x:box.left+point.x/D,y:box.top+point.y/D};
      });
      paneHits.push({pane:p.pane,corners,z:p.z});
    }
    rx.restore();
  };
  panels.filter(p => p.z <= 0).forEach(drawPanel);

  rx.save();
  const expansion=motion.expansion;
  rx.translate(S*motion.sway,S*motion.lift);
  rx.rotate(motion.roll);
  rx.scale(expansion-motion.stretch,expansion+motion.stretch);
  if (!drawOpticalCore(rx, S, motion, build) && !drawMetalFallback(rx,S,col,build,project)) {
  // A small spiral galaxy lives inside the glass: dust lanes and stars at different depths.
  rx.save(); rx.beginPath(); rx.arc(0, 0, R * 1.015 * (.72 + .28 * build), 0, TAU); rx.clip();
  rx.save(); rx.rotate(-.38 + Math.sin(t*.04)*.06); rx.globalAlpha = build * .85;
  rx.drawImage(space.galaxy, -R*1.15, -R*1.15, R*2.3, R*2.3); rx.restore();
  const galaxyAngle = t * .022, gc = Math.cos(galaxyAngle), gs = Math.sin(galaxyAngle);
  const dustColors = ['#8dafff', '#c9b6ff', '#f1e5ff', '#ffd6b3'];
  for (let i = 0; i < cosmicDust.length; i += big ? 1 : 4) {
    const p = cosmicDust[i], x = p.x*gc-p.z*gs, z = p.x*gs+p.z*gc;
    const [X,Y,Z] = project(x, p.y + z*.46 - x*.26, z*.65);
    const brightness = (.3 + (Z+1)*.2) * (.8+.2*Math.sin(t*.45+p.phase));
    rx.fillStyle = dustColors[p.warm ? 3 : i%3]; rx.globalAlpha = brightness * build;
    const size = Math.max(D*.35, S*.0013*p.size) * (1+pulse*.25);
    rx.fillRect(X,Y,size,size);
  }
  rx.restore();

  // Thin irregular shell, with delayed voice displacement and inward listening waves.
  const projected = shellPoints.map((p, i) => {
    const lat = Math.abs(p.y), voice = speech[Math.min(HISTORY-1, lat*(HISTORY-1)|0)];
    let r = 1 + voice * .07 + .007 * Math.sin(t * 1.3 + i);
    if (listening) r -= (.012 + mic * .04) * Math.max(0, Math.sin(lat * 12 + t * 5));
    const b = .72 + .28 * build;
    return project(p.x*r*b, p.y*r*b, p.z*r*b);
  });
  const shell = [new Path2D(), new Path2D()];
  for (const [i, j] of shellEdges) {
    const a = projected[i], b = projected[j], path = shell[a[2]+b[2] > 0 ? 1 : 0];
    path.moveTo(a[0], a[1]); path.lineTo(b[0], b[1]);
  }
  stroke(shell[0], col, .045, S * .0009);

  // Three broad, translucent streams wind around the sphere. Draw far halves first.
  const ribbons = [[], []];
  for (let strand = 0; strand < 3; strand++) {
    const edge = [new Path2D(), new Path2D()], film = [new Path2D(), new Path2D()];
    let prev = null;
    for (let k = 0; k <= 100; k++) {
      const u = k / 100, y = -.94 + u * 1.88, radius = Math.sqrt(1-y*y) * (1.03 + pulse*.06);
      const a = u*TAU*.92 + strand*TAU/3 + t*.23*spin;
      const width = .055 + .045 * Math.sin(u*Math.PI), b = .72 + .28 * build;
      const p = project(Math.cos(a)*radius*b, y*b, Math.sin(a)*radius*b);
      const q = project(Math.cos(a+width)*radius*b, y*b, Math.sin(a+width)*radius*b);
      if (prev) {
        const side = p[2]+prev[0][2] > 0 ? 1 : 0, e = edge[side], f = film[side];
        e.moveTo(prev[0][0], prev[0][1]); e.lineTo(p[0], p[1]);
        e.moveTo(prev[1][0], prev[1][1]); e.lineTo(q[0], q[1]);
        f.moveTo(prev[0][0], prev[0][1]); f.lineTo(p[0], p[1]); f.lineTo(q[0], q[1]); f.lineTo(prev[1][0], prev[1][1]); f.closePath();
      }
      prev = [p, q];
    }
    for (let side = 0; side < 2; side++) ribbons[side].push({ edge: edge[side], film: film[side] });
  }
  const drawRibbons = side => {
    for (const r of ribbons[side]) {
      rx.fillStyle = hex(col, (side ? .14 : .04) * build); rx.fill(r.film);
      stroke(r.edge, col, side ? .08 : .025, S*.015);
      stroke(r.edge, col, side ? .22 : .06, S*.005);
      stroke(r.edge, side ? '#dbc6ff' : col, side ? .8 : .22, S*.0015);
    }
  };
  drawRibbons(0);
  const rim = new Path2D(); rim.arc(0, 0, R * 1.025 * (.72+.28*build), 0, TAU);
  stroke(rim, col, .045, S*.012); stroke(rim, col, .28, S*.0012);
  stroke(shell[1], col, .14, S * .001);
  for (let i = 0; i < projected.length; i++) {
    const [x, y, z] = projected[i];
    if (z < 0 || i % 3) continue;
    rx.fillStyle = hex(i % 9 ? col : '#eee4ff', (.3 + .35 * Math.max(0, z)) * build);
    const dot = S * .0018; rx.fillRect(x-dot/2, y-dot/2, dot, dot);
  }

  // White-hot centre, nested optical rings and a fine star flare.
  const core = R * (.23 + pulse*.07 + mic*.035);
  glow(0, 0, core * 2.5, .55 + pulse*.25);
  for (let i = 0; i < 3; i++) {
    const path = new Path2D(), r = core * (1 + i*.24);
    path.ellipse(0, 0, r, r*(i === 1 ? .42 : 1), i === 1 ? -.5 : 0, 0, TAU);
    stroke(path, '#d5baff', .65 - i*.14, S*.0013);
  }
  if (listening) {
    const wave = (t*.7)%1, path = new Path2D(); path.arc(0, 0, R*(.35 + (1-wave)*.55), 0, TAU);
    stroke(path, col, Math.sin(wave*Math.PI)*(.24+mic*.2), S*.0015);
  }
  for (let i = 0; i < 8; i++) {
    const a = i * Math.PI/4, len = core*(i%2 ? .7 : 1.7);
    const g = rx.createLinearGradient(0, 0, Math.cos(a)*len, Math.sin(a)*len);
    g.addColorStop(0, hex('#ffffff', .95*build)); g.addColorStop(1, hex(col, 0));
    rx.strokeStyle=g; rx.lineWidth=S*.0014; rx.beginPath(); rx.moveTo(0,0); rx.lineTo(Math.cos(a)*len, Math.sin(a)*len); rx.stroke();
  }
  glow(0, 0, core*.65, 1);
  rx.fillStyle=hex('#ffffff', build); rx.beginPath(); rx.arc(0,0, S*(.0035+pulse*.002),0,TAU); rx.fill();
  drawRibbons(1);
  }
  rx.restore();
  // Wide, slow wavefronts: draw inward as you speak, radiate outward with Jarvis.
  if(!reduced.matches && motion.activity>.015){
    for(let i=0;i<4;i++){
      const travel=(t*.52+i/4)%1, inward=motion.input>motion.output || motion.listening>.5 && motion.output<.05;
      const radius=1.08+(inward?1-travel:travel)*.82;
      const path=new Path2D();
      for(let k=0;k<=100;k++){
        const a=k/100*TAU,[x,y]=onOrbit(radius,.28+Math.sin(t*.16)*.12+motion.thinking*Math.sin(t*.6+i)*.65,a);
        if(!k)path.moveTo(x,y+S*motion.lift);else path.lineTo(x,y+S*motion.lift);
      }
      stroke(path,col,Math.sin(travel*Math.PI)*motion.activity*.62,S*.0028);
    }
  }
  stroke(orbitPaths[1], col, .38, S*.0012);
  drawOrbitalDust(rx, S, t, col, build, big, project, true, pulse);
  for (let i = 0; i < 16; i++) {
    const ring = rings[i%2], a = i/8*TAU + t*ring.rate;
    const [x,y,z] = onOrbit(ring.radius, ring.inc, a);
    glow(x, y, S*(i%4 ? .007 : .012), z>0 ? .8 : .25);
  }
  panels.filter(p => p.z > 0).forEach(drawPanel);
  rx.restore();

  moonHits = [];
  if (!big) return;
  if(!document.body.classList.contains('compact-orb'))drawGauges(rx, S, col, build);
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
const paneAt = (x,y) => paneHits.filter(hit => {
  const signs=hit.corners.map((a,i)=>{const b=hit.corners[(i+1)%4];return (b.x-a.x)*(y-a.y)-(b.y-a.y)*(x-a.x);});
  return signs.every(v=>v>=0)||signs.every(v=>v<=0);
}).sort((a,b)=>b.z-a.z)[0];
const moonAt = (x, y) => moonHits.filter(h => Math.hypot(h.x - x, h.y - y) < h.r * 1.8).sort((a, b) => b.z - a.z)[0];
rc.addEventListener('pointerdown', e => {
  if (!main() || e.button !== 0) return;
  grab = { id: e.pointerId, x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, moved: false };
  rc.setPointerCapture(e.pointerId);
});
rc.addEventListener('pointermove', e => {
  if (!main()) return;
  if (!grab) { const pane=paneAt(e.clientX,e.clientY); if(pane)J.panes.select(pane.pane.id); rc.style.cursor = moonAt(e.clientX, e.clientY) || pane ? 'pointer' : 'grab'; return; }
  if (!grab.moved && Math.hypot(e.clientX - grab.sx, e.clientY - grab.sy) > 4) { grab.moved = true; hand.begin(performance.now()); rc.style.cursor = 'grabbing'; }
  if (grab.moved) hand.move(e.clientX - grab.x, e.clientY - grab.y, performance.now());
  grab.x = e.clientX; grab.y = e.clientY;
});
rc.addEventListener('pointerup', e => {
  if (!grab) return;
  if (grab.moved) hand.end(performance.now());
  else { const hit = moonAt(e.clientX, e.clientY), pane=paneAt(e.clientX,e.clientY); if (hit) showCard(hit); else if(pane)J.panes.focus(pane.pane.id); else hideCard(); }
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

J.holo = { drawSphere, hand, setTheme, setModel, showCard, themes: Object.keys(THEMES),
  get model(){return visualModel;},
  get renderer() { return opticalCore?.ready && !opticalFailed ? 'webgl2' : 'canvas2d'; },
  get motion() { return { ...coreMotion, color: [...coreMotion.color] }; },
  get moons() { return moonHits; }, get beams() { return beams; } };
})();
