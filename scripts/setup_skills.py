"""Install the agent skills that Jarvis's background agents and coding sessions use.

    .venv\\Scripts\\python.exe scripts\\setup_skills.py            install or update
    .venv\\Scripts\\python.exe scripts\\setup_skills.py --check    say what is installed
    .venv\\Scripts\\python.exe scripts\\setup_skills.py --remove   take them out again

A skill is a folder with a SKILL.md: instructions an agent loads when a task matches its description. They go in
  - ~/.claude/skills    Claude Code: terminal agents (terminal.py) and coding sessions
  - ~/.agents/skills    Codex: project agents (agent_sessions.py)
  - the Linux sandbox   the text-only coding skills, for unattended Claude agents (wsl_sandbox.py)
The talking brain loads none of them (claude_code_brain.py starts with setting_sources=[]).

Agents run with permissions bypassed, so a skill is something they will follow. Every skill below is pinned to the
commit that was read before it was added (2026-11-15); to take a newer one, read it first, then change the commit.
Left out on purpose:
  - Impeccable's engine: a downloaded program that reports usage and checks for updates. Only its guidance is
    installed, and the skill's own "launcher unavailable" path covers that.
  - mcp-builder's evaluation scripts: they bill the Anthropic API.
A folder this script did not install (no .jarvis-skill.json in it) is never replaced or removed.
"""
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CLAUDE = Path.home() / ".claude" / "skills"
CODEX = Path.home() / ".agents" / "skills"
SANDBOX_SKILLS = "/home/agent/.claude/skills"
MARKER = ".jarvis-skill.json"
FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

NO_ENGINE = ("Jarvis note: the engine launcher (scripts/) is not installed here, on purpose: it downloads a program "
             "that reports usage. Skip Setup step 1 and follow \"Launcher unavailable\" below; do not download it.")
NO_EVALUATION = ("Jarvis note: scripts/ (evaluation.py) is not installed here, on purpose: it bills the Anthropic "
                 "API. Write the evaluation questions, and leave running them to the owner.")

# repo -> (commit that was read, skills). A skill: name, folder in the repo ("" = the repo root), and optionally
# codex_folder (a Codex-worded copy), skip (names left out at the top of the folder), note, sandbox (text only).
SOURCES = {
    "obsidianmd/obsidian-skills": ("398127736bd4ba42d767b1419fee1a927508370b", [
        {"name": "obsidian-markdown", "folder": "plugins/obsidian/skills/obsidian-markdown", "sandbox": True},
        {"name": "obsidian-bases", "folder": "plugins/obsidian/skills/obsidian-bases"},
        {"name": "json-canvas", "folder": "plugins/obsidian/skills/json-canvas"},
        {"name": "obsidian-cli", "folder": "plugins/obsidian/skills/obsidian-cli"},
        {"name": "defuddle", "folder": "plugins/obsidian/skills/defuddle"},
    ]),
    "blader/humanizer": ("b48c832f0f809c1b5658edbb838c2521b72f2413", [
        {"name": "humanizer", "folder": "", "sandbox": True, "only": ("SKILL.md", "LICENSE")},
    ]),
    "DietrichGebert/ponytail": ("96608e078b2d5ea607c5c3b8b5a54d1c1fba6846", [
        {"name": "ponytail", "folder": "skills/ponytail", "sandbox": True},
        {"name": "ponytail-review", "folder": "skills/ponytail-review", "sandbox": True},
        {"name": "ponytail-audit", "folder": "skills/ponytail-audit", "sandbox": True},
        {"name": "ponytail-debt", "folder": "skills/ponytail-debt", "sandbox": True},
    ]),
    "pbakaus/impeccable": ("2b86d9c07b97d4bed7de23583e1bd1e58dd2baae", [
        {"name": "impeccable", "folder": ".claude/skills/impeccable", "codex_folder": ".agents/skills/impeccable",
         "skip": ("scripts",), "note": NO_ENGINE},
    ]),
    "addyosmani/agent-skills": ("39b723ceebf81474d0557c1fecd01eddab585563", [
        {"name": "debugging-and-error-recovery", "folder": "skills/debugging-and-error-recovery", "sandbox": True},
        {"name": "test-driven-development", "folder": "skills/test-driven-development", "sandbox": True},
    ]),
    "anthropics/skills": ("1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064", [
        {"name": "mcp-builder", "folder": "skills/mcp-builder", "skip": ("scripts",), "note": NO_EVALUATION},
        {"name": "webapp-testing", "folder": "skills/webapp-testing"},
    ]),
}


def git(*arguments, cwd):
    done = subprocess.run(["git", *arguments], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300, stdin=subprocess.DEVNULL, creationflags=FLAGS)
    return done.returncode, (done.stdout + done.stderr).strip()


