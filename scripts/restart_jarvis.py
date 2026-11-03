"""Cleanly restart Jarvis: stop every Jarvis process, then start a fresh copy and check it came up.

Used by the "Restart Jarvis" desktop shortcut and by Jarvis's own restart_jarvis tool.

    pythonw scripts/restart_jarvis.py            restart quietly (no spoken briefing)
    pythonw scripts/restart_jarvis.py --open     ...and open the Brain page afterwards
    pythonw scripts/restart_jarvis.py --delay 6  wait first, so a spoken reply can finish

What it does:
  1. Ends jarvis.py, brain.py and spotify_mcp.py from this folder, plus their own workers (Codex /
     Claude Code, shells). Apps Jarvis opened for the owner (Roblox Studio, VoiceStudio...) keep running.
  2. If VoiceStudio is the chosen voice and its window is open but its speech server is dead
     (e.g. part of it was ended in Task Manager), closes VoiceStudio so Jarvis reopens it whole.
  3. Starts jarvis.py (hidden, quiet start) and brain.py exactly like the Jarvis CEO shortcut does.
  4. Waits for both to answer, logs the result to data/restart.log, and shows a message box only
     if something failed.

Stale "running" agent sessions are marked interrupted by Jarvis itself when it loads them.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from instance_config import HUD_PORT  # noqa: E402

BRAIN_PORT = 7781
VOICESTUDIO_URL = ("127.0.0.1", 3900)
VOICESTUDIO_DIR = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "VoiceStudio"
SCRIPTS = ("jarvis.py", "brain.py", "spotify_mcp.py")
LOG = ROOT / "data" / "restart.log"


def log(text):
    LOG.parent.mkdir(exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        print(line, flush=True)
    except (OSError, ValueError):  # pythonw has no console
        pass


def port_open(port, host="127.0.0.1"):
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex((host, port)) == 0


def is_jarvis_process(cmdline, root=ROOT):
    """True for a python process running one of Jarvis's own scripts from this folder."""
    if not cmdline or "python" not in Path(cmdline[0]).name.casefold():
        return False
    for arg in cmdline[1:]:
        path = Path(arg)
        if path.name.casefold() in SCRIPTS:
            try:
                return path.resolve().parent == root.resolve()
            except OSError:
                return False
    return False


def jarvis_processes():
    me = os.getpid()
    found = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.pid != me and is_jarvis_process(proc.info["cmdline"]):
                found.append(proc)
        except (psutil.Error, OSError):
            pass
    return found


def stop_jarvis():
    targets, keep = {}, set()
    for proc in jarvis_processes():
        targets[proc.pid] = proc
        try:
            children = proc.children(recursive=True)
        except psutil.Error:
            continue
        # Only Jarvis's own workers are stopped. Apps he opened for the owner (Roblox Studio, VoiceStudio,
        # Spotify, browsers...) are theirs: leave each one and everything under it running, so a restart
        # never loses unsaved work and the voice stays warm.
        for child in children:
            if not _is_worker(child):
                keep.add(child.pid)
                try:
                    keep.update(p.pid for p in child.children(recursive=True))
                except psutil.Error:
                    pass
        for child in children:
            if child.pid not in keep:
                targets[child.pid] = child
    targets.pop(os.getpid(), None)
    if not targets:
        log("No Jarvis processes were running.")
        return
    log(f"Stopping {len(targets)} Jarvis process(es): " + ", ".join(sorted({_name(p) for p in targets.values()})))
    for proc in targets.values():
        try:
            proc.terminate()  # TerminateProcess on Windows
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(list(targets.values()), timeout=10)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    # The single-instance mutex and ports are released when the processes are gone.
    for _ in range(50):
        if not port_open(HUD_PORT) and not port_open(BRAIN_PORT):
            break
        time.sleep(.2)


# Programs Jarvis runs for himself: the Codex / Claude Code workers, their shells and consoles.
WORKERS = {"python.exe", "pythonw.exe", "claude.exe", "codex.exe", "node.exe", "conhost.exe", "cmd.exe",
           "powershell.exe", "pwsh.exe", "bash.exe", "sh.exe", "git.exe", "uv.exe", "rg.exe"}


def _is_worker(proc):
    try:
        return proc.name().casefold() in WORKERS
    except (psutil.Error, OSError):
        return False


def _name(proc):
    try:
        cmd = proc.cmdline()
        script = next((Path(a).name for a in cmd[1:] if a.endswith(".py")), "")
        return script or proc.name()
    except psutil.Error:
        return "process"


def voicestudio_chosen():
    try:
        prefs = json.loads((ROOT / "data" / "preferences.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True  # VoiceStudio is the default voice
    return str(prefs.get("voice_engine", "voicestudio")).startswith("voicestudio")


def voicestudio_processes():
    folder = str(VOICESTUDIO_DIR).casefold()
    found = []
    for proc in psutil.process_iter(["exe"]):
        try:
            if (proc.info["exe"] or "").casefold().startswith(folder):
                found.append(proc)
        except (psutil.Error, OSError):
            pass
    return found


def repair_voicestudio():
    """Close a half-dead VoiceStudio (window open, speech server gone) so Jarvis can reopen it whole."""
    if not voicestudio_chosen() or port_open(VOICESTUDIO_URL[1]):
        return
    procs = voicestudio_processes()
    if not procs:
        return  # closed: Jarvis opens it on start
    log("VoiceStudio is open but its speech server isn't answering - closing it so Jarvis reopens it.")
    for proc in procs:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    psutil.wait_procs(procs, timeout=10)


def start_jarvis(quiet=True):
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    args = [str(python), "-u", str(ROOT / "jarvis.py"), "--no-window"]
    if quiet:
        args.append("--quiet-start")
    with (ROOT / "data" / "brain-assistant.log").open("a", encoding="utf-8") as out:
        out.write(f"\n===== restarted {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        out.flush()
        subprocess.Popen(args, cwd=ROOT, stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.Popen([str(ROOT / ".venv" / "Scripts" / "pythonw.exe"), str(ROOT / "brain.py")], cwd=ROOT,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)


def wait_until_up(timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(HUD_PORT) and port_open(BRAIN_PORT):
            return True
        time.sleep(1)
    return False


def message_box(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Restart Jarvis", 0x30)
    except Exception:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--delay", type=float, default=0, help="seconds to wait before stopping Jarvis")
    parser.add_argument("--open", action="store_true", help="open the Brain page when Jarvis is back")
    parser.add_argument("--briefing", action="store_true", help="speak the startup briefing")
    args = parser.parse_args(argv)
    if args.delay > 0:
        time.sleep(min(args.delay, 60))
    log("Restart requested.")
    stop_jarvis()
    leftover = jarvis_processes()
    if leftover:
        msg = f"Couldn't stop {len(leftover)} Jarvis process(es); not starting a second copy."
        log(msg)
        message_box(msg + "\nTry again, or restart the PC.")
        return 1
    repair_voicestudio()
    start_jarvis(quiet=not args.briefing)
    if not wait_until_up():
        msg = "Jarvis was started but didn't come back within 2 minutes. See data\\brain-assistant.log."
        log(msg)
        message_box(msg)
        return 1
    log("Jarvis is back up.")
    if args.open:
        import webbrowser
        import chrome_browser  # noqa: F401 - open links in Chrome, like the Jarvis CEO shortcut
        webbrowser.open(f"http://127.0.0.1:{BRAIN_PORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
