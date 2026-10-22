import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
import mcp_connections as mcp
import spotify_mcp as spotify
from scripts import setup_spotify as setup


class SpotifyTest(unittest.TestCase):
    def test_dashboard_handler_opens_only_dashboard_without_client_id(self):
        dialog = setup.ClientIdDialog.__new__(setup.ClientIdDialog)
        dialog.browser_status = Mock()
        with patch.object(setup.webbrowser, 'open', return_value=True) as launch, \
                patch.object(setup, 'authorize') as authorize:
            dialog.open_dashboard()
            launch.assert_called_once_with(setup.DASHBOARD)
            authorize.assert_not_called()
            self.assertIn('launch requested', dialog.browser_status.set.call_args.args[0])
        with patch.object(setup.webbrowser, 'open', return_value=False):
            dialog.open_dashboard()
            self.assertIn(setup.DASHBOARD, dialog.browser_status.set.call_args.args[0])

    def test_callback_and_untrusted_urls_cannot_launch_as_sign_in_links(self):
        with patch.object(setup.webbrowser, 'open') as launch:
            for url in (setup.REDIRECT, 'https://accounts.spotify.com.evil.example/authorize',
                        'https://accounts.spotify.com/authorize#fragment', 'file:///example'):
                self.assertFalse(setup.open_browser(url))
            launch.assert_not_called()

    def test_invalid_client_id_never_opens_browser_or_listener(self):
        with patch.object(setup.webbrowser, 'open') as browser, patch.object(spotify, 'Server') as server, \
                patch.object(spotify, 'token_request') as exchange:
            for value in ('', ' ', 'not-a-client-id', 'g' * 32, None):
                with self.subTest(value=value), self.assertRaises(spotify.SpotifyError):
                    setup.authorize(value)
            browser.assert_not_called()
            server.assert_not_called()
            exchange.assert_not_called()

    def test_client_dialog_requires_id_and_callback_confirmation(self):
        dialog = setup.ClientIdDialog.__new__(setup.ClientIdDialog)
        dialog.entry, dialog.ready = Mock(), Mock()
        with patch.object(setup.messagebox, 'showerror') as error:
            dialog.entry.get.return_value = ''
            self.assertFalse(dialog.validate())
            dialog.entry.get.return_value = 'a' * 32
            dialog.ready.get.return_value = False
            self.assertFalse(dialog.validate())
            dialog.ready.get.return_value = True
            self.assertTrue(dialog.validate())
            self.assertEqual(error.call_count, 2)
            dialog.apply()
            self.assertEqual(dialog.result, 'a' * 32)

    def test_browser_failure_is_sanitized(self):
        with patch.object(setup.webbrowser, 'open', side_effect=OSError('sensitive-url')):
            self.assertFalse(setup.open_browser('https://accounts.spotify.com/authorize'))
        with patch.object(setup.webbrowser, 'open', return_value=False), \
                patch.object(spotify, 'token_request') as exchange, self.assertRaises(spotify.SpotifyError) as error:
            setup.authorize('a' * 32)
        self.assertNotIn('sensitive-url', str(error.exception))
        exchange.assert_not_called()

    def test_visible_browser_wait_failure_retry_and_completion(self):
        root, window, status = Mock(), Mock(), Mock()
        done, scheduled, buttons = threading.Event(), [], {}
        window.after.side_effect = lambda delay, callback: scheduled.append(callback)
        def button(parent, **kwargs):
            buttons[kwargs['text']] = kwargs['command']
            return Mock()
        def wait_window(child):
            scheduled.pop(0)()  # automatic launch fails
            self.assertIn('did not accept', status.set.call_args.args[0])
            buttons['Open Spotify sign-in again']()
            self.assertIn('Browser launch requested', status.set.call_args.args[0])
            done.set()
            scheduled.pop(0)()  # callback received; close the local status window
        root.wait_window.side_effect = wait_window
        with patch.object(setup.tk, 'Toplevel', return_value=window), \
                patch.object(setup.tk, 'StringVar', return_value=status), \
                patch.object(setup.tk, 'Label'), patch.object(setup.tk, 'Button', side_effect=button), \
                patch.object(setup, 'open_browser', side_effect=[False, True]) as launch:
            self.assertTrue(setup.browser_wait(root, 'in-memory-synthetic-url', done, time.monotonic() + 30))
            self.assertEqual([call.args for call in launch.call_args_list], [('in-memory-synthetic-url',)] * 2)
        window.destroy.assert_called_once()

    def test_browser_wait_cancellation_does_not_exchange_and_closes_listener(self):
        with patch.object(setup, 'open_browser') as launch, \
                patch.object(spotify, 'token_request') as exchange, self.assertRaises(spotify.SpotifyError):
            setup.authorize('a' * 32, wait_browser=lambda url, done, deadline: False)
        launch.assert_not_called()
        exchange.assert_not_called()
        # The callback port is immediately reusable after cancellation.
        with spotify.Server(('127.0.0.1', spotify.CALLBACK_PORT), Mock()):
            pass

    @staticmethod
    def free_port():
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            return listener.getsockname()[1]

    def setUp(self):
        # Never compete with the real bridge or a user's pending OAuth sign-in.
        port = self.free_port()
        for target, value in [('spotify_mcp.CALLBACK_PORT', port),
                              ('scripts.setup_spotify.REDIRECT', f'http://127.0.0.1:{port}/callback')]:
            mocked = patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_windows_dpapi_roundtrip(self):
        sealed = mcp.seal('synthetic-test-value')
        self.assertNotIn('synthetic-test-value', sealed)
        self.assertEqual(mcp.unseal(sealed), 'synthetic-test-value')

    def oauth_browser(self, auth_url, *, deny=False):
        query = parse_qs(urlsplit(auth_url).query)
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertEqual(query['scope'], [spotify.SCOPES])
        self.assertNotIn('client_secret', query)
        self.auth_query = query
        session = requests.Session(); session.trust_env = False
        try:
            bad = setup.REDIRECT + '?' + urlencode({'state': 'wrong', 'code': 'fake-code'})
            self.assertEqual(session.get(bad, timeout=3).status_code, 400)
            callback = setup.REDIRECT + '?' + urlencode({'state': query['state'][0],
                        **({'error': 'access_denied'} if deny else {'code': 'fake-code'})})
            self.assertEqual(session.get(callback, timeout=3).status_code, 200)
            self.assertEqual(session.get(callback, timeout=3).status_code, 400)  # replay
        finally:
            session.close()
        return True

    def test_oauth_pkce_state_replay_and_scope_enforcement(self):
        tokens = {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh',
                  'token_type': 'Bearer', 'expires_in': 3600, 'scope': spotify.SCOPES}
        with patch.object(setup.webbrowser, 'open', side_effect=self.oauth_browser), \
                patch.object(spotify, 'token_request', return_value=tokens) as request, \
                patch.object(spotify, 'save_credentials') as save:
            value = setup.authorize('a' * 32)
            self.assertEqual(value['client_id'], 'a' * 32)
            self.assertGreaterEqual(len(value['bridge_token']), 32)
            verifier = request.call_args.args[0]['code_verifier']
            challenge = setup.base64.urlsafe_b64encode(setup.hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            self.assertEqual(challenge, self.auth_query['code_challenge'][0])
            save.assert_not_called()
        with patch.object(setup.webbrowser, 'open', side_effect=self.oauth_browser), \
                patch.object(spotify, 'token_request', return_value=dict(tokens, scope='user-read-playback-state')), \
                self.assertRaises(spotify.SpotifyError):
            setup.authorize('a' * 32)

    def test_oauth_denial_never_exchanges_or_saves(self):
        with patch.object(setup.webbrowser, 'open', side_effect=lambda url: self.oauth_browser(url, deny=True)), \
                patch.object(spotify, 'token_request') as request, \
                patch.object(spotify, 'save_credentials') as save, self.assertRaises(spotify.SpotifyError):
            setup.authorize('a' * 32)
        request.assert_not_called()
        save.assert_not_called()

    def test_setup_registration_is_verified_and_resumable_without_nested_filelock(self):
        port, factory = self.free_port(), spotify.make_server
        with tempfile.TemporaryDirectory() as directory:
            handles = {}
            def seal(text):
                key = str(len(handles)); handles[key] = text; return key
            with patch.object(setup, 'URL', f'http://127.0.0.1:{port}/mcp'), \
                    patch.object(spotify, 'make_server', side_effect=lambda token: factory(token, port=port)), \
                    patch.object(mcp, 'STORE', Path(directory) / 'connections.json'), \
                    patch.object(mcp, 'seal', side_effect=seal), \
                    patch.object(mcp, 'unseal', side_effect=lambda key: handles[key]), \
                    patch.object(spotify, 'dispatch', return_value={'devices': []}) as dispatch:
                value = {'bridge_token': 'a' * 48}
                first, devices = setup.verify_and_connect(value)
                second, _ = setup.verify_and_connect(value)
                self.assertEqual(first['id'], second['id'])
                self.assertFalse(devices)
                self.assertEqual(len(mcp.connections()), 1)
                self.assertNotIn('spotify_play', [call.args[0] for call in dispatch.call_args_list])

    def test_scope_and_input_boundaries(self):
        self.assertEqual(set(spotify.SCOPES.split()), {'user-read-playback-state', 'user-modify-playback-state'})
        with patch.object(spotify, 'api') as api:
            for name, args in [('spotify_search', {'query': 'jazz', 'limit': 11}),
                               ('spotify_search', {'query': 'jazz', 'limit': True}),
                               ('spotify_play', {'uri': 'https://example.com'}),
                               ('spotify_pause', {'device_id': '../other'}),
                               ('spotify_devices', {'url': 'https://example.com'}),
                               ('spotify_search', {}), ('unknown', {})]:
                with self.subTest(name=name, args=args), self.assertRaises(spotify.SpotifyError):
                    spotify.dispatch(name, args)
            api.assert_not_called()

    def test_search_projection_and_current_limit(self):
        with patch.object(spotify, 'api', return_value={'tracks': {'items': [None, {
                'name': 'test', 'uri': 'spotify:track:' + 'a' * 22, 'private_field': 'omit',
                'artists': [{'name': 'artist'}]}]}}) as api:
            result = spotify.dispatch('spotify_search', {'query': 'jazz'})
            self.assertEqual(api.call_args.kwargs['params']['limit'], 5)
            self.assertNotIn('private_field', json.dumps(result))
            self.assertEqual(len(result['items']), 1)

    def test_playback_routes_and_no_premature_confirmation(self):
        with patch.object(spotify, 'api', return_value={}) as api:
            result = spotify.dispatch('spotify_play', {'uri': 'spotify:track:' + 'a' * 22})
            api.assert_called_once_with('PUT', '/me/player/play', params=None, body={'uris': ['spotify:track:' + 'a' * 22]})
            self.assertIn('read playback state to confirm', result['message'])
            api.reset_mock()
            spotify.dispatch('spotify_next', {})
            self.assertEqual(api.call_args.args, ('POST', '/me/player/next'))
            spotify.dispatch('spotify_playback', {})  # 204/no active player is valid.

    def test_refresh_rotates_and_encrypts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spotify.enc'
            value = {'client_id': 'client', 'refresh_token': 'old-refresh', 'access_token': 'old-access',
                     'expires_at': 0, 'bridge_token': 'local-bearer'}
            handles = {}
            def seal(text):
                key = str(len(handles)); handles[key] = text; return key
            with patch.object(spotify, 'STORE', path), patch.object(mcp, 'seal', side_effect=seal), \
                    patch.object(mcp, 'unseal', side_effect=lambda key: handles[key]), \
                    patch.object(spotify, 'token_request', return_value={
                        'access_token': 'new-access', 'refresh_token': 'new-refresh',
                        'token_type': 'Bearer', 'expires_in': 3600}) as request:
                spotify.save_credentials(value)
                self.assertEqual(spotify.access_token(), 'new-access')
                self.assertEqual(spotify.load_credentials()['refresh_token'], 'new-refresh')
                self.assertNotIn('new-refresh', path.read_text())
                spotify.access_token()
                request.assert_called_once_with({'grant_type': 'refresh_token', 'refresh_token': 'old-refresh', 'client_id': 'client'})

    def test_api_status_redaction_no_redirect_or_proxy(self):
        for status in (403, 404, 429, 302, 500):
            with self.subTest(status=status):
                session = Mock()
                response = Mock(status_code=status, text='PRIVATE PROVIDER BODY')
                session.request.return_value.__enter__ = Mock(return_value=response)
                session.request.return_value.__exit__ = Mock(return_value=False)
                with patch.object(spotify, 'access_token', return_value='PRIVATE TOKEN'), \
                        patch.object(spotify.requests, 'Session') as factory:
                    factory.return_value.__enter__.return_value = session
                    with self.assertRaises(spotify.SpotifyError) as error:
                        spotify.api('GET', '/me/player')
                    self.assertNotIn('PRIVATE', str(error.exception))
                    self.assertFalse(session.trust_env)
                    self.assertFalse(session.request.call_args.kwargs['allow_redirects'])

    def test_unauthorized_retries_refresh_once_and_204_is_success(self):
        session = Mock()
        contexts = []
        for status in (401, 204):
            context = Mock()
            context.__enter__ = Mock(return_value=Mock(status_code=status))
            context.__exit__ = Mock(return_value=False)
            contexts.append(context)
        session.request.side_effect = contexts
        with patch.object(spotify, 'access_token', return_value='token') as token, \
                patch.object(spotify.requests, 'Session') as factory:
            factory.return_value.__enter__.return_value = session
            self.assertEqual(spotify.api('PUT', '/me/player/pause'), {})
            self.assertEqual([x.kwargs['force'] for x in token.call_args_list], [False, True])

    def test_real_jarvis_client_transport_and_access_controls(self):
        token = 'synthetic-local-bearer-' + 'a' * 40
        server = spotify.make_server(token, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{server.server_port}/mcp'
        try:
            with patch.object(spotify, 'dispatch', return_value={'items': []}) as dispatch:
                with mcp.Client(url, token) as client:
                    self.assertEqual(len(client.tools()), 8)
                    result = client.rpc('tools/call', {'name': 'spotify_search', 'arguments': {'query': 'jazz'}})
                    self.assertFalse(result['isError'])
                dispatch.assert_called_once()
                dispatch.reset_mock()
                session = requests.Session(); session.trust_env = False
                payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'spotify_play'}}
                self.assertEqual(session.post(url, json=payload, timeout=3).status_code, 401)
                headers = {'Authorization': 'Bearer ' + token, 'Origin': 'https://hostile.example'}
                self.assertEqual(session.post(url, headers=headers, json=payload, timeout=3).status_code, 403)
                headers = {'Authorization': 'Bearer ' + token, 'Host': 'hostile.example'}
                self.assertEqual(session.post(url, headers=headers, json=payload, timeout=3).status_code, 403)
                del payload['id']
                self.assertEqual(session.post(url, headers={'Authorization': 'Bearer ' + token}, json=payload, timeout=3).status_code, 202)
                dispatch.assert_not_called()
                session.close()
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
