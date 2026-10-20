"""Finds and launches installed apps by name, using the Start Menu's app list."""

import difflib
import json
import os
import subprocess
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "apps.json")

# Windows tools that aren't in the Start Menu list under these names
BUILTIN = {
    "notepad": "notepad",
    "calculator": "calc",
    "paint": "mspaint",
    "file explorer": "explorer",
    "explorer": "explorer",
    "task manager": "taskmgr",
    "command prompt": "cmd",
    "terminal": "wt",
    "settings": "ms-settings:",
    "control panel": "control",
}

_index: dict[str, str] = {}  # lowercase name -> Start Menu AppID
_ready = threading.Event()


def _scan() -> dict[str, str]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
        capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout
    apps = json.loads(out or "[]")
    if isinstance(apps, dict):
        apps = [apps]
    return {a["Name"].lower(): a["AppID"] for a in apps if a.get("Name") and a.get("AppID")}


def refresh():
    """Load the cached list immediately, then rescan in the background (apps get installed)."""
    global _index
    try:
        with open(CACHE, encoding="utf-8") as f:
            _index = json.load(f)
            _ready.set()
    except (OSError, ValueError):
        pass

    def scan():
        global _index
        try:
            _index = _scan()
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump(_index, f)
        except Exception as e:
            print(f"(couldn't list installed apps: {e!r})", flush=True)
        _ready.set()

    threading.Thread(target=scan, daemon=True).start()


def match(name: str, index: dict[str, str] | None = None) -> str | None:
    """Best matching app name for what the user said, or None."""
    names = list(BUILTIN) + list(index if index is not None else _index)
    q = name.lower().strip()
    if q in names:
        return q
    starts = [n for n in names if n.startswith(q)]
    if starts:
        return min(starts, key=len)
    contains = [n for n in names if q in n]
    if contains:
        return min(contains, key=len)
    close = difflib.get_close_matches(q, names, n=1, cutoff=0.6)
    return close[0] if close else None


def launch(name: str) -> str:
    _ready.wait(timeout=30)
    found = match(name)
    if found is None:
        return f"No installed app matches '{name}'."
    if found in BUILTIN:
        target = BUILTIN[found]
        try:
            os.startfile(target)
        except OSError:
            subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{_index[found]}"])
    return f"Opened {found}"


def names() -> list[str]:
    return sorted(set(BUILTIN) | set(_index))
