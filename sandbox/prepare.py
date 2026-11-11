#!/usr/bin/env python3
"""Share in the folders for one job, and nothing else. Runs as root inside the sandbox distro.

wsl_sandbox.prepare() sends this a JSON spec on standard input:
    {"shares": [{"windows": "<the job's folder on Windows>", "at": "/work/job", "writable": true}, ...]}

The distro has no Windows drive mounted (sandbox/provision.sh), so these shares are everything of the owner's
the agent can see. Whatever an earlier job had is unmounted first. A share that isn't writable is mounted
read-only, which Linux enforces whatever the agent runs.
"""
import json
import os
import posixpath
import subprocess
import sys

WORK, OWNER = "/work", "/owner"
AGENT_UID = 1000


def mounted():
    """Mount points under /work and /owner, deepest first."""
    points = []
    with open("/proc/self/mounts", encoding="utf-8") as f:
        for line in f:
            point = line.split()[1].replace("\\040", " ")
            if point.startswith((WORK + "/", OWNER + "/")):
                points.append(point)
    return sorted(points, key=len, reverse=True)


def clear():
    for point in mounted():
        subprocess.run(["umount", point], check=True)
    for base in (WORK, OWNER):
        for name in os.listdir(base):
            os.rmdir(os.path.join(base, name))  # an empty mount point; never removes a file


def share(windows, at, writable):
    at = posixpath.normpath(at)
    if not at.startswith((WORK + "/", OWNER + "/")) or at.count("/") != 2:
        raise ValueError(f"shares go directly under {WORK} or {OWNER}, not {at}")
    os.makedirs(at, exist_ok=True)
    options = f"metadata,uid={AGENT_UID},gid={AGENT_UID},umask=022" + ("" if writable else ",ro")
    subprocess.run(["mount", "-t", "drvfs", windows, at, "-o", options], check=True)


def main():
    spec = json.load(sys.stdin)
    clear()
    for item in spec.get("shares", []):
        share(item["windows"], item["at"], bool(item.get("writable")))
    print(json.dumps({"ok": True, "mounted": mounted()}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # one line the Windows side can show
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}))
        sys.exit(1)
