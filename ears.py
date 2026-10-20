"""Microphone input with speaker verification.

Every phrase is checked against your enrolled voiceprint (run enroll.bat), and
phrases from other voices are ignored. The check runs alongside transcription
so it adds no delay.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import speech_recognition as sr

HERE = os.path.dirname(os.path.abspath(__file__))
VOICEPRINT_PATH = os.path.join(HERE, "data", "voiceprint.npz")
SAMPLE_RATE = 16000


class SpeakerCheck:
    def __init__(self):
        from resemblyzer import VoiceEncoder  # slow import (torch), so only load when needed

        self.encoder = VoiceEncoder("cpu", verbose=False)

    def embed(self, audio: sr.AudioData) -> np.ndarray | None:
        from resemblyzer import preprocess_wav

        raw = audio.get_raw_data(convert_rate=SAMPLE_RATE, convert_width=2)
        wav = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        wav = preprocess_wav(wav, source_sr=SAMPLE_RATE)
        if len(wav) < SAMPLE_RATE * 0.4:  # too little speech to judge
            return None
        return self.encoder.embed_utterance(wav)


class Ears:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 0.6  # how long a pause ends your sentence
        self.recognizer.non_speaking_duration = 0.4
        self.mic = sr.Microphone(sample_rate=SAMPLE_RATE)
        with self.mic as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)

        self.pool = ThreadPoolExecutor(max_workers=2)
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

    def listen(self, timeout: float | None = None) -> str | None:
        """Wait for one phrase. Returns its text, or None if nothing usable was heard."""
        with self.mic as source:
            try:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=15)
            except sr.WaitTimeoutError:
                return None

        if self.voiceprint is None:
            return self._transcribe(audio)

        # Transcribe and check the voice at the same time to keep latency low
        text = self.pool.submit(self._transcribe, audio)
        emb = self.checker.embed(audio)
        score = float(np.dot(emb, self.voiceprint)) if emb is not None else 0.0
        if score < self.threshold:
            print(f"(ignored a voice - match {score:.2f})", flush=True)
            return None
        return text.result()

    def _transcribe(self, audio: sr.AudioData) -> str | None:
        try:
            return self.recognizer.recognize_google(audio)
        except (sr.UnknownValueError, sr.RequestError):
            return None
