"""Text-to-speech, all running locally.

Engines:
  chatterbox - Chatterbox Turbo on the GPU (most human). Runs as a helper process
               in tts-venv (see tts_server.py). Skipped if the GPU is too busy.
  kokoro     - Kokoro on the CPU. Instant, and the automatic fallback.

Sentences are synthesized on one thread and played on another, so the next
chunk is ready the moment the current one finishes. Sentences that arrive
together are synthesized together so the intonation flows naturally, and all
audio goes through one continuously open stream so there are no gaps or clicks.
"""

import collections
import os
import queue
import re
import struct
import subprocess
import threading

import numpy as np
import sounddevice as sd
from kokoro_onnx import Kokoro

import hud

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(HERE, "models")
TTS_PYTHON = os.path.join(HERE, "tts-venv", "Scripts", "python.exe")
# Sound cues Chatterbox can perform; Kokoro would read them out, so they're stripped there
SOUND_TAGS = re.compile(r"\s*\[(chuckle|laugh|sigh|clear throat|cough|gasp|groan|sniff)\]\s*", re.I)
BRITISH_VOICES = ["bm_george", "bm_fable", "bm_lewis", "bm_daniel"]
MAX_CHUNK_CHARS = 250  # merge queued sentences up to about this length
PAUSE_SECONDS = 0.18  # breath between chunks
FADE_SECONDS = 0.008  # tiny fade in/out so chunk edges never click

_REPLACEMENTS = [
    (re.compile(r"[*#`_]+"), ""),
    (re.compile(r"°\s*F\b"), " degrees Fahrenheit"),
    (re.compile(r"°\s*C\b"), " degrees Celsius"),
    (re.compile(r"°"), " degrees"),
    (re.compile(r"%"), " percent"),
    (re.compile(r"\s+"), " "),
]


def clean_for_speech(text: str) -> str:
    for pattern, repl in _REPLACEMENTS:
        text = pattern.sub(repl, text)
    return text.strip()


class SentenceBuffer:
    """Collects streamed text and releases it in sentence-sized pieces.

    Very short sentences ("Good evening, sir.") are held until the next one
    arrives, so they're spoken together instead of as a clipped fragment.
    """

    _END = re.compile(r"[.!?…]+[\"')\]]*\s|\n+")
    MIN_CHARS = 40

    def __init__(self):
        self.buf = ""

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out = []
        while True:
            m = next((m for m in self._END.finditer(self.buf) if m.end() >= self.MIN_CHARS), None)
            if m:
                out.append(self.buf[: m.end()].strip())
                self.buf = self.buf[m.end():]
            elif len(self.buf) > 220 and (cut := max(self.buf.rfind(", "), self.buf.rfind("; "))) > 40:
                out.append(self.buf[: cut + 1].strip())
                self.buf = self.buf[cut + 2:]
            else:
                return [s for s in out if s]

    def flush(self) -> str:
        rest, self.buf = self.buf.strip(), ""
        return rest


class _Player:
    """One always-open output stream that plays queued chunks back to back."""

    def __init__(self, rate: int):
        self._chunks = collections.deque()
        self._cur = None
        self._pos = 0
        self._on_done = None
        self.level = 0.0  # loudness of what's playing right now, for the HUD
        self._lock = threading.Lock()
        self._stream = sd.OutputStream(samplerate=rate, channels=1, dtype="float32", callback=self._fill)
        self._stream.start()

    def play(self, samples: np.ndarray, on_done):
        with self._lock:
            self._chunks.append((samples, on_done))

    def _fill(self, outdata, frames, time_info, status):
        out = outdata[:, 0]
        filled = 0
        with self._lock:
            while filled < frames:
                if self._cur is None:
                    if not self._chunks:
                        break
                    self._cur, self._on_done = self._chunks.popleft()
                    self._pos = 0
                n = min(frames - filled, len(self._cur) - self._pos)
                out[filled:filled + n] = self._cur[self._pos:self._pos + n]
                filled += n
                self._pos += n
                if self._pos >= len(self._cur):
                    self._on_done()
                    self._cur = None
        out[filled:] = 0
        self.level = float(np.sqrt(np.mean(out * out))) if filled else 0.0


