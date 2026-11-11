#!/usr/bin/env python3
"""Start Claude Code for one job. Runs as the agent user inside the sandbox distro.

wsl_sandbox.launch() sends this a JSON spec on standard input:
    {"cwd": "/work/job", "prompt": "...", "rules": "...", "permission_mode": "bypassPermissions",
     "model": "...", "effort": "...", "resume": "<session id>"}
and reads Claude Code's stream of JSON events from standard output, as terminal.py does on Windows.

The spec comes in on standard input, never the command line: a task is long, has quotes and newlines in it, and
would have to survive two command lines otherwise. Claude Code is replaced into this process, so stopping the
run from Windows stops it.

What holds the agent here is not in this file. /etc/claude-code/managed-settings.json (root's, so the agent
can't change it) switches on Claude Code's own sandbox for every shell command and runs cc_guard.py before
every tool call. JARVIS_UNATTENDED_ROOT below tells that guard which folder the job owns, and JARVIS_SANDBOXED
that a question can't be answered in here.
"""
import json
import os
import sys
import tempfile

CLAUDE = os.path.expanduser("~/.local/bin/claude")


def main():
    spec = json.load(sys.stdin)
    cwd = spec["cwd"]
    command = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose", "--strict-mcp-config",
               "--permission-mode", spec.get("permission_mode") or "bypassPermissions",
               "--append-system-prompt", spec.get("rules", "")]
    for flag in ("model", "effort", "resume"):
        if spec.get(flag):
            command += [f"--{flag}", spec[flag]]
    home = os.path.expanduser("~")
    # Built from nothing, so no variable from Windows or from an earlier shell rides along.
    env = {"HOME": home, "USER": "agent", "LOGNAME": "agent", "SHELL": "/bin/bash", "LANG": "C.UTF-8",
           "PATH": f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin", "JARVIS_UNATTENDED_ROOT": cwd, "JARVIS_SANDBOXED": "1"}
    os.chdir(cwd)
    # The task is Claude Code's standard input: a file, already unlinked, so nothing is left behind.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as task:
        task.write(spec["prompt"])
    source = os.open(task.name, os.O_RDONLY)
    os.unlink(task.name)
    os.dup2(source, 0)
    os.execve(CLAUDE, command, env)


if __name__ == "__main__":
    main()
