"""Explicit desktop setup: local masked field, browser PKCE, DPAPI and MCP registration.

Run only after the user approves Spotify credential/connection settings changes.
No client secret is needed. No credentials, callback URLs or provider bodies print.
"""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mcp_connections as mcp
import mcp_oauth
import spotify_mcp as spotify

REDIRECT = f'http://127.0.0.1:{spotify.CALLBACK_PORT}/callback'
URL = f'http://127.0.0.1:{spotify.PORT}/mcp'
DASHBOARD = 'https://developer.spotify.com/dashboard'


def validate_client_id(client_id):
    if not isinstance(client_id, str) or not re.fullmatch(r'[A-Fa-f0-9]{32}', client_id.strip()):
        raise spotify.SpotifyError('Enter the 32-character Client ID from your Spotify developer app, not the client secret.')
    return client_id.strip()


class ClientIdDialog(simpledialog.Dialog):
    def body(self, master):
        tk.Label(master, justify='left', text=
                 '1. Open developer dashboard to edit your Spotify app settings.\n'
                 'Select Web API. In Redirect URIs, add the exact address below and save.\n'
                 'Include /callback. This is a return address, not a sign-in link.').pack(anchor='w')
        tk.Button(master, text='Open developer dashboard', command=self.open_dashboard).pack(anchor='w', pady=6)
        callback = tk.Entry(master, width=58)
        callback.insert(0, REDIRECT)
        callback.configure(state='readonly')
        callback.pack(fill='x', pady=6)
        tk.Label(master, justify='left', text=
                 '2. Enter only the app Client ID below, not the client secret.\n'
                 'Confirm the saved callback, then click Open Spotify sign-in.\n'
                 'Sign-in opens only after these checks pass. Spotify Premium is required.\n'
                 'After approval, tokens are encrypted and the Jarvis connection is saved.').pack(anchor='w')
        self.entry = tk.Entry(master, show='*', width=48)
        self.entry.pack(fill='x', pady=10)
        self.ready = tk.BooleanVar(master, value=False)
        tk.Checkbutton(master, variable=self.ready, text='I registered this callback in my Spotify developer app.').pack(anchor='w')
        self.browser_status = tk.StringVar(master, value='The dashboard button does not connect Spotify; sign-in is a separate step.')
        tk.Label(master, textvariable=self.browser_status, justify='left', wraplength=530).pack(anchor='w', pady=6)
        return self.entry

    def open_dashboard(self):
        if open_browser(DASHBOARD):
            self.browser_status.set('Developer dashboard launch requested. Check your browser, then return here after saving app settings.')
        else:
            self.browser_status.set('The browser rejected the launch request. Open https://developer.spotify.com/dashboard manually; then return here.')

    def buttonbox(self):
        box = tk.Frame(self)
        tk.Button(box, text='Open Spotify sign-in', command=self.ok, default='active').pack(side='left', padx=5, pady=5)
        tk.Button(box, text='Cancel', command=self.cancel).pack(side='left', padx=5, pady=5)
        self.bind('<Return>', self.ok)
        self.bind('<Escape>', self.cancel)
        box.pack()

    def validate(self):
        try:
            validate_client_id(self.entry.get())
            if not self.ready.get():
                raise spotify.SpotifyError('Register the callback in your developer app, then check the confirmation box before opening sign-in.')
        except spotify.SpotifyError as error:
            messagebox.showerror('JARVIS Spotify', str(error), parent=self)
            return False
        return True

    def apply(self):
        self.result = validate_client_id(self.entry.get())


def open_browser(url):
    # The callback address must never be treated as a webpage to open. Only the
    # dashboard and the internally constructed Spotify authorization URL belong here.
    parsed = urlsplit(url)
    if not (url == DASHBOARD or (parsed.scheme == 'https' and parsed.netloc == 'accounts.spotify.com'
                                and parsed.path == '/authorize' and not parsed.fragment)):
        return False
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False  # Never show exception strings that could contain the URL.


