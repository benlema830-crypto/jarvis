"""Set up the Fedora laptop: shows the one command to run on it and a 6-digit pairing code (ten minutes, once).

    .venv\\Scripts\\pythonw.exe scripts\\laptop_setup.py      (the tray's "Set up the laptop" runs this)

Makes the laptop key the first time (DPAPI, data/desk-token.dpapi) and publishes the laptop bridge to the owner's
own tailnet with `tailscale serve --bg --https=8443 http://127.0.0.1:7783` (never Funnel) if it isn't already.
To shut every laptop out: delete data/desk-token.dpapi and restart Jarvis, then pair again.
"""
import ctypes
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import desk_bridge  # noqa: E402

NO_WINDOW = subprocess.CREATE_NO_WINDOW


def tailscale(*args, timeout=20):
    return subprocess.run(["tailscale", *args], capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)


def address() -> str:
    try:
        name = json.loads(tailscale("status", "--json").stdout)["Self"]["DNSName"].rstrip(".")
        return f"https://{name}:{desk_bridge.PUBLIC_PORT}"
    except Exception:
        return f"https://draco420.tailf4c37e.ts.net:{desk_bridge.PUBLIC_PORT}"


def publish() -> str:
    """'' when the laptop address is published on the tailnet, else what went wrong."""
    target = f"127.0.0.1:{desk_bridge.PORT}"
    try:
        if target in tailscale("serve", "status").stdout:
            return ""
        result = tailscale("serve", "--bg", f"--https={desk_bridge.PUBLIC_PORT}", f"http://{target}")
        return "" if result.returncode == 0 else (result.stderr or result.stdout).strip()
    except Exception as exc:
        return repr(exc)


def main():
    desk_bridge.ensure_token()
    problem = publish()
    code = desk_bridge.new_pair_code()
    url = address()
    text = (f"On the laptop (Tailscale on, signed in as you), open a Terminal and run:\n\n"
            f"    curl -fsSL {url}/laptop | bash\n\n"
            f"When it asks, type this code:   {code[:3]} {code[3:]}\n\n"
            f"The code works once, for ten minutes. Ctrl+C copies this whole message.")
    if problem:
        text += f"\n\nWarning: publishing the laptop address on Tailscale failed: {problem}"
    print(text)
    ctypes.windll.user32.MessageBoxW(None, text, "Set up the laptop for Jarvis", 0x40 | 0x40000)  # info, topmost


if __name__ == "__main__":
    main()
