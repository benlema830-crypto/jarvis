"""Drive the real Brain page in headless Chrome against an inert fake backend.

Nothing here talks to the running assistant, a camera, the screen or any account.
Run:  .venv\\Scripts\\python.exe tests\\check_brain_browser.py      (prints PASS or the failing step)
Optional: --screenshot out.png saves a 1660x896 capture of the loaded page.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
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
    assert($('hubs').children.length >= 5, 'top hubs');
    const box = s => document.querySelector(s).getBoundingClientRect();
    assert(box('.left').width <= 232 && box('.right').width <= 190, 'panels exceed compact proportions');
    assert(box('.toolbar').top < 30 && box('.dock').bottom <= innerHeight, 'toolbar/dock placement');
    assert(!document.body.innerHTML.includes('<script>alert'), 'unsafe');

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

    stage('filter'); [...$('filters').children].find(b => b.textContent.includes('Memory')).click();
    assert(J.graph.hidden.has('Memory') && !J.graph.selected?.group?.includes('Memory'), 'filter hides group');
    [...$('filters').children].find(b => b.textContent.includes('Memory')).click();

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

    stage('look'); document.querySelector('[data-look=face]').click(); assert(document.querySelector('[data-look=face]').classList.contains('on'), 'face look');

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

    stage('focus'); document.querySelector('[data-mode=focus]').click(); assert(!$('modePanel').hidden, 'focus panel');
    await wait(() => $('modePanel').querySelector('select').options.length === 2, 'focus apps');
    $('modePanel').querySelector('select').value = 'code.exe';
    [...$('modePanel').querySelectorAll('button')].find(b => b.textContent === 'Start focus').click();
    await wait(() => window.posts.some(p => p.path === '/visual-modes' && p.body.mode === 'focus' && p.body.target === 'code.exe' && p.body.callouts === true), 'focus start');
    await wait(() => document.querySelector('[data-mode=focus] em').textContent.includes('·'), 'focus toggle timer');

    stage('eyes'); document.querySelector('[data-mode=eyes]').click();
    assert($('modePanel').textContent.includes('Lets JARVIS see you') && document.querySelector('[data-mode=eyes] em').textContent === 'off', 'eyes panel, camera untouched');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    assert($('modePanel').hidden, 'escape closes panel');

    stage('menu'); $('moreBtn').click(); assert(!$('moreMenu').hidden, 'menu');
    [...$('moreMenu').querySelectorAll('button')].find(b => b.textContent === 'Voice health').click();
    assert($('healthDialog').open && $('healthDialog').textContent.includes('Mock mic'), 'health'); $('healthDialog').close();

    stage('project tools'); $('projectToolsBtn').click();
    await wait(() => $('routineSelect').options.length, 'routines loaded');
    const clickTool = label => [...$('projectToolsDialog').querySelectorAll('button')].find(b => b.textContent === label).click();
    assert(!window.posts.some(p => p.path === '/routines' && p.body.action === 'run'), 'opening ran routine');
    clickTool('Review saved steps');
    await wait(() => $('projectToolResult').textContent.includes('Review only'), 'review displayed');
    assert(!window.posts.some(p => p.path === '/routines' && p.body.action === 'run'), 'preview ran routine');
    clickTool('Approve and run once');
    await wait(() => $('projectToolResult').textContent.includes('completed'), 'routine result');
    assert(window.posts.filter(p => p.path === '/routines' && p.body.action === 'run').length === 1, 'run once');
    clickTool('Where did we leave off?');
    await wait(() => $('projectToolResult').textContent.includes('fixture evidence'), 'project evidence');
    const query = $('projectToolsDialog').querySelector('[aria-label="Search vault by meaning"]'); query.value = 'player progress';
    clickTool('Search notes');
    await wait(() => $('projectToolResult').textContent.includes('Persistence.md'), 'semantic sources');
    assert($('projectToolResult').querySelector('a[href^="obsidian:"]'), 'semantic source link');
    $('projectToolsDialog').close();
    stage('dimension'); $('dimension').click(); assert($('dimension').textContent === '2D', '2D');
    document.documentElement.dataset.check = 'passed';
  } catch (e) { document.documentElement.dataset.check = e.message; }
});
window.posts = [];
const realFetch = window.fetch;
window.fetch = (url, init) => { if (init?.method === 'POST') window.posts.push({ path: url, body: JSON.parse(init.body) }); return realFetch(url, init); };
</script>'''

HEALTH = {"startup": "ready", "text_mode": False, "microphone": "Mock mic", "microphone_active": True, "microphone_receiving": True,
          "processing": True, "listener_alive": True, "output": "Mock speaker", "output_active": True, "listening_mode": "wake",
          "voice_lock": False, "ai_service": "responded", "recognition": {"reason": "none", "at": None}, "speech_pending": False,
          "output_error": False, "input_level": .1, "state": "standby"}


def serve():
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
                return self.send((ROOT / "hud/brain.html").read_text(encoding="utf-8").replace("<head>", "<head>" + CHECK, 1), "text/html")
            if path in ("/brain.js", "/panels.js", "/modes.js", "/productivity.js", "/brain.css"):
                return self.send((ROOT / "hud" / path[1:]).read_text(encoding="utf-8"), "text/css" if path.endswith(".css") else "text/javascript")
            routes = {
                "/brain-data": {"nodes": NODES, "links": LINKS, "vault": {"name": "Test Vault", "notes": 3, "unresolved": 0}},
                "/voice-health": HEALTH, "/status": {"state": "standby", "info": {"model": "gpt-test"}},
                "/settings": {"listening_mode": "wake"}, "/visual-modes": visual, "/focus-apps": {"apps": ["chrome.exe", "code.exe"]},
                "/models": {"active": {"provider": "codex", "model": "gpt-test"}, "pending": None, "validating": False, "error": "",
                            "ready": True, "credential": "n/a", "subscription_only": True, "models": {"codex": ["gpt-test"], "ollama": ["local:test"]}},
                "/mcp": {"connections": [{"id": "saved-test", "name": "Saved test server", "host": "example.test",
                    "enabled": True, "discovery_state": "discovered", "checked_at": 123, "tools": []}]}, "/sessions": {"sessions": []}, "/tasks": {"tasks": []},
                "/holo": {"installed": False, "running": False, "port": 4890, "path": ""},
                "/workspace": {"folders": []}, "/build-plan": {"text": ""}, "/eyes": {"on": False, "age": None},
                "/routines": {"routines": {"Wrap up": {"project":"Jarvis", "steps":[{"action":"tasks"}]}}},
            }
            if path == "/integration-status":
                from unittest.mock import patch
                sys.path.insert(0, str(ROOT))
                import integration_status
                with patch("mcp_connections.connections", return_value=[]), patch("holo_bridge.find_install", return_value=None):
                    return self.send(integration_status.snapshot())
            if path == "/events":
                return self.send("retry: 100000\n\n", "text/event-stream")
            return self.send(routes[path]) if path in routes else self.send({"error": "nope"}, code=404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
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
                "--window-size=1660,896", "--virtual-time-budget=20000", "--run-all-compositor-stages-before-draw"]
        dom = subprocess.run(args + ["--dump-dom", url], capture_output=True, text=True, timeout=120, encoding="utf-8").stdout
        if "--screenshot" in sys.argv:
            out = Path(sys.argv[sys.argv.index("--screenshot") + 1]).resolve()
            subprocess.run(args + [f"--screenshot={out}", url], capture_output=True, timeout=120)
    match = re.search(r'data-check="([^"]*)"', dom)
    stage = re.search(r'data-stage="([^"]*)"', dom)
    result = match.group(1) if match else f"no result (stage {stage.group(1) if stage else 'none'})"
    print("PASS" if result == "passed" else f"FAIL at {stage.group(1) if stage else '?'}: {result}")
    return 0 if result == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
