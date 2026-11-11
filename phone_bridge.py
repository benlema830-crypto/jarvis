"""Phone: talk to JARVIS from your iPhone (web page or Siri Shortcut) over Tailscale.

The server listens on 127.0.0.1 only; `tailscale serve` publishes it to your own tailnet
(never Funnel, never the internet). Every request needs the bearer token from
    .venv\\Scripts\\python.exe scripts\\setup_phone.py
which also restricts access to your Tailscale login when you give one.

Approvals: when Jarvis is waiting for a yes or no, the phone page shows the question with Yes and No buttons
(owner's decision in the makeover plan, 2026-11-10). The tap is the owner's own answer, checked with the same
key and Tailscale login as everything else; the AI still never answers for them. A yes or no typed or spoken
from the phone answers the question too (the owner's decision, 2026-11-11; see jarvis.answer_from_phone).
preferences "phone_approvals": false turns the buttons off.

Endpoints: GET / (chat page), GET /health, POST /ask {"text"} -> {"reply"},
POST /voice {"text"} -> the reply as a WAV in Jarvis's own voice (text in the X-Jarvis-Reply header),
GET /pending -> {"question"} (the open yes/no question, if any), POST /answer {"approve": true|false}.
"""
import base64
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote
import wave

import numpy as np

import preferences

ROOT = Path(__file__).resolve().parent
STORE = ROOT / "data" / "phone-token.dpapi"
PAGE = ROOT / "hud" / "phone.html"
PORT = int(os.getenv("JARVIS_PHONE_PORT") or 7782)
REPLY_SECONDS = 170   # a turn that runs longer answers "still working" instead of hanging the phone
MAX_BODY = 8000
LOCKOUT_FAILS, LOCKOUT_SECONDS = 10, 600


def save_token(token: str):
    import win32crypt
    protected = win32crypt.CryptProtectData(token.encode(), "JARVIS Phone", None, None, None, 0)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    temp = STORE.with_suffix(".tmp")
    temp.write_bytes(base64.b64encode(protected))
    os.replace(temp, STORE)


def load_token() -> str:
    if not STORE.is_file():
        return ""
    import win32crypt
    return win32crypt.CryptUnprotectData(base64.b64decode(STORE.read_bytes()), None, None, None, 0)[1].decode()


def new_token() -> str:
    token = secrets.token_urlsafe(32)
    save_token(token)
    return token


def to_wav(samples: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(pcm)
    return out.getvalue()


def owner_login() -> str:
    """The Tailscale login allowed in (from setup); empty means the token alone decides."""
    value = preferences.read().get("phone_tailscale_login")
    return value.strip().lower() if isinstance(value, str) else ""


class Bridge:
    def __init__(self):
        self.on_message = None   # (text, reply, voice) -> None; set by jarvis.py. reply(str, wav=None) answers.
        self.speak = None        # text -> WAV bytes in the phone voice; set by jarvis.py so /voice always returns audio
        self.running = False
        self.error = ""
        self.token = ""
        self.server = None
        self.fails = []
        self.busy = threading.Lock()   # one phone turn at a time

    def status(self):
        return {"token": STORE.is_file(), "running": self.running, "port": PORT, "error": self.error}

    def start(self) -> bool:
        if self.running:
            return True
        try:
            self.token = load_token()
        except Exception:
            self.error = "The saved phone token can't be read by this Windows account."
            return False
        if not self.token:
            return False
        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(self))
        except OSError as error:
            self.error = f"Port {PORT} is in use: {error}"
            return False
        self.server.daemon_threads = True
        self.running = True
        threading.Thread(target=self.server.serve_forever, daemon=True, name="phone").start()
        return True

    def allowed(self, headers) -> bool:
        now = time.time()
        self.fails = [t for t in self.fails if now - t < LOCKOUT_SECONDS]
        if len(self.fails) >= LOCKOUT_FAILS:
            return False
        given = headers.get("Authorization", "")
        good = bool(self.token) and hmac.compare_digest(given.encode(), f"Bearer {self.token}".encode())
        owner = owner_login()
        # tailscale serve stamps who is calling; anything else on the tailnet is turned away.
        if good and owner and headers.get("Tailscale-User-Login", "").strip().lower() != owner:
            good = False
        if not good:
            self.fails.append(now)
        return good

    @staticmethod
    def approvals_on() -> bool:
        return preferences.read().get("phone_approvals", True) is not False

    def pending(self) -> dict:
        """The open yes/no question, for the phone page. Questions that take free words stay at the PC."""
        import approvals
        if not self.approvals_on() or approvals.waiting() is None or approvals.waiting_for_answer():
            return {"question": ""}
        item = approvals._pending or {}
        return {"question": str(item.get("details") or item.get("question") or "")[:1500]}

    def answer(self, approve) -> dict:
        """The owner tapped Yes or No. Returns what happened; never raises."""
        import approvals
        if type(approve) is not bool:
            return {"ok": False, "reply": "Send approve as true or false."}
        if not self.approvals_on():
            return {"ok": False, "reply": "Approving from the phone is turned off."}
        if approvals.waiting() is None or approvals.waiting_for_answer():
            return {"ok": False, "reply": "Nothing is waiting for a yes or no."}
        print(f"(Phone answered the open question: {'yes' if approve else 'no'})", flush=True)
        approvals.answer("yes" if approve else "no")
        return {"ok": True, "reply": "Approved." if approve else "Declined. Nothing was changed."}

    def ask(self, text: str, voice=False) -> tuple[str, bytes | None]:
        """(reply text, WAV in Jarvis's voice when asked for and it could be made)."""
        if not self.on_message:
            return "JARVIS isn't fully started yet. Try again in a moment.", None
        if not self.busy.acquire(timeout=5):
            return "I'm still on your last request. Give me a moment.", None
        try:
            done, box = threading.Event(), []

            def reply(answer, wav=None):
                box.append((answer, wav))
                done.set()
            self.on_message(text, reply, voice)
            if not done.wait(REPLY_SECONDS):
                return "Still working on that. I'll show the result on the PC.", None
            return box[0]
        finally:
            self.busy.release()


