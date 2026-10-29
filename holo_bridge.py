"""Bridge to HOLO, the webcam hand-gesture notes app from the reference video's creator.

HOLO (https://github.com/zubair-trabzada/holo-gestures, MIT) is a separate local app:
a standard-library Python server on port 4890 plus one browser page that tracks your
hands with MediaPipe. It reads one notes folder from holo.json and records the latest
gesture event (grab/open/squeeze-to-summarize...) in state/holo-state.json.

JARVIS does three things with it, and nothing else:
  * finds the install and points holo.json at the Obsidian vault (keeping a backup);
  * starts its server and opens it in Chrome on request;
  * watches holo-state.json so a card you pick up lights the same note in the Brain
    graph, and a "squeeze" asks JARVIS (in his own voice) to summarize that note.

Camera frames never leave HOLO's browser page; JARVIS only reads the event file.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import chrome_browser  # noqa: F401 - open links in Chrome

HOME = Path.home()
CANDIDATES = [HOME / "holo", HOME / "holo-gestures", HOME / "Documents" / "holo",
              HOME / "Documents" / "holo-gestures", HOME / "Documents" / "Jarvis Agent" / "holo"]
REPO = "https://github.com/zubair-trabzada/holo-gestures.git"
_server = None
_last_event = {}
_watching = False


def port() -> int:
    try:
        return int(os.getenv("HOLO_PORT", "4890"))
    except ValueError:
        return 4890


def find_install():
    """The HOLO folder (contains server.py and holo.html), or None."""
    configured = os.getenv("HOLO_DIR")
    for folder in ([Path(configured)] if configured else []) + CANDIDATES:
        if (folder / "server.py").is_file() and (folder / "holo.html").is_file():
            return folder
    return None


def running() -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port())) == 0


def configure(folder: Path) -> str:
    """Point HOLO at the knowledge vault. The original holo.json is kept once as holo.json.bak."""
    import knowledge
    settings = folder / "holo.json"
    wanted = {"folder": str(knowledge.VAULT)}
    try:
        current = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = None
    if current == wanted:
        return "already uses your vault"
    backup = folder / "holo.json.bak"
    if settings.is_file() and not backup.exists():
        backup.write_bytes(settings.read_bytes())
    settings.write_text(json.dumps(wanted, indent=2), encoding="utf-8")
    return "now reads your vault"


def _open_browser(url: str):
    """HOLO needs camera access and WebGL; it's built and tested for Chrome."""
    chrome = next((p for p in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
                               Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
                               Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe")
                   if p.is_file()), None)
    if chrome:
        subprocess.Popen([str(chrome), url], creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        webbrowser.open(url)


def launch(narrate: bool = False) -> str:
    global _server
    folder = find_install()
    if not folder:
        return ("HOLO isn't installed. Run scripts\\setup_holo.ps1 (it clones " + REPO +
                " into your user folder), then ask again.")
    note = configure(folder)
    if not running():
        env = dict(os.environ, HOLO_PORT=str(port()))
        _server = subprocess.Popen([sys.executable, "server.py"], cwd=folder, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(30):
            if running():
                break
            time.sleep(0.1)
        else:
            return "HOLO's server didn't start. Try running python server.py in " + str(folder) + " to see why."
    watch()
    _open_browser(f"http://localhost:{port()}/" + ("?jarvis=1" if narrate else ""))
    return f"HOLO opened in Chrome; it {note}. Allow the camera and raise a hand."


def stop() -> str:
    global _server
    if _server and _server.poll() is None:
        _server.terminate()
        _server = None
        return "HOLO's server stopped."
    return "HOLO wasn't started by me, so I left it running." if running() else "HOLO isn't running."


def status() -> dict:
    folder = find_install()
    return {"installed": bool(folder), "path": str(folder) if folder else "", "running": running(),
            "port": port(), "last_event": dict(_last_event), "repo": REPO}


def describe() -> str:
    info = status()
    if not info["installed"]:
        return "HOLO isn't installed yet. Run scripts\\setup_holo.ps1, then say 'open HOLO'."
    event = info["last_event"]
    parts = ["HOLO is " + ("running" if info["running"] else "installed but not running") + "."]
    if event:
        age = int(time.time() - event.get("seen", time.time()))
        parts.append(f"Last gesture: {event.get('event')} on '{event.get('card')}', {age} seconds ago.")
        if event.get("path"):
            parts.append(f"That card is the vault note {event['path']}.")
    return " ".join(parts)


def note_for(title: str):
    """HOLO cards are titled by the note's first line (48 chars max). Match back to a vault note."""
    import knowledge
    want = title.strip().casefold()
    if not want:
        return None
    for note in knowledge.index()["notes"]:
        first = next((line.strip().lstrip("#").strip() for line in note["content"].splitlines() if line.strip()), "")
        if want in (first[:48].casefold(), note["title"][:48].casefold(), Path(note["path"]).stem[:48].casefold()):
            return note
    return None


def handle(event: dict, emit, ask):
    """React to one HOLO gesture event. emit(kind, **data) -> HUD, ask(label, prompt) -> JARVIS."""
    global _last_event
    kind, card = str(event.get("event", ""))[:20], str(event.get("card", ""))[:120]
    note = note_for(card) if kind in ("open", "grab", "sum", "dock") else None
    _last_event = {"event": kind, "card": card, "seen": time.time(), "path": note["path"] if note else ""}
    if not note:
        return
    if kind in ("open", "grab", "dock"):
        emit("knowledge", status="found", via="holo", sources=[{
            "id": "note:" + note["path"], "path": note["path"], "title": note["title"],
            "excerpt": note["content"][:600], "uri": note["uri"]}])
    elif kind == "sum":
        ask("HOLO summary", f'[HOLO] The owner squeezed the card for the vault note "{note["path"]}" in HOLO '
            "to hear a summary. Read it with read_knowledge_note and give the gist in one or two spoken sentences.")


def watch(emit=None, ask=None):
    """Poll HOLO's event file in the background (once per process)."""
    global _watching
    if _watching:
        return
    if emit is None or ask is None:
        import hud
        emit = emit or hud.emit
        ask = ask or (lambda label, prompt: hud.commands.put({"label": label, "prompt": prompt}))
    _watching = True

    def stamp():
        folder = find_install()
        path = folder / "state" / "holo-state.json" if folder else None
        try:
            return path, path.stat().st_mtime
        except (OSError, AttributeError):
            return path, 0.0

    def loop():
        _, last = stamp()  # an event from before JARVIS started is not replayed
        while True:
            time.sleep(0.5)
            path, now = stamp()
            if now and now != last:
                last = now
                try:
                    handle(json.loads(path.read_text(encoding="utf-8")), emit, ask)
                except (OSError, ValueError, TypeError, AttributeError):
                    pass
    threading.Thread(target=loop, daemon=True, name="holo-watch").start()
