"""Text-to-speech.

Engines:
  elevenlabs - ElevenLabs over the network (most human). Audio streams in, so
               playback starts before the whole sentence is generated.
  kokoro     - Kokoro on the CPU. Instant, offline, and the automatic fallback
               if ElevenLabs is unavailable or out of credits.

Sentences are synthesized on one thread and played on another, so the next
chunk is ready the moment the current one finishes. Sentences that arrive
together are synthesized together so the intonation flows naturally, and all
audio goes through one continuously open stream so there are no gaps or clicks.
"""

import collections
import os
import queue
import re
import threading

import numpy as np
import requests
import sounddevice as sd
from kokoro_onnx import Kokoro

import hud

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(HERE, "models")
RATE = 24000  # Kokoro's rate, and the PCM format we ask ElevenLabs for
# Sound cues Jarvis may write. Expressive ElevenLabs models perform them; other engines would read them out.
SOUND_TAGS = re.compile(r"\s*\[(chuckle|laugh|sigh|clear throat|cough|gasp|groan|sniff)\]\s*", re.I)
ELEVEN_TAGS = {"chuckle": "[soft chuckle]", "laugh": "[laughing]", "sigh": "[sigh]", "clear throat": "[clears throat]"}
BRITISH_VOICES = ["bm_george", "bm_fable", "bm_lewis", "bm_daniel"]
MAX_CHUNK_CHARS = 250  # merge queued sentences up to about this length
PAUSE_SECONDS = 0.18   # breath between chunks
FADE_SECONDS = 0.008   # tiny fade in/out so chunk edges never click

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


def output_devices() -> list[tuple[int, str]]:
    """Playback devices as (sounddevice index, name). MME names, since MME converts sample rates for us."""
    mme = next(i for i, h in enumerate(sd.query_hostapis()) if h["name"] == "MME")
    return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d["hostapi"] == mme and d["max_output_channels"] > 0 and "Mapper" not in d["name"]]


def find_output(name: str) -> int | None:
    """Device index for a name (or part of one, e.g. "Bose"). None means the Windows default."""
    name = name.strip().lower()
    if not name:
        return None
    return next((i for i, n in output_devices() if name in n.lower() or n.lower() in name), None)


class _Player:
    """One always-open output stream that plays queued chunks back to back."""

    def __init__(self, rate: int, device: int | None = None):
        self._chunks = collections.deque()
        self._cur = None
        self._pos = 0
        self._on_done = None
        self.level = 0.0  # loudness of what's playing right now, for the HUD
        self._lock = threading.Lock()
        self._stream = sd.OutputStream(samplerate=rate, channels=1, dtype="float32", callback=self._fill,
                                       device=device)
        self._stream.start()

    def play(self, samples: np.ndarray, on_done=None):
        with self._lock:
            self._chunks.append((samples, on_done))

    def clear(self):
        with self._lock:
            self._chunks.clear()
            self._cur = None

    def close(self) -> list:
        """Stop playing; returns what hadn't been played yet, so another player can finish it."""
        with self._lock:
            left = list(self._chunks)
            if self._cur is not None:
                left.insert(0, (self._cur[self._pos:], self._on_done))
            self._chunks.clear()
            self._cur = None
        self._stream.close()
        return left

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
                    if self._on_done:
                        self._on_done()
                    self._cur = None
        out[filled:] = 0
        self.level = float(np.sqrt(np.mean(out * out))) if filled else 0.0


class ElevenLabsError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"ElevenLabs error {status}: {detail}")
        self.status = status


