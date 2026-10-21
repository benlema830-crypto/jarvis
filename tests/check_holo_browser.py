"""Run installed HOLO's gesture self-test with fake notes, no camera or state writes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import holo_bridge
from check_brain_browser import CHROME


def main():
    folder = holo_bridge.find_install()
    if not folder or not CHROME:
        print('SKIP: installed HOLO and Chrome/Edge are required')
        return 0
    notes = [{'name': f'Note {i}.md', 'title': f'Note {i}', 'body': 'Synthetic test note.',
              'full': 'Synthetic test note for gesture checks.'} for i in range(4)]
    tree = [{'kind': 'folder', 'name': 'TEST NOTES', 'files': notes}]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body, kind='application/json', code=200):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Security-Policy', "default-src 'self' blob: data:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; media-src 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split('?')[0]
            if path == '/':
                html = (folder / 'holo.html').read_text(encoding='utf-8')
                # Disable startup camera in this disposable served copy only.
                html = html.replace('\nstartCamera();', '\n/* camera disabled in inert test */')
                html = html.replace('<head>', '''<head><script>
Object.defineProperty(navigator, 'mediaDevices', {value: {getUserMedia: async () => { throw Error('Camera disabled in test'); }}});
window.speechSynthesis.speak = () => {};
</script>''', 1)
                return self.send(html.encode(), 'text/html; charset=utf-8')
            if path == '/api/tree':
                return self.send(tree)
            if path == '/api/notes':
                return self.send(notes)
            if path == '/api/props':
                return self.send([p.name for p in (folder / 'props').glob('*.glb')][:1])
            if path.startswith(('/vendor/', '/props/')):
                target = (folder / path.lstrip('/')).resolve()
                if target.is_relative_to(folder.resolve()) and target.is_file():
                    kind = 'text/javascript' if target.suffix in ('.js', '.mjs') else 'application/octet-stream'
                    return self.send(target.read_bytes(), kind)
            self.send({}, code=404)

        def do_POST(self):
            self.rfile.read(min(int(self.headers.get('Content-Length', 0)), 100000))
            self.send({'ok': True})  # never writes the watched HOLO state file
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as profile:
            result = subprocess.run([str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run',
                f'--user-data-dir={profile}', '--window-size=1660,896', '--virtual-time-budget=20000',
                '--run-all-compositor-stages-before-draw', '--dump-dom',
                f'http://127.0.0.1:{server.server_port}/?probe=1'], capture_output=True,
                encoding='utf-8', timeout=90)
        match = re.search(r'<title>(PROBE .*?)</title>', result.stdout)
        title = match.group(1) if match else 'no probe result'
        passed = bool(match) and 'FAIL:' not in title
        print(('PASS: ' if passed else 'FAIL: ') + title)
        return 0 if passed else 1
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    sys.exit(main())
