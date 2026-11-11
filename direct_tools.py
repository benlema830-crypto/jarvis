"""Shell and file tools the conversation can use itself, so small jobs don't need a background agent.

A question that takes one command used to mean starting an agent, waiting, and hearing a report. These run
inside the turn, the way a terminal session does. They follow the same rules as the agents, through
cc_guard: a command that messages other people waits for the owner's yes, and everything else runs, deleting
and installing included.

Two extra precautions, because the conversation is what reads email:
  - once email has been read this turn, anything beyond plain reading asks first (truth_guard.tainted)
  - credentials can't be read this way, and the child process doesn't inherit Jarvis's API keys
"""
import base64
import fnmatch
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import cc_guard
import truth_guard

HOME = Path.home()
MAX_OUTPUT = 12000       # characters handed to the model; beyond this, the middle is cut
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 150        # past this it's a job for an agent: it would hold up the conversation
MAX_READ_LINES = 600
MAX_MATCHES = 80
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "models", "vendor", ".cache", "AppData"}

# Files whose contents must never go to a model provider, whichever tool asks. One rule, kept in cc_guard.
SECRET_FILE = cc_guard.SECRET_FILE
SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.I)
SECRET_REFUSAL = "That's a credentials file. Its contents can't be read into the conversation."
AFTER_UNTRUSTED = "after untrusted text"  # always asks, whatever the auto_approve setting

# Set by jarvis.Brain: the same "stop" that interrupts the turn ends a running command.
cancel = threading.Event()


class NeedsApproval(Exception):
    """Raised with (question, kind): the owner must answer before this can run."""

    def __init__(self, question, kind):
        super().__init__(question)
        self.question, self.kind = question, kind


def _resolve(path, default=None):
    text = os.path.expandvars(str(path or "").strip().strip('"'))
    if not text:
        if default is None:
            raise ValueError("Give a path.")
        return Path(default)
    resolved = Path(text).expanduser()
    return resolved if resolved.is_absolute() else HOME / resolved


def _clip(text):
    if len(text) <= MAX_OUTPUT:
        return text
    head = MAX_OUTPUT * 2 // 3
    return f"{text[:head]}\n... [{len(text) - MAX_OUTPUT} characters cut] ...\n{text[-(MAX_OUTPUT - head):]}"


def _guard(tool, tool_input, summary, read_only=False):
    """Raises when it may not run now. Returns quietly when it may."""
    verdict, detail = cc_guard.decide(tool, tool_input)
    if verdict == "blocked":
        raise ValueError(detail)
    if verdict == "approval":
        raise NeedsApproval(f"{summary}\nReason: {detail}", detail)
    if truth_guard.tainted() and not read_only:
        raise NeedsApproval(f"{summary}\nReason: this turn read email, so a change needs your OK in case a "
                            "message asked for it.", AFTER_UNTRUSTED)


def _clean_env():
    return {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}


def _kill(proc):
    if proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)


def execute(command, folder, seconds):
    """Run PowerShell with no guard check (the caller did that). Encoded so quoting can't change its meaning."""
    script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue';" + command
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    began = time.monotonic()
    proc = subprocess.Popen(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            cwd=str(folder), env=_clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW)
    chunks = []
    reader = threading.Thread(target=lambda: chunks.extend(iter(proc.stdout.readline, "")), daemon=True)
    reader.start()
    ending = None
    while proc.poll() is None:
        if cancel.is_set():
            ending = "Stopped by the user."
        elif time.monotonic() - began > seconds:
            ending = f"Timed out after {seconds} seconds and was stopped, so it did NOT finish."
        if ending:
            _kill(proc)
            break
        time.sleep(0.05)
    proc.wait()
    reader.join(2)
    output = "".join(chunks).strip()
    took = time.monotonic() - began
    status = ending or f"Exit code {proc.returncode} in {took:.1f}s."
    return f"{status}\n{_clip(output) if output else '(no output)'}"


def run_command(command, folder="", timeout=DEFAULT_TIMEOUT):
    command = str(command or "").strip()
    if not command:
        raise ValueError("Give a command.")
    if SECRET_FILE.search(command):
        raise ValueError(SECRET_REFUSAL)
    where = _resolve(folder, HOME)
    if not where.is_dir():
        raise ValueError(f"No such folder: {where}")
    seconds = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    _guard("PowerShell", {"command": command}, f"Run in {where}: {command}", cc_guard.plain_read_command(command))
    return execute(command, where, seconds)


def read_file(path, start_line=1, max_lines=300):
    target = _resolve(path)
    if SECRET_FILE.search(" " + str(target)):
        raise ValueError(SECRET_REFUSAL)
    _guard("Read", {"file_path": str(target)}, f"Read {target}", read_only=True)
    if target.is_dir():
        names = sorted(p.name + ("\\" if p.is_dir() else "") for p in target.iterdir())
        return _clip(f"{target} is a folder containing {len(names)} items:\n" + "\n".join(names[:300]))
    if not target.is_file():
        raise ValueError(f"No such file: {target}")
    with target.open("rb") as handle:
        if b"\0" in handle.read(4096):
            return f"{target} is a binary file ({target.stat().st_size} bytes); it can't be read as text."
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    first = max(1, int(start_line or 1))
    count = max(1, min(int(max_lines or 300), MAX_READ_LINES))
    shown = lines[first - 1:first - 1 + count]
    body = "\n".join(f"{first + i}: {line[:1000]}" for i, line in enumerate(shown))
    more = f"\n[Showing lines {first}-{first + len(shown) - 1} of {len(lines)}.]" if len(shown) < len(lines) else ""
    return _clip(body or "(empty)") + more