class ElevenLabsEngine:
    URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

    def __init__(self, api_key: str, voice_id: str, model: str, speed: float):
        self.session = requests.Session()
        self.session.headers["xi-api-key"] = api_key
        self.voice_id = voice_id
        self.model = model
        self.expressive = model.startswith(("eleven_v3", "eleven_v4"))  # these perform [sigh] etc.
        self.settings = {
            "stability": float(os.getenv("ELEVENLABS_STABILITY", "0.5")),
            "similarity_boost": float(os.getenv("ELEVENLABS_SIMILARITY", "0.75")),
            "style": float(os.getenv("ELEVENLABS_STYLE", "0")),
            "use_speaker_boost": True,
        }
        if not model.startswith("eleven_v4"):  # v4 has no speed setting
            self.settings["speed"] = speed
        self.previous_text = ""

    def prepare(self, text: str) -> str:
        if self.expressive:
            return SOUND_TAGS.sub(lambda m: f" {ELEVEN_TAGS.get(m.group(1).lower(), '')} ", text).strip()
        return SOUND_TAGS.sub(" ", text).strip()

    def stream(self, text: str):
        """Yield float32 audio pieces (~100 ms each) as they arrive."""
        body = {"text": self.prepare(text), "model_id": self.model, "voice_settings": self.settings}
        if self.previous_text and not self.expressive:
            body["previous_text"] = self.previous_text[-500:]  # keeps intonation flowing between chunks
        resp = self.session.post(self.URL.format(voice_id=self.voice_id), params={"output_format": "pcm_24000"},
                                 json=body, stream=True, timeout=(5, 20))
        if resp.status_code != 200:
            raise ElevenLabsError(resp.status_code, resp.text[:300])
        leftover = b""
        for chunk in resp.iter_content(chunk_size=4800):
            data = leftover + chunk
            usable = len(data) // 2 * 2
            leftover = data[usable:]
            if usable:
                yield np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0
        self.previous_text = text


def _chime() -> np.ndarray:
    """Two soft rising notes: "I'm listening"."""
    def note(freq, secs):
        t = np.arange(int(RATE * secs)) / RATE
        return np.sin(2 * np.pi * freq * t) * np.exp(-t * 18)
    return (np.concatenate([note(880, 0.09), note(1320, 0.16)]) * 0.18).astype(np.float32)


