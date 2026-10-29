"""Persistent pacing controls. Read at phrase/turn boundaries, never in audio callbacks."""
import json
import threading
import time
from pathlib import Path
from filelock import FileLock

STORE = Path(__file__).resolve().parent / 'data' / 'conversation-settings.json'
DEFAULTS = {'pause_seconds': 1.2, 'followup_seconds': 12, 'first_clause_chars': 85}
LIMITS = {'pause_seconds': (.6, 2.5), 'followup_seconds': (0, 45), 'first_clause_chars': (40, 200)}
_lock = threading.Lock()
_cache = (0., None)


def validate(values):
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError('Unknown conversation setting.')
    for key, value in values.items():
        low, high = LIMITS[key]
        if type(value) not in (float, int) or not low <= value <= high:
            raise ValueError(f'{key} must be between {low} and {high}.')
    return values


def read():
    global _cache
    with _lock:
        if _cache[1] is not None and time.monotonic() - _cache[0] < 2:
            return dict(_cache[1])
        try:
            values = dict(DEFAULTS, **validate(json.loads(STORE.read_text(encoding='utf-8'))))
        except (OSError, ValueError, TypeError):
            values = dict(DEFAULTS)
        _cache = (time.monotonic(), values)
        return dict(values)


def update(values):
    global _cache
    validate(values)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(STORE) + '.lock'):
        with _lock:
            _cache = (0., None)
        merged = dict(read(), **values)
        temporary = STORE.with_suffix('.tmp')
        temporary.write_text(json.dumps(merged, indent=2), encoding='utf-8')
        temporary.replace(STORE)
        with _lock:
            _cache = (time.monotonic(), merged)
    return merged
