"""What Jarvis is actually running right now, checked live, so he never goes by an old report about himself.

The trap this closes: a builder's report says "committed, not pushed, not live until Jarvis restarts". That
sentence is true when it's written and false after the next restart or push, but it stays in the agent
records and the conversation, and Jarvis kept repeating it after the owner had restarted him twice.

jarvis.py calls mark_started() once at start-up; it records the time and the git commit he started on in
data/self_state.json (so other processes can read it too). line() is then a short, live statement:
when he started, the commit he runs, whether newer code is waiting for a restart, and whether main is pushed.
It's sent with every turn's working state and wins over any older report.
"""
import datetime
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORE = HERE / "data" / "self_state.json"
CACHE_SECONDS = 30
_cache = {"at": 0.0, "line": ""}


def _git(*args, timeout=4, strip=True):
    try:
        out = subprocess.run(["git", "-C", str(HERE), *args], capture_output=True, text=True, timeout=timeout,
                             encoding="utf-8", errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (out.stdout.strip() if strip else out.stdout) if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def mark_started():
    """Record this jarvis.py's start: time, pid and the commit on disk now (= the code he loaded)."""
    state = {"pid": os.getpid(), "started": time.time(), "commit": _git("rev-parse", "HEAD") or ""}
    try:
        STORE.parent.mkdir(exist_ok=True)
        STORE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass
    _cache["at"] = 0.0
    return state


def started():
    """The running Jarvis's start record, or None when it isn't known (or that Jarvis has stopped)."""
    try:
        state = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        import psutil
        if not psutil.pid_exists(int(state.get("pid", 0))):
            return None
    except Exception:
        pass
    return state if state.get("started") else None


def _when(t):
    when = datetime.datetime.fromtimestamp(t)
    return when.strftime("today %H:%M") if when.date() == datetime.date.today() else when.strftime("%a %b %d %H:%M")


def _changed_since(state):
    """Code on disk that is newer than what he loaded: commits after his start commit, and edited .py files."""
    notes = []
    commit = state.get("commit") or ""
    if commit:
        newer = _git("log", "--format=%h %s", f"{commit}..HEAD")
        if newer:
            lines = newer.splitlines()
            notes.append(f"{len(lines)} commit{'s' if len(lines) != 1 else ''} made after you started "
                         f"(not live until a restart): " + "; ".join(line[:90] for line in lines[:3])
                         + (" ..." if len(lines) > 3 else ""))
    edited = []
    for line in (_git("status", "--porcelain", strip=False) or "").splitlines():  # " M name": keep the leading space
        name = line[3:].strip().strip('"')
        if name.endswith(".py"):
            try:
                if (HERE / name).stat().st_mtime > state["started"]:
                    edited.append(name)
            except OSError:
                pass
    if edited:
        notes.append("uncommitted edits made after you started (not live until a restart): " + ", ".join(edited[:5]))
    return notes


def _push_state():
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        return ""
    ahead = _git("rev-list", "--count", f"origin/{branch}..HEAD")
    if ahead is None:
        return f"branch {branch} (no GitHub copy to compare with)"
    return (f"branch {branch}, everything pushed to GitHub" if ahead == "0"
            else f"branch {branch}, {ahead} commit{'s' if ahead != '1' else ''} not pushed to GitHub yet")


def line(now=None):
    """One live paragraph about Jarvis himself, or "" when his start isn't recorded."""
    now = now or time.time()
    if now - _cache["at"] < CACHE_SECONDS and _cache["line"]:
        return _cache["line"]
    state = started()
    if not state:
        return ""
    commit = (state.get("commit") or "")[:7]
    subject = _git("log", "-1", "--format=%s", state["commit"]) if commit else None
    parts = [f"You (jarvis.py) last started {_when(state['started'])}"
             + (f", running commit {commit}" + (f' "{subject[:80]}"' if subject else "") if commit else "") + "."]
    changed = _changed_since(state)
    parts.append(" ".join(c[0].upper() + c[1:] + "." for c in changed) if changed
                 else "No code has changed since you started, so nothing is waiting for a restart.")
    push = _push_state()
    if push:
        parts.append(f"Code: {push}.")
    parts.append("Every tool in your tool list is loaded and works now; never say a tool you have needs a restart. "
                 f"Anything said before {_when(state['started'])} (agent reports, handoffs, earlier in this "
                 "conversation) about restarting, pushing or something not being live yet is out of date: these "
                 "lines are the live answer.")
    text = "About you right now (checked live, beats any older report):\n" + " ".join(parts)
    _cache.update(at=now, line=text)
    return text