def browser_wait(root, url, done, deadline):
    """Keep the pending flow visible; retry the same in-memory PKCE URL only."""
    window = tk.Toplevel(root)
    window.title('JARVIS Spotify - browser sign-in')
    status = tk.StringVar(window, value='Opening Spotify in your default browser...')
    tk.Label(window, textvariable=status, justify='left', wraplength=510, padx=20, pady=20).pack()
    accepted = False

    def launch():
        if done.is_set() or time.monotonic() >= deadline:
            return
        if open_browser(url):
            status.set('Browser launch requested. Complete Spotify sign-in in your browser.\n\n'
                       'If no page appeared, click Open Spotify sign-in again.\n'
                       'If Spotify rejects the app or redirect, cancel and check the developer app settings.\n'
                       'This window waits up to five minutes; Jarvis is not connected yet.')
        else:
            status.set('The default browser did not accept the launch request.\n\n'
                       'Open your browser normally, then click Open Spotify sign-in again.\n'
                       'You can cancel safely. No connection has been saved.')

    def poll():
        nonlocal accepted
        if done.is_set() or time.monotonic() >= deadline:
            accepted = done.is_set()
            window.destroy()
        else:
            window.after(200, poll)

    tk.Button(window, text='Open Spotify sign-in again', command=launch).pack(pady=5)
    tk.Button(window, text='Cancel sign-in', command=window.destroy).pack(pady=10)
    window.protocol('WM_DELETE_WINDOW', window.destroy)
    window.grab_set()
    window.after(100, launch)
    window.after(200, poll)
    root.wait_window(window)
    return accepted


