"""Piper voices: offline CPU text-to-speech from a downloaded <name>.onnx + <name>.onnx.json pair.

Drop both files into models/piper and the voice appears in the picker as "<name> (Piper)".
"""

import glob
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PIPER_DIR = os.path.join(HERE, "models", "piper")


def voices() -> list[str]:
    """Names of the Piper voices installed (each needs its .onnx.json beside it)."""
    found = glob.glob(os.path.join(PIPER_DIR, "*.onnx"))
    return sorted(os.path.basename(p)[:-5] for p in found if os.path.isfile(p + ".json"))


class PiperEngine:
    def __init__(self, name: str = "", speed: float = 1.0, rate: int = 24000):
        from piper import PiperVoice
        installed = voices()
        if not installed:
            raise RuntimeError(f"No Piper voices found in {PIPER_DIR}.")
        self.name = name if name in installed else installed[0]
        self.voice = PiperVoice.load(os.path.join(PIPER_DIR, self.name + ".onnx"))
        self.speed = speed
        self.rate = rate

    def render(self, text: str) -> np.ndarray:
        """Float32 audio at self.rate (Piper voices are usually 22050 Hz, so it's resampled)."""
        from piper import SynthesisConfig
        base = self.voice.config.length_scale or 1.0  # the voice's own pace, from its .onnx.json
        config = SynthesisConfig(length_scale=base / self.speed)
        chunks = [c.audio_float_array for c in self.voice.synthesize(text, syn_config=config)]
        if not chunks:
            return np.zeros(0, np.float32)
        samples = np.concatenate(chunks).astype(np.float32)
        source = self.voice.config.sample_rate
        if source != self.rate:
            n = int(len(samples) * self.rate / source)
            samples = np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples).astype(np.float32)
        return samples
