"""Open the second-brain companion without duplicating the voice assistant.

--no-browser starts the hidden assistant and Brain server only (used by the Startup shortcut)."""
from pathlib import Path
import socket
import subprocess
import sys
import time
import webbrowser
from instance_config import HUD_PORT

root = Path(__file__).resolve().parent
with socket.socket() as probe:
    assistant_running = probe.connect_ex(("127.0.0.1", HUD_PORT)) == 0
if not assistant_running:
    # The assistant's existing single-instance mutex handles simultaneous launches.
    (root / "data").mkdir(exist_ok=True)
    with (root / "data" / "brain-assistant.log").open("a", encoding="utf-8") as log:
        subprocess.Popen([str(root / ".venv" / "Scripts" / "python.exe"),
                          "-u", str(root / "jarvis.py"), "--no-window"], cwd=root,
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
with socket.socket() as probe:
    running = probe.connect_ex(("127.0.0.1", 7781)) == 0
if not running:
    python = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(python), str(root / "brain.py")], cwd=root,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(40):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 7781)) == 0:
                break
        time.sleep(.1)
if "--no-browser" not in sys.argv:
    webbrowser.open("http://127.0.0.1:7781")
