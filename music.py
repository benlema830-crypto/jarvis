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
_QUEUE = re.compile(r"queue(?:\s+up)?\s+(.+?)(?:\s+on\s+spotify)?|add\s+(.+?)\s+to\s+(?:the|my)\s+(?:spotify\s+)?queue", re.I)
_NOT_MUSIC = re.compile(r"\b(?:video|youtube|game|movie|film|episode|show|roblox)\b", re.I)


def parse(text):
    """(action, query) for a plain playback request, else None."""
    said = _POLITE.sub("", (text or "").strip())
    for action, pattern in _ACTIONS:
        if pattern.fullmatch(said):
            return action, None
    for action, pattern in (("queue", _QUEUE), ("play", _PLAY)):
        match = pattern.fullmatch(said)
        if match:
            query = next(group for group in match.groups() if group).strip()
            if _NOT_MUSIC.search(query) or query.lower() in apps.names():
                return None
            return action, query
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


def _spotify_windows():
    """(main, miniplayer) window handles of the running desktop app; either may be None.

    The Miniplayer is the app's always-on-top window; the main one has a title but isn't topmost."""
    import psutil
    import win32con
    import win32gui
    import win32process
    pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "spotify.exe"}
    found = {"main": None, "mini": None}
    def visit(hwnd, _):
        if (win32process.GetWindowThreadProcessId(hwnd)[1] in pids and win32gui.GetWindowText(hwnd)
                and win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1"):
            topmost = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOPMOST
            if topmost and win32gui.IsWindowVisible(hwnd):
                found["mini"] = found["mini"] or hwnd
            elif not topmost:
                found["main"] = found["main"] or hwnd
        return True
    if pids:
        win32gui.EnumWindows(visit, None)
    return found["main"], found["mini"]


def _main_in_view():
    """Whether the full Spotify window is open on screen (then the user is using it; leave it alone)."""
    import win32gui
    try:
        main, _ = _spotify_windows()
        return bool(main and win32gui.IsWindowVisible(main) and not win32gui.IsIconic(main))
    except Exception:
        return False


def show_miniplayer():
    """Open Spotify's Miniplayer (the small always-on-top corner window) and tuck the main window away.

    Spotify has no shortcut or command line switch for it, and the accessibility Invoke action
    doesn't count as a click (it is a picture-in-picture window, which needs a real user gesture),
    so a click is posted to its "Open Miniplayer" button. That needs the main window laid out, so a
    minimized or hidden one is shown fully transparent and without focus for the click, then put back.
    Doesn't move the mouse or steal focus. Premium-only; returns False if it couldn't be opened."""
    import uiautomation as auto
    import win32api
    import win32con
    import win32gui
    main, mini = _spotify_windows()
    for second in range(LAUNCH_WAIT):  # a freshly opened Spotify takes a few seconds to show its window;
        if main and (win32gui.IsWindowVisible(main) or second >= 3):  # one closed to the tray stays hidden
            break
        time.sleep(1)
        main, mini = _spotify_windows()
    if mini:
        return True
    if not main:
        return False
    focus = win32gui.GetForegroundWindow()
    hidden = not win32gui.IsWindowVisible(main)
    style = win32gui.GetWindowLong(main, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(main, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
    win32gui.SetLayeredWindowAttributes(main, 0, 0, win32con.LWA_ALPHA)
    try:
        win32gui.ShowWindow(main, win32con.SW_SHOWNOACTIVATE)
        with auto.UIAutomationInitializerInThread():
            button = auto.ControlFromHandle(main).ButtonControl(Name="Open Miniplayer", searchDepth=30)
            if not button.Exists(15):
                return False
            for _ in range(20):
                rect = button.BoundingRectangle
                if rect.width():
                    break
                time.sleep(0.1)
        x, y = win32gui.ScreenToClient(main, ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2))
        point = win32api.MAKELONG(x, y)
        win32gui.PostMessage(main, win32con.WM_MOUSEMOVE, 0, point)
        win32gui.PostMessage(main, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, point)
        win32gui.PostMessage(main, win32con.WM_LBUTTONUP, 0, point)
        for _ in range(30):
            time.sleep(0.1)
            if _spotify_windows()[1]:
                return True
        return False
    finally:
        win32gui.ShowWindow(main, win32con.SW_HIDE if hidden else win32con.SW_SHOWMINNOACTIVE)
        win32gui.SetWindowLong(main, win32con.GWL_EXSTYLE, style)
        _refocus(focus, main)


def _refocus(hwnd, spotify):
    """Give the keyboard back to the window the user was in; the Miniplayer takes focus when it opens."""
    import win32gui
    time.sleep(0.3)
    if not hwnd or hwnd == spotify or not win32gui.IsWindow(hwnd) or win32gui.GetForegroundWindow() == hwnd:
        return
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _miniplayer_soon():
    """show_miniplayer() in the background so the spoken command isn't held up; never fails playback."""
    import threading
    def run():
        try:
            show_miniplayer()
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


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


def perform(action, uri=None):
    """Do one playback action the way that works on this PC; "" on success, else a short sentence.

    Verified live 2026-10-22: the Web API play command stops playback here, and a track link doesn't
    switch songs mid-track. So: a link when idle, queue + media Next mid-song, media keys otherwise.
    Starting playback also pops up the Miniplayer in the screen corner unless the full Spotify window is open.
    Both the instant voice commands and the assistant's Spotify tools go through this."""
    import spotify_mcp
    try:
        playing = spotify_mcp.dispatch("spotify_playback", {}).get("is_playing", False)
        if (action == "play" or action == "resume" and not playing or action == "queue" and uri and not playing) \
                and not _main_in_view():
            _miniplayer_soon()  # waits for a Spotify being opened by the steps below
        if action in ("play", "queue") and uri:
            if not playing:
                os.startfile(uri)  # starts Spotify if needed and plays the track
            else:
                spotify_mcp.dispatch("spotify_queue", {"uri": uri})
                if action == "play":
                    _press("next")
        elif action == "pause":
            if playing:
                _press("play_pause")
        elif action in ("resume", "play"):
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


def run(text):
    """Instant spoken music command: None if not one (or Spotify isn't set up), "" if done, else a problem."""
    command = parse(text)
    if command is None or not configured():
        return None
    import spotify_mcp
    action, query = command
    if action in ("play", "queue"):
        try:
            track = _best_track(query)
        except spotify_mcp.SpotifyError as error:
            return str(error).split(". Run setup")[0].rstrip(".") + "."
        except Exception:
            return "Spotify isn't responding."
        if not track:
            return f"I couldn't find {query} on Spotify."
        return perform(action, track["uri"])
    return perform(action)


CONTROL_ACTIONS = {"spotify_play": "play", "spotify_queue": "queue", "spotify_pause": "pause",
                   "spotify_next": "next", "spotify_previous": "previous"}


def control(name, args):
    """The assistant's Spotify playback tool calls, routed through perform() (same behaviour as voice)."""
    import json
    problem = perform(CONTROL_ACTIONS[name], args.get("uri"))
    return json.dumps({"ok": True, "message": "Done."} if not problem else {"isError": True, "message": problem})
