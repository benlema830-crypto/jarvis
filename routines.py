"""Small named routines. Every execution requires a fresh, exact-step review."""
import copy
import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

import project_memory

STORE = Path(__file__).resolve().parent / 'data' / 'routines.json'
LOCK = threading.RLock()
RUN_LOCK = threading.Lock()
CANCEL = threading.Event()
REVIEWS = {}
DEFAULTS = {
    'Development mode': {'project': 'Rocket Frontier', 'steps': [
        {'action': 'open_project'}, {'action': 'project_status'}, {'action': 'tasks'},
        {'action': 'focus', 'app': 'RobloxStudioBeta.exe', 'minutes': 30}]},
    'Wrap up': {'project': 'Rocket Frontier', 'steps': [
        {'action': 'project_status'}, {'action': 'tasks'}, {'action': 'handoff'}]},
}


def validate(name, definition):
    if not isinstance(name, str) or not re.fullmatch(r'[\w -]{1,60}', name):
        raise ValueError('Use a short routine name with letters, numbers, spaces or hyphens.')
    if not isinstance(definition, dict) or set(definition) != {'project', 'steps'}:
        raise ValueError('A routine contains project and steps only.')
    project_memory.project(definition['project'])
    steps = definition['steps']
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ValueError('Choose 1–8 routine steps.')
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError('Each step must be an object.')
        action = step.get('action')
        if action not in {'open_project', 'project_status', 'tasks', 'focus', 'handoff'}:
            raise ValueError('Unknown routine step. Shell commands are not supported.')
        if set(step) != ({'action', 'app', 'minutes'} if action == 'focus' else {'action'}):
            raise ValueError('Unexpected routine step fields.')
        if action == 'focus' and (not isinstance(step['app'], str) or
                not re.fullmatch(r'[\w .()-]{1,80}\.exe', step['app'], re.ASCII | re.I) or
                type(step['minutes']) is not int or not 1 <= step['minutes'] <= 120):
            raise ValueError('Focus needs an executable name and 1–120 minutes.')
    return copy.deepcopy(definition)


def catalog():
    with LOCK:
        try:
            raw = json.loads(STORE.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raw = copy.deepcopy(DEFAULTS)
        if not isinstance(raw, dict):
            raise ValueError('The saved routine catalog must be an object.')
        return {name: validate(name, definition) for name, definition in raw.items()}


def save(name, definition):
    definition = validate(name, definition)
    with LOCK:
        all_routines = catalog()
        all_routines[name] = definition
        if len(all_routines) > 30:
            raise ValueError('At most 30 named routines.')
        STORE.parent.mkdir(parents=True, exist_ok=True)
        temp = STORE.with_suffix('.tmp')
        temp.write_text(json.dumps(all_routines, indent=2), encoding='utf-8')
        temp.replace(STORE)
        REVIEWS.clear()
        return {'saved': name, 'requires_review': True}


def _digest(definition):
    return hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()


def preview(name):
    if not isinstance(name, str):
        raise ValueError('Choose a routine name.')
    with LOCK:
        definition = catalog().get(name)
        if definition is None:
            raise ValueError('Unknown routine.')
        token = uuid.uuid4().hex
        now = time.monotonic()
        for old in list(REVIEWS):
            if REVIEWS[old]['expires'] < now:
                REVIEWS.pop(old)
        if len(REVIEWS) >= 100:
            REVIEWS.pop(next(iter(REVIEWS)))
        REVIEWS[token] = dict(name=name, definition=definition, expires=now+300)
        descriptions = []
        for step in definition['steps']:
            descriptions.append({
                'open_project': 'Open the project folder in Explorer.',
                'project_status': 'Read Git state, project notes and the last handoff.',
                'tasks': 'Read your vault task list.',
                'focus': f"Start {step.get('minutes')} minutes of Focus on {step.get('app')} (app names only; spoken drift reminders).",
                'handoff': 'Save a dated evidence snapshot and unfinished-task checklist in local Jarvis data.'
            }[step['action']])
        return dict(name=name, project=definition['project'], steps=definition['steps'],
                    descriptions=descriptions, token=token, expires_in=300,
                    notice='Approve and run these steps once. Completed steps are not undone if a later step fails.')


def execute_step(step, project):
    action = step['action']
    if action == 'open_project':
        _, root = project_memory.project(project)
        if not root.is_dir():
            raise ValueError('Project folder unavailable.')
        os.startfile(str(root))
        return {'opened': str(root)}
    if action == 'project_status':
        return project_memory.status(project)
    if action in {'tasks', 'handoff'}:
        import tasks
        pending = [t['text'] for t in tasks.items() if not t['done']]
        if action == 'tasks':
            return {'pending_tasks': pending, 'source': 'Tasks.md (all projects)'}
        return project_memory.handoff(project,
            summary='Session wrap-up: see dated Git evidence and attributed reports below.',
            unresolved='Project blockers need review. Unfinished vault tasks (all projects):\n' + '\n'.join(pending)[:5000],
            next_action='Review the latest project handoff and choose the next unfinished project task.')
    if action == 'focus':
        from visual_modes import controller
        return controller.start('focus', step['minutes'], step['app'])
    raise ValueError('Unknown step.')


def run(token):
    if not isinstance(token, str):
        raise ValueError('A review token is required.')
    if not RUN_LOCK.acquire(blocking=False):
        raise ValueError('A routine is already running.')
    try:
        with LOCK:
            CANCEL.clear()
            review = REVIEWS.pop(token, None)
            if not review or review['expires'] < time.monotonic():
                raise ValueError('Review expired or already used. Review the steps again.')
            current = catalog().get(review['name'])
            if _digest(current) != _digest(review['definition']):
                raise ValueError('Routine changed. Review the new steps.')
        results = []
        for step in review['definition']['steps']:
            if CANCEL.is_set():
                return {'name': review['name'], 'status': 'cancelled', 'steps': results}
            try:
                results.append({'action': step['action'], 'status': 'completed',
                                'result': execute_step(step, review['definition']['project'])})
            except Exception as error:
                results.append({'action': step['action'], 'status': 'failed', 'error': str(error)})
                return {'name': review['name'], 'status': 'stopped', 'steps': results}
        return {'name': review['name'], 'status': 'completed', 'steps': results}
    finally:
        RUN_LOCK.release()


def cancel():
    with LOCK:
        CANCEL.set()
        REVIEWS.clear()
    return {'status': 'stop_requested', 'message': 'No further steps will start. Completed steps are not undone.'}
