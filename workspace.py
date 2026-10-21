"""Curated local destinations; the browser never supplies arbitrary paths."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HUB = Path.home() / 'Documents' / 'Jarvis Agent'
DESTINATIONS = {
    'home': ('Workspace', 'All your JARVIS files in one place', HUB),
    'launchers': ('Launchers', 'Brain, classic assistants, and developer tools', HUB / '01 Launchers'),
    'knowledge': ('Knowledge vault', 'Your Obsidian notes and project decisions', HUB / '02 Knowledge'),
    'development': ('Development', 'Blue, Orange, and LocalVoice source folders', HUB / '03 Development'),
    'plans': ('Build plans', 'The current bedtime brief and future milestones', HUB / '04 Plans'),
    'reports': ('Build reports', 'Results and handoffs from completed agent tasks', HUB / '05 Reports'),
    'references': ('References', 'Video screenshots and earlier UI previews', HUB / '06 References'),
}


def catalog():
    return [{'id': key, 'name': name, 'description': description, 'path': str(path),
             'available': path.is_dir()} for key, (name, description, path) in DESTINATIONS.items()]


def open_folder(key):
    if key not in DESTINATIONS:
        raise ValueError('Choose a listed workspace folder.')
    path = DESTINATIONS[key][2]
    if not path.is_dir():
        raise ValueError('The folder is not available.')
    os.startfile(str(path))
    return {'opened': key}
