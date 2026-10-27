"""Text-to-speech.

Engines:
  voicestudio - The owner's VoiceStudio clone, generated on the GPU by the local
               VoiceStudio app. Falls back to Kokoro if the app is closed.
  qwen       - The owner's local Qwen clone.
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
import json
import os
import queue
import re
import threading
import time

import numpy as np
import requests
import sounddevice as sd
from kokoro_onnx import Kokoro

import hud
import voice_health

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(HERE, "models")
PROFILE_PATH = os.path.join(HERE, "voice-profile.json")
if os.path.isfile(PROFILE_PATH):
    with open(PROFILE_PATH, encoding="utf-8") as _profile_file:
        VOICE_PROFILE = json.load(_profile_file)
else:
    VOICE_PROFILE = {}
KOKORO_ONLY = VOICE_PROFILE.get("kokoro_only", False)


def custom_voice_style():
    """Read a complete snapshot; release the archive so fitting can keep saving."""
    path = VOICE_PROFILE.get("voice_file")
    if not path:
        return None
    with np.load(path, allow_pickle=False) as archive:
        style = archive[VOICE_PROFILE.get("voice_name", "assistant_custom")].copy()
    if style.shape != (510, 1, 256) or not np.isfinite(style).all():
        raise ValueError(f"Invalid custom Kokoro voice: {path}")
    return style.astype(np.float32)


RATE = 24000  # Kokoro's rate, and the PCM format we ask ElevenLabs for
# Sound cues Jarvis may write. Expressive ElevenLabs models perform them; other engines would read them out.
SOUND_TAGS = re.compile(r"\s*\[(chuckle|laugh|sigh|clear throat|cough|gasp|groan|sniff)\]\s*", re.I)
ELEVEN_TAGS = {"chuckle": "[soft chuckle]", "laugh": "[laughing]", "sigh": "[sigh]", "clear throat": "[clears throat]"}
BRITISH_VOICES = ["bm_george", "bm_fable", "bm_lewis", "bm_daniel"]
ENGINES = ("voicestudio", "qwen", "kokoro", "elevenlabs")
ENGINE_LABELS = {"voicestudio": "Jarvis (VoiceStudio)", "qwen": "Qwen clone",
                 "kokoro": "Kokoro", "elevenlabs": "ElevenLabs"}


def available_engines() -> list[str]:
    """Engines this copy can offer in the voice picker."""
    eleven = not KOKORO_ONLY and bool(os.getenv("ELEVENLABS_API_KEY", "").strip())
    return [e for e in ENGINES if e != "elevenlabs" or eleven]


def voice_choices(current: str = "") -> tuple[list[dict], str]:
    """Picker entries [{"id", "label"}] and the current entry's id. Every voice saved in VoiceStudio
    appears as its own choice ("voicestudio:<profile id>"), so a new voice needs no code or restart."""
    import voicestudio_voice
    found = voicestudio_voice.profiles()
    choices = [{"id": f"voicestudio:{p['id']}", "label": f"{p['name']} (VoiceStudio)"} for p in found]
    if current.startswith("voicestudio:"):  # the voice may be remembered by name rather than id
        wanted = current.partition(":")[2].casefold()
        current = next((f"voicestudio:{p['id']}" for p in found
                        if wanted in (p["id"].casefold(), p["name"].casefold())), current)
    if not choices:  # app closed: keep the current choice listed so the picker still makes sense
        choices = [{"id": current if current.startswith("voicestudio") else "voicestudio",
                    "label": "VoiceStudio voice (app closed)"}]
    elif current.startswith("voicestudio") and current not in {c["id"] for c in choices}:
        choices.insert(0, {"id": current, "label": "Current VoiceStudio voice (not found in the app)"})
    choices += [{"id": e, "label": ENGINE_LABELS[e]} for e in available_engines() if e != "voicestudio"]
    return choices, current


def is_choice(choice: str, current: str = "") -> bool:
    return choice in {c["id"] for c in voice_choices(current)[0]}
MAX_CHUNK_CHARS = 250  # merge queued sentences up to about this length
PAUSE_SECONDS = 0.18   # breath between chunks
FADE_SECONDS = 0.008   # tiny fade in/out so chunk edges never click

_REPLACEMENTS = [
    # Links belong in the interface, never in speech: keep a markdown link's label only.
    (re.compile(r"\[([^\]\n]+)\]\((?:https?://|www\.)[^)\s]*\)"), r"\1"),
    (re.compile(r"\(\s*(?:https?://|www\.)[^)\s]*\s*\)"), ""),
    (re.compile(r"(?:https?://|www\.)\S+"), ""),
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

    Release short complete sentences promptly, including quick confirmations.
    """

    _END = re.compile(r"[.!?…]+[\"')\]]*\s|\n+")
    MIN_CHARS = 1

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
        self.device_name = sd.query_devices(self._stream.device, kind="output")["name"]
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
        callbacks = []
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
                        callbacks.append(self._on_done)
                    self._cur = None
        out[filled:] = 0
        self.level = float(np.sqrt(np.mean(out * out))) if filled else 0.0
        # Never call into Voice while holding the player lock: stop() takes
        # these locks in the opposite order and could otherwise deadlock.
        for callback in callbacks:
            callback()


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
        engine, _, profile = engine.partition(":")  # "voicestudio:<profile id>" picks a VoiceStudio voice
        self.kokoro = Kokoro(
            os.path.join(MODELS_DIR, "kokoro-v1.0.onnx"),
            os.path.join(MODELS_DIR, "voices-v1.0.bin"),
        )
        custom_style = custom_voice_style()
        self.voice = custom_style if custom_style is not None else voice
        self.speed = speed
        self.eleven = None
        self.local = None
        self.studio = None
        self._studio_failures = 0
        if engine == "voicestudio":
            self._start_voicestudio(profile)
        if engine == 'qwen':
            import qwen_voice
            self.local = qwen_voice.create()
        self._eleven_failures = 0
        if engine == "elevenlabs":
            self._start_elevenlabs()
        self._text_q: queue.Queue[tuple[int, str]] = queue.Queue()
        self._gen = 0  # bumped by stop(); work from an older generation is thrown away
        self._pending = 0
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self.kokoro.create("Ready.", voice=self.voice, speed=speed, lang="en-gb")  # warm-up
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
        if self.local is not None:
            threading.Thread(target=self._warm_local, daemon=True).start()
        if self.studio is not None:
            threading.Thread(target=self._warm_studio, daemon=True).start()

    def _warm_studio(self):
        """Load VoiceStudio's model before the first reply (and start the app if it's closed)."""
        studio = self.studio
        hud.info['voice_warming'] = True
        try:
            if studio.launch():
                print("(Starting VoiceStudio...)", flush=True)
            for _ in range(90):  # the app can take a minute to start
                if self.studio is not studio:
                    return
                if studio.running():
                    started = time.monotonic()
                    studio.render("Ready.")
                    print(f"(VoiceStudio warmed in {time.monotonic() - started:.1f}s)", flush=True)
                    return
                time.sleep(1)
            hud.emit("error", text="VoiceStudio isn't running - using Kokoro until it is.")
        except Exception as e:
            print(f"(VoiceStudio warm-up failed: {e})", flush=True)
        finally:
            hud.info['voice_warming'] = False

    def _reopen_studio(self):
        try:
            self._warm_studio()
        finally:
            self._studio_reopening = False

    def _warm_local(self):
        local = self.local
        hud.info['voice_warming'] = True
        started = time.monotonic()
        try:
            local.render('Ready.')  # Load the clone before the first spoken request; do not play it.
            print(f'(Qwen warmed in {time.monotonic() - started:.1f}s)', flush=True)
        except Exception:
            hud.emit('error', text='Qwen warm-up failed; the next reply will retry loading it.')
        finally:
            hud.info['voice_warming'] = False

    def _play(self, samples: np.ndarray, on_done=None):
        with self._player_lock:
            self._player.play(samples, on_done)

    def _play_current(self, samples, gen, on_done=None):
        with self._lock:
            if gen == self._gen:
                self._play(samples, on_done)

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
        if getattr(self, "studio", None) is not None:
            return "voicestudio"
        if getattr(self, "local", None) is not None:
            return 'qwen'
        return "elevenlabs" if self.eleven else "kokoro"

    def _start_elevenlabs(self) -> bool:
        if KOKORO_ONLY:
            return False
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

    def _start_voicestudio(self, profile: str = ""):
        from voicestudio_voice import VoiceStudioEngine
        self.studio = VoiceStudioEngine(self.speed, profile)
        self._studio_failures = 0

    @property
    def choice(self) -> str:
        """The picker id of the current voice, e.g. "voicestudio:27c8e8a9" or "kokoro"."""
        studio = getattr(self, "studio", None)
        return f"voicestudio:{studio.profile}" if studio is not None else self.engine

    def switch_engine(self, engine: str) -> str:
        """Switch voice engine while running (see ENGINES, or "voicestudio:<profile id>").
        Returns the engine now in use."""
        engine, _, profile = engine.partition(":")
        if engine not in ENGINES:
            raise ValueError('Unknown voice engine.')
        studio = getattr(self, "studio", None)
        if engine == "voicestudio" and studio is not None and profile and profile != studio.profile:
            studio.profile = profile  # another VoiceStudio voice: same engine, takes effect next sentence
            self._studio_failures = 0
            threading.Thread(target=self._warm_studio, daemon=True).start()
            return engine
        if engine == self.engine:
            return engine
        local = getattr(self, 'local', None)
        if engine != 'qwen' and local is not None:
            local.cancel()
            self.local = None
        if engine != 'voicestudio':
            self.studio = None
        if engine != 'elevenlabs':
            self.eleven = None
        if engine == 'qwen':
            import qwen_voice
            self.local = qwen_voice.create()
        elif engine == 'voicestudio':
            self._start_voicestudio(profile)
            threading.Thread(target=self._warm_studio, daemon=True).start()
        elif engine == 'elevenlabs':
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
        """Yield audio pieces for `text` from the chosen engine, falling back to Kokoro."""
        studio = getattr(self, "studio", None)
        if studio is not None and not getattr(self, "_studio_reopening", False):
            from voicestudio_voice import VoiceStudioError
            try:
                started = time.monotonic()
                samples = studio.render(SOUND_TAGS.sub(' ', text).strip())
                print(f'(VoiceStudio generated {len(samples) / RATE:.1f}s audio in {time.monotonic() - started:.1f}s)', flush=True)
                self._studio_failures = 0
                if len(samples):
                    yield samples
                return
            except VoiceStudioError as e:
                self._studio_failures += 1
                print(f"(VoiceStudio: {e} - using Kokoro for this sentence)", flush=True)
                if self._studio_failures == 1:
                    hud.emit("error", text=f"VoiceStudio voice unavailable: {e}. Using Kokoro.")
                    # It may have been closed since startup: reopen it, and speak with Kokoro until it is ready
                    # instead of waiting on the dead connection every sentence.
                    self._studio_reopening = True
                    threading.Thread(target=self._reopen_studio, daemon=True).start()
        if self.local is not None:
            started = time.monotonic()
            samples = self.local.render(SOUND_TAGS.sub(' ', text).strip())
            print(f'(Qwen generated {len(samples) / RATE:.1f}s audio in {time.monotonic() - started:.1f}s)', flush=True)
            if len(samples):
                yield samples
            return
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

    def synthesize(self, text: str) -> np.ndarray:
        """Render text to one float32 array at RATE without playing it (e.g. a Telegram voice note)."""
        text = clean_for_speech(text)
        pieces = list(self._render(text)) if text else []
        return np.concatenate(pieces).astype(np.float32) if pieces else np.zeros(0, np.float32)

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
        # Playback is stopped immediately. Let in-flight local synthesis finish
        # and discard it via _gen, retaining the costly Qwen model for the next turn.
        # Explicit engine switches and process shutdown still unload the worker.

    def wait(self):
        """Block until everything queued has finished playing."""
        while not self._idle.wait(0.1):
            # A stopped/failed PortAudio stream can never deliver its completion
            # callback. This is a device-state check, not a speech time limit.
            with self._player_lock:
                active = voice_health.stream_active(self._player._stream)
            if not active:
                voice_health.output_failed()
                self.stop()
                return

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
            # Process one sentence at a time. Draining the queue here could
            # swallow a new turn arriving just after stop() changed generation.
            gen, text = self._text_q.get()
            count = 1
            if gen != self._gen:
                continue
            try:
                # Hold back one piece so the last one can get a fade-out
                held, first = None, True
                for piece in self._render(text):
                    if gen != self._gen:
                        break
                    if held is not None:
                        self._play_current(self._shape(held, first, False), gen)
                        first = False
                    held = piece
                if gen != self._gen:
                    continue
                if held is not None:
                    self._play_current(self._shape(held, first, True), gen)
                self._play_current(self._pause, gen, lambda c=count, g=gen: self._done(c, g))
            except Exception as e:  # never let one bad chunk kill the voice
                voice_health.output_failed()
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