def fetch(repo, commit, into):
    """The repo at exactly that commit, in a new folder under `into`."""
    folder = Path(into) / repo.replace("/", "_")
    folder.mkdir(parents=True)
    for arguments in (("init", "-q"), ("fetch", "-q", "--depth", "1", f"https://github.com/{repo}", commit),
                      ("-c", "advice.detachedHead=false", "checkout", "-q", "FETCH_HEAD")):
        code, output = git(*arguments, cwd=folder)
        if code:
            raise RuntimeError(f"{repo}: git {arguments[0]} failed: {output[-300:]}")
    if git("rev-parse", "HEAD", cwd=folder)[1] != commit:
        raise RuntimeError(f"{repo}: got a different commit than the one that was read")
    return folder


def with_note(text, note):
    """SKILL.md with a note placed straight after its frontmatter, where the agent reads it first."""
    parts = text.split("---", 2)
    if len(parts) == 3 and not parts[0].strip():
        return f"---{parts[1]}---\n\n> {note}\n{parts[2]}"
    return f"> {note}\n\n{text}"


def ours(folder):
    return (Path(folder) / MARKER).is_file()


def install(source, target, repo, commit, skill):
    """Copy one skill into place. "" when done, or why it was left alone."""
    source, target = Path(source), Path(target)
    if not (source / "SKILL.md").is_file():
        return f"no SKILL.md in {repo}/{skill.get('folder', '')}"
    if target.exists() and not ours(target):
        return "a folder of that name is already there and isn't Jarvis's; left alone"
    if target.exists():
        shutil.rmtree(target)
    left_out = {".git", *skill.get("skip", ())}
    only = skill.get("only")
    shutil.copytree(source, target, ignore=lambda _folder, names: [
        name for name in names if name in left_out or (only and _folder == str(source) and name not in only)])
    if skill.get("note"):
        page = target / "SKILL.md"
        page.write_text(with_note(page.read_text(encoding="utf-8"), skill["note"]), encoding="utf-8")
    (target / MARKER).write_text(json.dumps({"repo": repo, "commit": commit}), encoding="utf-8")
    return ""


def remove(target):
    """Take out a skill this script installed. True when it did."""
    if ours(target):
        shutil.rmtree(target)
        return True
    return False


def skills():
    return [(repo, commit, skill) for repo, (commit, found) in SOURCES.items() for skill in found]


def to_sandbox(names):
    """Copy the named skills from ~/.claude/skills into the Linux sandbox. "" when done, or why not."""
    import wsl_sandbox
    if wsl_sandbox.DISTRO not in wsl_sandbox.distros():
        return "no sandbox on this PC"
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz") as archive:
        for name in names:
            archive.add(CLAUDE / name, arcname=name)
    script = f'mkdir -p {SANDBOX_SKILLS} && cd {SANDBOX_SKILLS} && rm -rf {" ".join(names)} && tar -xzf -'
    try:
        done = subprocess.run(["wsl.exe", "-d", wsl_sandbox.DISTRO, "-u", "agent", "-e", "sh", "-c", script],
                              input=packed.getvalue(), capture_output=True, timeout=120, creationflags=FLAGS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    return "" if done.returncode == 0 else done.stderr.decode("utf-8", "replace").strip()[-300:]


def check():
    for _repo, commit, skill in skills():
        where = [label for label, home in (("Claude Code", CLAUDE), ("Codex", CODEX))
                 if ours(home / skill["name"])
                 and json.loads((home / skill["name"] / MARKER).read_text(encoding="utf-8")).get("commit") == commit]
        print(f"  {skill['name']:<30} {' + '.join(where) or 'not installed'}")


def main():
    if "--check" in sys.argv:
        return check()
    if "--remove" in sys.argv:
        gone = [skill["name"] for _repo, _commit, skill in skills()
                if [remove(home / skill["name"]) for home in (CLAUDE, CODEX)].count(True)]
        return print("removed: " + (", ".join(gone) or "nothing"))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    problems, for_sandbox = [], []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
        for repo, (commit, found) in SOURCES.items():
            try:
                source = fetch(repo, commit, work)
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                problems.append(str(error))
                continue
            for skill in found:
                for home, folder in ((CLAUDE, skill["folder"]), (CODEX, skill.get("codex_folder", skill["folder"]))):
                    home.mkdir(parents=True, exist_ok=True)
                    problem = install(source / folder, home / skill["name"], repo, commit, skill)
                    if problem:
                        problems.append(f"{skill['name']} ({home}): {problem}")
                if skill.get("sandbox") and ours(CLAUDE / skill["name"]):
                    for_sandbox.append(skill["name"])
    check()
    problem = to_sandbox(for_sandbox)
    print(f"  sandbox: {problem or ', '.join(for_sandbox)}")
    for problem in problems:
        print("  PROBLEM: " + problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