class ChatterboxEngine:
    """Talks to tts_server.py running in tts-venv."""

    def __init__(self, voice_sample: str):
        os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
        log = open(os.path.join(HERE, "data", "tts_server.log"), "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [TTS_PYTHON, os.path.join(HERE, "tts_server.py"), voice_sample],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, cwd=HERE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.rate = None
        self.ready = threading.Event()
        threading.Thread(target=self._wait_ready, daemon=True).start()

    def _wait_ready(self):
        try:
            self.rate = struct.unpack("<I", self._read(4))[0]
        except EOFError:
            pass  # server exited (GPU busy or an error - see data/tts_server.log)
        self.ready.set()

    def _read(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.proc.stdout.read(n - len(data))
            if not chunk:
                raise EOFError("voice server stopped")
            data += chunk
        return data

    def synth(self, text: str) -> np.ndarray:
        self.proc.stdin.write(text.replace("\n", " ").encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        n = struct.unpack("<I", self._read(4))[0]
        if n == 0:
            raise RuntimeError("Chatterbox couldn't voice that text")
        return np.frombuffer(self._read(n), dtype=np.float32).copy()

    def close(self):
        self.proc.kill()


class Voice:
    def __init__(self, voice: str = "bm_george", speed: float = 1.0,
                 engine: str = "kokoro", voice_sample: str | None = None):
        self.kokoro = Kokoro(
            os.path.join(MODELS_DIR, "kokoro-v1.0.onnx"),
            os.path.join(MODELS_DIR, "voices-v1.0.bin"),
        )
        self.voice = voice
        self.speed = speed
        self.voice_sample = voice_sample
        self.chatterbox = None
        if engine == "chatterbox":
            self._start_chatterbox()
        self._text_q: queue.Queue[str] = queue.Queue()
        self._pending = 0
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        _, rate = self.kokoro.create("Ready.", voice=voice, speed=speed, lang="en-gb")  # warm-up
        self.rate = rate
        self._fade = np.linspace(0, 1, int(rate * FADE_SECONDS), dtype=np.float32)
        self._pause = np.zeros(int(rate * PAUSE_SECONDS), dtype=np.float32)
        self._player = _Player(rate)
        threading.Thread(target=self._synth_worker, daemon=True).start()

    def wait_ready(self, timeout: float = 60) -> str:
        """Wait for the Chatterbox voice to load. Returns the engine that will be used."""
        if self.chatterbox:
            self.chatterbox.ready.wait(timeout)
            if self.chatterbox.rate != self.rate:  # failed to start, or still not ready
                print("(Chatterbox voice unavailable - using Kokoro. Details: data/tts_server.log)", flush=True)
                self._drop_chatterbox()
        return "chatterbox" if self.chatterbox else "kokoro"

    def _start_chatterbox(self):
        if os.path.exists(TTS_PYTHON) and self.voice_sample:
            self.chatterbox = ChatterboxEngine(self.voice_sample)

    def _drop_chatterbox(self):
        if self.chatterbox:
            self.chatterbox.close()
            self.chatterbox = None

    def switch_engine(self, engine: str) -> str:
        """Switch between 'chatterbox' and 'kokoro' while running. Returns the engine now in use."""
        if engine == "kokoro":
            self._drop_chatterbox()  # frees the GPU memory
            return "kokoro"
        if not self.chatterbox:
            self._start_chatterbox()
        return self.wait_ready(timeout=60)

    def _render(self, text: str) -> np.ndarray:
        cb = self.chatterbox
        if cb and cb.ready.is_set() and cb.rate == self.rate:
            try:
                return cb.synth(text)
            except Exception as e:
                print(f"(Chatterbox voice failed: {e} - switching to Kokoro)", flush=True)
                self._drop_chatterbox()
        text = SOUND_TAGS.sub(" ", text).strip()
        samples, _ = self.kokoro.create(text, voice=self.voice, speed=self.speed, lang="en-gb")
        return samples.astype(np.float32)

    def say(self, text: str):
        """Queue text to be spoken. Returns immediately."""
        text = clean_for_speech(text)
        if not text:
            return
        print(f"JARVIS: {text}", flush=True)
        hud.emit("jarvis", text=text)
        with self._lock:
            if self._pending == 0:
                hud.emit("state", state="speaking")
            self._pending += 1
            self._idle.clear()
        self._text_q.put(text)

    def wait(self):
        """Block until everything queued has finished playing."""
        self._idle.wait()

    @property
    def level(self) -> float:
        return self._player.level

    def _done(self, count: int):
        with self._lock:
            self._pending -= count
            if self._pending <= 0:
                self._pending = 0
                self._idle.set()

    def _synth_worker(self):
        while True:
            # Take the next sentence plus anything else already waiting, so the
            # whole run is spoken in one natural breath.
            text, count = self._text_q.get(), 1
            while len(text) < MAX_CHUNK_CHARS:
                try:
                    text += " " + self._text_q.get_nowait()
                    count += 1
                except queue.Empty:
                    break
            try:
                samples = self._render(text)
                n = len(self._fade)
                if len(samples) > 2 * n:
                    samples[:n] *= self._fade
                    samples[-n:] *= self._fade[::-1]
                audio = np.concatenate([samples, self._pause])
                self._player.play(audio, lambda c=count: self._done(c))
            except Exception as e:  # never let one bad chunk kill the voice
                print(f"(voice error: {e})", flush=True)
                self._done(count)
