"""Speak through the owner's VoiceStudio voice clone (the "J.A.R.V.I.S" profile).

VoiceStudio runs locally and serves an OpenAI-style /v1/audio/speech endpoint on
127.0.0.1:3900. Requests from this PC need no key. Audio is requested as raw
24 kHz 16-bit mono PCM, which is exactly the format the player uses.
"""
import os
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import requests

DEFAULT_URL = "http://127.0.0.1:3900"
DEFAULT_PROFILE = "J.A.R.V.I.S"  # VoiceStudio profile name or id
APP = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "VoiceStudio" / "VoiceStudio.exe"


class VoiceStudioError(Exception):
    pass


def _app_processes() -> set[int]:
    """Process IDs of the running VoiceStudio app (its window and helpers)."""
    import psutil
    app = str(APP).casefold()
    found = set()
    for proc in psutil.process_iter(["exe"]):
        try:
            if (proc.info["exe"] or "").casefold() == app:
                found.add(proc.pid)
        except (psutil.Error, OSError):
            pass
    return found


def _tuck_away(focus, seconds=25):
    """Minimize VoiceStudio's windows as they appear after a launch, and give focus back."""
    import win32con
    import win32gui
    import win32process
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pids = _app_processes()
        def visit(hwnd, _):
            if (win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd) and win32gui.GetWindowText(hwnd)
                    and win32process.GetWindowThreadProcessId(hwnd)[1] in pids):
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWMINNOACTIVE)
            return True
        try:
            win32gui.EnumWindows(visit, None)
            if focus and win32gui.IsWindow(focus) and win32gui.GetForegroundWindow() != focus:
                win32gui.SetForegroundWindow(focus)
        except Exception:
            pass
        time.sleep(.25)


def base_url() -> str:
    return os.getenv("VOICESTUDIO_URL", DEFAULT_URL).strip().rstrip("/")


PROFILE_CACHE_SECONDS = 15
_profiles_cache = (0.0, [])


def profiles(max_age=PROFILE_CACHE_SECONDS) -> list[dict]:
    """The voices saved in VoiceStudio (newest first), as [{"id", "name"}]. Empty if the app isn't running.

    A list fetched within max_age seconds is reused: the Brain page asks on every load and settings
    change, and a busy VoiceStudio can take seconds to answer. Pass max_age=0 to ask the app now."""
    global _profiles_cache
    fetched, found = _profiles_cache
    if time.monotonic() - fetched < max_age:
        return [dict(p) for p in found]
    found = _fetch_profiles()
    _profiles_cache = (time.monotonic(), found)
    return [dict(p) for p in found]


def _fetch_profiles() -> list[dict]:
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
        """Start the VoiceStudio app in the background if it is installed but closed. Returns True if launched.

        Its window ignores a minimized start, so it is minimized as it appears and focus goes back to the
        user's window. Never starts a second copy while one is still starting up."""
        if self.running() or not APP.is_file() or _app_processes():
            return False
        import win32gui
        focus = win32gui.GetForegroundWindow()
        subprocess.Popen([str(APP)], cwd=APP.parent, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        threading.Thread(target=_tuck_away, args=(focus,), daemon=True).start()
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
