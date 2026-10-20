"""Tracks what you're doing on the PC so Jarvis can recap it later.

While Jarvis runs, the title of your active window is logged (only when it
changes) to data/activity.jsonl. Nothing leaves your PC except the short
summary included in Jarvis's prompts.
"""

import datetime
import json
import os
import threading
import time

import psutil
import win32api
import win32gui
import win32process

import worksafe

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "data", "activity.jsonl")
RECENT_DIR = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Recent")
IDLE_AFTER_SECONDS = 300
MAX_LOG_BYTES = 5_000_000


def _foreground() -> tuple[str, str]:
    hwnd = win32gui.GetForegroundWindow()
    if worksafe.is_blocked(hwnd):
        return "work app", "(hidden)"  # Outlook / Teams: never log what's in them
    title = win32gui.GetWindowText(hwnd).strip()
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        app = psutil.Process(pid).name().removesuffix(".exe")
    except (psutil.Error, ValueError):
        app = "unknown"
    return app, title


def _idle_seconds() -> float:
    return (win32api.GetTickCount() - win32api.GetLastInputInfo()) / 1000.0


def _logger_loop(interval: float):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    last = None
    reported = set()
    while True:
        try:
            current = ("idle", "") if _idle_seconds() > IDLE_AFTER_SECONDS else _foreground()
            untitled = current[0] != "idle" and not current[1]  # desktop, taskbar, etc.
            if current != last and not untitled:
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"t": time.time(), "app": current[0], "title": current[1]}) + "\n")
                last = current
            if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_BYTES:
                with open(LOG_PATH, encoding="utf-8") as f:
                    keep = f.readlines()[-5000:]
                with open(LOG_PATH, "w", encoding="utf-8") as f:
                    f.writelines(keep)
        except Exception as e:
            if repr(e) not in reported:  # say so once, rather than failing silently forever
                reported.add(repr(e))
                print(f"(activity logger error: {e!r})", flush=True)
        time.sleep(interval)


def start_logger(interval: float = 10.0):
    threading.Thread(target=_logger_loop, args=(interval,), daemon=True).start()


def _read_log() -> list[dict]:
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def summarize(hours: float = 12, before: float | None = None) -> str:
    """Summarize activity in the `hours` before `before` (default: now)."""
    end = before or time.time()
    entries = [e for e in _read_log() if end - hours * 3600 <= e["t"] < end]
    if not entries:
        return "No activity recorded yet (Jarvis only tracks activity while it is running)."

    totals: dict[tuple[str, str], float] = {}
    for cur, nxt in zip(entries, entries[1:] + [{"t": end}]):
        if cur["app"] == "idle":
            continue
        key = (cur["app"], cur["title"][:90])
        totals[key] = totals.get(key, 0) + min(nxt["t"] - cur["t"], 600)  # cap gaps at 10 min

    last_active = next((e for e in reversed(entries) if e["app"] != "idle"), None)
    lines = []
    if last_active:
        when = datetime.datetime.fromtimestamp(last_active["t"]).strftime("%A %I:%M %p")
        lines.append(f"Last thing in focus: {last_active['app']} - \"{last_active['title'][:120]}\" (at {when})")
    lines.append("Most time spent on:")
    for (app, title), secs in sorted(totals.items(), key=lambda kv: -kv[1])[:8]:
        if secs >= 60:
            lines.append(f"  - {app}: \"{title}\" ({secs / 60:.0f} min)")
    return "\n".join(lines)


def recent_files(hours: float = 48, limit: int = 8) -> str:
    """Files recently opened in Windows (from the Recent Items folder)."""
    try:
        cutoff = time.time() - hours * 3600
        items = [
            (e.stat().st_mtime, e.name.removesuffix(".lnk"))
            for e in os.scandir(RECENT_DIR)
            if e.name.endswith(".lnk") and e.stat().st_mtime > cutoff
            and not e.name.startswith("ms-") and "=" not in e.name  # Windows system links
        ]
    except OSError:
        return "Unavailable."
    items.sort(reverse=True)
    if not items:
        return "None in the last two days."
    return "\n".join(
        f"  - {name} (opened {datetime.datetime.fromtimestamp(t).strftime('%a %I:%M %p')})"
        for t, name in items[:limit]
    )
