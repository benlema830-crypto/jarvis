"""Screen sync: the LED strips behind both monitors follow the colours on the screens.

HyperHDR (installed on this PC) captures both screens and streams each half to its monitor's WLED controller.
Switching it is done through HyperHDR's local API; the result is read back from the WLED controllers themselves,
which report whether they are receiving the live stream. The controller addresses come from HyperHDR's own
settings, so they stay right if the strips are re-pointed there.
"""
import os
import sqlite3
import subprocess
import time
from pathlib import Path

import requests

EXE = Path(r"C:\Program Files\HyperHDR\bin\hyperhdr.exe")
DB = Path(os.getenv("LOCALAPPDATA", "")) / "HyperHDR" / "db" / "hyperhdr.db"
API = "http://127.0.0.1:8090/json-rpc"
START_TIMEOUT = 20    # seconds for a freshly started HyperHDR to answer
CONFIRM_SECONDS = 8   # the controllers switch to or from the live stream within a few seconds
POLL = 0.5


class SyncError(RuntimeError):
    pass


def _session():
    s = requests.Session()
    s.trust_env = False  # both HyperHDR and the controllers are local; never through a proxy
    return s


def _rpc(body):
    with _session() as s:
        try:
            r = s.post(API, json=body, timeout=(2, 8))
        except requests.RequestException:
            return None
    try:
        return r.json()
    except ValueError:
        return None


def controllers():
    """{instance name: controller address} from HyperHDR's settings (read-only)."""
    import json
    if not DB.exists():
        raise SyncError("HyperHDR isn't set up on this PC, so there is no screen sync.")
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        names = dict(db.execute("select instance, friendly_name from instances where enabled=1"))
        out = {}
        for inst, config in db.execute("select hyperhdr_instance, config from settings where type='device'"):
            device = json.loads(config)
            if inst in names and device.get("type") == "wled" and device.get("host"):
                out[names[inst]] = device["host"]
        return out
    finally:
        db.close()


def _controller(host):
    """(receiving the live stream, light switched on), or None when the controller doesn't answer."""
    with _session() as s:
        try:
            info = s.get(f"http://{host}/json/info", timeout=(2, 4)).json()
            state = s.get(f"http://{host}/json/state", timeout=(2, 4)).json()
        except (requests.RequestException, ValueError):
            return None
    return bool(info.get("live")), bool(state.get("on"))


def _start():
    if not EXE.exists():
        raise SyncError("HyperHDR isn't installed, so screen sync can't start.")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([str(EXE)], cwd=str(EXE.parent), creationflags=flags, close_fds=True)
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if _rpc({"command": "serverinfo"}):
            return
        time.sleep(POLL)
    raise SyncError(f"HyperHDR was started but didn't answer within {START_TIMEOUT} seconds.")


def status():
    hosts = controllers()
    if _rpc({"command": "serverinfo"}) is None:
        return "Status: screen sync is off (HyperHDR isn't running)."
    parts = []
    for name, host in hosts.items():
        seen = _controller(host)
        if seen is None:
            parts.append(f"{name} isn't answering")
        else:
            parts.append(f"{name} {'is following the screen' if seen[0] else 'is not following the screen'}"
                         + ("" if seen[1] else " (its lights are switched off)"))
    return "Status: " + "; ".join(parts) + "."


def control(action):
    action = action.strip().lower()
    if action == "status":
        return status()
    if action not in ("on", "off"):
        raise SyncError("Screen sync takes on, off or status.")
    on = action == "on"
    hosts = controllers()
    running = _rpc({"command": "serverinfo"}) is not None
    if not on and not running:
        return "Screen sync was already off (HyperHDR isn't running), so nothing changed."
    if on and not running:
        _start()
    reply = _rpc({"command": "componentstate", "componentstate": {"component": "ALL", "state": on}})
    if not reply or not reply.get("success"):
        raise SyncError(f"HyperHDR refused to switch screen sync {action}.")
    switched_on = []
    if on:  # following the screen means nothing if the strip itself is off
        for name, host in hosts.items():
            seen = _controller(host)
            if seen and not seen[1]:
                with _session() as s:
                    try:
                        s.post(f"http://{host}/json/state", json={"on": True}, timeout=(2, 4))
                        switched_on.append(name)
                    except requests.RequestException:
                        pass
    deadline = time.monotonic() + CONFIRM_SECONDS
    while True:
        seen = {name: _controller(host) for name, host in hosts.items()}
        wrong = [name for name, s in seen.items() if s is None or s[0] != on]
        if not wrong or time.monotonic() >= deadline:
            break
        time.sleep(POLL)
    right = [name for name in hosts if name not in wrong]
    parts = []
    if right:
        parts.append(f"Confirmed: {', '.join(right)} {'now follow' if on else 'stopped following'} the screen.")
    if switched_on:
        parts.append(f"I also switched on {', '.join(switched_on)}, which {'were' if len(switched_on) > 1 else 'was'} off.")
    if wrong:
        parts.append(f"NOT CONFIRMED after {CONFIRM_SECONDS} seconds: {', '.join(wrong)} "
                     f"{'did not start' if on else 'did not stop'} following the screen. Do not say it worked.")
    return " ".join(parts)
