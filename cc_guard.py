"""Claude Code PreToolUse hook for Jarvis's terminal tasks (see terminal.py), and the same verdicts for Jarvis's
own commands and his Codex agents.

Claude Code runs this before every tool call. It reads the call as JSON on stdin and:
  - lets the work run (Claude Code is in bypass-permissions mode). Deleting, installing, system settings,
    git pushes and edits anywhere no longer wait for anyone: the owner's decision, 2026-11-11;
  - pauses only a command that messages other people in the owner's name, until they say yes;
  - never lets an agent rewrite these rules or its own approval records;
  - blocks the apps listed in JARVIS_BLOCK_WORK_APPS (none by default; see worksafe.py).

Approvals live in data/cc_approvals.json, written by terminal.py when the user says yes.
"""

import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APPROVALS = os.path.join(HERE, "data", "cc_approvals.json")
PENDING = os.path.join(HERE, "data", "cc_pending.json")

MESSAGE = "message other people"
RISKY = {
    # The one kind of command that still waits for the owner: it speaks to other people as them. Spending
    # money doesn't happen in a shell command; the screen agent and outside tools ask for that themselves.
    MESSAGE: re.compile(
        r"\bSend-MailMessage\b|\bgh\s+(?:issue|pr)\s+(?:comment|review)\b|\bgh\s+issue\s+create\b|"
        r"\b(?:sendmail|mutt|msmtp|swaks)\b|\bmail\s+-s\b|\bsmtplib\b|"
        r"hooks\.slack\.com|discord(?:app)?\.com/api/webhooks|\btwilio\b", re.I),
}
# Deleting asks nobody. An agent working unattended is still kept to deleting inside its own folder (see
# unattended), and this is how a delete is recognised.
DELETE = re.compile(
    r"\b(Remove-Item|rm|rmdir|rd|del|erase|Clear-RecycleBin|Clear-Content)\b|\bri\s|"
    r"\[(System\.)?IO\.(File|Directory)\]::Delete|\.Delete\(|shred|git\s+clean|"
    r"\bos\.(?:remove|unlink|rmdir|removedirs)\s*\(|\bshutil\.rmtree\b|\.(?:unlink|rmdir|rmSync|unlinkSync|rmdirSync)\s*\(", re.I)
# Apps the owner has put off-limits, approval or not. None by default: JARVIS_BLOCK_WORK_APPS=teams,outlook.
TEAMS_OFF_LIMITS = re.compile(
    r"\\Microsoft\\Teams\b|\\Packages\\MSTeams|\b(ms-teams|msteams|teams)\.exe\b", re.I)
OUTLOOK_OFF_LIMITS = re.compile(
    r"\\Microsoft\\(Outlook|Olk)\b|\\Packages\\Microsoft\.OutlookForWindows|"
    r"\.(pst|ost|nst)\b|\b(outlook|olk)\.exe\b|Microsoft\.Office\.Interop\.Outlook|Outlook\.Application", re.I)

# Plain inspection commands. Anything else, any redirection, subexpression or encoded
# command, and flags that can run programs or write files make the whole command "not read-only".
READ_COMMAND = re.compile(r"(Get-Content|gc|cat|type|Get-ChildItem|gci|dir|ls|Get-Item|Test-Path|Resolve-Path|"
                          r"Select-Object|select|Select-String|sls|Measure-Object|Sort-Object|Format-List|Format-Table|"
                          r"Out-String|rg|findstr|git\s+(status|log|diff|show|branch|rev-parse|ls-files|blame))(\s|$)", re.I)
UNSAFE = re.compile(r"[>`]|\$\(|\$\{|@'|@\"|&|--pre\b|--output|--ext-diff|\bgit\s+-c\b|-Encoded|\bInvoke-|\biex\b|"
                    r"-Stream\b|::|\bgit\s+branch\b[^;|\n]*\s-(?:[dDmMcCfu]\b|-(?:delete|move|copy|force|set-upstream))", re.I)
POWERSHELL = re.compile(r'^\s*"?[^"\s]*?(powershell|pwsh)(\.exe)?"?\s+(-NoProfile\s+|-NoLogo\s+)*-Command\s+(?P<script>.+)$', re.I | re.S)


def plain_read_command(command: str) -> bool:
    """True only when every part of a (PowerShell-wrapped) command just reads or searches."""
    match = POWERSHELL.match(command or "")
    script = (match.group("script") if match else command or "").strip()
    if len(script) > 1 and script[0] == script[-1] == '"':
        script = script[1:-1]
    if not script or UNSAFE.search(script):
        return False
    unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", "''", script)  # separators inside quotes are just text
    if "'" in unquoted.replace("''", "") or '"' in unquoted:
        return False  # unbalanced or nested quoting: don't guess
    parts = [p.strip() for p in re.split(r"[;\n|]", unquoted) if p.strip()]
    return bool(parts) and all(READ_COMMAND.match(p) for p in parts)


