"""Microphone input: wake word, phrase detection, local transcription, voice lock.

One always-open mic stream feeds:
  - openWakeWord, listening for "hey Jarvis" - even while Jarvis is talking, so you
    can cut him off mid-sentence
  - webrtcvad, which cuts the audio into phrases
  - faster-whisper, which transcribes each phrase on the GPU (CPU fallback)
Phrases from voices other than your enrolled voiceprint are ignored (run enroll.bat).
Transcription runs locally; accepted commands are sent to the assistant's AI service.
"""

import collections
import glob
import os
import queue
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import sounddevice as sd
import webrtcvad
import voice_health

HERE = os.path.dirname(os.path.abspath(__file__))
VOICEPRINT_PATH = os.path.join(HERE, "data", "voiceprint.npz")
EARS_LOG = os.path.join(HERE, "data", "ears.log")
SAMPLE_RATE = 16000
BLOCK = 1280             # 80 ms - openWakeWord's frame size
BLOCK_SECONDS = BLOCK / SAMPLE_RATE
VAD_FRAME = 320          # 20 ms frames for webrtcvad
END_SILENCE = float(os.getenv("JARVIS_END_SILENCE", "1.2"))
BARGE_END_SILENCE = float(os.getenv("JARVIS_BARGE_END_SILENCE", "0.48"))
MAX_PHRASE = 15.0
MIN_SPEECH = 0.3         # shorter bursts are noise, not speech
PRE_ROLL = 4             # blocks kept from before speech starts, so the first word isn't clipped
WAKE_MODEL = "hey_jarvis_v0.1"
WAKE_THRESHOLD = float(os.getenv("JARVIS_WAKE_THRESHOLD", "0.5"))
STT_MODEL = os.getenv("JARVIS_STT_MODEL", "large-v3-turbo")
HOTWORDS = os.getenv("JARVIS_STT_HOTWORDS", "Jarvis")
WAKE_WORDS = ("jarvis", "jarvas", "jervis")
# Whisper sometimes "hears" these in noise or silence
HALLUCINATIONS = {"you", "thanks for watching", "thank you for watching", "subtitles by the amara.org community", ""}


def split_wake_word(heard: str, woke: bool = False) -> str | None:
    """Return the command after the wake word, or None if Jarvis wasn't addressed.

    `woke` means the wake-word model fired during the phrase, so Jarvis was
    addressed even if the transcript garbled his name ("hey Travis, ...").
    """
    lower = heard.lower()
    for w in WAKE_WORDS:
        if w in lower:
            return heard[lower.index(w) + len(w):].strip(" ,.!?")
    if woke:
        return re.sub(r"^\W*(hey|hi|okay|ok|a)\W+\w+\W*", "", heard, flags=re.I).strip(" ,.!?")
    return None


def command_for_mode(text, woke=False, mode="wake", in_followup=False):
    """Filter an already voice-checked phrase for the current listening mode."""
    if mode == "continuous" and not woke:
        # In natural conversation, mentioning Jarvis mid-sentence is not a prefix.
        prefix = re.match(r"^\s*(?:(?:hey|hi|okay|ok)[\s,]+)?(?:jarvis|jarvas|jervis)\b[\s,.!?]*", text, re.I)
        return text[prefix.end():].strip() if prefix else text
    command = split_wake_word(text, woke)
    if command is not None:
        return command
    return text if mode == "continuous" or in_followup else None


def find_input(name: str) -> int | None:
    """Mic index for a name (or part of one). None means the Windows default mic."""
    name = name.strip().lower()
    if not name:
        return None
    mme = next(i for i, h in enumerate(sd.query_hostapis()) if h["name"] == "MME")
    return next((i for i, d in enumerate(sd.query_devices())
                 if d["hostapi"] == mme and d["max_input_channels"] > 0
                 and (name in d["name"].lower() or d["name"].lower() in name)), None)


def _add_cuda_dlls():
    """faster-whisper needs the CUDA libraries that pip put in site-packages/nvidia."""
    for d in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin")):
        os.add_dll_directory(d)
        os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


class Transcriber:
    def __init__(self):
        _add_cuda_dlls()
        from faster_whisper import WhisperModel

        try:
            self.model = WhisperModel(STT_MODEL, device="cuda", compute_type="float16")
            self._run(np.zeros(SAMPLE_RATE, dtype=np.float32))  # warm-up; also proves the GPU works
            self.device = "GPU"
        except Exception as e:
            print(f"(GPU speech recognition unavailable: {e} - using the CPU)", flush=True)
            self.model = WhisperModel("small.en", device="cpu", compute_type="int8")
            self.device = "CPU"

    def _run(self, audio: np.ndarray) -> str:
        segments, _ = self.model.transcribe(
            audio, language="en", beam_size=1, condition_on_previous_text=False,
            without_timestamps=True, hotwords=HOTWORDS,
        )
        return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()

    def __call__(self, audio: np.ndarray) -> str:
        text = self._run(audio)
        return "" if text.lower().strip(" .!?") in HALLUCINATIONS else text


