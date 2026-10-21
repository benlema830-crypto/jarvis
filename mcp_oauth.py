"""MCP OAuth public clients: discovery, PKCE, loopback callbacks and token lifecycle.

No browser or network activity occurs at import. Begin is an explicit UI action.
Secrets stay in memory until discovery succeeds, then in the MCP DPAPI store.
"""
import base64
import hashlib
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import requests


class OAuthError(ValueError):
    """Fixed messages only: provider responses can contain credentials."""


def endpoint(url):
    if not isinstance(url, str) or len(url) > 4096 or any(c.isspace() for c in url):
        raise OAuthError('Invalid OAuth endpoint.')
    p = urlsplit(url)
    if (not p.hostname or p.username or p.password or p.fragment or
            (p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in ('127.0.0.1', '::1', 'localhost')))):
        raise OAuthError('OAuth requires HTTPS, except for loopback servers.')
    return url


def origin(url):
    p = urlsplit(endpoint(url))
    return p.scheme + '://' + p.netloc


def check_issuer(resource, issuer):
    """A remote resource cannot redirect discovery into private local services."""
    if origin(resource) == origin(issuer):
        return  # explicitly selected endpoint; supports local development servers
    try:
        host = urlsplit(issuer).hostname
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise OAuthError('Cross-origin OAuth discovery cannot access a private network address.')
    except (OSError, ValueError):
        raise OAuthError('OAuth issuer could not be verified as a public address.') from None


def request(method, url, *, data=None, body=None, accept_empty=False):
    """Bounded, redirect-free requests. Never return raw errors to the browser."""
    endpoint(url)
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.request(method, url, data=data, json=body, timeout=(5, 15),
                                 allow_redirects=False, stream=True,
                                 headers={'Accept': 'application/json'}) as response:
                if response.status_code not in (200, 201):
                    raise OAuthError('OAuth request rejected. Check server setup or sign in again.')
                if accept_empty:
                    return {}
                chunks, size, deadline = [], 0, time.monotonic() + 30
                for chunk in response.iter_content(8192):
                    size += len(chunk)
                    if size > 262144 or time.monotonic() > deadline:
                        raise OAuthError('OAuth response exceeded the size or time limit.')
                    chunks.append(chunk)
                result = json.loads(b''.join(chunks))
                if not isinstance(result, dict):
                    raise OAuthError('Invalid OAuth response.')
                return result
    except (requests.RequestException, ValueError, TypeError) as error:
        if isinstance(error, OAuthError):
            raise
        raise OAuthError('OAuth server unavailable or returned an invalid response.') from None


def discover(resource):
    resource = endpoint(resource)
    p = urlsplit(resource)
    if p.query:
        raise OAuthError('OAuth endpoints cannot contain query credentials. Use the bearer-token connection option.')
    # An unauthenticated GET is only a discovery probe, never a tool invocation.
    challenge = {}
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(resource, timeout=(5, 10), allow_redirects=False, stream=True) as response:
                header = response.headers.get('WWW-Authenticate', '')
                if response.status_code == 401 and header.lower().startswith('bearer '):
                    challenge = requests.utils.parse_dict_header(header[7:])
    except requests.RequestException:
        raise OAuthError('Could not reach the MCP server for OAuth discovery.') from None
    candidates = ([challenge['resource_metadata']] if challenge.get('resource_metadata') else
                  list(dict.fromkeys([origin(resource) + '/.well-known/oauth-protected-resource' + p.path.rstrip('/'),
                                      origin(resource) + '/.well-known/oauth-protected-resource'])))
    metadata = None
    for url in candidates:
        # Resource metadata must be served by the explicitly selected resource.
        if origin(url) != origin(resource):
            raise OAuthError('Cross-origin protected-resource metadata is not supported.')
        try:
            metadata = request('GET', url)
            break
        except OAuthError:
            continue
    if not metadata or metadata.get('resource', '').rstrip('/') != resource.rstrip('/'):
        raise OAuthError('MCP resource metadata is missing or does not match this endpoint.')
    issuers = metadata.get('authorization_servers')
    if not isinstance(issuers, list) or not issuers:
        raise OAuthError('MCP server did not advertise an authorization server.')
    issuer = endpoint(issuers[0])
    check_issuer(resource, issuer)
    ip = urlsplit(issuer)
    if ip.query or (p.scheme == 'https' and ip.scheme != 'https'):
        raise OAuthError('Invalid OAuth issuer.')
    base, path = origin(issuer), ip.path.rstrip('/')
    urls = list(dict.fromkeys([base + '/.well-known/oauth-authorization-server' + path,
                              base + '/.well-known/openid-configuration' + path,
                              issuer.rstrip('/') + '/.well-known/openid-configuration']))
    auth = None
    for url in urls:
        try:
            auth = request('GET', url)
            break
        except OAuthError:
            continue
    if not auth or auth.get('issuer') != issuer:
        raise OAuthError('Authorization metadata issuer does not match.')
    if 'S256' not in auth.get('code_challenge_methods_supported', []):
        raise OAuthError('This authorization server does not advertise PKCE S256.')
    if 'none' not in auth.get('token_endpoint_auth_methods_supported', ['client_secret_basic']):
        raise OAuthError('This server requires confidential-client authentication; public clients are required here.')
    for key in ('authorization_endpoint', 'token_endpoint', 'registration_endpoint', 'revocation_endpoint'):
        if key in auth or key in ('authorization_endpoint', 'token_endpoint'):
            if origin(auth.get(key, '')) != origin(issuer):
                raise OAuthError('Cross-origin authorization endpoints are not supported.')
    reserved = {'state', 'client_id', 'redirect_uri', 'response_type', 'code_challenge', 'code_challenge_method', 'resource', 'scope'}
    if reserved.intersection(parse_qs(urlsplit(auth['authorization_endpoint']).query)):
        raise OAuthError('Authorization endpoint contains conflicting OAuth parameters.')
    scope = challenge.get('scope', ' '.join(metadata.get('scopes_supported', [])))
    if not isinstance(scope, str) or len(scope) > 4096:
        raise OAuthError('Invalid OAuth scopes.')
    return dict(auth, resource=resource, scope=scope)


