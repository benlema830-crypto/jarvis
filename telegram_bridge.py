"""Telegram: message JARVIS from your phone by text or voice note; he replies in kind.

One-time setup: create a bot with @BotFather, then run
    .venv\\Scripts\\python.exe scripts\\setup_telegram.py
It stores the bot token with Windows DPAPI and pairs exactly one chat (yours) with a
one-time code. Messages from any other chat are ignored. Telegram can't approve risky
actions: approvals still need your spoken "yes" at the PC.

Uses the Bot API over HTTPS long polling (no webhook, no open port), `requests` for HTTP
and PyAV (already installed for speech) for Opus voice notes.
"""
import base64
import io
import os
from pathlib import Path
import threading
import time

import numpy as np
import requests

import preferences

ROOT = Path(__file__).resolve().parent
STORE = ROOT / "data" / "telegram-token.dpapi"
API = "https://api.telegram.org/bot{token}/{method}"
FILE_API = "https://api.telegram.org/file/bot{token}/{path}"
MAX_AGE = 15 * 60  # messages older than this (sent while JARVIS was off) get a short notice instead


def save_token(token: str):
    import win32crypt
    token = token.strip()
    if not token or any(c.isspace() for c in token) or ":" not in token:
        raise ValueError("That doesn't look like a bot token (it should contain a colon).")
    protected = win32crypt.CryptProtectData(token.encode(), "JARVIS Telegram", None, None, None, 0)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    temp = STORE.with_suffix(".tmp")
    temp.write_bytes(base64.b64encode(protected))
    os.replace(temp, STORE)


def load_token() -> str:
    if not STORE.is_file():
        return ""
    import win32crypt
    return win32crypt.CryptUnprotectData(base64.b64decode(STORE.read_bytes()), None, None, None, 0)[1].decode()


def chat_id():
    value = preferences.read().get("telegram_chat_id")
    return value if type(value) is int else None


def call(token, method, timeout=30, files=None, **params):
    response = requests.post(API.format(token=token, method=method), data=params if files else None,
                             json=None if files else params, files=files, timeout=timeout)
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram request failed"))
    return data["result"]


# ---------- Audio: Opus voice notes <-> PCM ----------

def decode_voice(blob: bytes, rate: int = 16000) -> np.ndarray:
    import av
    out = []
    with av.open(io.BytesIO(blob)) as container:
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        for frame in container.decode(audio=0):
            for chunk in resampler.resample(frame):
                out.append(chunk.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.float32) if out else np.zeros(0, np.float32)


def encode_voice(samples: np.ndarray, rate: int) -> bytes:
    """Mono float32 PCM -> OGG/Opus, the format Telegram plays as a voice note."""
    import av
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="ogg") as container:
        stream = container.add_stream("libopus", rate=48000)
        stream.layout = "mono"
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
        frame.sample_rate = rate
        for chunk in resampler.resample(frame) + resampler.resample(None):
            for packet in stream.encode(chunk):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return buffer.getvalue()


# ---------- The bridge ----------

class Bridge:
    def __init__(self):
        self.on_message = None   # (chat, text, was_voice) -> None; set by jarvis.py
        self.transcribe = None   # float32 16 kHz -> text; set by jarvis.py
        self.running = False
        self.error = ""
        self.ignored = 0
        self.token = ""

    def status(self):
        try:
            has_token = STORE.is_file()
        except OSError:
            has_token = False
        return {"token": has_token, "paired": chat_id() is not None, "running": self.running,
                "error": self.error, "ignored_chats": self.ignored}

    def start(self) -> bool:
        if self.running:
            return True
        try:
            self.token = load_token()
        except Exception:
            self.error = "The saved Telegram token can't be read by this Windows account."
            return False
        if not self.token or chat_id() is None:
            return False
        self.running = True
        threading.Thread(target=self._loop, daemon=True, name="telegram").start()
        return True

    def _loop(self):
        offset, backoff = None, 2
        while self.running:
            try:
                updates = self._updates(offset)
                self.error, backoff = "", 2
                for update in updates:
                    offset = update["update_id"] + 1
                    try:
                        self._handle(update.get("message") or {})
                    except Exception as error:  # one bad message must not stop the bridge
                        self.error = f"Message handling failed: {type(error).__name__}"
            except requests.RequestException:
                self.error = "Can't reach Telegram; retrying."
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except Exception as error:  # anything unexpected: report, back off, keep polling
                self.error = str(error)[:200] or type(error).__name__
                if "Unauthorized" in self.error or "Conflict" in self.error:
                    time.sleep(30)  # revoked token, or another program polling the same bot
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _updates(self, offset):
        params = {"timeout": 25, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        response = requests.post(API.format(token=self.token, method="getUpdates"), json=params, timeout=40)
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Telegram polling failed"))
        return data["result"]

    def _handle(self, message):
        chat = (message.get("chat") or {}).get("id")
        if chat is None:
            return
        if chat != chat_id():
            self.ignored += 1
            return
        if time.time() - message.get("date", 0) > MAX_AGE:
            self.send(chat, "I was offline when you sent that. Send it again if it still matters.")
            return
        text = (message.get("text") or "").strip()
        if text.startswith("/start") or text.startswith("/help"):
            self.send(chat, "JARVIS here. Message me or send a voice note. I'll reply here; "
                            "anything risky still needs your OK at the PC.")
            return
        was_voice = False
        if not text and (message.get("voice") or message.get("audio")):
            media = message.get("voice") or message.get("audio")
            if media.get("file_size", 0) > 20_000_000 or not self.transcribe:
                self.send(chat, "I can't take that voice note right now.")
                return
            info = call(self.token, "getFile", file_id=media["file_id"])
            blob = requests.get(FILE_API.format(token=self.token, path=info["file_path"]), timeout=60).content
            text = self.transcribe(decode_voice(blob)).strip()
            if not text:
                self.send(chat, "I couldn't make that out. Try again?")
                return
            was_voice = True
        if text and self.on_message:
            self.typing(chat)
            self.on_message(chat, text[:3000], was_voice)

    def typing(self, chat):
        try:
            call(self.token, "sendChatAction", timeout=10, chat_id=chat, action="typing")
        except Exception:
            pass

    def send(self, chat, text: str):
        text = text.strip() or "(no reply)"
        for start in range(0, len(text), 4000):
            call(self.token, "sendMessage", timeout=20, chat_id=chat, text=text[start:start + 4000])

    def send_voice(self, chat, samples: np.ndarray, rate: int):
        call(self.token, "sendVoice", timeout=60, files={"voice": ("jarvis.ogg", encode_voice(samples, rate), "audio/ogg")},
             chat_id=str(chat))


BRIDGE = Bridge()


def send_to_owner(text: str) -> str:
    """Used by the send_telegram tool: only ever the paired owner chat."""
    chat = chat_id()
    if chat is None or not STORE.is_file():
        return "Telegram isn't set up. Run scripts\\setup_telegram.py once."
    BRIDGE.token = BRIDGE.token or load_token()
    BRIDGE.send(chat, text)
    return "Sent to your Telegram."
