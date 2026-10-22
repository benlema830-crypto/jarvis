"""Phase D: local HTTP surfaces stay loopback-only and refuse other websites."""
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import queue
import re
import threading
import unittest
from unittest import mock

import hud

ROOT = Path(__file__).resolve().parents[1]


class HudOriginTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), hud._Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.commands = queue.Queue()
        for patcher in (mock.patch.object(hud, 'ALLOWED_HOSTS', {f'127.0.0.1:{self.port}', f'localhost:{self.port}'}),
                        mock.patch.object(hud, 'commands', self.commands)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def post(self, path, payload, origin=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        headers = {'Content-Type': 'application/json', **({'Origin': origin} if origin else {})}
        try:
            connection.request('POST', path, json.dumps(payload), headers)
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def test_other_websites_cannot_send_commands_or_approvals(self):
        for origin in ('https://evil.example', 'http://127.0.0.1:9999', 'null'):
            self.assertEqual(self.post('/command', {'text': 'yes'}, origin), 403, origin)
        self.assertTrue(self.commands.empty())

    def test_own_page_and_local_services_still_work(self):
        self.assertEqual(self.post('/command', {'text': 'open notepad'}, f'http://127.0.0.1:{self.port}'), 200)
        self.assertEqual(self.post('/command', {'text': 'what time is it'}), 200)  # Brain proxy sends no Origin
        self.assertEqual([self.commands.get_nowait(), self.commands.get_nowait()], ['open notepad', 'what time is it'])


class LoopbackBindingTest(unittest.TestCase):
    def test_servers_bind_to_loopback_only(self):
        for name in ('hud.py', 'brain.py'):
            source = (ROOT / name).read_text(encoding='utf-8')
            binds = re.findall(r'ThreadingHTTPServer\(\(\s*["\']([^"\']+)["\']', source)
            self.assertTrue(binds, name)
            self.assertEqual(set(binds), {'127.0.0.1'}, name)


if __name__ == '__main__':
    unittest.main()
