"""Configured project identities shared by sessions, handoffs and daily review."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GIANT = "Don't Wake the Giant"
KNIGHT = "KnightShow"  # Sir Wendell AI comedy series (content workflow agents)
PROJECTS = {'Jarvis': ROOT, 'Rocket Frontier': Path.home() / 'Documents' / 'Rocket Frontier',
            GIANT: Path.home() / 'Documents' / GIANT, KNIGHT: Path.home() / 'Documents' / KNIGHT}
DEFAULT_SESSIONS = {'Jarvis': 'Jarvis Builder', 'Rocket Frontier': 'Frontier', GIANT: 'Giant Builder', KNIGHT: 'KnightShow'}
MIGRATIONS = ROOT / 'data' / 'session-project-migrations.json'


def normalize(name):
    return ' '.join(str(name).strip().casefold().replace('’', "'").split())


def canonical(name):
    key = normalize(name)
    aliases = {'frontier': 'Rocket Frontier', 'jarvis brain': 'Jarvis', 'jarvis blue': 'Jarvis',
               'dont wake the giant': GIANT, 'knight show': KNIGHT, 'knight series': KNIGHT,
               'knight comedy series': KNIGHT, 'sir wendell': KNIGHT, 'content workflow': KNIGHT,
               'content workflow agents': KNIGHT}
    for project in PROJECTS:
        if normalize(project) == key:
            return project
    if key in aliases:
        return aliases[key]
    raise ValueError('Configured projects are ' + ', '.join(PROJECTS) + '.')


def migrate_sessions(entries):
    """Reassign explicitly approved saved sessions; retain thread/history verbatim.

    The expected thread and old project prevent applying a stale migration to a
    different session that later reuses the same name. No worker starts here.
    """
    try:
        migrations = json.loads(MIGRATIONS.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return False
    changed = False
    for key, migration in migrations.items():
        entry = entries.get(key)
        if (not entry or entry.get('thread_id') != migration['thread_id']
                or entry.get('project') != migration['from_project']):
            continue
        project = canonical(migration['project'])
        folder = PROJECTS[project]
        if not folder.is_dir():
            raise ValueError('Migration destination folder is missing: ' + project)
        entry.update(project=project, cwd=str(folder))
        changed = True
    return changed
