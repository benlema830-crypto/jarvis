"""Spoken Spotify commands that act immediately, without an AI turn or a spoken reply.

parse() recognises only plain playback requests ("pause the music", "next song", "play <song>");
anything else is left to the assistant. run() returns None when the text isn't a music command
(or Spotify isn't set up), "" when it was done, or a short sentence describing a failure.
Uses the local Spotify account saved by scripts/setup_spotify.py (spotify_mcp.dispatch), so it
works whether or not the separate bridge process is running."""
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import apps

LAUNCH_WAIT = 20  # seconds to wait for a freshly opened Spotify to appear as a device

_POLITE = re.compile(r"^(?:(?:hey|ok|okay)\s+)?(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?|(?:,?\s+please)?[\s.!?]*$", re.I)
_TARGET = r"(?:\s+(?:the|this|my))?(?:\s+(?:music|song|track|spotify|playback|tune))?(?:\s+on\s+spotify)?"
_ACTIONS = [
    ("pause", re.compile(r"(?:pause|hold)" + _TARGET, re.I)),
    ("resume", re.compile(r"(?:resume|unpause|continue|keep\s+playing)" + _TARGET
                          + r"|play\s+(?:the\s+|some\s+|my\s+)?(?:music|spotify)", re.I)),
    ("next", re.compile(r"skip" + _TARGET + r"|(?:play\s+(?:the\s+)?)?next\s+(?:song|track|one)", re.I)),
    ("previous", re.compile(r"(?:play\s+(?:the\s+)?)?(?:previous|last)\s+(?:song|track|one)"
                            r"|go\s+back(?:\s+(?:a|one))?\s+(?:song|track)", re.I)),
]
_PLAY = re.compile(r"play\s+(.+?)(?:\s+on\s+spotify)?", re.I)
_NOT_MUSIC = re.compile(r"\b(?:video|youtube|game|movie|film|episode|show|roblox)\b", re.I)


def parse(text):
    """(action, query) for a plain playback request, else None."""
    said = _POLITE.sub("", (text or "").strip())
    for action, pattern in _ACTIONS:
        if pattern.fullmatch(said):
            return action, None
    match = _PLAY.fullmatch(said)
    if match:
        query = match[1].strip()
        if _NOT_MUSIC.search(query) or query.lower() in apps.names():
            return None
        return "play", query
    return None


def configured():
    import spotify_mcp
    try:
        return spotify_mcp.STORE.exists()
    except OSError:
        return False


def _listening(port):
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def start_bridge():
    """Start the local Spotify bridge (for the assistant's Spotify tools) if it is set up and not running.

    CREATE_NO_WINDOW without DETACHED_PROCESS, like open_brain.py: a detached console program's
    Python child gets its own console window, and closing that window kills the bridge."""
    import spotify_mcp
    if not configured() or _listening(spotify_mcp.PORT):
        return False
    root = Path(__file__).resolve().parent
    subprocess.Popen([sys.executable, str(root / "spotify_mcp.py")], cwd=root, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    return True


def _spotify_exe():
    """The desktop app, or the Microsoft Store app's execution alias."""
    for path in (Path(os.environ.get("APPDATA", "")) / "Spotify" / "Spotify.exe",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "Spotify.exe"):
        if path.is_file():
            return str(path)
    return shutil.which("Spotify.exe")


def launch_spotify():
    exe = _spotify_exe()
    if not exe:
        return False
    try:
        subprocess.Popen([exe, "--minimized"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


def _devices():
    import spotify_mcp
    return [d for d in spotify_mcp.dispatch("spotify_devices", {})["devices"] if not d.get("is_restricted")]


MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}


def _press(key):
    import win32api
    win32api.keybd_event(MEDIA_KEYS[key], 0, 0, 0)
    win32api.keybd_event(MEDIA_KEYS[key], 0, 2, 0)


def _norm(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def _best_track(query):
    """Top search results ranked by title/artist match; Spotify's own top result can be another song."""
    import spotify_mcp
    title, _, artist = query.partition(" by ")
    items = spotify_mcp.dispatch("spotify_search", {"query": query[:300], "type": "track", "limit": 5})["items"]
    def score(item):
        name = _norm(item.get("name", ""))
        artists = _norm(" ".join(item.get("artists", [])))
        return 2 * (name == _norm(title)) + (bool(name) and name in _norm(query)) + (bool(artist) and _norm(artist) in artists)
    return max(items, key=score) if items else None


def run(text):
    """Play by opening the track link in the Spotify app and control playback with media keys.

    This account's Web API playback commands are accepted but ignored (verified live 2026-10-22,
    likely no Premium); searching and reading playback state work, and the app obeys links/keys."""
    command = parse(text)
    if command is None or not configured():
        return None
    import spotify_mcp
    action, query = command
    try:
        if action == "play":
            track = _best_track(query)
            if not track:
                return f"I couldn't find {query} on Spotify."
            os.startfile(track["uri"])  # starts Spotify if needed and plays the track
            return ""
        playing = spotify_mcp.dispatch("spotify_playback", {}).get("is_playing", False)
        if action == "pause":
            if playing:
                _press("play_pause")
        elif action == "resume":
            if not playing:
                if not _devices():
                    if not launch_spotify():
                        return "I couldn't open Spotify on this PC."
                    for _ in range(LAUNCH_WAIT):
                        time.sleep(1)
                        if _devices():
                            break
                _press("play_pause")
        else:
            if not playing and not _devices():
                return "Nothing is playing on Spotify."
            _press(action)
    except spotify_mcp.SpotifyError as error:
        return str(error).split(". Run setup")[0].rstrip(".") + "."
    except Exception:
        return "Spotify isn't responding."
    return ""