class SpeakerCheck:
    def __init__(self):
        from resemblyzer import VoiceEncoder  # slow import (torch), so only load when needed

        self.encoder = VoiceEncoder("cpu", verbose=False)

    def embed(self, audio) -> np.ndarray | None:
        """`audio` is float32 samples at 16 kHz, or a speech_recognition AudioData (enrollment)."""
        from resemblyzer import preprocess_wav

        if not isinstance(audio, np.ndarray):
            raw = audio.get_raw_data(convert_rate=SAMPLE_RATE, convert_width=2)
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        wav = preprocess_wav(audio, source_sr=SAMPLE_RATE)
        if len(wav) < SAMPLE_RATE * 0.4:  # too little speech to judge
            return None
        return self.encoder.embed_utterance(wav)


class Ears:
    def __init__(self, accepting: threading.Event):
        """`accepting` is set while Jarvis wants to hear commands; phrases spoken
        while it's clear are dropped (but the wake word still works)."""
        from openwakeword.model import Model
        from openwakeword.utils import download_models

        download_models(model_names=[WAKE_MODEL])  # no-op once downloaded
        self.wake = Model(wakeword_models=[WAKE_MODEL], inference_framework="onnx")
        self.vad = webrtcvad.Vad(2)
        self.transcribe = Transcriber()
        self.accepting = accepting
        self.on_wake = None       # called from the audio thread when "hey Jarvis" is heard
        self.on_barge_in = None   # called with (text, is_owner) for phrases spoken while Jarvis is busy
        self.level = 0.0     # mic loudness, for the HUD

        self.pool = ThreadPoolExecutor(max_workers=1)
        self.voiceprint = None
        self.threshold = 0.0
        if os.path.exists(VOICEPRINT_PATH):
            data = np.load(VOICEPRINT_PATH)
            self.voiceprint = data["embedding"]
            self.threshold = float(os.getenv("VOICE_MATCH_THRESHOLD") or data["threshold"])
            self.checker = SpeakerCheck()
            print(f"Voice lock ON (match threshold {self.threshold:.2f})", flush=True)
        else:
            print("Voice lock OFF - run enroll.bat so Jarvis only responds to you.", flush=True)

        self._blocks: queue.Queue[np.ndarray] = queue.Queue()
        self._phrases: queue.Queue[tuple[np.ndarray, bool, float]] = queue.Queue()
        self._busy_phrases: queue.Queue[tuple[np.ndarray, bool, float]] = queue.Queue(maxsize=1)
        # Pinning the mic stops e.g. a Bluetooth speaker's mic taking over when it connects
        wanted = os.getenv("JARVIS_INPUT_DEVICE", "")
        device = find_input(wanted)
        if wanted.strip() and device is None:
            print(f"(Mic '{wanted}' not found - using the Windows default mic)", flush=True)
        self.last_input = self.last_processed = 0.0
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK,
                                     device=device,
                                     callback=self._receive)
        self.mic = sd.query_devices(self.stream.device, kind="input")["name"]
        self.stream.start()
        threading.Thread(target=self._process, daemon=True).start()
        threading.Thread(target=self._barge_in_worker, daemon=True).start()
        print(f"Ears online: mic \"{self.mic}\", wake word \"hey Jarvis\", "
              f"speech recognition on the {self.transcribe.device}", flush=True)

    def _receive(self, indata, *_):
        self.last_input = time.monotonic()
        self._blocks.put(indata[:, 0].copy())

    def _is_speech(self, block: np.ndarray) -> bool:
        frames = (block[i:i + VAD_FRAME].tobytes() for i in range(0, BLOCK, VAD_FRAME))
        return sum(self.vad.is_speech(f, SAMPLE_RATE) for f in frames) >= 2

    def _process(self):
        """Runs on its own thread, in real time: wake word + cutting audio into phrases.

        Phrases that end while Jarvis is idle become commands. Phrases that end while he's
        busy go to the barge-in checker, so "Jarvis, stop" works mid-sentence.
        """
        pre_roll = collections.deque(maxlen=PRE_ROLL)
        phrase: list[np.ndarray] = []
        voiced = silence = 0
        woke = False
        wake_max = 0.0
        last_wake = 0.0
        phrase_busy = False
        while True:
            block = self._blocks.get()
            self.last_processed = time.monotonic()
            self.level = float(np.sqrt(np.mean((block / 32768.0) ** 2)))

            score = self.wake.predict(block)[WAKE_MODEL]
            wake_max = max(wake_max, score)
            if score >= WAKE_THRESHOLD and time.time() - last_wake > 2:
                last_wake = time.time()
                woke = True
                self.wake.reset()
                self._log(f"wake word {score:.2f} while {'idle' if self.accepting.is_set() else 'busy'}")
                if self.on_wake:
                    self.on_wake()

            speech = self._is_speech(block)
            if not phrase:
                pre_roll.append(block)
                if speech:
                    phrase, voiced, silence = list(pre_roll), 1, 0
                    phrase_busy = not self.accepting.is_set()
                    pre_roll.clear()
                elif time.time() - last_wake > 3:  # forget a wake word only once it's clearly stale
                    woke, wake_max = False, 0.0
                continue

            phrase.append(block)
            phrase_busy = phrase_busy or not self.accepting.is_set()
            voiced, silence = (voiced + 1, 0) if speech else (voiced, silence + 1)
            # Give normal requests room for natural pauses. Speech overlapping
            # playback retains a short endpoint so "stop" stays responsive.
            # Once the wake detector cuts playback, allow a full new request.
            end_silence = BARGE_END_SILENCE if phrase_busy and not woke else END_SILENCE
            if silence * BLOCK_SECONDS >= end_silence or len(phrase) * BLOCK_SECONDS >= MAX_PHRASE:
                if voiced * BLOCK_SECONDS >= MIN_SPEECH:
                    item = (np.concatenate(phrase), woke, wake_max)
                    # Speech that overlapped Jarvis's reply must never become a fresh
                    # command when playback ends (especially in continuous mode).
                    busy = (phrase_busy and not woke) or not self.accepting.is_set()
                    target = self._busy_phrases if busy else self._phrases
                    if busy and target.full():
                        try:
                            target.get_nowait()  # don't act on a backlog of old interruptions
                        except queue.Empty:
                            pass
                    target.put_nowait(item)
                phrase, woke, wake_max = [], False, 0.0

    def _log(self, line: str):
        """Diagnostics in data/ears.log: what was heard, wake scores, voice-lock matches."""
        try:
            with open(EARS_LOG, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")
        except OSError:
            pass

    def _owner_check(self, audio: np.ndarray) -> float | None:
        """Voice-lock match score, or None when no voiceprint is enrolled."""
        if self.voiceprint is None:
            return None
        emb = self.checker.embed(audio)
        return float(np.dot(emb, self.voiceprint)) if emb is not None else 0.0

    def _barge_in_worker(self):
        """Phrases spoken while Jarvis is busy: passed to on_barge_in(text, is_owner)."""
        while True:
            pcm, woke, wake_max = self._busy_phrases.get()
            try:
                self._handle_barge_phrase(pcm, wake_max)
            except Exception as exc:
                voice_health.recognition("recognition_error")
                self._log(f"busy: recognition failed ({type(exc).__name__}); continuing")

    def _handle_barge_phrase(self, pcm, wake_max):
        if self.on_barge_in is None:
            return
        started = time.perf_counter()
        audio = pcm.astype(np.float32) / 32768.0
        future = self.pool.submit(self.transcribe, audio)
        match = self._owner_check(audio)
        if match is not None and match < self.threshold:
            voice_health.recognition("voice_not_matched")
            self._log(f"busy: ignored a voice (match {match:.2f}, wake {wake_max:.2f})")
            return
        text = future.result()
        voice_health.recognition("recognized" if text else "no_speech")
        elapsed = time.perf_counter() - started
        self._log(f"busy: heard {text!r} (match {match if match is None else round(match, 2)}, wake {wake_max:.2f}, processing {elapsed:.2f}s)")
        if text:
            self.on_barge_in(text, match is not None)

    def listen(self, timeout: float | None = None) -> tuple[str, bool] | None:
        """Wait for one phrase. Returns (text, woke), or None if nothing usable was heard."""
        try:
            pcm, woke, wake_max = self._phrases.get(timeout=timeout)
        except queue.Empty:
            return None
        audio = pcm.astype(np.float32) / 32768.0

        if self.voiceprint is None:
            text = self.transcribe(audio)
        else:
            # Transcribe and check the voice at the same time to keep latency low
            future = self.pool.submit(self.transcribe, audio)
            score = self._owner_check(audio)
            if score < self.threshold:
                voice_health.recognition("voice_not_matched")
                print(f"(ignored a voice - match {score:.2f})", flush=True)
                self._log(f"idle: ignored a voice (match {score:.2f}, wake {wake_max:.2f})")
                return None
            text = future.result()
        voice_health.recognition("recognized" if text else "no_speech")
        self._log(f"idle: heard {text!r} (wake {wake_max:.2f})")
        return (text, woke) if text else None
