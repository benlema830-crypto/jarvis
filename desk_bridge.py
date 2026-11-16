"""Laptop: Jarvis's full page and a room microphone on the owner's Fedora laptop, over Tailscale.

The server listens on 127.0.0.1:7783 only; `tailscale serve --bg --https=8443 http://127.0.0.1:7783` publishes it
to the owner's own tailnet (never Funnel), so it works wherever the laptop is. Everything except the setup files
needs the laptop key AND the owner's Tailscale login, the same lock as the phone (phone_bridge.owner_login).

    Dashboard  GET /login#key=...  sets a cookie (Secure, HttpOnly, SameSite=Strict) in the laptop's Jarvis browser
               profile; every other path is passed through to the Brain page server (brain.py, 127.0.0.1:7781), so
               the laptop sees and controls exactly what the PC's page does. Requests from any other website are
               refused before they reach brain.py (its own Origin check only knows the PC).
    Room mic   POST /room/listen with a WAV clip the laptop cut at a pause (laptop/satellite.py). Transcribed on this
               PC, acted on only when it starts with "Jarvis" (always: nothing here checks whose voice it is), and answered
               in his PC voice. A request the PC's own microphone also heard is answered once, at the PC.
    Pairing    scripts/laptop_setup.py (tray: "Set up the laptop") makes a 6-digit code valid for ten minutes, used
               once. The laptop runs  curl -fsSL https://<pc>:8443/laptop | bash  and types it; POST /laptop/pair
               swaps the code for the key, which is then kept on the laptop only (chmod 600).
"""
import base64
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

import phone_bridge

ROOT = Path(__file__).resolve().parent
PORT = int(os.getenv("JARVIS_DESK_PORT") or 7783)
BRAIN_PORT = int(os.getenv("JARVIS_BRAIN_PORT") or 7781)
PUBLIC_PORT = 8443  # what `tailscale serve --https=8443` listens on
STORE = ROOT / "data" / "desk-token.dpapi"
PAIR = ROOT / "data" / "desk-pair.json"
LAPTOP = ROOT / "laptop"
COOKIE = "jarvis_desk"
MAX_UPLOAD = 100_000_000  # the workshop page may hand over a large model
REPLY_SECONDS = 170
PAIR_SECONDS = 600
HEARD_AT_PC_SECONDS = 8
CALLED_SECONDS = 15           # after "Jarvis" alone: time to say the request and for the clip to arrive
LOCKOUT_FAILS, LOCKOUT_SECONDS = 10, 600
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authenticate",
       "proxy-authorization", "content-length"}


# ---------- the laptop key ----------

def load_token() -> str:
    if not STORE.is_file():
        return ""
    import win32crypt
    return win32crypt.CryptUnprotectData(base64.b64decode(STORE.read_bytes()), None, None, None, 0)[1].decode()


def ensure_token() -> str:
    token = load_token()
    if token:
        return token
    import win32crypt
    token = secrets.token_urlsafe(32)
    STORE.parent.mkdir(exist_ok=True)
    STORE.write_bytes(base64.b64encode(win32crypt.CryptProtectData(token.encode(), "JARVIS Laptop", None, None, None, 0)))
    return token


def new_pair_code() -> str:
    """A 6-digit code the laptop can swap for the key once, within ten minutes."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    PAIR.parent.mkdir(exist_ok=True)
    PAIR.write_text(json.dumps({"hash": hashlib.sha256(code.encode()).hexdigest(), "until": time.time() + PAIR_SECONDS,
                                "tries": 0}), encoding="utf-8")
    return code


# ---------- what the PC's own microphone just heard (so the two don't both answer) ----------

_heard_at_pc: list[tuple[float, set]] = []


def _words(text):
    return {w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if w not in {"jarvis", "hey"}}


def pc_heard(text: str):
    """Called by jarvis.py when the PC's microphone accepts a request."""
    now = time.time()
    _heard_at_pc[:] = [h for h in _heard_at_pc if now - h[0] < HEARD_AT_PC_SECONDS] + [(now, _words(text))]


