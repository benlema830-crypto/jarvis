"""Optional loopback Spotify MCP bridge. No network or credential reads on import.

Uses existing requests, filelock and Windows DPAPI support. Setup is explicit;
this module neither installs dependencies nor registers startup tasks.
"""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import time

from filelock import FileLock
import requests

import mcp_connections
import mcp_oauth

STORE = Path(__file__).resolve().parent / 'data' / 'spotify-mcp.enc'
PORT = 8791
CALLBACK_PORT = 8792
SCOPES = 'user-read-playback-state user-modify-playback-state'
_lock = threading.RLock()


class SpotifyError(ValueError):
    """Only fixed messages, never provider bodies or credentials."""


def save_credentials(value):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    temp = STORE.with_suffix('.tmp')
    temp.write_text(mcp_connections.seal(json.dumps(value)), encoding='utf-8')
    temp.replace(STORE)


def load_credentials():
    try:
        return json.loads(mcp_connections.unseal(STORE.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        raise SpotifyError('Spotify is not configured for this Windows account.') from None


def token_request(data):
    return mcp_oauth.request('POST', 'https://accounts.spotify.com/api/token', data=data)


def access_token(force=False):
    with _lock, FileLock(str(STORE) + '.lock', timeout=45):
        value = load_credentials()
        if force or value['expires_at'] <= time.time() + 60:
            result = token_request({'grant_type': 'refresh_token',
                                    'refresh_token': value['refresh_token'],
                                    'client_id': value['client_id']})
            value.update(mcp_oauth.token_result(result, value))
            save_credentials(value)
        return value['access_token']


def api(method, path, *, params=None, body=None):
    # All paths are chosen by dispatch below, never by a model or remote response.
    for attempt in range(2):
        token = access_token(force=bool(attempt))
        try:
            with requests.Session() as session:
                session.trust_env = False
                with session.request(method, 'https://api.spotify.com/v1' + path,
                                     params=params, json=body, timeout=(5, 20),
                                     allow_redirects=False, stream=True,
                                     headers={'Authorization': 'Bearer ' + token}) as response:
                    status = response.status_code
                    if status == 401 and attempt == 0:
                        continue
                    if status == 204 or (method != 'GET' and status in (200, 202)):
                        return {}  # commands answer with an empty or non-JSON body (queue returns an ID)
                    errors = {401: 'Spotify sign-in expired. Run setup again.',
                              403: 'Spotify denied access. Check Premium, app user access and playback scopes.',
                              404: 'No active Spotify device. Open Spotify and play a track first.',
                              429: 'Spotify rate or account quota reached. Wait before trying again.'}
                    if status != 200:
                        raise SpotifyError(errors.get(status, 'Spotify request failed. Check app access and connection.'))
                    chunks, size = [], 0
                    for chunk in response.iter_content(16384):
                        size += len(chunk)
                        if size > 2_000_000:
                            raise SpotifyError('Spotify response was too large.')
                        chunks.append(chunk)
                    result = json.loads(b''.join(chunks))
                    if not isinstance(result, dict):
                        raise SpotifyError('Spotify returned an invalid response.')
                    return result
        except (requests.RequestException, json.JSONDecodeError):
            raise SpotifyError('Spotify could not be reached securely or returned an invalid response.') from None


def tool(name, description, properties=None, required=()):
    return {'name': name, 'description': description, 'inputSchema': {
        'type': 'object', 'properties': properties or {}, 'required': list(required),
        'additionalProperties': False}}


DEVICE = {'type': 'string', 'maxLength': 128, 'description': 'Optional Spotify device ID from spotify_devices.'}
TOOLS = [
    tool('spotify_search', 'Search Spotify tracks, artists, albums or playlists.', {
        'query': {'type': 'string', 'minLength': 1, 'maxLength': 300},
        'type': {'type': 'string', 'enum': ['track', 'artist', 'album', 'playlist']},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}, ['query']),
    tool('spotify_devices', 'List available Spotify Connect devices.'),
    tool('spotify_playback', 'Read current Spotify playback state.'),
    tool('spotify_play', 'Play a Spotify track URI or resume. Requires Premium and an active Spotify device.', {
        'uri': {'type': 'string', 'pattern': '^spotify:track:[A-Za-z0-9]{22}$'}, 'device_id': DEVICE}),
    tool('spotify_queue', 'Add a Spotify track URI to the playback queue. Requires Premium and something playing.', {
        'uri': {'type': 'string', 'pattern': '^spotify:track:[A-Za-z0-9]{22}$'}, 'device_id': DEVICE}, ['uri']),
    tool('spotify_pause', 'Pause Spotify playback. Requires Premium.', {'device_id': DEVICE}),
    tool('spotify_next', 'Skip to the next Spotify track. Requires Premium.', {'device_id': DEVICE}),
    tool('spotify_previous', 'Skip to the previous Spotify track. Requires Premium.', {'device_id': DEVICE}),
]


def summary(item):
    return {key: item[key] for key in ('name', 'uri', 'type') if key in item} | {
        'artists': [x.get('name', '') for x in item.get('artists', []) if isinstance(x, dict)]}


def dispatch(name, args):
    definition = next((t for t in TOOLS if t['name'] == name), None)
    if not definition or not isinstance(args, dict):
        raise SpotifyError('Unknown Spotify tool or invalid arguments.')
    schema = definition['inputSchema']
    if set(args) - set(schema['properties']) or set(schema['required']) - set(args):
        raise SpotifyError('Unexpected or missing Spotify arguments.')
    for key, value in args.items():
        prop = schema['properties'][key]
        if prop['type'] == 'string':
            if not isinstance(value, str) or not 1 <= len(value) <= prop.get('maxLength', 128):
                raise SpotifyError('Invalid Spotify text argument.')
            if ('enum' in prop and value not in prop['enum']) or ('pattern' in prop and not re.fullmatch(prop['pattern'], value)):
                raise SpotifyError('Invalid Spotify type or track URI.')
            if key == 'device_id' and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
                raise SpotifyError('Invalid Spotify device ID.')
        elif type(value) is not int or not prop['minimum'] <= value <= prop['maximum']:
            raise SpotifyError('Spotify search limit must be from 1 to 10.')
    if name == 'spotify_search':
        kind = args.get('type', 'track')
        data = api('GET', '/search', params={'q': args['query'], 'type': kind, 'limit': args.get('limit', 5)})
        return {'items': [summary(x) for x in data.get(kind + 's', {}).get('items', []) if isinstance(x, dict)]}
    if name == 'spotify_devices':
        data = api('GET', '/me/player/devices')
        return {'devices': [{k: d[k] for k in ('id', 'name', 'type', 'is_active', 'is_restricted') if k in d}
                            for d in data.get('devices', []) if isinstance(d, dict)]}
    if name == 'spotify_playback':
        data = api('GET', '/me/player')
        return {'is_playing': data.get('is_playing', False), 'item': summary(data.get('item') or {}),
                'device': {k: data.get('device', {})[k] for k in ('id', 'name', 'is_active') if k in data.get('device', {})}}
    action = name.removeprefix('spotify_')
    params = {'device_id': args['device_id']} if 'device_id' in args else None
    if action == 'queue':
        api('POST', '/me/player/queue', params=dict(params or {}, uri=args['uri']))
        return {'accepted': True, 'message': 'Spotify accepted the track for the queue.'}
    body = {'uris': [args['uri']]} if 'uri' in args else None
    api('POST' if action in ('next', 'previous') else 'PUT', '/me/player/' + action, params=params, body=body)
    return {'accepted': True, 'message': 'Spotify accepted the playback command; read playback state to confirm.'}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # No tracebacks from credential-bearing requests.


def make_server(token, port=PORT):
    if not isinstance(token, str) or len(token) < 32:
        raise SpotifyError('A strong local MCP bearer token is required.')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def reply(self, status, value=None):
            body = json.dumps(value).encode() if value is not None else b''
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            # Consume a bounded body before rejecting authentication. Closing a
            # Windows socket with unread bytes can reset the response mid-flight.
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384 or self.headers.get('Transfer-Encoding'):
                    raise ValueError()
                raw = self.rfile.read(length)
            except (ValueError, OSError):
                self.reply(400)
                return
            if (self.path != '/mcp' or self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}'
                    or self.headers.get('Origin') is not None):
                self.reply(403)
                return
            auth = self.headers.get('Authorization', '')
            if not hmac.compare_digest(auth.encode(), ('Bearer ' + token).encode()):
                self.reply(401)
                return
            try:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError()
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get('jsonrpc') != '2.0':
                    raise ValueError()
                method, ident = data.get('method'), data.get('id')
                params = data.get('params', {})
                if not isinstance(params, dict):
                    raise ValueError()
                if 'id' not in data:
                    self.reply(202)
                    return  # Notifications must never execute tools.
            except (ValueError, OSError):
                self.reply(400)
                return
            if method == 'initialize':
                version = params.get('protocolVersion')
                result = {'protocolVersion': version if version in mcp_connections.VERSIONS else '2025-11-25',
                          'capabilities': {'tools': {}}, 'serverInfo': {'name': 'jarvis-local-spotify', 'version': '1.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': TOOLS}
            elif method == 'tools/call':
                try:
                    value = dispatch(params.get('name'), params.get('arguments', {}))
                    result = {'content': [{'type': 'text', 'text': json.dumps(value)}], 'isError': False}
                except (SpotifyError, mcp_oauth.OAuthError) as error:
                    result = {'content': [{'type': 'text', 'text': str(error)}], 'isError': True}
                except Exception:
                    result = {'content': [{'type': 'text', 'text': 'Spotify operation failed securely. Check local setup.'}], 'isError': True}
            else:
                self.reply(200, {'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32601, 'message': 'Method not found'}})
                return
            self.reply(200, {'jsonrpc': '2.0', 'id': ident, 'result': result})

        def do_GET(self):
            self.reply(405)

        do_DELETE = do_GET

    return Server(('127.0.0.1', port), Handler)


def main():
    try:
        value = load_credentials()
        with make_server(value['bridge_token']) as server:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception:
        print('Spotify bridge could not start. Check setup and whether its port is already in use.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
