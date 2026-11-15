"""One-time setup for reading windows by name (ui_tree.py): install agent-desktop inside Jarvis.

    .venv\\Scripts\\python.exe scripts\\setup_agent_desktop.py           install (if needed) and check
    .venv\\Scripts\\python.exe scripts\\setup_agent_desktop.py --remove  take it out again

Installs the agent-desktop npm package into vendor/agent-desktop (nothing global; npm install scripts are not
run: the Windows program is already in the package). The program must match the checksum below, which is the one
that was tried on this PC on 2026-11-15; a different one is refused, so a new version is a deliberate change here.
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ui_tree  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SHA256 = "a7ef5e539fb97287a35eb9ed49d3803b4d6bd705bc4106eb28617229f9be679e"  # agent-desktop-win32-x64.exe 1.3.1
FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def main():
    if "--remove" in sys.argv:
        shutil.rmtree(ui_tree.FOLDER, ignore_errors=True)
        return print("removed")
    if not ui_tree.available():
        npm = shutil.which("npm")
        if not npm:
            return print("npm isn't installed (it comes with Node.js), so agent-desktop can't be installed.") or 1
        ui_tree.FOLDER.mkdir(parents=True, exist_ok=True)
        (ui_tree.FOLDER / "package.json").write_text('{"name":"jarvis-agent-desktop","private":true}', encoding="utf-8")
        done = subprocess.run([npm, "install", f"agent-desktop@{ui_tree.VERSION}", "--ignore-scripts", "--no-audit",
                               "--no-fund"], cwd=str(ui_tree.FOLDER), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300, creationflags=FLAGS)
        if done.returncode or not ui_tree.available():
            return print("npm install failed: " + (done.stdout + done.stderr).strip()[-400:]) or 1
    if hashlib.sha256(ui_tree.EXE.read_bytes()).hexdigest() != SHA256:
        shutil.rmtree(ui_tree.FOLDER, ignore_errors=True)
        return print("The program isn't the one that was checked (its checksum differs). Removed it.") or 1
    found = ui_tree.windows()
    print(f"agent-desktop {ui_tree.VERSION} is ready: it sees {len(found)} windows. Restart Jarvis to use it.")


if __name__ == "__main__":
    sys.exit(main() or 0)
