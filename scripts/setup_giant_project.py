"""Apply the user-approved Giant project folder/note setup; never edit the place.

Run only with filesystem authorization for the Documents workspace and vault.
The --complete-task step is separate and is used only after verification.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from project_catalog import GIANT, PROJECTS

FOLDER = PROJECTS[GIANT]
PLACE = Path.home() / 'OneDrive/Documents/Dont Wake the Giant v2.rbxl'
VAULT = Path.home() / 'Documents/JARVIS Knowledge'
TASK = "After the noise meter finishes, have Jarvis Builder add Don't Wake the Giant as its own project with its own folder"
FILES = {
    'AGENTS.md': """# Don't Wake the Giant project instructions

- This is a separate Roblox project, not Rocket Frontier. Do not edit Rocket Frontier files or places.
- Read PROJECT-HANDOFF.txt before work. Treat saved agent reports as claims, not verified game state.
- The existing place is referenced in README.txt. Setup did not copy, move, import or modify it.
- Inspect the intended Roblox Studio session/place before game changes; never assume the active place belongs to this project.
- Keep future source, backups and verification in this project folder. Follow the user's current scope and approval requirements.
- Do not publish, purchase assets, delete data or overwrite the original place without explicit authorization.
""",
    'README.txt': f"""DON'T WAKE THE GIANT

Independent Jarvis project workspace: {FOLDER}
Existing Roblox Studio place (reference only): {PLACE}

User-provided premise: sneak into a sleeping giant's kitchen, collect five golden
eggs, and escape. The game uses a shared noise meter.

This setup registers the project and keeps Giant Builder's existing Codex thread.
No game implementation, playtest, place import, or publication is performed here.
Source/build workflow has not yet been established. Do not use Rocket Frontier's
fresh/ directory or its build scripts for this game.
""",
    'PROJECT-HANDOFF.txt': f"""Project: {GIANT}
Date: 2026-11-02

Workspace created and registered separately from Jarvis and Rocket Frontier.
Giant Builder is assigned here using its original saved Codex thread ID, task,
report and timeline. Old thread messages may mention Rocket Frontier because that
was the previous workspace; this project identity supersedes those old paths.

Reference place: {PLACE}
The original binary remains at that path and has not been edited or copied.
Game premise: sleeping giant's kitchen, five golden eggs, escape, shared noise.

No game code was changed or game behavior verified in this setup. Next game work
must begin by inspecting the correct Studio session and existing source, when
requested. Project reports/handoffs must use Don't Wake the Giant going forward.
""",
}
NOTE = f"""# Don't Wake the Giant

Independent Roblox game project. Sneak into a sleeping giant's kitchen, collect
five golden eggs, and escape; shared noise meter (user-provided game description).

Workspace: `{FOLDER}`
Existing place reference: `{PLACE}`
Agent session: **Giant Builder**, retaining its saved Codex conversation thread.

Select **Don't Wake the Giant** for agent sessions, project handoffs and daily
review. Setup did not import game code, alter the place, or edit Rocket Frontier.
Progress belongs in this project's handoffs and normal Journal/Reports notes.

See [[Projects/JARVIS]] for the assistant project.
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--complete-task', action='store_true')
    args = p.parse_args()
    if args.complete_task:
        # Match one exact checkbox; do not fuzzy-match or rewrite other tasks.
        path = VAULT / 'Tasks.md'
        raw = path.read_bytes()
        old = ('- [ ] ' + TASK).encode()
        if raw.count(old) != 1:
            raise ValueError('Expected exactly one matching open task; inspect Tasks.md.')
        backup = ROOT / 'data/reports/giant-project-tasks-before.md'
        if not backup.exists(): backup.write_bytes(raw)
        path.write_bytes(raw.replace(old, ('- [x] ' + TASK).encode(), 1))
        print('Checked off the exact Giant project setup task; other bytes preserved.')
        return
    stat = PLACE.stat()
    before = (stat.st_size, stat.st_mtime_ns)
    targets = {FOLDER / name: text for name, text in FILES.items()}
    targets[VAULT / 'Projects' / (GIANT + '.md')] = NOTE
    for path, text in targets.items():
        if path.exists() and path.read_text(encoding='utf-8') != text:
            raise ValueError('Existing file differs; refusing to overwrite: ' + str(path))
    for path, text in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists(): path.write_text(text, encoding='utf-8')
    after = PLACE.stat()
    assert before == (after.st_size, after.st_mtime_ns)
    print(json.dumps({'workspace': str(FOLDER), 'files': [str(p) for p in targets],
                      'place_size_and_mtime_unchanged': True}, indent=2))


if __name__ == '__main__':
    main()