def heard_at_pc(text: str) -> bool:
    words, now = _words(text), time.time()
    for when, other in _heard_at_pc:
        if now - when < HEARD_AT_PC_SECONDS and words and len(words & other) >= max(1, len(words) // 2):
            return True
    return False


class Bridge:
    def __init__(self):
        self.on_message = None   # (text, reply) -> None; set by jarvis.py. reply(str, wav=None) answers.
        self.transcribe = None   # float32 16 kHz -> text; set by jarvis.py
        self.speak = None        # text -> WAV in his PC voice; set by jarvis.py
        self.token = ""
        self.running = False
        self.error = ""
        self.fails = []
        self.called_until = 0.0
        self.busy = threading.Lock()

    def start(self) -> bool:
        if self.running:
            return True
        self.key()  # no key yet is fine: "Set up the laptop" makes one and the bridge picks it up
        try:
            server = ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(self))
        except OSError as error:
            self.error = f"Port {PORT} is in use: {error}"
            return False
        server.daemon_threads = True
        self.running = True
        threading.Thread(target=server.serve_forever, daemon=True, name="laptop").start()
        return True

    def key(self) -> str:
        if not self.token:
            try:
                self.token = load_token()
            except Exception:
                self.error = "The saved laptop key can't be read by this Windows account."
        return self.token

    def locked_out(self) -> bool:
        now = time.time()
        self.fails = [t for t in self.fails if now - t < LOCKOUT_SECONDS]
        return len(self.fails) >= LOCKOUT_FAILS

    def owner_ok(self, headers) -> bool:
        owner = phone_bridge.owner_login()
        return not owner or headers.get("Tailscale-User-Login", "").strip().lower() == owner

    def allowed(self, headers, given=None) -> bool:
        """The laptop key (given, or from the Authorization header or the cookie) and the owner's Tailscale login."""
        if self.locked_out():
            return False
        given = given if given is not None else headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not given:
            for part in headers.get("Cookie", "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE:
                    given = value
        good = bool(self.key()) and bool(given) and hmac.compare_digest(given.encode(), self.token.encode())
        good = good and self.owner_ok(headers)
        if not good and given:
            self.fails.append(time.time())
        return good

    def pair(self, code, headers) -> str | None:
        """The key for a correct, unexpired, unused code from the owner's own Tailscale login; else None."""
        if self.locked_out() or not self.owner_ok(headers) or not isinstance(code, str):
            self.fails.append(time.time())
            return None
        try:
            saved = json.loads(PAIR.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        good = time.time() < saved.get("until", 0) and saved.get("tries", 0) < 5 and hmac.compare_digest(
            hashlib.sha256(code.strip().encode()).hexdigest(), str(saved.get("hash", "")))
        if not good:
            self.fails.append(time.time())
            saved["tries"] = saved.get("tries", 0) + 1
            PAIR.write_text(json.dumps(saved), encoding="utf-8")
            return None
        PAIR.unlink(missing_ok=True)  # used once
        print("(Laptop paired)", flush=True)
        return self.key() or None

    def listen(self, audio: bytes, followup: bool) -> dict:
        """One clip from the laptop's microphone: {"ignored"}, {"awake"} or {"heard", "reply", "wav"}."""
        if not self.transcribe or not self.on_message:
            return {"error": "Jarvis isn't fully started yet."}
        arrived = time.time()
        text = " ".join(self.transcribe(phone_bridge.from_wav(audio)).split())
        if phone_bridge.hint_echo(text):
            return {"ignored": True}
        command = phone_bridge.wake_command(text, "Jarvis")
        called, self.called_until = arrived < self.called_until, 0.0  # the one clip after "Jarvis" on its own
        if command is None:
            # Without his name he takes only that one clip (he chimed; the request follows). Not any clip after an
            # answer (`followup`): nothing checks whose voice this is, so stray sound in that window became
            # requests and every answer opened it again (2026-11-15).
            if not called or text.lower().strip(" .,!?") in phone_bridge.NOISE:
                return {"ignored": True}
            command = text
        if not command.strip(" .,!?"):
            self.called_until = time.time() + CALLED_SECONDS
            return {"awake": True}
        # The laptop next to the PC: both microphones hear "Jarvis, ...". Give the PC a moment to claim it.
        time.sleep(max(0.0, 2.0 - (time.time() - arrived)))
        if heard_at_pc(command):
            return {"ignored": True, "why": "heard at the PC"}
        print(f"(Laptop room mic: {command})", flush=True)
        answer, wav = self.ask(command[:3000])
        if "(quiet)" in answer.lower():  # he judged it wasn't meant for him: say nothing, not the word "quiet"
            return {"ignored": True}
        return {"heard": command, "reply": answer, "wav": wav}

    def ask(self, text: str) -> tuple[str, bytes | None]:
        if not self.busy.acquire(timeout=5):
            return "I'm still on your last request.", self._voice("I'm still on your last request.")
        try:
            done, box = threading.Event(), []
            self.on_message(text, lambda answer, wav=None: (box.append((answer, wav)), done.set()))
            if not done.wait(REPLY_SECONDS):
                answer = "Still working on that. You'll find the answer on the dashboard."
                return answer, self._voice(answer)
            answer, wav = box[0]
            return answer, wav or self._voice(answer)
        finally:
            self.busy.release()

    def _voice(self, text):
        try:
            return self.speak(text) if self.speak else None
        except Exception:
            return None


def public_url(headers) -> str:
    host = headers.get("X-Forwarded-Host") or headers.get("Host") or ""
    if host.endswith(".ts.net"):
        host += f":{PUBLIC_PORT}"
    return f"https://{host}" if host and not host.startswith("127.0.0.1") else f"https://draco420.tailf4c37e.ts.net:{PUBLIC_PORT}"


LOGIN_PAGE = b"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Jarvis</title><style>body{background:#030608;color:#dfe9e6;font:16px system-ui,sans-serif;display:grid;place-items:center;
height:100vh;margin:0}p{max-width:30em;text-align:center;color:#9bafad}</style></head><body><p id="m">Connecting to Jarvis...</p>
<script>
const key = new URLSearchParams(location.hash.slice(1)).get('key');
history.replaceState(null, '', '/login');
if (!key) document.getElementById('m').textContent = 'Open Jarvis from the Jarvis icon on this laptop. To set the laptop up, use "Set up the laptop" in the Jarvis tray menu on the PC.';
else fetch('/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key})})
  .then(r => { if (r.ok) location.replace('/board'); else document.getElementById('m').textContent = 'Jarvis refused this laptop key. Run the setup again.'; })
  .catch(() => document.getElementById('m').textContent = "Can't reach Jarvis. Is Tailscale on and the PC awake?");
</script></body></html>"""


def make_handler(bridge: Bridge):
    class Handler(BaseHTTPRequestHandler):
        server_version = "JARVIS"
        sys_version = ""

        def log_message(self, *args):
            pass

        def send(self, status, body, kind="application/json", extra=None):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def body(self, limit):
            size = int(self.headers.get("Content-Length", 0) or 0)
            if not 0 < size <= limit:
                raise ValueError("Request is empty or too large.")
            return self.rfile.read(size)

        def route(self):
            return self.path.split("?")[0]

        def do_GET(self):
            route = self.route()
            if route == "/laptop":  # the setup script, with this PC's address filled in
                script = (LAPTOP / "install.sh").read_text(encoding="utf-8").replace("__JARVIS_URL__", public_url(self.headers))
                return self.send(200, script.replace("\r\n", "\n").encode(), "text/x-shellscript; charset=utf-8")
            if route == "/laptop/satellite.py":  # Linux line endings whatever git did on Windows
                return self.send(200, (LAPTOP / "satellite.py").read_bytes().replace(b"\r\n", b"\n"),
                                 "text/x-python; charset=utf-8")
            if route == "/laptop/icon.png":
                return self.send(200, (ROOT / "hud" / "phone-icon-192.png").read_bytes(), "image/png")
            if route == "/login":
                return self.send(200, LOGIN_PAGE, "text/html; charset=utf-8")
            if not bridge.allowed(self.headers):
                if route in ("/", "/board"):
                    return self.send(303, b"", "text/plain", {"Location": "/login"})
                return self.send(401, {"error": "This laptop isn't paired with Jarvis."})
            if route == "/room/ping":
                return self.send(200, {"ok": True})
            self.proxy()

        def do_POST(self):
            route = self.route()
            try:
                if route == "/laptop/pair":
                    key = bridge.pair(json.loads(self.body(200)).get("code"), self.headers)
                    return self.send(200, {"key": key}) if key else self.send(403, {"error": "That code didn't work."})
                if route == "/login":
                    key = str(json.loads(self.body(500)).get("key", ""))
                    if not key or not bridge.allowed(self.headers, given=key):
                        return self.send(401, {"error": "Key refused."})
                    cookie = f"{COOKIE}={key}; Path=/; Max-Age=31536000; Secure; HttpOnly; SameSite=Strict"
                    return self.send(200, {"ok": True}, extra={"Set-Cookie": cookie})
            except (ValueError, AttributeError):
                return self.send(400, {"error": "Bad request."})
            if not bridge.allowed(self.headers):
                return self.send(401, {"error": "This laptop isn't paired with Jarvis."})
            if route == "/room/listen":
                try:
                    result = bridge.listen(self.body(phone_bridge.MAX_AUDIO), "followup=1" in self.path)
                except Exception as exc:  # a bad clip must not take the room mic down
                    print(f"(Laptop room mic: clip refused: {exc!r})", flush=True)
                    return self.send(400, {"error": "Jarvis couldn't read that recording."})
                if result.get("wav"):
                    return self.send(200, result["wav"], "audio/wav", {"X-Jarvis-Reply": quote(result["reply"][:2000]),
                                                                     "X-Jarvis-Heard": quote(result["heard"][:500])})
                result.pop("wav", None)
                return self.send(503 if "error" in result else 200, result)
            self.proxy()

        def proxy(self):
            """Pass the request to the Brain page server as if it came from the PC's own page."""
            origin = self.headers.get("Origin")
            if origin and origin != public_url(self.headers):
                return self.send(403, {"error": "Requests from other sites are refused."})
            try:
                size = int(self.headers.get("Content-Length", 0) or 0)
                if not 0 <= size <= MAX_UPLOAD:
                    raise ValueError
                body = self.rfile.read(size) if size else None
            except ValueError:
                return self.send(400, {"error": "Bad request size."})
            headers = {k: v for k, v in self.headers.items() if k.lower() in ("content-type", "accept", "last-event-id")}
            headers["Host"] = f"127.0.0.1:{BRAIN_PORT}"
            if origin:
                headers["Origin"] = f"http://127.0.0.1:{BRAIN_PORT}"
            streaming = self.route() == "/events"
            connection = http.client.HTTPConnection("127.0.0.1", BRAIN_PORT, timeout=None if streaming else 120)
            try:
                connection.request(self.command, self.path, body, headers)
                upstream = connection.getresponse()
                self.send_response(upstream.status)
                for name, value in upstream.getheaders():
                    if name.lower() not in HOP and name.lower() != "access-control-allow-origin":
                        self.send_header(name, value)
                self.send_header("Connection", "close")  # the end of the body is the end of the connection
                self.end_headers()
                while chunk := (upstream.read1(65536) if streaming else upstream.read(65536)):
                    self.wfile.write(chunk)
                    if streaming:
                        self.wfile.flush()
            except OSError:
                try:
                    self.send(503, {"error": "Jarvis's page server isn't running on the PC."})
                except OSError:
                    pass
            finally:
                connection.close()

    return Handler


BRIDGE = Bridge()
