"""Has the speaker finished? A small local model listens to how the phrase ends.

A fixed silence timer has to be long (1.2 s) so a pause mid-thought isn't taken as the end. This model
(Pipecat Smart Turn v3.2, 8 MB, BSD-2, runs on the CPU in a few tens of ms) hears the difference between
"turn off the fan." and "turn off the, um", so a finished request can be answered after a short pause while an
unfinished one still gets the full wait. If the model file is missing or fails, callers fall back to the timer.
"""
import threading
from pathlib import Path

import numpy as np

MODEL = Path(__file__).resolve().parent / "models" / "smart-turn" / "smart-turn-v3.2-cpu.onnx"
URL = "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx"
SAMPLE_RATE = 16000
WINDOW_SECONDS = 8  # the model hears the last 8 seconds


def download():
    """Fetch the model once (8 MB). Returns whether the file is there afterwards."""
    if MODEL.is_file():
        return True
    try:
        import urllib.request
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        temporary = MODEL.with_suffix(".part")
        with urllib.request.urlopen(URL, timeout=60) as response, temporary.open("wb") as handle:
            while chunk := response.read(1 << 16):
                handle.write(chunk)
        temporary.replace(MODEL)
    except Exception:
        return False
    return MODEL.is_file()


class TurnDetector:
    def __init__(self, path=MODEL):
        import onnxruntime as ort
        from faster_whisper.feature_extractor import FeatureExtractor
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 2  # the mic thread calls this; don't take every core
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        self.features = FeatureExtractor(feature_size=80, sampling_rate=SAMPLE_RATE, hop_length=160,
                                         chunk_length=WINDOW_SECONDS, n_fft=400)
        self._lock = threading.Lock()
        self.probability(np.zeros(SAMPLE_RATE, dtype=np.int16))  # warm up, and fail now rather than mid-sentence

    def probability(self, pcm) -> float:
        """0..1 that the speaker has finished. `pcm` is int16 or float32 mono at 16 kHz."""
        audio = np.asarray(pcm)
        audio = audio.astype(np.float32) / 32768.0 if audio.dtype == np.int16 else audio.astype(np.float32)
        wanted = WINDOW_SECONDS * SAMPLE_RATE
        audio = audio[-wanted:] if len(audio) >= wanted else np.pad(audio, (wanted - len(audio), 0))
        audio = (audio - audio.mean()) / np.sqrt(audio.var() + 1e-7)  # as the model's training pipeline does
        mel = self.features(audio, padding=0)[:, :WINDOW_SECONDS * 100]
        if mel.shape[1] < WINDOW_SECONDS * 100:
            mel = np.pad(mel, ((0, 0), (0, WINDOW_SECONDS * 100 - mel.shape[1])))
        with self._lock:
            value = float(self.session.run(None, {"input_features": mel[None].astype(np.float32)})[0].reshape(-1)[0])
        return value if 0.0 <= value <= 1.0 else float(1 / (1 + np.exp(-value)))


def load():
    """A ready detector, or None when it can't be used (callers then keep the silence timer)."""
    try:
        if not download():
            return None
        return TurnDetector()
    except Exception as error:
        print(f"(turn detector unavailable: {type(error).__name__} - using the pause timer)", flush=True)
        return None
