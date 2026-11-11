#!/usr/bin/env python3
"""Is this still a sandbox? Runs as the agent user inside the distro and prints the facts as JSON.

wsl_sandbox.problem() reads them before every job, so a distro someone loosened by hand (a drive mounted again,
the agent given sudo) is not trusted with an unattended agent.
"""
import json
import os
import shutil
import subprocess

SETTINGS = "/etc/claude-code/managed-settings.json"
GUARD = "/opt/jarvis/cc_guard.py"
CLAUDE = os.path.expanduser("~/.local/bin/claude")


def windows_drives():
    """Windows folders mounted anywhere but the two places a job's shares go."""
    found = []
    with open("/proc/self/mounts", encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if "aname=drvfs" in parts[3] and not parts[1].startswith(("/work/", "/owner/")):
                found.append(parts[1])
    return found


def locked(path):
    """There, and not the agent's to change."""
    return os.path.isfile(path) and not os.access(path, os.W_OK) and not os.access(os.path.dirname(path), os.W_OK)


def main():
    try:
        sudo = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        sudo = False
    print(json.dumps({
        "user": os.environ.get("USER") or str(os.getuid()),
        "root": os.getuid() == 0,
        "sudo": sudo,
        "windows_drives": windows_drives(),
        "windows_programs": os.environ.get("WSL_INTEROP", "") != "",
        "bwrap": bool(shutil.which("bwrap")),
        "socat": bool(shutil.which("socat")),
        "claude": os.access(CLAUDE, os.X_OK),
        "settings_locked": locked(SETTINGS),
        "guard_locked": locked(GUARD),
    }))


if __name__ == "__main__":
    main()
