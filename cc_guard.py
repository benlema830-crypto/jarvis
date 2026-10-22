"""Claude Code PreToolUse hook for Jarvis's terminal tasks (see terminal.py).

Claude Code runs this before every tool call. It reads the call as JSON on stdin and:
  - lets ordinary work run (Claude Code is in bypass-permissions mode),
  - blocks risky actions - deleting, installing/uninstalling software, changing system
    settings - until the user has approved that kind of action out loud,
  - always blocks Teams data, and Outlook's too unless JARVIS_ALLOW_OUTLOOK=1 (see worksafe.py).

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

RISKY = {
    # Keyword rules cannot see through encoding or string-built commands, so those always ask.
    "hidden or encoded command": re.compile(
        r"\s-(?:e|ec|en|enc|enco\w*|encodedcommand)\s+[A-Za-z0-9+/=]{12,}|\b(?:Invoke-Expression|iex)\b|FromBase64String", re.I),
    "destructive git": re.compile(r"\bgit\s+(?:reset\s+--hard|push\b[^\n]*(?:--force|-f\b)|checkout\s+--\s|restore\s+(?:--worktree\s+)?\.)", re.I),
    "publish or external message": re.compile(r"\b(?:git\s+push|npm\s+publish|gh\s+(?:release\s+create|pr\s+merge|issue\s+comment|pr\s+comment)|Send-MailMessage)\b", re.I),
    "delete": re.compile(
        r"\b(Remove-Item|rm|rmdir|rd|del|erase|Clear-RecycleBin|Clear-Content)\b|\bri\s|"
        r"\[(System\.)?IO\.(File|Directory)\]::Delete|\.Delete\(|shred|git\s+clean|"
        r"\bos\.(?:remove|unlink|rmdir|removedirs)\s*\(|\bshutil\.rmtree\b|\.(?:unlink|rmdir|rmSync|unlinkSync|rmdirSync)\s*\(", re.I),
    "install": re.compile(
        r"\b(winget|choco|scoop|msiexec|Add-AppxPackage|Remove-AppxPackage|Install-Package|"
        r"Uninstall-Package|Install-Module|Uninstall-Module|Install-Script)\b|"
        r"\bnpm\s+(i|install|uninstall)\s+(-g|--global)\b|\.msi\b|setup\.exe|installer\.exe", re.I),
    "system settings": re.compile(
        r"\breg(\.exe)?\s+(add|delete|import|restore|load)\b|"
        r"\b(Set|New|Remove|Rename)-ItemProperty\b|\bHKLM:|\bHKCU:|"
        r"\b(Set-ExecutionPolicy|netsh|bcdedit|diskpart|powercfg|schtasks|Register-ScheduledTask|"
        r"Unregister-ScheduledTask|Set-Service|Stop-Service|Start-Service|Restart-Service|New-Service|"
        r"Set-NetFirewall\w*|New-NetFirewallRule|Disable-NetAdapter|Enable-NetAdapter|Set-MpPreference|"
        r"Add-MpPreference|Set-TimeZone|Set-Date|Rename-Computer|Restart-Computer|Stop-Computer|shutdown|"
        r"takeown|icacls|Add-LocalGroupMember|New-LocalUser|Set-LocalUser|Disable-ComputerRestore|"
        r"Enable-WindowsOptionalFeature|Disable-WindowsOptionalFeature|dism)\b|\bsfc\s+/|\bformat(\.com)?\s+[a-z]:|\bsc(\.exe)?\s+(config|delete|create|stop)\b",
        re.I),
}
# Teams apps and data: never, approval or not. Outlook too, unless JARVIS_ALLOW_OUTLOOK=1.
TEAMS_OFF_LIMITS = re.compile(
    r"\\Microsoft\\Teams\b|\\Packages\\MSTeams|\b(ms-teams|msteams|teams)\.exe\b", re.I)
OUTLOOK_OFF_LIMITS = re.compile(
    r"\\Microsoft\\(Outlook|Olk)\b|\\Packages\\Microsoft\.OutlookForWindows|"
    r"\.(pst|ost|nst)\b|\b(outlook|olk)\.exe\b|Microsoft\.Office\.Interop\.Outlook|Outlook\.Application", re.I)

SHELL_TOOLS = {"Bash", "PowerShell"}
FILE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# An agent must never be able to grant itself approval or rewrite the rules that pause it.
PROTECTED = {os.path.normcase(os.path.join(HERE, *p)) for p in (
    ("data", "cc_approvals.json"), ("data", "cc_pending.json"), ("data", "cc_settings.json"),
    ("cc_guard.py",), ("approvals.py",))}
STATE_NAMES = re.compile(r"\bcc_(?:approvals|pending|settings)\.json\b", re.I)
HOME = os.path.expanduser("~")
# Writes stay inside the user's folder; inside it, autostart, credentials and agent configuration still ask.
ALLOWED_ROOTS = [HOME]
SENSITIVE = [os.path.join(HOME, *p) for p in (
    ("AppData", "Roaming", "Microsoft", "Windows", "Start Menu"), (".ssh",), (".codex",), (".claude",),
    ("Documents", "WindowsPowerShell"), ("Documents", "PowerShell"))]


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
    if not any(_inside(path, root) for root in ALLOWED_ROOTS):
        return "approval", "write outside allowed folders"
    if any(_inside(path, place) for place in SENSITIVE):
        return "approval", "change startup, credential or agent settings"
    return None


def outlook_allowed() -> bool:
    # Same switch as worksafe.outlook_allowed(); not imported to keep this hook light. Jarvis's
    # .env reaches it through the environment terminal.py passes to Claude Code.
    return os.getenv("JARVIS_ALLOW_OUTLOOK", "").strip().lower() in ("1", "true", "yes", "on")


def decide(tool: str, tool_input: dict) -> tuple[str, str]:
    """('allow' | 'approval' | 'blocked', detail)."""
    text = json.dumps(tool_input).replace("\\\\", "\\") if tool in SHELL_TOOLS | FILE_TOOLS else ""
    if text and TEAMS_OFF_LIMITS.search(text):
        return "blocked", "Microsoft Teams (its app and data) is off-limits."
    if text and not outlook_allowed() and OUTLOOK_OFF_LIMITS.search(text):
        return "blocked", "Outlook (its app and data) is off-limits."
    if tool in WRITE_TOOLS:
        verdict = _write_verdict(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))
        if verdict:
            return verdict
    if tool in SHELL_TOOLS and STATE_NAMES.search(str(tool_input.get("command", ""))):
        return "blocked", "Jarvis's approval records can't be changed by an agent."
    if tool in SHELL_TOOLS:
        command = str(tool_input.get("command", ""))
        for category, pattern in RISKY.items():
            if pattern.search(command):
                return "approval", category
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
    verdict, detail = decide(tool, tool_input)
    if verdict == "blocked":
        deny(f"BLOCKED: {detail} Don't try another way; tell the user it's off-limits.")
    if verdict == "approval" and not approved(session, detail):
        record_pending(session, detail, str(tool_input.get("command", "")))
        deny(f"PAUSED: this action ({detail}) needs the user's spoken approval first. Do not look for a "
             "workaround. Stop now and make your final message start with 'APPROVAL NEEDED:' followed by "
             "one short spoken sentence saying exactly what you want to do and why.")
    sys.exit(0)  # no decision: bypass-permissions mode lets it run


if __name__ == "__main__":
    main()
