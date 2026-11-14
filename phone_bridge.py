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

The phone app: the same page installs to the iPhone home screen (manifest, icons and service worker below need no
key; they hold nothing private). GET /inbox?after=N -> the shared feed: Siri Shortcut conversations (asked
without the app's X-Jarvis-Client: app header) and answers that came after the phone stopped waiting;
GET /push/key, POST /push/subscribe and /push/unsubscribe {subscription} turn alerts on and off (phone_push.py).

Hands-free (the app open on screen): POST /listen with a short WAV the app cut at a pause. It is transcribed on
this PC (the same Whisper as Telegram voice notes) and acted on only when it starts with the phone persona's name
("Friday, ...") or comes as a follow-up right after an answer (?followup=1). Anything else is dropped unread.
"""
import collections
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
MAX_AUDIO = 1_500_000  # about 45 seconds of 16 kHz speech: hands-free clips are cut at a pause, far shorter
FEED = ROOT / "data" / "phone-feed.json"
NOISE = {"", "you", "thank you", "thanks", "thank you for watching", "thanks for watching", "bye", "okay", "ok",
         "so", "um", "uh", "hmm", "mm"}  # what Whisper makes of a cough or a door; never a follow-up request
APP_FILES = {  # the installable app's files: public, like the page
    "/manifest.webmanifest": ("phone.webmanifest", "application/manifest+json"),
    "/sw.js": ("phone-sw.js", "text/javascript; charset=utf-8"),
    "/apple-touch-icon.png": ("phone-icon-180.png", "image/png"),
    "/phone-icon-180.png": ("phone-icon-180.png", "image/png"),
    "/phone-icon-192.png": ("phone-icon-192.png", "image/png"),
    "/phone-icon-512.png": ("phone-icon-512.png", "image/png"),
}
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


def from_wav(data: bytes) -> np.ndarray:
    """A mono 16-bit WAV (the app sends 16 kHz) as float32 samples at 16 kHz."""
    with wave.open(io.BytesIO(data), "rb") as file:
        if file.getsampwidth() != 2 or file.getnchannels() != 1:
            raise ValueError("Expected mono 16-bit audio.")
        rate = file.getframerate()
        samples = np.frombuffer(file.readframes(file.getnframes()), "<i2").astype("float32") / 32768
    if rate != 16000:
        samples = np.interp(np.arange(0, len(samples), rate / 16000), np.arange(len(samples)), samples).astype("float32")
    return samples


def wake_command(text: str, name: str) -> str | None:
    """"Friday, lights off" -> "lights off"; "Hey Friday" -> ""; no name at the start -> None.
    The name may follow a greeting ("hey", "okay") and come with the punctuation Whisper adds."""
    import re
    word = re.escape(name.strip().lower()) if name.strip() else "friday"
    found = re.match(rf"^\W*(?:(?:hey|hi|hello|ok|okay|yo)\W+)?{word}\b\W*(.*)$", text.strip(), re.I | re.S)
    return found.group(1).strip() if found else None


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
        self.transcribe = None   # float32 16 kHz -> text; set by jarvis.py (the Telegram voice-note transcriber)
        self.name = lambda: "Friday"  # the name hands-free listens for; jarvis.py sets it to the phone persona
        self.feed_path = None    # where the feed is kept between restarts (only the real BRIDGE has one)
        self.inbox = collections.deque(maxlen=60)  # the feed: Shortcut conversations and late answers
        self.inbox_id = 0
        self._inbox_lock = threading.Lock()

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

    def ask(self, text: str, voice=False, source="app") -> tuple[str, bytes | None]:
        """(reply text, WAV in Jarvis's voice when asked for and it could be made). A conversation the app didn't
        start itself (source "shortcut") also goes in the feed, so the app shows it."""
        answer, wav = self._ask(text, voice)
        if source != "app":
            self.to_feed("you", text)
            if not answer.startswith("Still working on that"):
                self.to_feed("jarvis", answer)
        return answer, wav

    def _ask(self, text: str, voice=False) -> tuple[str, bytes | None]:
        if not self.on_message:
            return "JARVIS isn't fully started yet. Try again in a moment.", None
        if not self.busy.acquire(timeout=5):
            return "I'm still on your last request. Give me a moment.", None
        try:
            done, box, gate, waiting = threading.Event(), [], threading.Lock(), [True]

            def reply(answer, wav=None):
                with gate:
                    if waiting[0]:
                        box.append((answer, wav))
                        done.set()
                        return
                self.late_reply(answer)  # the phone stopped waiting: send it to the app instead
            self.on_message(text, reply, voice)
            done.wait(REPLY_SECONDS)
            with gate:
                waiting[0] = False
                if box:
                    return box[0]
            return "Still working on that. I'll send the answer to your phone when it's done.", None
        finally:
            self.busy.release()

    def load_feed(self, path):
        """Keep the feed in `path` from now on, starting from what is already there."""
        self.feed_path = Path(path)
        try:
            saved = json.loads(self.feed_path.read_text(encoding="utf-8"))
            items = [i for i in saved.get("items", []) if isinstance(i, dict) and isinstance(i.get("id"), int)]
            with self._inbox_lock:
                self.inbox.extend(items[-self.inbox.maxlen:])
                self.inbox_id = max([int(saved.get("last", 0))] + [i["id"] for i in items])
        except (OSError, ValueError, AttributeError, TypeError):
            pass

    def to_feed(self, who: str, text: str) -> int:
        with self._inbox_lock:
            self.inbox_id += 1
            self.inbox.append({"id": self.inbox_id, "who": who, "text": str(text)[:4000], "t": time.time()})
            if self.feed_path:
                try:
                    temp = self.feed_path.with_suffix(".tmp")
                    temp.write_text(json.dumps({"last": self.inbox_id, "items": list(self.inbox)}), encoding="utf-8")
                    temp.replace(self.feed_path)
                except OSError:
                    pass
            return self.inbox_id

    def late_reply(self, answer: str):
        """An answer after the phone gave up waiting: kept for the app (GET /inbox) and sent as an alert."""
        number = self.to_feed("jarvis", answer)
        import phone_push
        if phone_push.ready():
            threading.Thread(target=phone_push.send, args=(self.name() or "Jarvis", str(answer)),
                             kwargs={"tag": f"reply-{number}", "kind": "reply"}, daemon=True,
                             name="phone-alert").start()

    def inbox_after(self, after: int) -> dict:
        with self._inbox_lock:
            return {"items": [item for item in self.inbox if item["id"] > after], "last": self.inbox_id,
                    "name": self.name() or "Jarvis"}

    def listen(self, audio: bytes, followup: bool) -> dict:
        """One hands-free clip. Returns {"ignored"}, {"awake"} (just the name: listen for the request next) or
        {"heard", "reply", "wav"}."""
        if not self.transcribe:
            return {"error": "Hands-free isn't ready on the PC yet."}
        text = " ".join(self.transcribe(from_wav(audio)).split())
        command = wake_command(text, self.name() or "Friday")
        if command is None:
            if not followup or text.lower().strip(" .,!?") in NOISE:
                return {"ignored": True}
            command = text  # right after an answer: no name needed, as at the PC
        if not command.strip(" .,!?"):
            return {"awake": True}
        print(f"(Phone hands-free: {command})", flush=True)
        answer, wav = self.ask(command[:3000], voice=True)
        if not wav and self.speak:
            try:
                wav = self.speak(answer)
            except Exception:
                wav = None
        return {"heard": command, "reply": answer, "wav": wav}


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
            if route in APP_FILES:
                name, kind = APP_FILES[route]
                return self.reply(200, (PAGE.parent / name).read_bytes(), kind)
            if route in ("/pending", "/inbox", "/push/key"):
                if not bridge.allowed(self.headers):
                    return self.reply(401, {"error": "key refused"})
                if route == "/inbox":
                    try:
                        after = int(self.path.partition("after=")[2].split("&")[0] or 0)
                    except ValueError:
                        after = 0
                    return self.reply(200, bridge.inbox_after(after))
                if route == "/push/key":
                    import phone_push
                    try:
                        return self.reply(200, {"key": phone_push.public_key()})
                    except Exception:
                        return self.reply(500, {"error": "Alerts can't be set up on this PC."})
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
            if route not in ("/ask", "/voice", "/answer", "/listen", "/push/subscribe", "/push/unsubscribe"):
                return self.refuse(404, "Wrong address. It should end in slash ask, or slash voice.")
            if not bridge.allowed(self.headers):
                return self.refuse(401, "Jarvis refused the phone key. Check the Authorization header.")
            if route == "/listen":
                try:
                    size = int(self.headers.get("Content-Length", 0))
                    if not 0 < size <= MAX_AUDIO:
                        raise ValueError
                    clip = self.rfile.read(size)
                    self._body_read = True
                    result = bridge.listen(clip, "followup=1" in self.path)
                except (ValueError, EOFError, wave.Error):
                    return self.refuse(400, "Jarvis couldn't read that recording.")
                if result.get("wav"):
                    return self.reply(200, result["wav"], "audio/wav", {"X-Jarvis-Reply": quote(result["reply"][:2000]),
                                                                       "X-Jarvis-Heard": quote(result["heard"][:500])})
                result.pop("wav", None)
                return self.reply(503 if "error" in result else 200, result)
            if route in ("/push/subscribe", "/push/unsubscribe"):
                import phone_push
                try:
                    size = int(self.headers.get("Content-Length", 0))
                    if not 0 < size <= 4000:
                        raise ValueError
                    body = self.rfile.read(size)
                    self._body_read = True
                    sub = json.loads(body).get("subscription")
                except (ValueError, AttributeError):
                    return self.refuse(400, "Jarvis couldn't read that alert setting.")
                if route == "/push/unsubscribe":
                    phone_push.unsubscribe(sub.get("endpoint") if isinstance(sub, dict) else None)
                    return self.reply(200, {"ok": True})
                if not phone_push.subscribe(sub):
                    return self.refuse(400, "That isn't a phone alert subscription.")
                print("(Phone alerts turned on)", flush=True)
                return self.reply(200, {"ok": True})
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
            source = "app" if self.headers.get("X-Jarvis-Client") == "app" else "shortcut"
            answer, wav = bridge.ask(text[:3000], voice=spoken, source=source)
            if spoken and not wav:  # "still working", "busy" and the like: still answer out loud
                wav = self.audio(answer)
            if route == "/voice" and wav:
                return self.reply(200, wav, "audio/wav", {"X-Jarvis-Reply": quote(answer[:2000])})
            self.reply(200, {"reply": answer})

    return Handler


BRIDGE = Bridge()
