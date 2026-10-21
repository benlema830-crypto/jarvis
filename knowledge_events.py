"""Bounded source events derived only from actual knowledge tool results."""
import json


def result_event(name, content, failed=False):
    if name not in ('search_knowledge', 'read_knowledge_note'):
        return None
    sources = []
    try:
        value = json.loads(content) if isinstance(content, str) else content
        notes = value if name == 'search_knowledge' else [value]
        if not isinstance(notes, list):
            raise ValueError()
        for note in notes[:8]:
            if not isinstance(note, dict) or not isinstance(note.get('path'), str):
                continue
            path = note['path'][:500]
            sources.append({'id': 'note:' + path, 'path': path,
                'title': str(note.get('title', path))[:200],
                'excerpt': str(note.get('excerpt', note.get('content', '')))[:1200],
                'uri': str(note.get('uri', ''))[:2000]})
    except (ValueError, TypeError):
        failed = True
    return {'sources': [] if failed else sources,
            'status': 'unavailable' if failed else 'found' if sources else 'empty'}
