"""Speak through the owner's VoiceStudio voice clone (the "J.A.R.V.I.S" profile).

VoiceStudio runs locally and serves an OpenAI-style /v1/audio/speech endpoint on
127.0.0.1:3900. Requests from this PC need no key. Audio is requested as raw
24 kHz 16-bit mono PCM, which is exactly the format the player uses.
"""
import os
import subprocess
from pathlib import Path

import numpy as np
import requests

DEFAULT_URL = "http://127.0.0.1:3900"
DEFAULT_PROFILE = "J.A.R.V.I.S"  # VoiceStudio profile name or id
APP = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "VoiceStudio" / "VoiceStudio.exe"


class VoiceStudioError(Exception):
    pass


def base_url() -> str:
    return os.getenv("VOICESTUDIO_URL", DEFAULT_URL).strip().rstrip("/")


def profiles() -> list[dict]:
    """The voices saved in VoiceStudio (newest first), as [{"id", "name"}]. Empty if the app isn't running."""
    try:  # the app's own list answers in milliseconds
        voices = requests.get(base_url() + "/profiles", timeout=2).json()
        if not isinstance(voices, list):
            raise ValueError("unexpected profile list")
    except (requests.RequestException, ValueError):
        try:  # the documented OpenAI-style list is slower (about 2 s) but stable across versions
            voices = [v for v in requests.get(base_url() + "/v1/audio/voices", timeout=6).json().get("voices", [])
                      if isinstance(v, dict) and v.get("type") == "profile"]
        except (requests.RequestException, ValueError, AttributeError):
            return []
    return [{"id": str(v["id"]), "name": str(v.get("name") or v["id"])}
            for v in voices if isinstance(v, dict) and v.get("id")]


def open_app() -> bool:
    """Open (or bring forward) the VoiceStudio app so the user can make a new voice."""
    if not APP.is_file():
        return False
    subprocess.Popen([str(APP)], cwd=APP.parent, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True


class VoiceStudioEngine:
    def __init__(self, speed: float = 1.0, profile: str = ""):
        self.url = base_url()
        self.profile = profile.strip() or os.getenv("VOICESTUDIO_VOICE", DEFAULT_PROFILE).strip()
        seed = os.getenv("VOICESTUDIO_SEED", "").strip()
        self.seed = int(seed) if seed else None  # a fixed seed keeps delivery consistent between sentences
        self.speed = speed
        self.session = requests.Session()

    def running(self) -> bool:
        try:
            return self.session.get(self.url + "/health", timeout=1).ok
        except requests.RequestException:
            return False

    def launch(self) -> bool:
        """Start the VoiceStudio app if it is installed but closed. Returns True if launched."""
        if self.running() or not APP.is_file():
            return False
        subprocess.Popen([str(APP)], cwd=APP.parent, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        return True

    def render(self, text: str) -> np.ndarray:
        body = {"model": "omnivoice", "input": text, "voice": self.profile,
                "response_format": "pcm", "speed": self.speed}
        if self.seed is not None:
            body["seed"] = self.seed
        try:
            r = self.session.post(self.url + "/v1/audio/speech", json=body, timeout=(2, 60))
        except requests.RequestException as e:
            raise VoiceStudioError("VoiceStudio isn't running" if isinstance(e, requests.ConnectionError)
                                   else f"network error {type(e).__name__}") from e
        if not r.ok:
            raise VoiceStudioError(f"HTTP {r.status_code}: {r.text[:160]}")
        return np.frombuffer(r.content, dtype="<i2").astype(np.float32) / 32768.0
