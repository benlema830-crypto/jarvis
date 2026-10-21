import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

import requests
import mcp_connections as mcp
import mcp_oauth as oauth


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch('STORE', Path(self.temp.name) / 'connections.json')
        self.secrets = {}
        def seal(value):
            key = 'opaque-' + str(len(self.secrets))
            self.secrets[key] = value
            return key
        self.patch('seal', seal)
        self.patch('unseal', lambda key: self.secrets[key])
        self.calls, self.flows = [], []
        self.fail_token = False
        self.no_pkce = False
        self.issuer_mismatch = False
        self.header_discovery = True
        self.oidc_only = False
        test = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, data, status=200, headers=None):
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                test.calls.append(('GET', self.path, {}))
                if self.path == '/mcp':
                    header = {'WWW-Authenticate': f'Bearer resource_metadata="{test.url}/metadata", scope="notes:read"'} if test.header_discovery else {}
                    return self.reply({}, 401, header)
                if self.path in ('/metadata', '/.well-known/oauth-protected-resource/mcp'):
                    return self.reply({'resource': test.url + '/mcp', 'authorization_servers': [test.url + '/auth'],
                                       'scopes_supported': ['notes:read']})
                if self.path == '/.well-known/oauth-authorization-server/auth' and test.oidc_only:
                    return self.reply({}, 404)
                if self.path in ('/.well-known/oauth-authorization-server/auth', '/.well-known/openid-configuration/auth'):
                    return self.reply({'issuer': test.url + ('/wrong' if test.issuer_mismatch else '/auth'),
                        'authorization_endpoint': test.url + '/authorize', 'token_endpoint': test.url + '/token',
                        'registration_endpoint': test.url + '/register', 'revocation_endpoint': test.url + '/revoke',
                        'code_challenge_methods_supported': [] if test.no_pkce else ['S256'],
                        'token_endpoint_auth_methods_supported': ['none']})
                return self.reply({}, 404)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                body = json.loads(raw) if self.headers.get('Content-Type', '').startswith('application/json') else {k: v[0] for k, v in parse_qs(raw.decode()).items()}
                test.calls.append(('POST', self.path, body))
                if self.path == '/register':
                    return self.reply({'client_id': 'public-test-client', 'token_endpoint_auth_method': 'none'}, 201)
                if self.path == '/token':
                    if test.fail_token:
                        return self.reply({'error_description': 'SECRET_PROVIDER_ERROR'}, 400)
                    refresh = body.get('grant_type') == 'refresh_token'
                    return self.reply({'token_type': 'Bearer', 'access_token': 'rotated-access' if refresh else 'private-access',
                                       'refresh_token': 'rotated-refresh' if refresh else 'private-refresh', 'expires_in': 3600})
                if self.path == '/revoke':
                    return self.reply({})
                if self.path == '/mcp':
                    method = body['method']
                    if method == 'notifications/initialized':
                        return self.reply({}, 202)
                    if method == 'initialize':
                        result = {'protocolVersion': '2025-11-25', 'capabilities': {}, 'serverInfo': {'name': 'fake', 'version': '1'}}
                    elif method == 'tools/list':
                        result = {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}}]}
                    else:
                        result = {'content': [{'type': 'text', 'text': 'fake result'}]}
                    return self.reply({'id': body['id'], 'jsonrpc': '2.0', 'result': result})
                return self.reply({}, 404)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.addCleanup(self.stop)

    def patch(self, name, value):
        p = patch.object(mcp, name, value)
        p.start()
        self.addCleanup(p.stop)

    def stop(self):
        for flow in self.flows:
            flow.cancel()
            flow.server.shutdown()
            flow.server.server_close()
        self.server.shutdown()
        self.server.server_close()

    def flow(self, **kwargs):
        flow = oauth.Flow('Test OAuth', self.url + '/mcp', **kwargs)
        self.flows.append(flow)
        return flow

    def complete(self, flow):
        return flow.complete('/callback?' + urlencode({'code': 'one-time-code', 'state': flow.state}))

    def test_real_loopback_callback_pkce_encryption_and_tool_discovery(self):
        flow = self.flow()
        params = parse_qs(urlsplit(flow.url).query)
        expected = base64.urlsafe_b64encode(hashlib.sha256(flow.verifier.encode()).digest()).decode().rstrip('=')
        self.assertEqual(params['code_challenge'], [expected])
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertEqual(params['resource'], [self.url + '/mcp'])
        self.assertEqual(params['scope'], ['notes:read'])
        verifier = flow.verifier
        callback = flow.redirect + '?' + urlencode({'code': 'one-time-code', 'state': flow.state})
        with requests.get(callback, timeout=5) as response:
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('one-time-code', response.text)
        self.assertEqual(flow.phase, 'complete')
        exchange = next(c[2] for c in self.calls if c[1] == '/token')
        self.assertEqual(exchange['code_verifier'], verifier)
        public = mcp.connections()[0]
        self.assertEqual(public['auth_type'], 'oauth')
        self.assertEqual(public['tools'][0]['name'], 'echo')
        for secret in ('private-access', 'private-refresh', 'one-time-code', verifier):
            self.assertNotIn(secret, mcp.STORE.read_text())
            self.assertNotIn(secret, json.dumps(public))
        self.assertFalse(any(c[2].get('method') == 'tools/call' for c in self.calls))
        self.assertIn('fake result', mcp.call(public['id'], 'echo', {}))

    def test_wrong_state_duplicate_state_and_replay_never_exchange(self):
        flow = self.flow()
        for path in ('/callback?code=a&state=wrong', f'/callback?code=a&state={flow.state}&state={flow.state}'):
            self.assertFalse(flow.complete(path))
        self.assertFalse(any(c[1] == '/token' for c in self.calls))
        path = '/callback?' + urlencode({'state': flow.state, 'code': 'once'})
        self.assertTrue(flow.complete(path))
        self.assertFalse(flow.complete(path))
        self.assertEqual(sum(c[1] == '/token' for c in self.calls), 1)

    def test_cancel_denial_timeout_and_issuer_mismatch_do_not_save(self):
        for reason in ('cancel', 'deny', 'timeout', 'issuer'):
            flow = self.flow()
            state = flow.state
            if reason == 'cancel':
                flow.cancel()
            if reason == 'timeout':
                flow.deadline = time.monotonic() - 1
            query = {'state': state, 'code': 'unused'}
            if reason == 'deny':
                query['error'] = 'access_denied'
            if reason == 'issuer':
                query['iss'] = 'https://wrong.example'
            self.assertFalse(flow.complete('/callback?' + urlencode(query)))
        self.assertEqual(mcp.connections(), [])
        self.assertFalse(any(c[1] == '/token' for c in self.calls))

    def test_provider_error_is_not_exposed(self):
        flow = self.flow()
        self.fail_token = True
        self.assertFalse(self.complete(flow))
        self.assertEqual(flow.phase, 'failed')
        self.assertNotIn('SECRET_PROVIDER_ERROR', json.dumps(flow.snapshot()))
        self.assertEqual(mcp.connections(), [])

    def test_discovery_fallback_and_preregistered_client(self):
        self.header_discovery = False
        self.oidc_only = True
        flow = self.flow(client_id='registered-client', scope='notes:read')
        self.assertEqual(flow.client_id, 'registered-client')
        self.assertFalse(any(c[1] == '/register' for c in self.calls))
        self.assertTrue(any(c[1] == '/.well-known/openid-configuration/auth' for c in self.calls))

    def test_bad_metadata_and_insecure_endpoints_are_rejected(self):
        for url in ('http://remote.example/mcp', 'file:///secret', 'https://u:p@example.com', 'https://example.com/#secret'):
            with self.assertRaises(oauth.OAuthError):
                oauth.endpoint(url)
        self.no_pkce = True
        with self.assertRaisesRegex(oauth.OAuthError, 'PKCE'):
            self.flow()
        self.no_pkce, self.issuer_mismatch = False, True
        with self.assertRaisesRegex(oauth.OAuthError, 'issuer'):
            self.flow()

    def expire(self):
        items = mcp._load()
        secret = json.loads(mcp.unseal(items[0]['secret']))
        secret['oauth']['expires_at'] = 0
        items[0]['secret'] = mcp.seal(json.dumps(secret))
        mcp._save(items)

    def test_refresh_rotation_is_saved_once_and_revocation_removes(self):
        flow = self.flow()
        self.assertTrue(self.complete(flow))
        self.expire()
        id_ = mcp.connections()[0]['id']
        threads = [threading.Thread(target=mcp.call, args=(id_, 'echo', {})) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        refreshes = [c for c in self.calls if c[2].get('grant_type') == 'refresh_token']
        self.assertEqual(len(refreshes), 1)
        saved = json.loads(mcp.unseal(mcp._load()[0]['secret']))
        self.assertEqual(saved['oauth']['refresh_token'], 'rotated-refresh')
        result = mcp.manage({'action': 'remove', 'id': id_})
        self.assertIn('accepted', result['message'])
        self.assertEqual(mcp.connections(), [])
        self.assertEqual(sum(c[1] == '/revoke' for c in self.calls), 2)

    def test_failed_refresh_does_not_execute_tool_or_lose_old_token(self):
        self.assertTrue(self.complete(self.flow()))
        self.expire()
        before = mcp.STORE.read_text()
        self.fail_token = True
        with self.assertRaises(oauth.OAuthError):
            mcp.call(mcp.connections()[0]['id'], 'echo', {})
        self.assertEqual(mcp.STORE.read_text(), before)
        self.assertFalse(any(c[2].get('method') == 'tools/call' for c in self.calls))

    def test_private_cross_origin_discovery_is_rejected(self):
        with self.assertRaises(oauth.OAuthError):
            oauth.check_issuer('https://public.example/mcp', 'https://127.0.0.1/auth')

    def test_discovery_failure_after_token_revokes_and_saves_nothing(self):
        flow = self.flow()
        with patch.object(mcp.Client, 'tools', side_effect=ValueError('not compatible')):
            self.assertFalse(self.complete(flow))
        self.assertEqual(mcp.connections(), [])
        self.assertEqual(sum(c[1] == '/revoke' for c in self.calls), 2)

    def test_cancellation_during_exchange_does_not_save_connection(self):
        flow = self.flow()
        original = oauth.request
        def request(method, url, **kwargs):
            result = original(method, url, **kwargs)
            if url.endswith('/token'):
                flow.cancel()
            return result
        with patch.object(oauth, 'request', side_effect=request):
            self.assertFalse(self.complete(flow))
        self.assertEqual(flow.phase, 'cancelled')
        self.assertEqual(mcp.connections(), [])

    def test_invalid_token_and_failed_revocation_do_not_leak(self):
        with self.assertRaises(oauth.OAuthError):
            oauth.token_result({'token_type': 'Bearer', 'access_token': 'bad\ntoken'})
        secret = {'oauth': {'revocation_endpoint': self.url + '/revoke', 'client_id': 'id', 'access_token': 'secret'}}
        with patch.object(oauth, 'request', side_effect=oauth.OAuthError('failed')):
            result = oauth.revoke(secret)
        self.assertIn('revoke access on the service', result)
        self.assertNotIn('secret', result)


if __name__ == '__main__':
    unittest.main()