SHELL_TOOLS = {"Bash", "PowerShell"}
FILE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# An agent must never be able to grant itself approval or rewrite the rules that pause it.
PROTECTED = {os.path.normcase(os.path.join(HERE, *p)) for p in (
    ("data", "cc_approvals.json"), ("data", "cc_pending.json"), ("data", "cc_settings.json"),
    ("cc_guard.py",), ("approvals.py",))}
STATE_NAMES = re.compile(r"\bcc_(?:approvals|pending|settings)\.json\b", re.I)
HOME = os.path.expanduser("~")


def _inside(path, root):
    path, root = os.path.normcase(path), os.path.normcase(os.path.abspath(root))
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def _write_verdict(file_path):
    if not file_path:
        return None
    try:  # resolve links/junctions so a link inside the home folder can't point elsewhere
        path = os.path.realpath(os.path.abspath(file_path))
    except (OSError, ValueError):
        path = os.path.abspath(file_path)  # unreadable volume: judged by its plain path (outside -> ask)
    path = os.path.normcase(path)
    if path in PROTECTED:
        return "blocked", "Jarvis's approval records and guard rules can't be changed by an agent."
    return None  # anywhere else is the agent's to write, with no question


def blocked_work_apps() -> set:
    # Same switch as worksafe.blocked(); not imported to keep this hook light. Jarvis's .env reaches it
    # through the environment terminal.py passes to Claude Code.
    return {name.strip().lower() for name in os.getenv("JARVIS_BLOCK_WORK_APPS", "").split(",") if name.strip()}


def decide(tool: str, tool_input: dict) -> tuple[str, str]:
    """('allow' | 'approval' | 'blocked', detail)."""
    text = json.dumps(tool_input).replace("\\\\", "\\") if tool in SHELL_TOOLS | FILE_TOOLS else ""
    off_limits = blocked_work_apps() if text else ()
    if "teams" in off_limits and TEAMS_OFF_LIMITS.search(text):
        return "blocked", "Microsoft Teams (its app and data) is off-limits."
    if "outlook" in off_limits and OUTLOOK_OFF_LIMITS.search(text):
        return "blocked", "Outlook (its app and data) is off-limits."
    if tool in WRITE_TOOLS:
        verdict = _write_verdict(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))
        if verdict:
            return verdict
    if tool in SHELL_TOOLS and STATE_NAMES.search(str(tool_input.get("command", ""))):
        return "blocked", "Jarvis's approval records can't be changed by an agent."
    if tool in SHELL_TOOLS:
        command = str(tool_input.get("command", ""))
        if plain_read_command(command):
            return "allow", ""  # searching for "shutdown" or "Remove-Item" changes nothing
        for category, pattern in RISKY.items():
            if pattern.search(command):
                return "approval", category
    return "allow", ""


# Files whose contents must never go to a model provider, whichever tool asks (direct_tools.py uses this too).
SECRET_FILE = re.compile(r"(?:^|[\\/\s'\"=])(?:\.env(?:\.[\w-]+)?(?<!\.example)|[\w-]*\.(?:dpapi|enc|pem|key|pfx|kdbx)|id_(?:rsa|ed25519|ecdsa)"
                         r"|credentials\.json|auth\.json|\.credentials\.json|\.git-credentials|\.npmrc|\.pypirc)(?=$|[\s'\";|,)])", re.I)

# Set by terminal.py for an agent working with nobody at the PC (an away job on Claude): the one folder it works in.
UNATTENDED_ROOT = "JARVIS_UNATTENDED_ROOT"
SANDBOXED = "JARVIS_SANDBOXED"  # set by sandbox/run_agent.py: this hook is running inside the Linux sandbox
# A full path: quoted (it may hold spaces, as "Jarvis Builds" does) or bare.
_ABSOLUTE = re.compile(r"'([A-Za-z]:[\\/][^']*)'|\"([A-Za-z]:[\\/][^\"]*)\"|(?<![\w'\"])([A-Za-z]:[\\/][^\s'\"|;&<>)]*)")
_ELSEWHERE = re.compile(r"(?:^|[\s'\"=(])(?:~|\.\.(?:[\\/]|$|\s)|\$HOME\b|\$env:|%[A-Za-z_]+%|/[A-Za-z]/)", re.I)
_CHANGE_FOLDER = re.compile(r"(?:^|[;&|\n(]|\b)\s*(?:cd|chdir|Set-Location|sl|pushd|Push-Location)\b\s+([^;&|\n]+)", re.I)


