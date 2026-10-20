"""Claude Code PreToolUse hook for Jarvis's terminal tasks (see terminal.py).

Claude Code runs this before every tool call. It reads the call as JSON on stdin and:
  - lets ordinary work run (Claude Code is in bypass-permissions mode),
  - blocks risky actions - deleting, installing/uninstalling software, changing system
    settings - until the user has approved that kind of action out loud,
  - always blocks Outlook and Teams data, which are off-limits.

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
    "delete": re.compile(
        r"\b(Remove-Item|rm|rmdir|rd|del|erase|Clear-RecycleBin|Clear-Content)\b|\bri\s|"
        r"\[(System\.)?IO\.(File|Directory)\]::Delete|\.Delete\(|shred|git\s+clean", re.I),
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
# Outlook and Teams apps and data: never, approval or not
OFF_LIMITS = re.compile(
    r"\\Microsoft\\(Outlook|Teams|Olk)\b|\\Packages\\(MSTeams|Microsoft\.OutlookForWindows)|"
    r"\.(pst|ost|nst)\b|\b(outlook|olk|ms-teams|msteams|teams)\.exe\b|Microsoft\.Office\.Interop\.Outlook|"
    r"Outlook\.Application", re.I)

SHELL_TOOLS = {"Bash", "PowerShell"}
FILE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep"}


def decide(tool: str, tool_input: dict) -> tuple[str, str]:
    """('allow' | 'approval' | 'blocked', detail)."""
    text = json.dumps(tool_input) if tool in SHELL_TOOLS | FILE_TOOLS else ""
    if text and OFF_LIMITS.search(text.replace("\\\\", "\\")):
        return "blocked", "Outlook and Microsoft Teams (their apps and data) are off-limits."
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