def token_result(result, previous=None):
    token = result.get('access_token')
    if (not isinstance(token, str) or not token or len(token) > 8192 or
            any(c.isspace() for c in token) or str(result.get('token_type', '')).lower() != 'bearer'):
        raise OAuthError('OAuth server did not return a usable bearer token.')
    try:
        lifetime = float(result.get('expires_in', 300))
        if not 0 < lifetime <= 365 * 86400:
            raise ValueError()
    except (TypeError, ValueError):
        raise OAuthError('OAuth token lifetime is invalid.') from None
    refresh = result.get('refresh_token', (previous or {}).get('refresh_token', ''))
    if not isinstance(refresh, str) or len(refresh) > 16384:
        raise OAuthError('Invalid OAuth refresh token.')
    return {'access_token': token, 'refresh_token': refresh, 'expires_at': time.time() + lifetime}


def access(secret):
    """Return token + updated secret. Caller serializes refresh and saves rotation."""
    oauth = secret['oauth']
    if oauth['expires_at'] > time.time() + 30:
        return oauth['access_token'], secret
    if not oauth.get('refresh_token'):
        raise OAuthError('OAuth access expired. Remove this connection and sign in again.')
    result = request('POST', oauth['token_endpoint'], data={
        'grant_type': 'refresh_token', 'refresh_token': oauth['refresh_token'],
        'client_id': oauth['client_id'], 'resource': secret['url']})
    updated = dict(secret, oauth=dict(oauth, **token_result(result, oauth)))
    return updated['oauth']['access_token'], updated


def revoke(secret):
    oauth = secret.get('oauth')
    if not oauth:
        return 'Not an OAuth connection.'
    if not oauth.get('revocation_endpoint'):
        return 'Removed locally. Revoke access on the service account page.'
    try:
        for key in ('refresh_token', 'access_token'):
            if oauth.get(key):
                request('POST', oauth['revocation_endpoint'], data={
                    'token': oauth[key], 'token_type_hint': key, 'client_id': oauth['client_id']}, accept_empty=True)
        return 'Removed locally; the service accepted the revocation request.'
    except OAuthError:
        return 'Removed locally. Remote revocation failed; revoke access on the service account page.'