def _leaves(text, root) -> bool:
    """The text names somewhere outside `root`: an absolute path elsewhere, or one that can't be judged (~, ..,
    an environment variable)."""
    if _ELSEWHERE.search(text):
        return True
    for groups in _ABSOLUTE.findall(text):
        try:
            path = os.path.realpath(next(g for g in groups if g))
        except (OSError, ValueError):
            return True
        if not _inside(path, root):
            return True
    return False


def unattended(tool: str, tool_input: dict, root: str) -> tuple[str, str]:
    """The verdict for an agent working in a folder of its own with nobody at the PC (an away job).

    It may do what any agent may. What differs is that the job owns one folder, and stays in it:
      - its file tools write only inside that folder;
      - deleting is allowed only inside it, and it can't move its shell out of it;
      - credentials files can't be read or named in a command.
    'approval' means what it means for any agent (a message to other people): the owner is texted and asked.
    This judges what the agent asks to do; it is not a sandbox. A program the agent writes and runs can still
    reach the rest of the PC, which is why a Claude away job runs inside the Linux sandbox when that is ready
    (wsl_sandbox.py)."""
    verdict, detail = decide(tool, tool_input)
    if verdict != "allow":
        return verdict, detail
    root = os.path.realpath(root)
    # Only where a file is named, never what is written into one: a README may say "copy .env.example to .env".
    named = " ".join(str(tool_input.get(key) or "") for key in ("command", "file_path", "notebook_path", "path", "pattern", "glob"))
    if tool in SHELL_TOOLS | FILE_TOOLS and SECRET_FILE.search(" " + named):
        return "blocked", "Credentials files are off-limits."
    if tool in WRITE_TOOLS:
        target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        try:
            inside = bool(target) and _inside(os.path.realpath(os.path.abspath(target)), root)
        except (OSError, ValueError):
            inside = False
        if not inside:
            return "blocked", f"You may create and change files only inside {root}. Read elsewhere, write here."
        return "allow", ""
    if tool in SHELL_TOOLS:
        command = str(tool_input.get("command", ""))
        if plain_read_command(command):
            return "allow", ""
        for target in _CHANGE_FOLDER.findall(command):
            if _leaves(" " + target.strip().strip("'\""), root):
                return "blocked", f"Stay in {root}: don't change to another folder. Use full paths to read elsewhere."
        if DELETE.search(command) and _leaves(command, root):
            return "blocked", (f"You may delete only inside {root}, named by a path relative to it or a full path "
                               "under it. Leave anything else and say so in your report.")
    return "allow", ""


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def approved(session: str, category: str) -> bool:
    grant = _load(APPROVALS).get(session, {})
    return category in grant.get("categories", []) and grant.get("expires", 0) > time.time()


def record_pending(session: str, category: str, command: str):
    pending = _load(PENDING)
    entry = pending.setdefault(session, {"categories": [], "commands": []})
    if category not in entry["categories"]:
        entry["categories"].append(category)
    entry["commands"] = (entry["commands"] + [command[:500]])[-10:]
    os.makedirs(os.path.dirname(PENDING), exist_ok=True)
    with open(PENDING, "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=1)


def deny(reason: str):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))
    sys.exit(0)


def main():
    call = json.load(sys.stdin)
    tool, tool_input, session = call.get("tool_name", ""), call.get("tool_input") or {}, call.get("session_id", "")
    root = os.environ.get(UNATTENDED_ROOT, "").strip()
    verdict, detail = unattended(tool, tool_input, root) if root else decide(tool, tool_input)
    if verdict == "blocked":
        deny(f"BLOCKED: {detail}" if root else f"BLOCKED: {detail} Don't try another way; tell the user it's off-limits.")
    if verdict == "approval" and os.environ.get(SANDBOXED):
        # Inside the Linux sandbox there is nothing to send from and no way for a yes to reach this hook.
        deny(f"BLOCKED: that ({detail}) can't be done from inside the sandbox. Leave it undone and say in your "
             "report exactly what you would have sent, so the owner can decide.")
    if verdict == "approval" and not approved(session, detail):
        try:
            record_pending(session, detail, str(tool_input.get("command", "")))
        except OSError:
            pass  # the pause must still be reported: a hook that crashes here would let the action through
        deny(f"PAUSED: this action ({detail}) needs the user's approval first. Do not look for a "
             "workaround. Stop now and make your final message start with 'APPROVAL NEEDED:' followed by "
             "one short spoken sentence saying exactly what you want to do and why.")
    sys.exit(0)  # no decision: bypass-permissions mode lets it run


if __name__ == "__main__":
    main()