def authorize(client_id, wait_browser=None):
    # Validate even non-UI callers before opening sockets or launching a page.
    client_id = validate_client_id(client_id)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    done, result = threading.Event(), {}
    deadline = time.monotonic() + 300

    class Callback(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            valid = (self.headers.get('Host') == f'127.0.0.1:{spotify.CALLBACK_PORT}'
                     and not self.headers.get('Origin') and parsed.path == '/callback'
                     and len(self.path) < 8192 and time.monotonic() < deadline
                     and not done.is_set() and len(query.get('state', [])) == 1
                     and secrets.compare_digest(query['state'][0], state))
            if valid:
                if len(query.get('code', [])) == 1 and 'error' not in query:
                    result['code'] = query['code'][0]
                done.set()
            body = b'Return to the local JARVIS setup window.'
            self.send_response(200 if valid else 400)
            for key, value in [('Content-Type', 'text/plain'), ('Cache-Control', 'no-store'),
                               ('Referrer-Policy', 'no-referrer'), ('Content-Length', str(len(body)))]:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    with spotify.Server(('127.0.0.1', spotify.CALLBACK_PORT), Callback) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            auth = 'https://accounts.spotify.com/authorize?' + urlencode({
                'response_type': 'code', 'client_id': client_id, 'redirect_uri': REDIRECT,
                'scope': spotify.SCOPES, 'state': state,
                'code_challenge_method': 'S256', 'code_challenge': challenge})
            if wait_browser is not None:
                if not wait_browser(auth, done, deadline):
                    raise spotify.SpotifyError('Spotify sign-in was cancelled or timed out. Nothing was connected.')
            else:
                if not open_browser(auth):
                    raise spotify.SpotifyError('Browser could not open. Open your default browser and rerun setup.')
                done.wait(300)
            if not done.is_set() or 'code' not in result:
                raise spotify.SpotifyError('Spotify authorization was denied or timed out. Nothing was connected.')
            tokens = spotify.token_request({'grant_type': 'authorization_code', 'code': result.pop('code'),
                                            'redirect_uri': REDIRECT, 'client_id': client_id, 'code_verifier': verifier})
            if not set(spotify.SCOPES.split()) <= set(tokens.get('scope', '').split()):
                raise spotify.SpotifyError('Spotify did not grant the required playback scopes. Nothing was saved.')
            value = mcp_oauth.token_result(tokens)
            if not value['refresh_token']:
                raise spotify.SpotifyError('Spotify did not return a refresh token. Nothing was saved.')
            return dict(value, client_id=client_id, bridge_token=secrets.token_urlsafe(48))
        finally:
            server.shutdown()
            worker.join(timeout=2)


def verify_and_connect(value):
    # Verify reads before registration; never start music as a setup side effect.
    spotify.dispatch('spotify_search', {'query': 'Kind of Blue', 'limit': 1})
    devices = spotify.dispatch('spotify_devices', {})
    spotify.dispatch('spotify_playback', {})
    # Probe our actual bearer-authenticated transport before saving Jarvis settings.
    with spotify.make_server(value['bridge_token']) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with mcp.Client(URL, value['bridge_token']) as client:
                catalog = client.tools()
                result = client.rpc('tools/call', {'name': 'spotify_search', 'arguments': {'query': 'Kind of Blue', 'limit': 1}})
                if result.get('isError'):
                    raise spotify.SpotifyError('Live MCP search failed. Connection was not registered.')
            with mcp.store_lock():
                existing = next((x for x in mcp._load() if json.loads(mcp.unseal(x['secret']))['url'] == URL), None)
                if existing:
                    secret = json.loads(mcp.unseal(existing['secret']))
                    if secret.get('token') != value['bridge_token'] or not existing['enabled']:
                        raise spotify.SpotifyError('Existing local MCP connection differs or is disabled. Review it in Tool Armory before retrying.')
                    connection = mcp.public(existing)
            if not existing:
                connection = mcp.save_connection('Spotify (local)', {'url': URL, 'token': value['bridge_token']}, catalog)
        finally:
            server.shutdown()
            worker.join(timeout=2)
    return connection, bool(devices['devices'])


def main():
    root = tk.Tk()
    root.withdraw()
    try:
        # Do not overwrite an existing account or rotate a running bridge's token.
        resume = sys.argv[1:] == ['--resume']
        if spotify.STORE.exists() and not resume:
            messagebox.showinfo('JARVIS Spotify', 'Spotify credentials already exist. See docs/SPOTIFY-MCP.md for verification and recovery. Nothing changed.', parent=root)
            return 1
        if resume and not messagebox.askokcancel('JARVIS Spotify',
                'Resume the saved Spotify account, verify live access, register the local MCP connection\n'
                'and start its separate bridge? Jarvis will stay running.', parent=root):
            return 1
        if resume:
            value = spotify.load_credentials()
        else:
            value = None
        client_id = None if resume else ClientIdDialog(root, 'JARVIS Spotify client ID').result
        if client_id is None and not resume:
            return 1
        if not resume:
            value = authorize(client_id, wait_browser=lambda url, done, deadline: browser_wait(root, url, done, deadline))
            spotify.save_credentials(value)
        connection, has_devices = verify_and_connect(value)
        process = subprocess.Popen([sys.executable, str(ROOT / 'spotify_mcp.py')], cwd=ROOT,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        # Only mark the service ready after the independent process answers.
        for _ in range(20):
            if process.poll() is not None:
                raise spotify.SpotifyError('Bridge exited. Encrypted settings remain; see recovery instructions.')
            try:
                with mcp.Client(URL, value['bridge_token']) as client:
                    client.tools()
                break
            except ValueError:
                time.sleep(.25)
        else:
            raise spotify.SpotifyError('Bridge did not become ready. Settings remain; see recovery instructions.')
        report = {'connection_id': connection['id'], 'search_verified': True,
                  'playback_read_verified': True, 'devices_available': has_devices,
                  'playback_control_verified': False, 'bridge_pid': process.pid, 'checked_at': time.time()}
        path = ROOT / 'data/reports/spotify-setup.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        messagebox.showinfo('JARVIS Spotify', 'Live search and playback reads passed. The local bridge is running.\n'
                'Playback control is still unverified. Open Spotify, play a track, then ask Jarvis to pause Spotify\n'
                'and approve its normal external-tool prompt. Ask for playback state to confirm.\n'
                'The bridge must be started again after Windows restarts; no startup task was installed.', parent=root)
        return 0
    except (spotify.SpotifyError, mcp_oauth.OAuthError) as error:
        messagebox.showerror('JARVIS Spotify', str(error), parent=root)
        return 1
    except Exception:
        messagebox.showerror('JARVIS Spotify', 'Setup could not finish. No credential details were logged.\n'
                'If sign-in completed, encrypted settings may remain. See docs/SPOTIFY-MCP.md for recovery.', parent=root)
        return 1
    finally:
        root.destroy()


if __name__ == '__main__':
    raise SystemExit(main())
