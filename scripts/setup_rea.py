"""One-time setup for teardowns (teardown.py): install REA and connect it to the teardown agent.

    .venv\\Scripts\\python.exe scripts\\setup_rea.py           install (if needed), connect, check
    .venv\\Scripts\\python.exe scripts\\setup_rea.py --remove  disconnect it again

What it does:
  1. Installs the rea-agents npm package into vendor/rea inside Jarvis (nothing global; npm install scripts
     are not run).
  2. Registers REA with Claude Code at "local" scope for the folder data/teardowns. That writes one entry into
     your Claude Code settings (~/.claude.json) under that folder's path, so only an agent started in that
     folder loads REA. Your other Claude Code projects are not touched.
  3. Asks Claude Code whether the server connects, and leaves a marker so Jarvis knows it is ready.
"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import teardown  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def run(command, cwd, timeout=300):
    done = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, stdin=subprocess.DEVNULL, creationflags=FLAGS)
    return done.returncode, (done.stdout + done.stderr).strip()


def claude():
    import terminal
    exe = terminal._claude_exe()
    if not exe:
        raise SystemExit("Claude Code isn't installed, and the teardown agent runs on it.")
    return exe


def main():
    node = shutil.which("node")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not node or not npm:
        raise SystemExit("Node.js isn't installed. REA needs Node 22.23.4+, 24.22.1+ or 26.12.1+.")
    teardown.FOLDER.mkdir(parents=True, exist_ok=True)
    if "--remove" in sys.argv:
        code, out = run([claude(), "mcp", "remove", "--scope", "local", "rea"], teardown.FOLDER)
        teardown.MARKER.unlink(missing_ok=True)
        print(out or "Removed.")
        return
    if not teardown.ENTRY.is_file():
        print(f"Installing {teardown.PACKAGE}@{teardown.VERSION} into {teardown.INSTALL} ...")
        teardown.INSTALL.mkdir(parents=True, exist_ok=True)
        code, out = run([npm, "install", "--prefix", str(teardown.INSTALL), f"{teardown.PACKAGE}@{teardown.VERSION}",
                         "--ignore-scripts", "--no-audit", "--no-fund"], teardown.INSTALL, timeout=900)
        if code or not teardown.ENTRY.is_file():
            raise SystemExit("The install failed:\n" + out[-1500:])
    code, out = run([node, str(teardown.ENTRY), "--version"], teardown.FOLDER, timeout=60)
    if code:
        raise SystemExit("REA doesn't start on this PC:\n" + out[-1500:])
    print("REA", out.splitlines()[-1], "is installed.")

    exe = claude()
    run([exe, "mcp", "remove", "--scope", "local", "rea"], teardown.FOLDER)  # replace an older registration quietly
    code, out = run([exe, "mcp", "add", "--scope", "local", "rea", "-e", "REA_MCP_OUTPUT_SCHEMA_PROFILE=off",
                     "--", node, str(teardown.ENTRY), "mcp"], teardown.FOLDER)
    if code:
        raise SystemExit("Claude Code refused the registration:\n" + out[-1500:])
    code, out = run([exe, "mcp", "get", "rea"], teardown.FOLDER, timeout=120)
    print(out)
    if code or "connected" not in out.lower() or "failed" in out.lower():
        teardown.MARKER.unlink(missing_ok=True)
        raise SystemExit("REA is registered but Claude Code couldn't connect to it. See the output above.")
    teardown.MARKER.write_text(f"{teardown.PACKAGE}@{teardown.VERSION}\n", encoding="utf-8")
    print("Ready: Jarvis can run teardowns (the reverse_engineer tool).")


if __name__ == "__main__":
    main()