class Flow:
    def __init__(self, name, resource, client_id='', scope=None, callback_port=0):
        self.lock = threading.RLock()
        self.id = secrets.token_urlsafe(24)
        self.state = secrets.token_urlsafe(32)
        self.verifier = secrets.token_urlsafe(48)
        self.deadline = time.monotonic() + 300
        self.phase, self.message = 'preparing', ''
        self.name, self.resource = name, endpoint(resource)
        self.server = None
        self.auth = None
        self.url = ''
        try:
            self.auth = discover(resource)
            flow = self
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass  # callback query contains a short-lived authorization code

                def do_GET(self):
                    if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                        self.send_error(403)
                        return
                    ok = flow.complete(self.path)
                    body = b'Authorization received. Return to JARVIS to check the connection.' if ok else b'Authorization rejected. Return to JARVIS.'
                    self.send_response(200 if ok else 400)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            self.server = ThreadingHTTPServer(('127.0.0.1', callback_port), Handler)
            self.server.daemon_threads = True
            self.redirect = f'http://127.0.0.1:{self.server.server_port}/callback'
            if not client_id:
                if not self.auth.get('registration_endpoint'):
                    raise OAuthError('Register a public OAuth client with this service and enter its client ID and callback port.')
                registration = request('POST', self.auth['registration_endpoint'], body={
                    'client_name': 'JARVIS Desktop', 'redirect_uris': [self.redirect],
                    'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
                    'token_endpoint_auth_method': 'none'})
                client_id = registration.get('client_id')
                if registration.get('token_endpoint_auth_method', 'none') != 'none':
                    raise OAuthError('Registration did not accept a public OAuth client.')
            if not isinstance(client_id, str) or not client_id or len(client_id) > 2048:
                raise OAuthError('Invalid OAuth client ID.')
            self.client_id = client_id
            challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('=')
            params = {'response_type': 'code', 'client_id': client_id, 'redirect_uri': self.redirect,
                      'state': self.state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
                      'resource': resource}
            selected_scope = self.auth['scope'] if scope is None else scope
            if selected_scope:
                params['scope'] = selected_scope
            self.url = self.auth['authorization_endpoint'] + ('&' if '?' in self.auth['authorization_endpoint'] else '?') + urlencode(params)
            self.phase = 'waiting'
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            self.timer = threading.Timer(300, self.cancel)
            self.timer.daemon = True
            self.timer.start()
        except Exception:
            if self.server:
                self.server.server_close()
            raise

    def snapshot(self):
        with self.lock:
            return {'id': self.id, 'state': self.phase, 'message': self.message,
                    'authorization_url': self.url if self.phase == 'waiting' else '',
                    'redirect_uri': self.redirect, 'expires_in': max(0, int(self.deadline - time.monotonic()))}

    def stop_server(self):
        if hasattr(self, 'timer'):
            self.timer.cancel()
        if self.server:
            def stop():
                self.server.shutdown()
                self.server.server_close()
            threading.Thread(target=stop, daemon=True).start()

    def cancel(self):
        with self.lock:
            if self.phase in ('waiting', 'exchanging'):
                self.phase, self.message = 'cancelled', 'Sign-in cancelled or expired.'
                self.verifier = self.state = self.url = ''
        self.stop_server()

    def complete(self, path):
        with self.lock:
            p = urlsplit(path)
            try:
                query = parse_qs(p.query, max_num_fields=12)
            except ValueError:
                return False
            if (p.path != '/callback' or self.phase != 'waiting' or time.monotonic() >= self.deadline or
                    len(query.get('state', [])) != 1 or not secrets.compare_digest(query['state'][0], self.state)):
                return False
            if query.get('iss', [self.auth['issuer']]) != [self.auth['issuer']]:
                return False
            if 'error' in query:
                self.phase, self.message = 'failed', 'Authorization was declined by the service.'
                self.verifier = self.state = self.url = ''
                self.stop_server()
                return False
            if len(query.get('code', [])) != 1 or len(query['code'][0]) > 8192:
                return False
            self.phase = 'exchanging'  # consume state before network; reject replay
            verifier = self.verifier
        secret = None
        try:
            result = request('POST', self.auth['token_endpoint'], data={
                'grant_type': 'authorization_code', 'code': query['code'][0], 'client_id': self.client_id,
                'redirect_uri': self.redirect, 'code_verifier': verifier, 'resource': self.resource})
            oauth = dict(token_result(result), client_id=self.client_id,
                         token_endpoint=self.auth['token_endpoint'], issuer=self.auth['issuer'],
                         revocation_endpoint=self.auth.get('revocation_endpoint', ''))
            secret = {'url': self.resource, 'oauth': oauth}
            import mcp_connections
            with mcp_connections.Client(self.resource, oauth['access_token']) as client:
                tools = client.tools()
            with self.lock:
                if self.phase != 'exchanging' or time.monotonic() >= self.deadline:
                    revoke(secret)
                    return False
                mcp_connections.save_connection(self.name, secret, tools)
                self.phase, self.message = 'complete', 'Authorization saved and tools discovered.'
            return True
        except Exception:
            if secret:
                revoke(secret)
            with self.lock:
                if self.phase != 'cancelled':
                    self.phase, self.message = 'failed', 'Sign-in or tool discovery failed. Nothing was saved; try again.'
            return False
        finally:
            self.verifier = self.state = self.url = ''
            self.stop_server()


_lock = threading.RLock()
_flow = None


def manage(payload):
    global _flow
    with _lock:
        action = payload.get('action')
        if action == 'start':
            if _flow and _flow.phase in ('waiting', 'exchanging'):
                raise OAuthError('A sign-in is already pending. Finish or cancel it first.')
            name = payload.get('name')
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise OAuthError('Give the connection a name (up to 80 characters).')
            scope = payload.get('scope') or None
            if scope is not None and (not isinstance(scope, str) or len(scope) > 4096):
                raise OAuthError('Invalid OAuth scopes.')
            port = payload.get('callback_port', 0)
            if not isinstance(port, int) or isinstance(port, bool) or not (port == 0 or 1024 <= port <= 65535):
                raise OAuthError('Callback port must be 0 (automatic) or 1024 through 65535.')
            try:
                _flow = Flow(name.strip(), payload.get('url', ''), payload.get('client_id', ''), scope, port)
            except OAuthError:
                raise
            except Exception:
                raise OAuthError('Could not start OAuth sign-in. Check metadata and the callback port.') from None
            return _flow.snapshot()
        if not _flow or payload.get('id') != _flow.id:
            raise OAuthError('Sign-in session not found. Start again.')
        if action == 'cancel':
            _flow.cancel()
        elif action != 'status':
            raise OAuthError('Unknown OAuth action.')
        return _flow.snapshot()
