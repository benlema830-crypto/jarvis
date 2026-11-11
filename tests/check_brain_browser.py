"""Drive the real Brain page in headless Chrome against an inert fake backend.

Nothing here talks to the running assistant, a camera, the screen or any account.
Run:  .venv\\Scripts\\python.exe tests\\check_brain_browser.py      (prints PASS or the failing step)
Optional: --screenshot out.png saves a 1660x896 capture of the loaded page.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import copy
import psutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from graph_organization import organize
CHROME = next((p for p in (Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                           Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
                           Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")) if p.is_file()), None)

NODES = [
    {"id": "root", "label": "JARVIS", "kind": "Core", "group": "JARVIS", "body": "Core", "degree": 3},
    {"id": "vault", "label": "Obsidian vault", "kind": "Core", "group": "JARVIS", "body": "Vault", "degree": 3},
    {"id": "folder:Projects", "label": "Projects", "kind": "Folder", "group": "Projects", "body": "Folder", "degree": 3},
    {"id": "note:Projects/Alpha.md", "label": "Alpha", "kind": "Note", "group": "Projects", "body": "# Alpha\nAlpha links to [[Beta]].",
     "source": "Projects/Alpha.md", "uri": "obsidian://open?path=Alpha", "degree": 2},
    {"id": "note:Projects/Beta.md", "label": "Beta", "kind": "Note", "group": "Projects", "body": "# Beta\nBeta body.",
     "source": "Projects/Beta.md", "uri": "obsidian://open?path=Beta", "degree": 3},
    {"id": "note:Gamma.md", "label": "Gamma", "kind": "Note", "group": "Notes", "body": "Gamma mentions Beta.",
     "source": "Gamma.md", "uri": "obsidian://open?path=Gamma", "degree": 1},
    {"id": "memory", "label": "Long-term memory", "kind": "Memory", "group": "Memory", "body": "Facts", "degree": 2},
    {"id": "memory-0", "label": "Likes tea", "kind": "Memory", "group": "Memory", "body": "Likes tea", "degree": 1},
]
LINKS = [
    {"source": "root", "target": "vault"}, {"source": "vault", "target": "folder:Projects"},
    {"source": "folder:Projects", "target": "note:Projects/Alpha.md"}, {"source": "folder:Projects", "target": "note:Projects/Beta.md"},
    {"source": "note:Projects/Alpha.md", "target": "note:Projects/Beta.md", "kind": "note-link"},
    {"source": "note:Projects/Beta.md", "target": "note:Gamma.md", "kind": "note-link"},
    {"source": "root", "target": "memory"}, {"source": "memory", "target": "memory-0"},
]

CHECK = r'''<script>
window.EventSource = class { constructor() { window.testStream = this; setTimeout(() => { this.onopen?.(); this.emit({ type: 'hello', state: 'standby', history: [] }); }, 50); }
  addEventListener() {} emit(v) { this.onmessage?.({ data: JSON.stringify(v) }); } close() {} };
addEventListener('error', e => document.documentElement.dataset.scriptError = e.message);
addEventListener('load', async () => {
  const stage = s => document.documentElement.dataset.stage = s;
  const wait = async (f, what) => { for (let i = 0; i < 200; i++) { if (f()) return; await new Promise(r => setTimeout(r, 25)); } throw Error('Timed out: ' + what); };
  const assert = (c, m) => { if (!c) throw Error(m); };
  const $ = id => document.getElementById(id);
  try {
    stage('load'); await wait(() => J.graph.nodes.length === 8, 'graph load');
    assert(!document.documentElement.dataset.scriptError, 'Script error: ' + document.documentElement.dataset.scriptError);
    assert($('filters').children.length === 4, 'filter rows');
    assert($('hubs').children.length >= 4, 'project overview hubs');
    const box = s => document.querySelector(s).getBoundingClientRect();
    assert(box('.left').width >= 270 && box('.right').width >= 215, 'readable sidebar sizes');
    assert(parseFloat(getComputedStyle($('search')).fontSize) >= 14, 'readable search text');
    assert(box('.toolbar').top < 30 && box('.dock').bottom <= innerHeight, 'toolbar/dock placement');
    assert(box('.dock').left > box('.left').right && box('.dock').right < box('.right').left, 'dock clears sidebars');
    assert(!document.body.innerHTML.includes('<script>alert'), 'unsafe');

    stage('organized graph');
    assert(G.scope==='projects' && G.shown.size===5,'compact project overview by default');
    assert(G.byId.get('root').label==='Jarvis Assistant','assistant label is unambiguous');
    assert(!$('hubs').querySelector('.relation-label'),'hub list does not show array positions as relationships');
    assert(!J.isNodeVisible(G.byId.get('memory-0')),'memory details initially collapsed');
    [...$('hubs').querySelectorAll('button')].find(b=>b.textContent.includes('Saved memories')).click();
    assert(J.isNodeVisible(G.byId.get('memory-0')),'click expands a group');
    $('inspector').querySelector('.group-toggle').click();
    assert(!J.isNodeVisible(G.byId.get('memory-0')),'inspector collapses group');
    $('search').value='Likes tea';$('search').dispatchEvent(new Event('input'));
    $('searchResults').querySelector('button').click();
    assert(J.isNodeVisible(G.selected)&&G.expanded.has('memory'),'search reveals a collapsed result');
    $('collapseGroups').click();
    J.select(G.byId.get('note:Projects/Beta.md'));
    assert(J.isNodeVisible(G.byId.get('note:Gamma.md')),'project expands referenced knowledge');
    assert($('inspector').textContent.includes('References'),'inspector explains relationships');
    $('scopeVault').click();
    assert(!J.isNodeVisible(G.byId.get('memory-0'))&&J.isNodeVisible(G.byId.get('note:Gamma.md')),'vault remains available');
    $('scopeAll').click();
    assert(G.shown.size===G.nodes.length&&G.hidden.size===0,'show everything reveals every indexed node');
    assert(JSON.parse(localStorage.getItem('jarvis.graphScope'))==='all','show everything choice saved');
    await load(true);assert(G.shown.size===G.nodes.length&&G.scope==='all','refresh retains full view');
    $('search').value='';search();clearSelection();

    stage('graph momentum');
    // Synthetic input exercises the real handlers; capture itself needs a hardware pointer.
    const graph = $('graph'), captures = new Set();
    graph.setPointerCapture = id => captures.add(id);
    graph.hasPointerCapture = id => captures.has(id);
    graph.releasePointerCapture = id => captures.delete(id);
    const pointer = (type, x, y, button = 0) => graph.dispatchEvent(new PointerEvent(type,
      {pointerId: 91, pointerType: 'mouse', clientX: x, clientY: y, button, buttons: type === 'pointerup' ? 0 : 1}));
    G.orbit = false; settling = 0; G.cam.goal = G.cam.follow = null;
    pointer('pointerdown', 780, 350); pointer('pointermove', 830, 365); pointer('pointerup', 830, 365);
    const yaw = G.cam.yaw, velocity = Math.abs(G.cam.velocityYaw);
    assert(velocity > .1, 'flick starts momentum');
    stepCamera(1 / 60);
    assert(G.cam.yaw > yaw && Math.abs(G.cam.velocityYaw) < velocity, 'rotation continues and slows after release');
    for (let i = 0; i < 240; i++) stepCamera(1 / 60);
    assert(G.cam.velocityYaw === 0, 'rotation settles');
    pointer('pointerdown', 780, 350); pointer('pointermove', 830, 350);
    drag.at -= 150; pointer('pointerup', 830, 350);
    assert(G.cam.velocityYaw === 0, 'holding before release prevents fling');
    pointer('pointerdown', 780, 350); pointer('pointermove', 830, 350); pointer('pointercancel', 830, 350);
    assert(!drag && G.cam.velocityYaw === 0, 'cancel stops momentum');
    pointer('pointerdown', 780, 350, 2); pointer('pointermove', 810, 350, 2); pointer('pointerup', 810, 350, 2);
    assert(G.cam.velocityYaw === 0, 'pan does not start rotation');
    pointer('pointerdown', 780, 350); pointer('pointermove', 830, 350); pointer('pointerup', 830, 350);
    pointer('pointerdown', 780, 350);
    assert(G.cam.velocityYaw === 0, 'new grab stops the previous fling');
    pointer('pointercancel', 780, 350);
    Object.defineProperty(reduced, 'matches', {value:true, configurable:true});
    pointer('pointerdown', 780, 350); pointer('pointermove', 830, 350); pointer('pointerup', 830, 350);

    assert(G.cam.velocityYaw === 0, 'reduced motion disables coast');
    delete reduced.matches;
    stage('elastic node dragging');
    G.cam.goal = G.cam.follow = null;
    const savedNodes = G.nodes.map(n => ({n, x:n.x, y:n.y, z:n.z}));
    const grab = G.byId.get('note:Projects/Alpha.md');
    const neighbor = G.byId.get('note:Projects/Beta.md');
    G.cam.yaw = .8; G.cam.pitch = -.3; G.cam.zoom = 1.4;
    project(grab);
    const gx = grab.sx, gy = grab.sy, cameraYaw = G.cam.yaw, neighborX = neighbor.x, neighborY = neighbor.y;
    for (const n of G.nodes) if (n !== grab) n.sx = n.sy = -10000;
    pointer('pointerdown', gx, gy);
    assert(drag.node === grab, 'node is grabbed instead of orbiting');
    pointer('pointermove', gx + 110, gy + 55);
    project(grab);
    assert(Math.hypot(grab.sx - gx - 110, grab.sy - gy - 55) < .001, 'grab tracks cursor at rotated camera and zoom');
    for (let i=0;i<35;i++) simulate();
    project(grab);
    assert(Math.hypot(grab.sx - gx - 110, grab.sy - gy - 55) < .001, 'springs cannot move held node');
    assert(Math.hypot(neighbor.x-neighborX, neighbor.y-neighborY)>1, 'connected nodes follow the pull');
    assert(G.cam.yaw === cameraYaw, 'node drag does not rotate camera');
    pointer('pointerup', gx + 110, gy + 55);
    const released = {x:grab.x,y:grab.y,z:grab.z};
    for (let i=0;i<30;i++) simulate();
    assert(Math.hypot(grab.x-released.x,grab.y-released.y,grab.z-released.z)>.1,'released node relaxes with graph');
    for (const mode of [true,false]) {
      G.is3d=mode;const root=G.byId.get('root');project(root);
      for (const n of G.nodes) if(n!==root)n.sx=n.sy=-10000;
      const x=root.sx,y=root.sy;pointer('pointerdown',x,y);pointer('pointermove',x+70,y+25);simulate();project(root);
      assert(Math.hypot(root.sx-x-70,root.sy-y-25)<.001,'root can be pulled in 2D and 3D');
      pointer('pointercancel',x+70,y+25);assert(!drag,'cancel releases held node');
    }
    G.is3d=true;
    for (const s of savedNodes) Object.assign(s.n,{x:s.x,y:s.y,z:s.z,vx:0,vy:0,vz:0});
    G.nodes.forEach(project);fit();
    delete graph.setPointerCapture; delete graph.hasPointerCapture; delete graph.releasePointerCapture;

    stage('search'); $('search').value = 'beta'; $('search').dispatchEvent(new Event('input'));
    await wait(() => $('searchResults').querySelector('button'), 'search results');
    $('searchResults').querySelector('button').click();
    assert(J.graph.selected?.label === 'Beta', 'search select');
    assert($('inspector').textContent.includes('Beta') && $('inspector').querySelector('a[href^="obsidian:"]'), 'inspector note link');
    const depth1 = J.graph.focus.size; [...$('inspector').querySelectorAll('.depth button')][2].click();
    assert(J.graph.focus.size > depth1, 'depth 3 widens focus');

    stage('path'); J.select(J.graph.byId.get('note:Gamma.md'));
    tracePath(J.graph.byId.get('note:Gamma.md'), J.graph.byId.get('memory-0'));
    assert(J.graph.path && J.graph.path[0] === 'note:Gamma.md' && J.graph.path.at(-1) === 'memory-0', 'path trace');
    assert($('inspector').textContent.includes('Path ('), 'path shown');

    stage('filter'); [...$('filters').children].find(b => b.dataset.group==='Memory').click();
    assert(J.graph.hidden.has('Memory') && !J.graph.selected?.group?.includes('Memory'), 'filter hides group');
    [...$('filters').children].find(b => b.dataset.group==='Memory').click();

    stage('sources'); window.testStream.emit({ type: 'knowledge', status: 'found', sources: [{ path: 'Projects/Alpha.md', title: '<b>Alpha</b>', excerpt: '<scr' + 'ipt>alert(1)</scr' + 'ipt>', uri: 'obsidian://open?path=Alpha' }] });
    assert(!$('sourcesBox').hidden && J.graph.selected?.id === 'note:Projects/Alpha.md', 'knowledge focus');
    assert($('sourcesList').querySelector('button').textContent === '<b>Alpha</b>', 'source rendered as text');
    window.testStream.emit({ type: 'sources', sources: [{ title: 'Good', url: 'https://example.com' }, { title: 'Bad', url: 'javascript:alert(1)' }] });
    assert($('sourcesList').querySelectorAll('a').length === 1, 'unsafe citation filtered');
    $('clearSources').click(); assert($('sourcesBox').hidden && !J.graph.selected, 'sources clear');

    stage('chat'); window.testStream.emit({ type: 'you', text: 'Hello there', t: 1 });
    window.testStream.emit({ type: 'jarvis', text: 'Good evening.', t: 2 }); window.testStream.emit({ type: 'jarvis', text: 'All systems nominal.', t: 3 });
    assert($('replyText').textContent === 'Good evening. All systems nominal.', 'reply bubble accumulates');
    $('historyToggle').click(); assert(!$('chatLog').hidden && $('chatLog').children.length === 3, 'history');
    window.testStream.emit({ type: 'tool', name: 'web_search', t: 4 }); assert(!$('activityCount').hidden, 'activity badge');
    window.testStream.emit({ type: 'state', state: 'thinking' }); assert(document.body.dataset.state === 'thinking', 'state');

    stage('command'); $('prompt').value = 'TEST COMMAND'; $('command').requestSubmit();
    await wait(() => window.posts.some(p => p.path === '/command' && p.body.text === 'TEST COMMAND'), 'command post');
    assert($('prompt').value === '', 'prompt cleared');
    $('micBtn').click(); await wait(() => window.posts.some(p => p.path === '/settings'), 'mic toggle');

    stage('look'); assert(document.querySelector('[data-look=sphere]').classList.contains('on'), 'sphere is the default look');
    document.querySelector('[data-look=face]').click(); assert(document.querySelector('[data-look=face]').classList.contains('on'), 'face look');
    document.querySelector('[data-look=sphere]').click();

    stage('stage swap'); $('stageSlot').click();
    await wait(() => document.body.classList.contains('jarvis-main'), 'JARVIS becomes the main view');
    const slot = $('stageSlot').getBoundingClientRect(), mini = $('graph').getBoundingClientRect(), big = $('reactor').getBoundingClientRect();
    assert(Math.abs(mini.left - slot.left) < 2 && Math.abs(mini.width - slot.width) < 2, 'graph shrinks into the hologram slot');
    assert(big.width === innerWidth && big.height === innerHeight, 'hologram fills the screen');
    assert($('reactor').width === Math.round(innerWidth * Math.min(devicePixelRatio || 1, 2)), 'hologram redrawn at full size');
    $('stageSlot').click();
    await wait(() => !document.body.classList.contains('jarvis-main') && $('stageSlot').contains($('reactor')), 'graph is the main view again');
    assert($('graph').getBoundingClientRect().width === innerWidth, 'graph fills the screen again');

    stage('themes'); assert(J.holo && document.querySelectorAll('.themes button').length === 5, 'theme picker');
    assert(document.body.dataset.theme === 'violet', 'holographic core starts violet');
    document.querySelector('.themes [data-theme=mark42]').click();
    assert(document.body.dataset.theme === 'mark42' && J.stateColors.standby === '#f59e0b' && J.linkColors.note === '#f59e0b', 'mark 42 theme');
    document.querySelector('.themes [data-theme=cyan]').click(); assert(J.stateColors.standby === '#5eead4', 'cyan theme');

    stage('core transitions');
    stage('real holographic panels');
    await wait(()=>J.panes?.visible.some(p=>p.kind==='note'),'real note panes');
    await J.panes.focus('note:Projects/Alpha.md');
    assert($('holoPaneDialog').open && $('holoPaneDialog').textContent.includes('Alpha links to'), 'expanded pane reads real note');
    J.panes.dismiss('note:Projects/Alpha.md');
    assert(!$('holoPaneDialog').open && !J.panes.visible.some(p=>p.id==='note:Projects/Alpha.md'),'dismiss removes pane');
    J.panes.add({id:'test-unsafe',title:'Literal text',kind:'research',body:'<script>alert(1)<\/script>'},true);
    await J.panes.focus('test-unsafe');
    assert($('holoPaneDialog').textContent.includes('<script>') && !$('holoPaneDialog').querySelector('script'),'pane text is inert');
    J.panes.dismiss('test-unsafe');
    J.emit('project-resume',{project:'Jarvis',summary:'Saved progress',summary_source:'Test handoff',unresolved:'Audio pending',next_action:'Run checks',files:[],verified:[],interpretation:'Saved claim'});
    assert($('resumeDialog').open && $('resumeDialog').textContent.includes('Run checks'),'resume restores recorded next action');
    $('resumeDialog').close();
    if(J.view.jarvisMain)setStage(false,false);
    stage('core transitions');
    J.emit('resources', {active:['synthesis']});
    assert(J.graphics.budget().fps === 24 && J.graphics.budget().max === 512, 'graphics yields to speech synthesis');
    J.emit('resources', {active:[]});
    assert(J.graphics.budget().fps === 24, 'graphics holds reduced budget to prevent oscillation');
    J.graphics.busyUntil = 0; J.graphics.setQuality('economy');
    assert(J.graphics.budget().fps === 30, 'saved economy budget');
    J.graphics.setQuality('auto');
    const beforeCore = J.holo.motion;
    uiState = 'thinking'; drawReactor(10000);
    assert(J.holo.motion.phase - beforeCore.phase < .15, 'state change preserves rotation phase');
    await new Promise(r => setTimeout(r, 80)); drawReactor(10001);
    assert(J.holo.motion.thinking > 0 && J.holo.motion.thinking < 1, 'thinking blends in gradually');
    const thinkingCore = J.holo.motion.thinking;
    uiState = 'listening'; await new Promise(r => setTimeout(r, 80)); drawReactor(10002);
    assert(J.holo.motion.thinking > 0 && J.holo.motion.thinking < thinkingCore, 'thinking blends out');
    assert(J.holo.motion.listening > 0 && J.holo.motion.listening < 1, 'listening blends in');
    assert(['webgl2', 'canvas2d'].includes(J.holo.renderer), 'core renderer available');
    uiState = 'standby';

    stage('cinematic audio motion');
    const audioBurst=async(input,output,count=7)=>{
      window.motionTestState=uiState;
      const frames=[];
      for(let i=0;i<count;i++){
        window.testStream.emit({type:'level',v:Math.max(input,output),input,output});
        await new Promise(r=>setTimeout(r,65));drawReactor(performance.now()/1000);
        frames.push(J.holo.motion);
      }
      return frames;
    };
    for(const model of ['holographic-core','jarvis-orbit','fracture-sphere']){
      J.holo.setModel(model);uiState='thinking';
      const thought=await audioBurst(0,0,32);
      assert(J.holo.motion.energy<.02 && J.holo.motion.activity>.5,'thinking moves without invented audio for '+model+': '+JSON.stringify(J.holo.motion));
      const sizes=thought.slice(-12).map(m=>m.expansion);
      assert(Math.max(...sizes)-Math.min(...sizes)>.025,'thinking visibly breathes for '+model);
      uiState='standby';await audioBurst(.06,0);
      assert(J.holo.motion.input>.6,'microphone drives '+model+' even before wake word');
      assert(J.holo.motion.swell>.45 && Math.abs(J.holo.motion.lift)>.005,'visible displacement for '+model);
      uiState='speaking';await audioBurst(0,.08);
      assert(J.holo.motion.output>.6 && J.holo.motion.input<.2,'separate speech reaction for '+model);
      assert(J.holo.motion.expansion>1.16,'speech has a much larger physical pulse for '+model);
    }
    J.audio.at=performance.now()-1000;uiState='standby';
    window.motionTestState='standby';
    for(let i=0;i<30;i++){await new Promise(r=>setTimeout(r,65));drawReactor(performance.now()/1000);}
    assert(J.holo.motion.energy<.01 && J.holo.motion.swell<.015,'stale/disconnected audio settles to rest');
    J.holo.setModel('holographic-core');
    delete window.motionTestState;

    stage('moons'); $('stageSlot').click(); await wait(() => document.body.classList.contains('jarvis-main'), 'main view for moons');
    await wait(() => J.holo.moons.length === 4, 'agent, event and song moons (' + J.holo.moons.length + ')');
    const moonKinds = J.holo.moons.map(h => h.m.kind).sort().join();
    assert(moonKinds === 'agent,agent,event,track', 'moon kinds ' + moonKinds);
    const song = J.holo.moons.find(h => h.m.kind === 'track');
    J.holo.showCard(song); assert(!document.querySelector('.moon-card').hidden && document.querySelector('.moon-card').textContent.includes('Thunderstruck'), 'song card');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    document.querySelector('.moon-card .moon-close')?.click(); assert(document.querySelector('.moon-card').hidden, 'card closes');

    stage('holo reply'); window.testStream.emit({ type: 'you', text: 'Status?', t: 2 }); window.testStream.emit({ type: 'jarvis', text: 'Systems nominal, sir.', t: 3 });
    const holoText = () => document.querySelector('.holo-reply').textContent;
    // Headless Chrome barely advances animation frames, so step the per-frame work directly.
    await wait(() => { J.emit('frame'); return holoText().length > 1 && 'Systems nominal, sir.'.startsWith(holoText()); }, 'reply types out under the sphere');
    assert(!document.querySelector('.holo-reply').hidden && $('replyText').offsetParent === null, 'holo reply replaces the dock text in the main view');

    stage('beams'); window.testStream.emit({ type: 'knowledge', status: 'found', sources: [{ path: 'Projects/Alpha.md', title: 'Alpha' }] });
    assert(J.holo.beams.some(b => b.id === 'note:Projects/Alpha.md'), 'beam to the note being read');
    $('stageSlot').click(); await wait(() => !document.body.classList.contains('jarvis-main'), 'graph main again');

    stage('armory'); $('armoryBtn').click(); assert($('armoryDialog').open, 'armory open');
    await wait(() => document.querySelectorAll('#armoryDialog .tile').length > 16, 'armory tiles');
    assert($('armoryDialog').textContent.includes('Add your own tool') && $('armoryDialog').textContent.includes('Telegram'), 'connect section');
    assert([...document.querySelectorAll('#armoryDialog .tile')].find(t => t.textContent.includes('Telegram')).querySelector('.chip').textContent === '+', 'Telegram not falsely connected');
    await wait(() => [...document.querySelectorAll('#armoryDialog .tile')].find(t => t.textContent.includes('Saved test server')), 'saved MCP tile');
    assert([...document.querySelectorAll('#armoryDialog .tile')].find(t => t.textContent.includes('Saved test server')).querySelector('.chip').textContent === 'configured', 'saved discovery is not live connectivity');
    assert($('armoryDialog').querySelector('small').textContent === '1 saved MCP connections', 'armory count describes saved configuration');
    [...document.querySelectorAll('#armoryDialog .tile')].find(t => t.textContent.includes('Add your own tool')).click();
    assert($('mcpDialog').open, 'mcp dialog');
    $('mcp_name').value = 'Test'; $('mcp_url').value = 'https://example.com/mcp'; $('mcp_token').value = 'secret';
    document.querySelector('#mcpDialog form').requestSubmit();
    await wait(() => !$('mcpDialog').open, 'mcp connect'); assert(!$('mcp_token').value && !$('mcp_url').value, 'mcp secrets cleared');
    stage('oauth');
    const openOAuth = () => {
      [...document.querySelectorAll('#armoryDialog .tile')].find(t => t.textContent.includes('Add your own tool')).click();
      $('mcp_auth').value = 'oauth'; $('mcp_auth').dispatchEvent(new Event('change'));
      assert($('mcp_token').hidden, 'bearer token hidden for OAuth');
      $('mcp_name').value = 'OAuth test'; $('mcp_url').value = 'https://example.com/mcp';
      document.querySelector('#mcpDialog form').requestSubmit();
    };
    openOAuth();
    await wait(() => !$('mcp_oauth_link').hidden, 'OAuth sign-in link');
    assert($('mcp_oauth_link').href === 'https://example.com/authorize?state=fake', 'authorization link');
    assert($('mcp_oauth_link').rel.includes('noreferrer'), 'OAuth link does not send referrer');
    $('mcpDialog').close();
    await wait(() => window.posts.some(p => p.path === '/mcp/oauth' && p.body.action === 'cancel'), 'OAuth cancellation on close');
    assert(!$('mcp_oauth_link').hasAttribute('href'), 'OAuth link cleared');
    openOAuth();
    await wait(() => !$('mcpDialog').open, 'OAuth completion');
    assert($('armoryDialog').textContent.includes('OAuth saved'), 'OAuth result shown');
    $('armoryDialog').close();

    stage('model'); $('modelPill').click(); await wait(() => $('modelDialog').textContent.includes('Active: codex'), 'model status');
    const provider = $('modelDialog').querySelector('select');
    assert([...provider.options].find(o => o.value === 'openai').disabled, 'paid API blocked');
    assert(![...provider.options].find(o => o.value === 'ollama').disabled, 'local provider allowed');
    provider.value = 'ollama'; provider.dispatchEvent(new Event('change'));
    assert($('modelDialog').querySelectorAll('select')[1].value === 'local:test', 'local model listed');
    $('modelDialog').close();

    stage('holo mode'); assert(document.querySelectorAll('.mode').length === 1, 'only the HOLO mode is left');
    assert(!document.querySelector('[data-mode=eyes],[data-mode=watch],[data-mode=focus]'), 'removed modes are gone');
    document.querySelector('[data-mode=holo]').click(); assert(!$('modePanel').hidden, 'holo panel');
    assert($('modePanel').textContent.includes('Control this second brain with your hands') && document.querySelector('[data-mode=holo] em').textContent === 'off', 'holo panel, camera untouched');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    assert($('modePanel').hidden, 'escape closes panel');

    stage('tidy layout');
    assert(document.querySelectorAll('.command-row .round').length === 5, 'five dock buttons: mic, stop, activity, agents, more');
    assert(!$('screenBtn') && !document.querySelector('.command-row #armoryBtn'), 'screen and armory left the dock');
    assert(!$('graphSettings').open && $('graphSettings').contains($('repel')) && $('graphSettings').contains($('showStars')), 'graph settings folded away');
    assert(!$('lookSettings').open && $('lookSettings').contains(document.querySelector('.appearance')) && $('lookSettings').contains(document.querySelector('.themes')), 'appearance folded away');
    assert(document.querySelectorAll('.scope button').length === 3, 'one row of three scope choices');

    stage('menu'); $('moreBtn').click(); assert(!$('moreMenu').hidden, 'menu');
    const groups = [...$('moreMenu').querySelectorAll('.menu-group:not([hidden])')].map(g => g.querySelector('small').textContent);
    assert(groups.join() === 'Projects,Jarvis,View,Tools', 'menu grouped: ' + groups.join());
    assert(!/Next steps|Scheduled digests|File tools|Keyboard:/.test($('moreMenu').textContent), 'stale menu entries removed');
    assert($('moreMenu').querySelector('[data-group=tools]').contains($('armoryBtn')), 'armory lives in the menu');
    [...$('moreMenu').querySelectorAll('button')].find(b => b.textContent === 'Voice health').click();
    assert($('healthDialog').open && $('healthDialog').textContent.includes('Mock mic'), 'health');
    const healthButton=label=>[...$('healthDialog').querySelectorAll('button')].find(b=>b.textContent===label);
    const pacing=$('healthDialog').querySelector('[aria-label="Pause before responding (seconds)"]');
    await wait(()=>pacing.value==='1.2','pacing loaded');pacing.value='1.4';healthButton('Save pacing').click();
    await wait(()=>window.posts.some(p=>p.path==='/conversation-settings' && p.body.pause_seconds===1.4),'pacing saved');
    healthButton('Reconnect microphone').click();
    await wait(()=>window.posts.some(p=>p.path==='/voice-recovery' && p.body.component==='microphone'),'microphone recovery');
    $('healthDialog').close();
    stage('saved visual models');
    J.holo.setModel('fracture-sphere');J.holo.setTheme('violet');
    J.holo.setModel('jarvis-orbit');assert(J.holo.model==='jarvis-orbit','orbit selected');
    J.holo.setModel('fracture-sphere');assert(document.body.dataset.theme==='violet','per-model palette restored');
    assert(JSON.parse(localStorage.getItem('jarvis.visualModel'))==='fracture-sphere','model persisted');
    J.holo.setModel('holographic-core');
    stage('job controls');$('agentsBtn').click();
    await wait(()=>$('agentsDialog').textContent.includes('Reading source'),'observed milestone displayed');
    [...$('agentsDialog').querySelectorAll('button')].find(b=>b.textContent==='Pause').click();
    await wait(()=>window.posts.some(p=>p.path==='/session-control' && p.body.action==='pause' && p.body.name==='Frontier'),'pause requested');
    $('agentsDialog').close();

    stage('project tools'); $('projectToolsBtn').click();
    const clickTool = label => [...$('projectToolsDialog').querySelectorAll('button')].find(b => b.textContent === label).click();
    assert(!$('routineSelect') && !$('projectToolsDialog').textContent.includes('routine'), 'routines removed');
    clickTool('Where did we leave off?');
    await wait(() => $('projectToolResult').textContent.includes('fixture evidence'), 'project evidence');
    const query = $('projectToolsDialog').querySelector('[aria-label="Search vault by meaning"]'); query.value = 'player progress';
    clickTool('Search notes');
    await wait(() => $('projectToolResult').textContent.includes('Persistence.md'), 'semantic sources');
    assert($('projectToolResult').querySelector('a[href^="obsidian:"]'), 'semantic source link');
    $('projectToolsDialog').close();
    stage('response settings');$('responseSettingsBtn').click();
    await wait(()=>$('responseSettingsDialog').querySelector('[aria-label="Humor"]').value==='25','style loaded');
    const humor=$('responseSettingsDialog').querySelector('[aria-label="Humor"]');humor.value='80';humor.dispatchEvent(new Event('input'));
    [...$('responseSettingsDialog').querySelectorAll('button')].find(b=>b.textContent==='Save response settings').click();
    await wait(()=>window.posts.some(p=>p.path==='/response-settings' && p.body.humor===80),'style saved');
    $('responseSettingsDialog').close();
    assert(!$('moreMenu').textContent.includes('Classic HUD'),'old HUD option returned');
    stage('memory tools'); $('memoryToolsBtn').click();
    await wait(() => $('memoryDialog').textContent.includes('Save correction'), 'memory loaded');
    const memInput=$('memoryDialog').querySelector('[aria-label="Remembered fact"]');memInput.value='Likes coffee';
    [...$('memoryDialog').querySelectorAll('button')].find(b=>b.textContent==='Save correction').click();
    await wait(()=>window.posts.some(p=>p.path==='/memory' && p.body.fact==='Likes coffee'),'memory correction');
    $('memoryDialog').close();
    assert(!$('digestToolsBtn') && !$('fileToolsBtn'), 'digest and file tools removed');

    stage('console');
    assert($('console').hidden && !document.body.classList.contains('view-console'), 'model view is the default');
    const wasMain = document.body.classList.contains('jarvis-main');
    $('viewConsole').click();
    assert(document.body.classList.contains('view-console') && !$('console').hidden, 'console shown');
    assert(getComputedStyle($('graph')).display === 'none' && getComputedStyle($('left')).display === 'none', 'graph and its panel step aside');
    assert(!document.body.classList.contains('jarvis-main'), 'full-screen model steps aside for the console');
    assert($('viewConsole').getAttribute('aria-pressed') === 'true' && JSON.parse(localStorage.getItem('jarvis.view')) === 'console', 'choice remembered');
    const emit = v => window.testStream.emit({ t: 10, ...v });
    emit({ type: 'you', text: '(Telegram) turn on the <img src=x onerror=alert(1)> TV' });
    emit({ type: 'tool', name: 'home_control', input: { device: 'tv', action: 'turn_on' } });
    emit({ type: 'result', name: 'home_control', ok: true, text: 'NOT CONFIRMED after 20 seconds' });
    emit({ type: 'receipt', tool: 'home_control', about: 'tv', status: 'unknown' });
    emit({ type: 'tool', name: 'run_command', input: { command: 'pytest -q' } });
    emit({ type: 'result', name: 'run_command', ok: true, text: Array.from({ length: 30 }, (_, i) => 'line ' + i).join('\n') });
    emit({ type: 'receipt', tool: 'run_command', about: 'pytest -q', status: 'confirmed' });
    emit({ type: 'tool', name: 'edit_file', input: { path: 'a.py', old_text: 'x = 1', new_text: 'x = 2' } });
    emit({ type: 'result', name: 'edit_file', ok: true, text: 'Edited a.py: replaced 1 place, checked on disk.' });
    emit({ type: 'jarvis', text: 'I sent it, but the TV still reports off.' });
    const last = $('consoleStream').lastElementChild;
    assert(last.classList.contains('turn') && last.querySelector('.turn-text').textContent.includes('<img src=x'), 'request shown as text');
    assert(!$('consoleStream').querySelector('img'), 'no markup from event text');
    assert(last.querySelector('.via').textContent === 'Telegram', 'source label');
    assert(last.querySelectorAll('.tool').length === 3, 'three tool rows');
    assert(last.querySelector('.tool code').textContent === 'pytest -q', 'command shown');
    assert(last.querySelectorAll('.out')[1].textContent.split('\n').length === 14, 'long output clipped');
    [...last.querySelectorAll('button')].find(b => b.textContent === 'show all 30 lines').click();
    assert(last.querySelectorAll('.out')[1].textContent.split('\n').length === 30, 'output expands');
    assert(last.querySelector('.diff .del').textContent.includes('x = 1') && last.querySelector('.diff .add').textContent.includes('x = 2'), 'diff card');
    const chips = [...last.querySelectorAll('.chip-proof')].map(c => c.textContent);
    assert(chips.length === 2 && chips[0].includes('could not confirm') && chips[0].startsWith('?') && chips[1].includes('confirmed'), 'receipt chips: ' + chips.join(' | '));
    assert(last.querySelector('.turn-say').textContent === 'I sent it, but the TV still reports off.', 'reply text');
    emit({ type: 'event', text: 'Approval needed: Delete the old build folder?' });
    assert(last.querySelector('.note.wait').textContent.includes('Delete the old build folder?'), 'the question is noted in the stream');
    await wait(() => $('railHome').querySelectorAll('.home-tile').length === 3, 'home tiles');
    assert($('railHome').querySelector('.home-tile.unknown b').textContent === 'unknown', 'an unavailable device reads unknown, never off');
    await wait(() => $('railWork').textContent.includes('Frontier') && !$('railWork').textContent.includes('Docs'), 'only running work is listed');
    await wait(() => $('railToday').textContent.includes('Dentist'), 'today');
    assert(!$('railWork').textContent.includes('Add the shop screen'), 'a finished job is a card, not a second entry under Working');

    stage('cards');
    const cardOf = id => document.querySelector(`#cards [data-card="${id}"]`);
    const press = (id, label) => [...cardOf(id).querySelectorAll('button')].find(b => b.textContent === label).click();
    const sent = () => window.posts.filter(p => p.path === '/command').map(p => p.body.text);
    await wait(() => cardOf('ask') && cardOf('held') && cardOf('job:a1'), 'cards for the question, held updates and the finished job');
    assert($('cards').closest('.console-rail'), 'in the Console the cards sit at the top of the rail');
    assert(cardOf('ask').querySelector('h3').textContent === 'Delete the old build folder?', 'the question is the card');
    assert(cardOf('job:a1').querySelector('.card-proof.ok').textContent.includes('Jarvis re-ran the tests: 41 passed.'), 'job card shows Jarvis\'s own check');
    assert(cardOf('job:a1').textContent.includes('jarvis/shop-a1') && cardOf('job:a1').textContent.includes('Nothing was merged'), 'job card names the branch and says it is not merged');
    let before = sent().length;
    press('job:a1', 'What changed?');
    await wait(() => sent().length === before + 1 && sent().at(-1).includes('jarvis/shop-a1'), 'What changed asks Jarvis about that branch');
    before = sent().length; press('held', 'Hear them');
    await wait(() => sent().length === before + 1 && sent().at(-1) === 'What did I miss?', 'Hear them asks Jarvis');
    $('cards').querySelector('.more')?.click();
    await wait(() => document.querySelector('#cards [data-card^="agent:Docs"]'), 'finished agent card');
    const agent = document.querySelector('#cards [data-card^="agent:Docs"]');
    assert(agent.textContent.includes('wrote the <b>guide</b>') && !agent.querySelector('b'), 'an agent report is shown as text, never as markup');
    assert(agent.textContent.includes('Recommendation: wrote') && agent.textContent.includes('the research note links') && !/\*\*|\]\(|research\.md/.test(agent.textContent), 'Markdown marks and link targets are stripped: ' + agent.textContent);
    const sameNode = document.querySelector('#cards [data-card^="agent:Docs"]');
    await J.cards.poll(); await J.cards.poll();
    assert(document.querySelector('#cards [data-card^="agent:Docs"]') === sameNode, 'a card is not redrawn when nothing changed (no twitching every few seconds)');
    assert(agent.querySelector('.card-proof.note').textContent.includes('own account'), 'an agent report is labelled as its own claim');
    assert(!document.querySelector('#cards [data-card^="agent:Frontier"]'), 'a running agent is not a finished card');
    [...agent.querySelectorAll('button')].find(b => b.textContent === 'Dismiss').click();
    assert(!document.querySelector('#cards [data-card^="agent:Docs"]') && JSON.parse(localStorage.getItem('jarvis.dismissedCards')).length === 1, 'dismiss hides the card and is remembered');
    before = sent().length; press('ask', 'No');
    await wait(() => sent().length === before + 1 && sent().at(-1) === 'no', 'No sends the owner\'s own word');
    assert(!cardOf('ask'), 'an answered question leaves at once');
    await J.cards.poll(); assert(!cardOf('ask'), 'and stays gone while the same question is still being settled');
    $('prompt').value = ''; $('prompt').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    assert($('prompt').value === 'TEST COMMAND', 'up arrow recalls the last typed command: ' + $('prompt').value);
    $('prompt').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); assert($('prompt').value === '', 'down returns to the draft');
    dispatchEvent(new KeyboardEvent('keydown', { key: '.', ctrlKey: true }));
    assert(!document.body.classList.contains('view-console') && $('console').hidden, 'Ctrl+. goes back to the model');
    assert(document.body.classList.contains('jarvis-main') === wasMain, 'the model view comes back as it was left');
    assert(getComputedStyle($('graph')).display !== 'none', 'graph is back');
    assert(!$('cards').closest('.console-rail') && getComputedStyle($('cards')).position === 'fixed' && cardOf('job:a1'), 'beside the model the same cards float on their own');
    window.testStream.emit({ type: 'hello', state: 'standby', history: [{ type: 'you', text: 'replayed', t: 3 }, { type: 'event', text: 'Approval needed: old question', t: 4 }] });
    assert($('consoleStream').querySelectorAll('.turn').length === 1 , 'reconnect replays the history once');

    stage('dimension'); $('dimension').click(); assert($('dimension').textContent === '2D', '2D');
    document.documentElement.dataset.check = 'passed';
  } catch (e) { document.documentElement.dataset.check = e.message; }
  await fetch('/probe-complete', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
    result:document.documentElement.dataset.check,stage:document.documentElement.dataset.stage})});
});
window.posts = [];
const realFetch = window.fetch;
window.fetch = async (url, init) => {
  if (init?.method === 'POST') window.posts.push({ path: url, body: JSON.parse(init.body) });
  const response=await realFetch(url,init);
  // Polling must agree with the synthetic conversation, as the real backend does.
  if(window.motionTestState && ['/status','/voice-health'].includes(url))
    return new Response(JSON.stringify({...await response.json(),state:window.motionTestState}),{headers:{'Content-Type':'application/json'}});
  return response;
};
</script>'''

HEALTH = {"startup": "ready", "text_mode": False, "microphone": "Mock mic", "microphone_active": True, "microphone_receiving": True,
          "processing": True, "listener_alive": True, "output": "Mock speaker", "output_active": True, "listening_mode": "wake",
          "voice_lock": False, "ai_service": "responded", "recognition": {"reason": "none", "at": None}, "speech_pending": False,
          "output_error": False, "input_level": .1, "state": "standby"}


FINISHED_AT = __import__("time").time() - 600  # fixed, as a real finished session's time is


def serve(with_checks=True):
    graph_nodes,graph_links=copy.deepcopy(NODES),copy.deepcopy(LINKS)
    organize(graph_nodes,graph_links)
    visual = {"state": "off", "mode": None, "session": "", "reason": "Not started.", "error": "", "target": "", "remaining_seconds": 0,
              "samples": 0, "drift_count": 0, "evidence": [], "preview": None, "observation": "Not observed.", "needs_heartbeat": True}

    oauth_starts = [0]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body, kind="application/json", code=200):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                script = CHECK if with_checks else '<script>window.EventSource=class {close(){} addEventListener(){}};</script>'
                return self.send((ROOT / "hud/brain.html").read_text(encoding="utf-8").replace("<head>", "<head>" + script, 1), "text/html")
            if path in ("/brain.js", "/holo.js", "/experience.js", "/panels.js", "/modes.js", "/productivity.js", "/automation.js", "/console.js", "/cards.js", "/brain.css"):
                return self.send((ROOT / "hud" / path[1:]).read_text(encoding="utf-8"), "text/css" if path.endswith(".css") else "text/javascript")
            routes = {
                "/brain-data": {"nodes": graph_nodes, "links": graph_links, "vault": {"name": "Test Vault", "notes": 3, "unresolved": 0}},
                "/voice-health": HEALTH, "/status": {"state": "standby", "info": {"model": "gpt-test"}, "cpu": 37, "mem": 58, "disk": 40,
                            "gpu": {"util": 22, "temp": 51}, "net_up": 42000, "net_down": 1800000, "uptime": 200000},
                "/settings": {"listening_mode": "wake"},
                "/home": {"devices": [{"name": "Bedroom Fan", "domain": "switch", "state": "on"}, {"name": "Ceiling Light", "domain": "light", "state": "off"},
                                      {"name": "Living Room TV", "domain": "media_player", "state": "unavailable"}], "error": "", "read_at": 0},
                "/intel": {"schedule": "Tomorrow 10:30 Dentist.", "weather": "38 and overcast."},
                "/attention": {"cap": 5, "spoken_today": 5, "question": "Delete the old build folder?",
                               "held": [{"t": 1794350000, "label": "Giant Builder finished", "why": "today's limit reached"}]},
                "/jobs": {"jobs": [{"id": "a1", "kind": "build", "status": "done", "label": "Finished", "what": "Add the shop screen",
                                    "check": "Jarvis re-ran the tests: 41 passed.", "branch": "jarvis/shop-a1", "attempt": 0}]},
                "/models": {"active": {"provider": "codex", "model": "gpt-test"}, "pending": None, "validating": False, "error": "",
                            "ready": True, "credential": "n/a", "subscription_only": True, "models": {"codex": ["gpt-test"], "ollama": ["local:test"]}},
                "/mcp": {"connections": [{"id": "saved-test", "name": "Saved test server", "host": "example.test",
                    "enabled": True, "discovery_state": "discovered", "checked_at": 123, "tools": []}]}, "/sessions": {"sessions": [{"name": "Frontier", "project": "Rocket Frontier", "status": "running", "task": "Playtest the build", "timeline":[{"label":"Reading source","status":"completed","started_at":123}]},
                    {"name": "Docs", "project": "Jarvis", "status": "completed", "report": "**Recommendation:** wrote the <b>guide</b> and checked the [research note](</C:/notes/research.md>) links.",
                     "updated_at": FINISHED_AT}]}, "/tasks": {"tasks": []},
                "/holo": {"installed": False, "running": False, "port": 4890, "path": ""},
                "/workspace": {"folders": []},
                '/memory': {'revision':'v1','facts':[{'id':'f1','fact':'Likes tea'}],'recent':[],
                    'privacy':{'terms':[],'email':False,'phone':False}},
                '/conversation-settings': {'pause_seconds':1.2,'followup_seconds':12,'first_clause_chars':85},
                '/response-settings': {'humor':25,'directness':75,'detail':'brief','tone':'classic','pushback':'balanced','address':'occasionally'},
            }
            if path == "/orbit":
                import datetime
                soon = (datetime.datetime.now().astimezone() + datetime.timedelta(minutes=40)).isoformat()
                return self.send({"events": [{"title": "Team sync", "location": "Zoom", "all_day": False, "start": soon}],
                                  "track": {"name": "Thunderstruck", "artists": ["AC/DC"], "album": "The Razors Edge", "art": "",
                                            "uri": "spotify:track:T", "playing": True, "progress_ms": 60000, "duration_ms": 292000}})
            if path == "/integration-status":
                from unittest.mock import patch
                sys.path.insert(0, str(ROOT))
                import integration_status
                # The owner's real pairings must not decide a fixture's outcome.
                with patch("mcp_connections.connections", return_value=[]), patch("holo_bridge.find_install", return_value=None),                         patch("telegram_bridge.BRIDGE.status", return_value={"token": False, "paired": False}):
                    return self.send(integration_status.snapshot())
            if path == "/events":
                return self.send("retry: 100000\n\n", "text/event-stream")
            return self.send(routes[path]) if path in routes else self.send({"error": "nope"}, code=404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path=='/probe-complete':
                self.server.check=body
                self.send({'ok':True})
                self.server.done.set()
                return
            if self.path=='/memory':
                return self.send({'revision':'v2','facts':[{'id':'f2','fact':body.get('fact','Likes tea')}],
                    'recent':[],'privacy':{'terms':[],'email':False,'phone':False}})
            if self.path in {'/response-settings','/conversation-settings','/voice-recovery','/session-control'}:return self.send(body)
            if self.path=='/digests':return self.send({'saved':True})
            if self.path=='/artifacts':return self.send({'name':'Sample.xlsx'})
            if self.path == '/routines':
                return self.send({'name':'Wrap up', 'project':'Jarvis', 'descriptions':['Review only'],
                    'notice':'Review only', 'token':'fixture', 'status':'completed'} if body.get('action') == 'preview'
                    else {'status':'completed'})
            if self.path == '/project-memory':
                return self.send({'project':'Jarvis', 'checked_at':'2026-10-21', 'verified':[{'source':'fixture','text':'fixture evidence'}]})
            if self.path == '/knowledge-search':
                return self.send({'mode':'semantic', 'results':[{'path':'Persistence.md', 'excerpt':'Saved state', 'uri':'obsidian://open?path=Persistence.md'}]})
            if self.path == "/visual-modes" and body.get("action") == "start":
                visual.update(state="running", mode=body["mode"], target=body.get("target", ""), remaining_seconds=1800,
                              drift_count=0, session="s1", needs_heartbeat=body["mode"] != "focus", reason="Observing locally.")
            if self.path == "/mcp":
                return self.send({"name": body.get("name"), "tools": []})
            if self.path == "/mcp/oauth":
                if body.get('action') == 'start':
                    oauth_starts[0] += 1
                return self.send({'id': 'fake-flow', 'state': 'complete' if body.get('action') == 'status' and oauth_starts[0] > 1 else 'waiting',
                                  'authorization_url': 'https://example.com/authorize?state=fake', 'message': 'OAuth saved'})
            if self.path == "/settings":
                return self.send({"listening_mode": body.get("listening_mode", "wake")})
            return self.send(visual if self.path == "/visual-modes" else {"ok": True})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.done=threading.Event()
    server.check={}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    if not CHROME:
        print("SKIP: Chrome/Edge not found")
        return 0
    server = serve()
    url = f"http://127.0.0.1:{server.server_port}/"
    with tempfile.TemporaryDirectory() as profile:
        args = [str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                "--window-size=1660,896", "--run-all-compositor-stages-before-draw"]
        # Check completion comes from the actual browser assertions. Do not wait for Chrome's
        # virtual clock to drain while Focus's worker and polling intervals remain alive.
        with tempfile.TemporaryFile() as log:
            proc=subprocess.Popen(args+[url],stdout=log,stderr=log)
            try:
                server.done.wait(90)
            finally:
                try:
                    parent=psutil.Process(proc.pid); children=parent.children(recursive=True)
                    for child in children:
                        try: child.terminate()
                        except psutil.NoSuchProcess: pass
                    parent.terminate()
                    _,alive=psutil.wait_procs(children+[parent],timeout=5)
                    for child in alive: child.kill()
                except psutil.NoSuchProcess:
                    pass
                proc.wait(timeout=10)
        if "--screenshot" in sys.argv:
            out = Path(sys.argv[sys.argv.index("--screenshot") + 1]).resolve()
            # A preview must not rerun checks against the first run's mutated fixture state.
            preview = serve(with_checks=False)
            try:
                subprocess.run(args + [f"--screenshot={out}", f"http://127.0.0.1:{preview.server_port}/"], capture_output=True, timeout=120)
            finally:
                preview.shutdown(); preview.server_close()
    result=server.check.get('result','browser did not report completion')
    stage=server.check.get('stage','unknown')
    server.shutdown();server.server_close()
    print("PASS" if result == "passed" else f"FAIL at {stage}: {result}")
    return 0 if result == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
