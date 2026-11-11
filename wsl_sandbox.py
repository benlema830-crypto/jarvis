"""A real sandbox for a Claude agent working while the owner is away: a locked-down Linux inside Windows.

Claude Code has no sandbox on Windows, so an unattended Claude agent used to be held by rules alone
(cc_guard.unattended), which judge what the agent asks to do and can't hold a program it writes and runs. Claude
Code does have a sandbox on Linux, and Windows can run a small Linux (WSL2). So the agent runs there:

  - The distro (JarvisSandbox, made by scripts/setup_wsl_sandbox.py) has no Windows drive mounted and can't start
    Windows programs. The agent is an ordinary user in it, with no sudo. See sandbox/provision.sh.
  - Before each run Jarvis shares in the one folder the job works in, and for research the owner's Documents
    read-only (sandbox/prepare.py). That is all of the owner's PC the agent can see, whatever it runs.
  - Inside, Claude Code's own sandbox holds every shell command to that folder and to a short list of package
    sites, and cc_guard.py still checks every tool call (sandbox/managed-settings.json, which is root's).
  - Nothing of Jarvis's is in there: no tokens, no connected services, and Jarvis's own ports don't answer.

What it does not do: stop the agent reading the web, or reading what was shared in. A job's folder and, for
research, Documents can still be read and so could be sent somewhere by an agent that was talked into it.

The Claude sign-in inside the distro is the owner's to do, once: `wsl -d JarvisSandbox -e
/home/agent/.local/bin/claude auth login --claudeai`. Until then problem() says so and away jobs fall back to the rules.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = HERE / "sandbox"
DISTRO = os.getenv("JARVIS_SANDBOX_DISTRO", "JarvisSandbox")
WORK, OWNER = "/work", "/owner"
CLAUDE = "/home/agent/.local/bin/claude"
PYTHON = "/usr/bin/python3"
SIGN_IN = f"wsl -d {DISTRO} -e {CLAUDE} auth login --claudeai"
SETUP = "scripts/setup_wsl_sandbox.py"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Kept the same as the copies in the repo before every run, so a fix to the guard reaches the sandbox too.
# Each is root's inside the distro: the agent can read them and can't change them.
INSTALLED = {
    "prepare.py": "/opt/jarvis/prepare.py",
    "run_agent.py": "/opt/jarvis/run_agent.py",
    "check.py": "/opt/jarvis/check.py",
    "managed-settings.json": "/etc/claude-code/managed-settings.json",
}
GUARD = "/opt/jarvis/cc_guard.py"


def _exe():
    import testing_guard
    if testing_guard.under_test():
        return None  # a test must supply a fake: the real thing would start a Linux VM and a real agent
    return shutil.which("wsl.exe")


def _env():
    env = dict(os.environ)
    env["WSL_UTF8"] = "1"      # wsl.exe's own messages in UTF-8, not UTF-16
    env.pop("WSLENV", None)    # the list of Windows variables to carry into Linux: none
    return env


def run(*command, root=False, text_in="", timeout=120):
    """Run a command inside the distro: (exit code, output). The code is None when it couldn't be run at all."""
    exe = _exe()
    if not exe:
        return None, "WSL isn't available."
    try:
        done = subprocess.run([exe, "-d", DISTRO, "-u", "root" if root else "agent", "-e", *command],
                              input=text_in.replace("\r\n", "\n").encode("utf-8"), capture_output=True,
                              timeout=timeout, env=_env(), creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    return done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace").strip()


def _last_json(output):
    for line in reversed((output or "").splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def distros():
    exe = _exe()
    if not exe:
        return []
    try:
        done = subprocess.run([exe, "--list", "--quiet"], capture_output=True, timeout=30, env=_env(),
                              creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in done.stdout.decode("utf-8", "replace").replace("\x00", "").splitlines() if line.strip()]


def sync():
    """Put the repo's copies of the sandbox's files in place. "" or what went wrong."""
    files = {name: (FILES / name).read_text(encoding="utf-8") for name in INSTALLED}
    targets = {**{INSTALLED[name]: text for name, text in files.items()},
               GUARD: (HERE / "cc_guard.py").read_text(encoding="utf-8")}
    for target, text in targets.items():
        code, output = run("/usr/bin/tee", target, root=True, text_in=text)
        if code != 0:
            return f"couldn't write {target} in the sandbox: {output[-200:]}"
    return ""


def weaknesses(facts):
    """What in check.py's facts means this is no longer a sandbox. Empty when it holds."""
    found = []
    if not facts:
        return ["its self-check didn't answer"]
    if facts.get("root") or facts.get("sudo"):
        found.append("the agent has administrator rights in it")
    if facts.get("windows_drives"):
        found.append("a Windows drive is mounted in it (" + ", ".join(facts["windows_drives"]) + ")")
    if facts.get("windows_programs"):
        found.append("it can start Windows programs")
    if not (facts.get("bwrap") and facts.get("socat")):
        found.append("the packages Claude Code's sandbox needs are missing")
    if not facts.get("claude"):
        found.append("Claude Code isn't installed in it")
    if not (facts.get("settings_locked") and facts.get("guard_locked")):
        found.append("its rules are missing or the agent could change them")
    return found


def problem():
    """"" when an unattended agent can run in the sandbox now, else one plain sentence saying why not."""
    if not _exe():
        return "the Linux sandbox isn't installed on this PC"
    if DISTRO not in distros():
        return f"the Linux sandbox hasn't been set up (run {SETUP})"
    code, output = run(PYTHON, "/opt/jarvis/check.py", timeout=60)
    found = weaknesses(_last_json(output) if code == 0 else {})
    if found:
        return f"the Linux sandbox isn't safe to use: {'; '.join(found)} (run {SETUP})"
    code, output = run(CLAUDE, "auth", "status", timeout=60)
    try:
        signed_in = bool(json.loads(output[output.index("{"):output.rindex("}") + 1]).get("loggedIn"))
    except ValueError:
        signed_in = False
    if not signed_in:
        return f"Claude Code inside the Linux sandbox isn't signed in to your Claude plan (run: {SIGN_IN})"
    return ""


def _safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "job"


def inside(folder):
    """Where a job's folder appears inside the sandbox. The same every time, so a session can be continued."""
    return f"{WORK}/{_safe(Path(folder).name)}"


def owner_path(folder):
    """Where a folder shared read-only appears inside the sandbox."""
    return f"{OWNER}/{_safe(Path(folder).name)}"


def prepare(workspace, read_only=()):
    """Share the job's folder in (and the read-only ones), and nothing else. Returns the job folder's path inside.

    Raises RuntimeError with a plain reason when the sandbox can't be made ready."""
    failed = sync()
    if failed:
        raise RuntimeError(failed)
    shares = [{"windows": str(workspace), "at": inside(workspace), "writable": True}]
    shares += [{"windows": str(folder), "at": owner_path(folder), "writable": False} for folder in read_only]
    code, output = run(PYTHON, "/opt/jarvis/prepare.py", root=True, text_in=json.dumps({"shares": shares}))
    reply = _last_json(output)
    if code != 0 or not reply.get("ok"):
        raise RuntimeError(f"couldn't share the job's folder into the sandbox: {reply.get('error') or output[-300:]}")
    return shares[0]["at"]


def launch(cwd, prompt, rules, model="", effort="", resume="", permission_mode="bypassPermissions"):
    """Start Claude Code inside the sandbox. Returns the process; its standard output is Claude Code's event stream."""
    exe = _exe()
    if not exe:
        raise RuntimeError("WSL isn't available.")
    proc = subprocess.Popen([exe, "-d", DISTRO, "-u", "agent", "-e", PYTHON, "/opt/jarvis/run_agent.py"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_env(),
                            text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    proc.stdin.write(json.dumps({"cwd": cwd, "prompt": prompt, "rules": rules, "model": model, "effort": effort,
                                 "resume": resume, "permission_mode": permission_mode}))
    proc.stdin.close()
    return proc


def stop():
    """Shut the distro down: every process in it ends and every share is gone. Its memory goes back to Windows."""
    exe = _exe()
    if not exe:
        return
    try:
        subprocess.run([exe, "--terminate", DISTRO], capture_output=True, timeout=60, env=_env(), creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        pass
