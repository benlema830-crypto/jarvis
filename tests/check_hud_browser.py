"""Manual integration check using installed Edge; no real services or credentials."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hud
import preferences
import context

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CHECK = '''<script>
window.addEventListener('error', e => document.documentElement.dataset.scriptError = e.message);
window.addEventListener('load', async () => {
  const waitFor = async predicate => {
    for (let i=0; i<200; i++) { if(predicate()) return; await new Promise(r=>setTimeout(r,20)); }
    throw new Error('UI action timed out');
  };
  try {
    const toggle=document.getElementById('listenToggle');
    await waitFor(()=>!toggle.disabled);
    toggle.click(); await waitFor(()=>toggle.getAttribute('aria-checked')==='true' && !toggle.disabled);
    toggle.click(); await waitFor(()=>toggle.getAttribute('aria-checked')==='false' && !toggle.disabled);
    const input=document.getElementById('calendarUrl');
    document.getElementById('calendarSettings').open=true;
    input.value='https://example.com/private-test.ics'; input.focus();
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'/'}));
    if(document.activeElement!==input) throw new Error('URL input lost keyboard focus');
    document.getElementById('calendarForm').requestSubmit();
    await waitFor(()=>!document.getElementById('calendarDisconnect').hidden && !document.getElementById('calendarDisconnect').disabled);
    if(input.value!=='') throw new Error('Private URL not cleared');
    document.getElementById('calendarDisconnect').click();
    await waitFor(()=>document.getElementById('calendarDisconnect').hidden);
    document.documentElement.dataset.integrationCheck='passed';
  } catch(error) { document.documentElement.dataset.integrationCheck=error.message; }
});
</script>'''


def main():
    with tempfile.TemporaryDirectory(prefix="jarvis-ui-") as temp:
        folder = Path(temp)
        page = folder / "index.html"
        page.write_text(Path(hud.PAGE).read_text(encoding="utf-8").replace("</head>", CHECK + "</head>"), encoding="utf-8")
        server = ThreadingHTTPServer(("127.0.0.1", 0), hud._Handler)
        server.daemon_threads = True
        port = server.server_port
        try:
            with mock.patch.object(preferences, "PATH", folder / "preferences.json"), \
                 mock.patch.object(hud, "PAGE", str(page)), \
                 mock.patch.object(hud, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"}), \
                 mock.patch.object(hud, "_state", "standby"), \
                 mock.patch.object(hud, "info", {"ears": "CPU"}), \
                 mock.patch.object(hud, "_intel_cache", (0.0, None)), \
                 mock.patch.object(hud, "status", return_value={}), \
                 mock.patch.object(context, "weather", return_value="Weather test"), \
                 mock.patch.object(context, "fetch_calendar", return_value=context.icalendar.Calendar()), \
                 mock.patch.object(hud, "commands") as commands:
                preferences.update(listening_mode="wake", calendar_urls=[])
                threading.Thread(target=server.serve_forever, daemon=True).start()
                result = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--no-default-browser-check", "--disable-background-networking",
                    "--user-data-dir=" + str(folder / "edge"), "--dump-dom", "--virtual-time-budget=10000",
                    "--window-size=1440,1000", f"http://127.0.0.1:{port}"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
                assert result.returncode == 0, result.stderr[-2000:]
                assert 'data-integration-check="passed"' in result.stdout, result.stdout[:2000] + result.stderr[-1000:]
                assert 'data-script-error=' not in result.stdout, result.stdout[:2000]
                assert preferences.listening_mode() == "wake"
                assert context.calendar_urls() == []
                commands.put.assert_not_called()
                print("Browser passed: listening toggle, calendar connect/disconnect, private URL clearing, input focus, no accidental commands.")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