def make_handler(bridge: Bridge):
    class Handler(BaseHTTPRequestHandler):
        server_version = "JARVIS"
        sys_version = ""

        def log_message(self, *args):
            pass

        def reply(self, status, body, content_type="application/json", extra=None):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            route = self.path.split("?")[0]
            if route == "/health":
                return self.reply(200, {"ok": True})
            if route in ("/", "/index.html"):  # the page holds no secrets; the token is typed in once
                return self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if route == "/pending":
                if not bridge.allowed(self.headers):
                    return self.reply(401, {"error": "key refused"})
                return self.reply(200, bridge.pending())
            self.reply(404, {"error": "not found"})

        def audio(self, text):
            try:
                return bridge.speak(text) if bridge.speak else None
            except Exception:
                return None

        def drain(self):
            """Read a small unread request body before answering. Windows otherwise resets the connection
            when it closes with bytes unread, and the phone sees a dropped call instead of the reason."""
            if getattr(self, "_body_read", True):
                return
            self._body_read = True
            previous = self.connection.gettimeout()
            try:
                size = int(self.headers.get("Content-Length", 0))
                if 0 < size <= MAX_BODY:
                    self.connection.settimeout(.25)
                    self.rfile.read(size)
            except (ValueError, OSError):
                pass
            finally:
                self.connection.settimeout(previous)

        def refuse(self, status, why, spoken=False):
            # `reply` too, so a Siri Shortcut reads the problem out instead of going silent; on /voice the
            # problem comes back as audio, since Play Sound hangs on a text answer.
            print(f"(Phone request refused: {why})", flush=True)
            self.drain()
            wav = self.audio(why) if spoken else None
            if wav:
                return self.reply(status, wav, "audio/wav", {"X-Jarvis-Reply": quote(why)})
            self.reply(status, {"error": why, "reply": why})

        def do_POST(self):
            route = self.path.split("?")[0]
            self._body_read = False
            if route not in ("/ask", "/voice", "/answer"):
                return self.refuse(404, "Wrong address. It should end in slash ask, or slash voice.")
            if not bridge.allowed(self.headers):
                return self.refuse(401, "Jarvis refused the phone key. Check the Authorization header.")
            if route == "/answer":
                try:
                    size = int(self.headers.get("Content-Length", 0))
                    if not 0 < size <= 200:
                        raise ValueError
                    body = self.rfile.read(size)
                    self._body_read = True
                    choice = json.loads(body).get("approve")
                except (ValueError, AttributeError):
                    return self.refuse(400, "Jarvis couldn't read that answer.")
                result = bridge.answer(choice)
                return self.reply(200 if result["ok"] else 409, result)
            spoken = route == "/voice"  # only after the key checked out, so strangers can't make it talk
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.refuse(400, "Jarvis needs the request body set to JSON.", spoken)
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= MAX_BODY:
                    raise ValueError
                body = self.rfile.read(size)
                self._body_read = True
                text = str(json.loads(body).get("text", "")).strip()
            except (ValueError, AttributeError):
                return self.refuse(400, "Jarvis couldn't read that request. The JSON field should be called text.", spoken)
            if not text:
                return self.refuse(400, "Jarvis got an empty message. Set the text field to Dictated Text.", spoken)
            answer, wav = bridge.ask(text[:3000], voice=spoken)
            if spoken and not wav:  # "still working", "busy" and the like: still answer out loud
                wav = self.audio(answer)
            if route == "/voice" and wav:
                return self.reply(200, wav, "audio/wav", {"X-Jarvis-Reply": quote(answer[:2000])})
            self.reply(200, {"reply": answer})

    return Handler


BRIDGE = Bridge()
