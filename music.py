"""Spoken Spotify commands that act immediately, without an AI turn or a spoken reply.

parse() recognises only plain playback requests ("pause the music", "next song", "play <song>");
anything else is left to the assistant. run() returns None when the text isn't a music command
(or Spotify isn't set up), "" when it was done, or a short sentence describing a failure.
Uses the local Spotify account saved by scripts/setup_spotify.py (spotify_mcp.dispatch), so it
works whether or not the separate bridge process is running."""
import re
import socket
import subprocess
import sys
from pathlib import Path

import apps

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


def _with_device(name, args):
    """Retry on an available device when Spotify reports none active (prefer this PC)."""
    import spotify_mcp
    try:
        return spotify_mcp.dispatch(name, args)
    except spotify_mcp.SpotifyError as error:
        if "No active Spotify device" not in str(error):
            raise
        devices = [d for d in spotify_mcp.dispatch("spotify_devices", {})["devices"] if not d.get("is_restricted")]
        if not devices:
            raise spotify_mcp.SpotifyError("Open Spotify on one of your devices first.") from None
        device = next((d for d in devices if d.get("type") == "Computer"), devices[0])
        return spotify_mcp.dispatch(name, dict(args, device_id=device["id"]))


def run(text):
    command = parse(text)
    if command is None or not configured():
        return None
    import spotify_mcp
    action, query = command
    try:
        if action == "play":
            found = spotify_mcp.dispatch("spotify_search", {"query": query[:300], "type": "track", "limit": 1})["items"]
            if not found:
                return f"I couldn't find {query} on Spotify."
            _with_device("spotify_play", {"uri": found[0]["uri"]})
        else:
            _with_device({"resume": "spotify_play"}.get(action, "spotify_" + action), {})
    except spotify_mcp.SpotifyError as error:
        return str(error).split(". Run setup")[0].rstrip(".") + "."
    except Exception:
        return "Spotify isn't responding."
    return ""
