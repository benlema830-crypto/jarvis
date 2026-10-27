"""The JARVIS HUD: a live interface at http://127.0.0.1:7777.

Shows what Jarvis is doing (listening, thinking, speaking), the conversation,
live system stats, weather and schedule, and lets you type commands. It only
listens on 127.0.0.1, so nothing outside this PC can reach it.

Endpoints:
  GET  /          the page (hud/index.html)
  GET  /events    server-sent events: state changes, what was said, tools used
  GET  /status    CPU / memory / disk / GPU / network / battery as JSON
  GET  /intel     weather and schedule as JSON (cached for 10 minutes)
  POST /command   {"text": "..."} - run a typed command
  POST /stop      stop Jarvis mid-sentence

Every conversation is also saved to data/transcripts/<date>.jsonl.
"""

import collections
import datetime
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil

import context
import preferences
import voice_health

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "hud", "index.html")
from instance_config import HUD_PORT
PORT = HUD_PORT
URL = f"http://127.0.0.1:{PORT}"
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
INTEL_TTL = 600
TRANSCRIPTS = os.path.join(HERE, "data", "transcripts")
TRANSCRIBED = {"you", "jarvis", "tool", "error", "event"}
LIVE_ONLY = {"level", "usage", "settings", "ui"}  # not replayed to pages that connect later

# Read by jarvis.py: typed commands (str) and background events (dict)
commands: queue.Queue = queue.Queue()
on_stop = None  # set by jarvis.py
on_voice = None  # set by jarvis.py: switches the speaking voice
info: dict = {}  # shown on the HUD: voice engine, speech recognition device, model

_subscribers: list[queue.Queue] = []
_sub_lock = threading.Lock()
_history = collections.deque(maxlen=80)  # replayed to a page that opens mid-conversation
_state = "booting"


def emit(kind: str, /, **data):
    """Send an event to every open HUD page. Safe to call from any thread."""
    global _state
    event = {"type": kind, "t": time.time(), **data}
    if kind == "state":
        _state = data["state"]
    elif kind not in LIVE_ONLY:
        _history.append(event)
    if kind in TRANSCRIBED:
        _save_transcript(event)
    with _sub_lock:
        for q in _subscribers:
            q.put_nowait(event)


def _under_test() -> bool:
    """The test suite emits fake conversations; keep them out of the real transcript."""
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    return bool(spec and spec.name.startswith("unittest")) or "pytest" in sys.modules