class Voice:
    def __init__(self, voice: str = "bm_george", speed: float = 1.0, engine: str = "kokoro"):
        self.kokoro = Kokoro(
            os.path.join(MODELS_DIR, "kokoro-v1.0.onnx"),
            os.path.join(MODELS_DIR, "voices-v1.0.bin"),
        )
        self.voice = voice
        self.speed = speed
        self.eleven = None
        self._eleven_failures = 0
        if engine == "elevenlabs":
            self._start_elevenlabs()
        self._text_q: queue.Queue[tuple[int, str]] = queue.Queue()
        self._gen = 0  # bumped by stop(); work from an older generation is thrown away
        self._pending = 0
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self.kokoro.create("Ready.", voice=voice, speed=speed, lang="en-gb")  # warm-up
        self._fade = np.linspace(0, 1, int(RATE * FADE_SECONDS), dtype=np.float32)
        self._pause = np.zeros(int(RATE * PAUSE_SECONDS), dtype=np.float32)
        self._chime = _chime()
        self.output = os.getenv("JARVIS_OUTPUT_DEVICE", "").strip()
        device = find_output(self.output)
        if self.output and device is None:
            print(f"(Speaker '{self.output}' not found - using the Windows default output)", flush=True)
            self.output = ""
        self._player = _Player(RATE, device)
        self._player_lock = threading.Lock()  # held while swapping devices, so no chunk lands on a closed player
        threading.Thread(target=self._synth_worker, daemon=True).start()

    def _play(self, samples: np.ndarray, on_done=None):
        with self._player_lock:
            self._player.play(samples, on_done)

    def set_output(self, name: str) -> str:
        """Play through another device ("" = Windows default). Returns its name."""
        device = find_output(name)
        if name.strip() and device is None:
            raise ValueError(f"No audio output matches '{name}'.")
        new = _Player(RATE, device)
        with self._player_lock:
            old, self._player = self._player, new
            for samples, on_done in old.close():  # finish the current sentence on the new device
                new.play(samples, on_done)
        self.output = dict(output_devices()).get(device, "") if device is not None else ""
        return self.output or "the Windows default output"

    def test_outputs(self) -> list[tuple[int, str]]:
        """Say "This is speaker number N" through each output in turn."""
        devices = output_devices()
        for n, (index, _) in enumerate(devices, 1):
            samples, _ = self.kokoro.create(f"This is speaker number {n}.", voice=self.voice, speed=self.speed, lang="en-gb")
            sd.play(samples.astype(np.float32), RATE, device=index, blocking=True)
        return devices

    @property
    def engine(self) -> str:
        return "elevenlabs" if self.eleven else "kokoro"

    def _start_elevenlabs(self) -> bool:
        key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if not key:
            return False
        self.eleven = ElevenLabsEngine(
            key,
            os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb").strip(),  # "George", a premade British voice
            os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5").strip(),
            self.speed,
        )
        self._eleven_failures = 0
        return True

    def switch_engine(self, engine: str) -> str:
        """Switch between 'elevenlabs' and 'kokoro' while running. Returns the engine now in use."""
        if engine == "kokoro":
            self.eleven = None
        elif not self.eleven:
            self._start_elevenlabs()
        return self.engine

    def _drop_elevenlabs(self, reason: str):
        print(f"(ElevenLabs voice unavailable: {reason} - switching to Kokoro)", flush=True)
        hud.emit("error", text=f"ElevenLabs voice unavailable: {reason}")
        self.eleven = None

    def _eleven_failed(self, reason: str):
        """A one-off failure: use Kokoro for this sentence; give up after three in a row."""
        self._eleven_failures += 1
        if self._eleven_failures >= 3:
            self._drop_elevenlabs(reason)
        else:
            print(f"(ElevenLabs: {reason} - using Kokoro for this sentence)", flush=True)

    def _render(self, text: str):
        """Yield audio pieces for `text`, from ElevenLabs if possible, else Kokoro."""
        el = self.eleven
        if el:
            started = False
            try:
                for piece in el.stream(text):
                    started = True
                    yield piece
                self._eleven_failures = 0
                return
            except ElevenLabsError as e:
                if e.status in (401, 402, 403) or "quota" in str(e).lower():
                    self._drop_elevenlabs(str(e))  # bad key or out of credits: stop trying this session
                else:
                    self._eleven_failed(str(e))
            except requests.RequestException as e:
                self._eleven_failed(f"network error {type(e).__name__}")
            if started:
                return  # half a sentence already played; don't repeat it in another voice
        text = SOUND_TAGS.sub(" ", text).strip()
        samples, _ = self.kokoro.create(text, voice=self.voice, speed=self.speed, lang="en-gb")
        yield samples.astype(np.float32)

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
            self._text_q.put((self._gen, text))

    def chime(self):
        """Play the "listening" chime right away."""
        self._play(self._chime)

    def stop(self):
        """Stop talking immediately and drop everything queued."""
        with self._lock:
            self._gen += 1
            while True:
                try:
                    self._text_q.get_nowait()
                except queue.Empty:
                    break
            self._player.clear()
            self._pending = 0
            self._idle.set()

    def wait(self):
        """Block until everything queued has finished playing."""
        self._idle.wait()

    @property
    def level(self) -> float:
        return self._player.level

    def _done(self, count: int, gen: int):
        with self._lock:
            if gen != self._gen:
                return  # stop() already reset the count
            self._pending -= count
            if self._pending <= 0:
                self._pending = 0
                self._idle.set()

    def _synth_worker(self):
        while True:
            # Take the next sentence plus anything else already waiting, so the
            # whole run is spoken in one natural breath.
            gen, text = self._text_q.get()
            count = 1
            while len(text) < MAX_CHUNK_CHARS:
                try:
                    g, more = self._text_q.get_nowait()
                except queue.Empty:
                    break
                if g == gen:
                    text += " " + more
                    count += 1
            if gen != self._gen:
                continue
            try:
                # Hold back one piece so the last one can get a fade-out
                held, first = None, True
                for piece in self._render(text):
                    if gen != self._gen:
                        break
                    if held is not None:
                        self._play(self._shape(held, first, False))
                        first = False
                    held = piece
                if gen != self._gen:
                    continue
                if held is not None:
                    self._play(self._shape(held, first, True))
                self._play(self._pause, lambda c=count, g=gen: self._done(c, g))
            except Exception as e:  # never let one bad chunk kill the voice
                print(f"(voice error: {e})", flush=True)
                self._done(count, gen)

    def _shape(self, samples: np.ndarray, fade_in: bool, fade_out: bool) -> np.ndarray:
        n = len(self._fade)
        if len(samples) > 2 * n:
            samples = samples.copy()
            if fade_in:
                samples[:n] *= self._fade
            if fade_out:
                samples[-n:] *= self._fade[::-1]
        return samples
