import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mcp_connections as mcp


class ConnectionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = patch.object(mcp, 'STORE', Path(self.temp.name) / 'connections.json')
        self.store.start()
        # Unit tests use opaque handles; actual Windows DPAPI requires the owner's
        # desktop account and is a separate live check, not a transport prerequisite.
        secrets = {}
        def seal(value):
            handle = 'opaque-' + str(len(secrets))
            secrets[handle] = value
            return handle
        self.seal_patch = patch.object(mcp, 'seal', side_effect=seal)
        self.unseal_patch = patch.object(mcp, 'unseal', side_effect=lambda handle: secrets[handle])
        self.seal_patch.start()
        self.unseal_patch.start()
        self.addCleanup(self.seal_patch.stop)
        self.addCleanup(self.unseal_patch.stop)
        self.calls = []
        calls = self.calls

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_DELETE(self):
                self.send_response(204); self.end_headers()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append((body, dict(self.headers)))
                if self.path == '/unauthorized':
                    self.send_response(401); self.end_headers(); return
                if self.path == '/redirect':
                    self.send_response(302); self.send_header('Location', '/mcp'); self.end_headers(); return
                method = body['method']
                if method == 'notifications/initialized':
                    self.send_response(202); self.end_headers(); return
                if method == 'initialize':
                    result = dict(protocolVersion='2025-11-25', capabilities={'tools': {}}, serverInfo={'name':'test','version':'1'})
                elif method == 'tools/list':
                    result = {'tools':[{'name':'echo','description':'Test echo','inputSchema':{'type':'object','properties':{'text':{'type':'string'}}}}]} if body['params'].get('cursor') else {'tools':[], 'nextCursor':'page2'}
                else:
                    result = {'content':[{'type':'text','text':body['params']['arguments']['text']}]}
                data = json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result})
                self.send_response(200)
                self.send_header('Mcp-Session-Id','test-session')
                self.send_header('Content-Type','text/event-stream' if self.path == '/sse' else 'application/json')
                self.end_headers()
                self.wfile.write(('event: message\ndata: '+data+'\n\n' if self.path == '/sse' else data).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        self.store.stop(); self.temp.cleanup()

    def connect(self, path='/mcp'):
        return mcp.manage(dict(action='connect',name='Test connection',url=self.url+path,token='secret-token'))

    def test_discovery_pagination_session_and_private_storage(self):
        result = self.connect()
        self.assertEqual([x['name'] for x in result['tools']], ['echo'])
        self.assertNotIn('secret-token', mcp.STORE.read_text())
        self.assertNotIn(self.url, mcp.STORE.read_text())
        self.assertNotIn('secret', result)
        self.assertNotIn('tools/call', [x[0]['method'] for x in self.calls])
        request = next(x for x in self.calls if x[0]['method']=='tools/list')
        self.assertEqual(request[1]['Mcp-Session-Id'], 'test-session')
        self.assertEqual(request[1]['Authorization'], 'Bearer secret-token')
        self.assertEqual(request[1]['MCP-Protocol-Version'], '2025-11-25')

    def test_call_pause_refresh_remove(self):
        connection = self.connect()
        self.assertIn('hello', mcp.call(connection['id'],'echo',{'text':'hello'}))
        mcp.manage(dict(action='toggle',id=connection['id']))
        with self.assertRaises(ValueError):
            mcp.call(connection['id'],'echo',{})
        self.assertEqual(mcp.catalog(), [])
        mcp.manage(dict(action='refresh',id=connection['id']))
        mcp.manage(dict(action='remove',id=connection['id']))
        self.assertEqual(mcp.connections(), [])

    def test_sse(self):
        self.assertEqual(len(self.connect('/sse')['tools']), 1)

    def test_failed_refresh_retains_catalog_with_truthful_state_then_recovers(self):
        connection = self.connect()
        with patch.object(mcp.Client, 'tools', side_effect=ValueError('test failure')):
            with self.assertRaises(ValueError):
                mcp.manage(dict(action='refresh', id=connection['id']))
        failed = mcp.connections()[0]
        self.assertEqual(failed['tools'], connection['tools'])
        self.assertEqual(failed['checked_at'], connection['checked_at'])
        self.assertEqual(failed['discovery_state'], 'refresh_failed')
        self.assertFalse(failed['live_verified'])
        self.assertNotIn('test failure', mcp.STORE.read_text())
        refreshed = mcp.manage(dict(action='refresh', id=connection['id']))
        self.assertEqual(refreshed['discovery_state'], 'discovered')
        self.assertFalse(refreshed['live_verified'])

    def test_auth_failure_and_redirect_never_save(self):
        for path in ['/unauthorized', '/redirect']:
            with self.assertRaises(ValueError):
                self.connect(path)
        self.assertEqual(mcp.connections(), [])

    def test_endpoint_validation_and_duplicate(self):
        for url in ['file:///tmp/a','http://example.com/mcp','https://user:password@example.com/mcp','https://example.com/mcp#secret']:
            with self.assertRaises(ValueError):
                mcp.validate_url(url)
        self.connect()
        with self.assertRaises(ValueError):
            self.connect()
        self.assertEqual(len(mcp.connections()), 1)


if __name__ == '__main__':
    unittest.main()