def _python_search(pattern, root, glob):
    regex = re.compile(pattern, re.I)
    found = []
    roots = [root] if root.is_file() else None
    for base, dirs, files in ([(str(root.parent), [], [root.name])] if roots else os.walk(root)):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if (glob and not fnmatch.fnmatch(name, glob)) or SECRET_FILE.search(" " + name):
                continue
            path = Path(base) / name
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                with path.open(encoding="utf-8", errors="strict") as handle:
                    for number, line in enumerate(handle, 1):
                        if regex.search(line):
                            found.append(f"{path}:{number}: {line.strip()[:300]}")
                            if len(found) >= MAX_MATCHES:
                                return found
            except (OSError, UnicodeDecodeError):
                continue
    return found


def _match_path(line):
    """The file part of a "path:line: text" match (the path itself has a colon after the drive letter)."""
    found = re.match(r"(.+?):\d+:", line)
    return found.group(1) if found else line


def search_text(pattern, folder="", glob=""):
    pattern = str(pattern or "")
    if not pattern:
        raise ValueError("Give a pattern to search for.")
    root = _resolve(folder, HOME)
    if SECRET_FILE.search(" " + str(root)):  # naming the file itself would otherwise search it line by line
        raise ValueError(SECRET_REFUSAL)
    _guard("Grep", {"path": str(root), "pattern": pattern}, f"Search {root}", read_only=True)
    if not root.exists():
        raise ValueError(f"No such folder: {root}")
    try:
        re.compile(pattern)
    except re.error as error:
        raise ValueError(f"Not a valid search pattern: {error}") from None
    rg = shutil.which("rg")
    if rg:
        command = [rg, "-n", "-i", "--no-heading", "--max-count", "20", "--max-columns", "300", "--max-filesize", "2M"]
        for skip in SKIP_DIRS:
            command += ["-g", f"!**/{skip}/**"]
        command += ["-g", "!.env", "-g", "!*.dpapi", "-g", "!*.enc"]
        if glob:
            command += ["-g", glob]
        command += ["-e", pattern, str(root)]
        try:
            lines = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW).stdout.splitlines()
        except subprocess.TimeoutExpired:
            return f"The search of {root} took over 30 seconds and was stopped. Search a smaller folder."
        # The three globs above cover the common cases; this applies the full rule read_file uses, so a match
        # inside .env.local, a .pem or credentials.json never reaches the conversation either.
        lines = [line for line in lines if not SECRET_FILE.search(" " + _match_path(line))]
    else:
        lines = _python_search(pattern, root, glob)
    if not lines:
        return f"No matches for {pattern!r} in {root}."
    extra = f"\n[First {MAX_MATCHES} of {len(lines)} matches.]" if len(lines) > MAX_MATCHES else ""
    return _clip("\n".join(lines[:MAX_MATCHES])) + extra


def _write(target, text):
    """Atomic: never leaves a half-written file. os.replace, per the ReplaceFile incident in the dev notes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    if not temp.exists():
        raise OSError(f"Could not write {target}.")
    os.replace(temp, target)


def _read_exact(target):
    with target.open(encoding="utf-8", newline="") as handle:  # keeps CRLF line endings as they are
        return handle.read()


def edit_file(path, old_text, new_text):
    target = _resolve(path)
    if SECRET_FILE.search(" " + str(target)):
        raise ValueError(SECRET_REFUSAL)
    _guard("Edit", {"file_path": str(target)}, f"Edit {target}")
    return apply_edit(target, old_text, new_text)


def apply_edit(target, old_text, new_text):
    if not target.is_file():
        raise ValueError(f"No such file: {target}")
    if not old_text:
        raise ValueError("Give the exact text to replace.")
    try:
        content = _read_exact(target)
    except UnicodeDecodeError:
        raise ValueError(f"{target} isn't a text file.") from None
    crlf = "\r\n" in content and "\r\n" not in old_text
    wanted = old_text.replace("\n", "\r\n") if crlf else old_text
    count = content.count(wanted)
    if count == 0:
        raise ValueError("That exact text isn't in the file, so nothing was changed. Read the file again.")
    if count > 1:
        raise ValueError(f"That text appears {count} times, so nothing was changed. Include more of the surrounding text.")
    _write(target, content.replace(wanted, new_text.replace("\n", "\r\n") if crlf else new_text))
    if (new_text.replace("\n", "\r\n") if crlf else new_text) not in _read_exact(target):
        raise OSError(f"The edit to {target} didn't take.")
    return f"Edited {target}: replaced 1 place, checked on disk."


def write_file(path, content, overwrite=False):
    target = _resolve(path)
    if SECRET_FILE.search(" " + str(target)):
        raise ValueError(SECRET_REFUSAL)
    if target.is_dir():
        raise ValueError(f"{target} is a folder.")
    if target.exists() and not overwrite:
        raise ValueError(f"{target} already exists, so nothing was changed. Use edit_file, or set overwrite if "
                         "the owner wants it replaced.")
    _guard("Write", {"file_path": str(target)}, f"{'Replace' if target.exists() else 'Create'} {target}")
    return apply_write(target, content)


def apply_write(target, content, _overwrite=False):
    _write(target, str(content))
    if _read_exact(target) != str(content):
        raise OSError(f"{target} didn't match what was written.")
    return f"Wrote {target} ({target.stat().st_size} bytes), checked on disk."


# The steps that run once the owner has said yes: the guard already had its say.
AFTER_APPROVAL = {"edit_file": apply_edit, "write_file": apply_write}
