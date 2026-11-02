"""Jarvis checks himself: a read-only health report of his own processes, voice, brain, background
work, smart home and recent errors, so he can answer "what's wrong with you?" from facts instead
of guessing from the conversation.

Every check is independent, short (about a second at most) and never changes anything.
"""
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "data" / "brain-assistant.log"
PORTS = {"HUD": 7778, "Brain page": 7781, "phone bridge": 7782, "VoiceStudio": 3900, "local model (Ollama)": 11435}
SCRIPTS = ("jarvis.py", "brain.py", "spotify_mcp.py")
PROBLEM = re.compile(r"traceback|error|failed|couldn't|could not|isn't running|not found|timed out|refused|exception",
                     re.I)
NOISE = re.compile(r"ignored a voice|VoiceStudio generated|^JARVIS:|^You:", re.I)


def _port(port):
    with socket.socket() as probe:
        probe.settimeout(.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _ago(seconds):
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


def processes():
    """Jarvis's own processes (python running jarvis.py / brain.py / spotify_mcp.py from this folder)."""
    import psutil
    found = {name: [] for name in SCRIPTS}
    for proc in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            cmd = proc.info["cmdline"] or []
            if not cmd or "python" not in Path(cmd[0]).name.casefold():
                continue
            for arg in cmd[1:]:
                path = Path(arg)
                if path.name.casefold() in SCRIPTS and path.resolve().parent == ROOT:
                    found[path.name.casefold()].append(proc.info)
                    break
        except (psutil.Error, OSError):
            pass
    return found


def _copies(procs):
    """The venv launcher starts a second python for the same script: count launchers, not both."""
    venv = str(ROOT / ".venv").casefold()
    launchers = [p for p in procs if str((p["cmdline"] or [""])[0]).casefold().startswith(venv)]
    return len(launchers) or len(procs)


def check_processes():
    lines = []
    procs = processes()
    me = procs["jarvis.py"]
    if me:
        started = min(p["create_time"] for p in me)
        lines.append(f"Running: jarvis.py up {_ago(time.time() - started)}"
                     + (f" - WARNING {_copies(me)} copies running" if _copies(me) > 1 else ""))
        changed = _changed_since(started)
        if changed:
            lines.append(f"Code changed since start ({len(changed)} file(s), e.g. {', '.join(changed[:3])}): "
                         "a restart is needed to load it.")
    else:
        lines.append("jarvis.py isn't running (this check ran outside Jarvis).")
    brain = procs["brain.py"]
    lines.append(f"Brain page server: {'up' if brain and _port(7781) else 'DOWN'}"
                 + (f" ({_copies(brain)} copies)" if _copies(brain) > 1 else ""))
    return lines


def _changed_since(started):
    changed = []
    for pattern in ("*.py", "hud/*"):
        for path in ROOT.glob(pattern):
            try:
                if path.is_file() and path.stat().st_mtime > started + 5:
                    changed.append(path.relative_to(ROOT).as_posix())
            except OSError:
                pass
    return sorted(changed)


def check_code():
    def git(*args):
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.strip()
    try:
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        head = git("log", "-1", "--format=%h %s (%cr)")
        dirty = [line for line in git("status", "--porcelain").splitlines() if line.strip()]
        return [f"Code: branch {branch}, last commit {head}"
                + (f", {len(dirty)} uncommitted change(s)" if dirty else ", no uncommitted changes")]
    except (OSError, subprocess.SubprocessError):
        return ["Code: git isn't available."]


def _preferences():
    try:
        return json.loads((ROOT / "data" / "preferences.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check_voice(info):
    chosen = _preferences().get("voice_engine", "voicestudio")
    speaking = info.get("voice") or "unknown"
    lines = [f"Voice: chosen {chosen}; speaking with {speaking}"
             + (" (still loading)" if info.get("voice_warming") else "")]
    if str(chosen).startswith("voicestudio"):
        try:
            import voicestudio_voice
            procs = voicestudio_voice._app_processes()
        except Exception:
            procs = set()
        if _port(3900):
            lines.append("VoiceStudio: running and answering.")
        elif procs:
            lines.append("VoiceStudio: PROBLEM - its window is open but its speech server isn't answering, so a "
                         "fallback voice is used. It is reopened automatically after 2 minutes, or restart Jarvis.")
        else:
            lines.append("VoiceStudio: closed - Jarvis reopens it automatically; a fallback voice is used meanwhile.")
    for key, label in (("mic", "Microphone"), ("output", "Speaker"), ("ears", "Speech recognition")):
        if info.get(key):
            lines.append(f"{label}: {info[key]}")
    return lines


def check_brain(info):
    provider, model = info.get("provider"), info.get("model")
    if not provider and not model:
        prefs = _preferences().get("conversation_model") or {}
        provider, model = prefs.get("provider"), prefs.get("model")
    return [f"Conversation brain: {model or 'unknown'} via {provider or 'unknown'}"]


def check_ports():
    status = [f"{name} {'up' if _port(port) else 'down'}" for name, port in PORTS.items()]
    return ["Services: " + ", ".join(status)]


def check_home():
    try:
        import home_assistant
        devices = home_assistant.devices()
    except Exception as e:
        return [f"Home Assistant: NOT reachable - {e}"]
    lights = [d for d in devices if d["domain"] == "light"]
    on = [d["name"] for d in lights if d["state"] == "on"]
    offline = [d["name"] for d in devices if d["state"] == "unavailable"]
    tvs = [f"{d['name']} {d['state']}" for d in devices if d["domain"] == "media_player"]
    lines = [f"Home Assistant: reachable, {len(devices)} controllable entities, {len(lights)} lights "
             f"({len(on)} on)" + (f"; UNAVAILABLE: {', '.join(offline)}" if offline else "")]
    if tvs:
        lines.append("Media players: " + "; ".join(tvs))
    return lines


def recent_problems(limit=8, log=LOG):
    """Problem lines from the log since Jarvis last started."""
    try:
        with log.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 400_000))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = text.splitlines()
    start = max((i for i, line in enumerate(lines) if "JARVIS starting up" in line), default=0)
    problems = [line.strip() for line in lines[start:] if PROBLEM.search(line) and not NOISE.search(line.strip())]
    seen, unique = set(), []
    for line in reversed(problems):  # newest first, without repeats
        if line not in seen:
            seen.add(line)
            unique.append(line[:220])
    return unique[:limit]


CHECKS = {
    "processes": lambda ctx: check_processes(),
    "code": lambda ctx: check_code(),
    "brain": lambda ctx: check_brain(ctx.get("info", {})),
    "voice": lambda ctx: check_voice(ctx.get("info", {})),
    "background": lambda ctx: ctx.get("background", []),
    "services": lambda ctx: check_ports(),
    "home": lambda ctx: check_home(),
}


def report(focus="", info=None, background=None):
    """The health report as plain text. focus limits it to one area: processes, code, brain, voice,
    background, services, home or errors."""
    focus = (focus or "").strip().casefold()
    ctx = {"info": info or {}, "background": background or []}
    names = [focus] if focus in CHECKS else ([] if focus == "errors" else list(CHECKS))
    out = []
    for name in names:
        try:
            out.extend(CHECKS[name](ctx))
        except Exception as e:  # one broken check never hides the others
            out.append(f"{name}: check failed ({type(e).__name__}: {e})")
    if not focus or focus == "errors":
        problems = recent_problems()
        out.append("Recent problems since start (newest first): " + (" | ".join(problems) if problems else "none"))
    return "\n".join(out)