def _save_transcript(event: dict):
    if _under_test():
        return
    try:
        os.makedirs(TRANSCRIPTS, exist_ok=True)
        day = datetime.date.today().isoformat()
        with open(os.path.join(TRANSCRIPTS, f"{day}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


# ---------- Live data ----------

_net_last = (time.time(), psutil.net_io_counters())
_gpu_cache = (0.0, None)


def _gpu() -> dict | None:
    global _gpu_cache
    if time.time() - _gpu_cache[0] < 4:
        return _gpu_cache[1]
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
        util, used, total, temp = (float(x) for x in out.splitlines()[0].split(","))
        gpu = {"util": util, "mem_used": used / 1024, "mem_total": total / 1024, "temp": temp}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        gpu = None
    _gpu_cache = (time.time(), gpu)
    return gpu


def status() -> dict:
    global _net_last
    now, net = time.time(), psutil.net_io_counters()
    then, prev = _net_last
    _net_last = (now, net)
    dt = max(now - then, 0.001)
    battery = psutil.sensors_battery()
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "mem": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("C:\\").percent,
        "gpu": _gpu(),
        "battery": {"percent": battery.percent, "plugged": battery.power_plugged} if battery else None,
        "uptime": time.time() - psutil.boot_time(),
        "net_up": (net.bytes_sent - prev.bytes_sent) / dt,
        "net_down": (net.bytes_recv - prev.bytes_recv) / dt,
        "state": _state,
        "info": info,
    }


_intel_cache = (0.0, None)
_intel_lock = threading.Lock()


def intel(refresh=False) -> dict:
    global _intel_cache
    with _intel_lock:
        if refresh or _intel_cache[1] is None or time.time() - _intel_cache[0] > INTEL_TTL:
            result = {}
            for key, fn in (("weather", context.weather), ("schedule", lambda: context.upcoming_events(1))):
                try:
                    result[key] = fn()
                except Exception as e:
                    result[key] = f"Unavailable ({type(e).__name__})."
            _intel_cache = (time.time(), result)
        return _intel_cache[1]


def settings():
    return {"listening_mode": preferences.listening_mode(),
            "microphone_enabled": info.get("ears") != "keyboard",
            "calendar_connected": bool(context.calendar_urls()),
            **voice_settings()}


def voice_settings():
    import voice
    choices, current = voice.voice_choices(info.get("voice_choice") or info.get("voice", ""))
    return {"voice_engine": current, "voice_engines": choices}


def update_settings(payload):
    if set(payload) == {"open_voice_studio"}:
        import voicestudio_voice
        if not voicestudio_voice.open_app():
            raise ValueError("VoiceStudio isn't installed.")
        return settings()
    if set(payload) == {"voice_engine"}:
        import voice
        if not isinstance(payload["voice_engine"], str) or not on_voice or \
                not voice.is_choice(payload["voice_engine"], info.get("voice_choice", "")):
            raise ValueError("Choose a listed voice.")
        try:
            on_voice(payload["voice_engine"])  # emits the new settings itself
        except RuntimeError as e:
            raise ValueError(str(e)) from e
        return settings()
    if set(payload) != {"listening_mode"}:
        raise ValueError("Supply a listening mode.")
    preferences.set_listening_mode(payload["listening_mode"])
    result = settings()
    emit("settings", **result)
    return result


_APP = re.compile(r"[\w .()-]{1,84}", re.ASCII)


def notification(payload):
    """Fixed prompts for local system events. The Brain supplies numbers and app names, never prose."""
    event, count = payload.get("event"), payload.get("count")
    if event == "eyes_check":
        return {"label": "Eyes check", "quiet": True, "prompt":
                "[EYES CHECK] Coach mode: use look_through_camera once. Only if the owner is clearly slouching, "
                "on their phone, or looks exhausted, say one short, kind, witty sentence about it. "
                "Otherwise reply with exactly (quiet) and nothing else."}
    app, target = str(payload.get("app", "")), str(payload.get("target", ""))
    if type(count) is not int or not 0 <= count <= 999 or not _APP.fullmatch(target) or (app and not _APP.fullmatch(app)):
        raise ValueError("Invalid notification.")
    if event == "focus_drift":
        left = payload.get("minutes_left")
        left = left if type(left) is int and 0 <= left <= 120 else 0
        return {"label": f"Focus drift {count}", "prompt":
                f"[FOCUS DRIFT] During the owner's focus session on {target}, they switched to {app} "
                f"(drift {count}, about {left} minutes left). Call it out in one short, dry, witty sentence "
                "and nudge them back. No tools."}
    if event == "focus_done":
        return {"label": "Focus complete", "chime": True, "prompt":
                f"[FOCUS COMPLETE] The owner's focus session on {target} has finished with {count} drift(s). "
                "Tell them in one sentence, with a little wit."}
    raise ValueError("Unknown notification.")


def update_calendar(payload):
    global _intel_cache
    if payload.get("action") == "disconnect":
        preferences.update(calendar_urls=[])
    elif payload.get("action") == "connect" and isinstance(payload.get("url"), str):
        context.connect_calendar(payload["url"])
    else:
        raise ValueError("Choose connect or disconnect.")
    with _intel_lock:
        _intel_cache = (0.0, None)
    result = settings()
    emit("settings", **result)
    return result


# ---------- Web server ----------

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the console for the conversation

    def _reject(self, code):
        # Windows can reset a socket when closing with an unread POST body,
        # hiding the intended HTTP error. Drain only small bodies, briefly.
        previous_timeout = self.connection.gettimeout()
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if self.command == 'POST' and 0 < length <= 16000:
                self.connection.settimeout(.25)
                self.rfile.read(length)
        except (ValueError, OSError):
            pass
        finally:
            self.connection.settimeout(previous_timeout)
        self.send_error(code)

    def _host_ok(self) -> bool:
        # Blocks DNS-rebinding: only pages actually served from this PC may talk to Jarvis
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            self._reject(403)
            return False
        # Defence in depth beside the JSON-only rule: a browser page from any other origin is refused.
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + host for host in ALLOWED_HOSTS}:
            self._reject(403)
            return False
        return True

    def _json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host_ok():
            return
        if self.path == "/":
            with open(PAGE, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/events":
            self._stream_events()
        elif self.path == "/status":
            self._json(status())
        elif self.path == "/voice-health":
            self._json(voice_health.snapshot(_state, preferences.listening_mode()))
        elif self.path in ("/intel", "/intel?refresh=1"):
            self._json(intel(refresh=self.path.endswith("refresh=1")))
        elif self.path == "/settings":
            self._json(settings())
        elif self.path == "/models":
            from model_provider import SELECTION
            self._json(SELECTION.snapshot())
        elif self.path == "/sessions":
            from agent_sessions import MANAGER
            self._json(MANAGER.snapshot())
        else:
            self.send_error(404)

    def do_POST(self):
        if not self._host_ok():
            return
        # Requiring JSON forces a CORS preflight, so other websites can't send commands
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self._reject(400)
            return
        if self.path == '/models':
            from model_provider import SELECTION
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2000:
                    raise ValueError('Invalid model request size.')
                result = SELECTION.request(json.loads(self.rfile.read(length)))
                self._json(result)
            except (ValueError, TypeError):
                self._json({'error': 'Model request rejected. Choose a listed model when no change is pending.'}, 400)
            return
        if self.path in ("/settings", "/calendar"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16000:
                    raise ValueError("Request is too large or empty.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected an object.")
                result = (update_settings if self.path == "/settings" else update_calendar)(payload)
            except (ValueError, TypeError):
                self._json({"error": "Could not save. Check the listening mode or voice, or use a valid, reachable ICS calendar link."}, 400)
                return
            except OSError:
                self._json({"error": "Could not save settings on this computer. Please try again."}, 500)
                return
            self._json(result)
            return
        if self.path == "/stop":
            if on_stop:
                on_stop()
            self._json({"ok": True})
            return
        if self.path == "/notify":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2000:
                    raise ValueError("Request is too large or empty.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or self.headers.get("Origin"):
                    raise ValueError("Notifications come from local JARVIS services only.")
                commands.put(notification(payload))
            except (ValueError, TypeError):
                self._json({"error": "Notification rejected."}, 400)
                return
            self._json({"ok": True})
            return
        if self.path != "/command":
            self.send_error(404)
            return
        try:
            length = min(int(self.headers.get("Content-Length", 0)), 4000)
            text = str(json.loads(self.rfile.read(length))["text"]).strip()
        except (ValueError, KeyError, TypeError):
            self.send_error(400)
            return
        if text:
            commands.put(text)
        self._json({"ok": True})

    def _stream_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        q: queue.Queue = queue.Queue()
        with _sub_lock:
            _subscribers.append(q)
            hello = {"type": "hello", "state": _state, "history": list(_history)}
        try:
            self.wfile.write(f"retry: 2000\ndata: {json.dumps(hello)}\n\n".encode("utf-8"))
            self.wfile.flush()
            while True:
                try:
                    msg = f"data: {json.dumps(q.get(timeout=15))}\n\n"
                except queue.Empty:
                    msg = ": keep-alive\n\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
        except OSError:
            pass  # page closed
        finally:
            with _sub_lock:
                _subscribers.remove(q)


def track_voice(level_fn):
    """Stream audio loudness so the reactor pulses as Jarvis speaks (or you do)."""
    threading.Thread(target=_level_loop, args=(level_fn,), daemon=True).start()


def _level_loop(level_fn):
    last = 0.0
    while True:
        try:
            level = level_fn()
        except Exception:  # e.g. the audio device changed mid-read; keep the meter alive
            level = 0.0
        if level > 0.002 or last > 0.002:
            emit("level", v=round(level, 4))
        last = level
        time.sleep(1 / 20)


def start() -> bool:
    """Start the HUD server in the background. Returns False if the port is taken."""
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    except OSError as e:
        print(f"(HUD unavailable - port {PORT} is in use: {e})", flush=True)
        return False
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=intel, daemon=True).start()  # warm the cache
    print(f"HUD online at {URL}", flush=True)
    return True


def open_window():
    """Open a fullscreen Edge app using Jarvis's own browser profile."""
    try:
        edge = shutil.which("msedge") or next((path for path in (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ) if os.path.isfile(path)), None)
        if not edge:
            raise FileNotFoundError("Microsoft Edge not found")
        subprocess.Popen([edge, f"--app={URL}", "--start-fullscreen", "--no-first-run",
                          "--no-default-browser-check",
                          f"--user-data-dir={os.path.join(HERE, 'data', 'hud-browser')}"],
                         creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError:
        import webbrowser
        webbrowser.open(URL)
