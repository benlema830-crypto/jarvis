"""Bounded timing and GPU workload telemetry. No prompts, speech or audio are stored."""
from collections import deque
from contextlib import contextmanager
import json
import math
import sys
from pathlib import Path
import threading
import time

_lock = threading.RLock()
_samples = {}
_active = {}
_turn = None
_sequence = 0
_emit = None
STAGES = {'recognition', 'synthesis', 'accepted', 'first_text', 'first_audio', 'complete'}
# One line per finished turn: when each stage happened (ms after the end of speech or the keypress)
# and which tools ran, with whether each worked. No words are stored.
LOG = DEFAULT_LOG = Path(__file__).resolve().parent / 'data' / 'turn_stages.jsonl'
KEEP = 5000


def bind(emit):
    global _emit
    _emit = emit


def begin_turn(ended_at=None, source='keyboard'):
    global _turn, _sequence
    now = time.monotonic()
    if type(ended_at) not in (int, float) or not math.isfinite(ended_at) or not 0 <= now-ended_at < 120:
        ended_at = now
    with _lock:
        _sequence += 1
        _turn = {'id': _sequence, 'source': source if source in {'voice', 'keyboard'} else 'keyboard',
                 'started': ended_at, 'stages': {}, 'tools': []}
    mark('accepted')
    return _sequence


def mark(stage):
    if stage not in STAGES:
        raise ValueError('Unknown timing stage.')
    with _lock:
        if _turn is None or stage in _turn['stages'] or 'complete' in _turn['stages']:
            return
        elapsed = max(0, time.monotonic()-_turn['started'])
        _turn['stages'][stage] = round(elapsed*1000, 1)
        _samples.setdefault(stage, deque(maxlen=60)).append(elapsed*1000)
        row = _row() if stage == 'complete' else None
    if row:
        _save(row)


def note_tool(name, ok, seconds, status=None):
    """A tool finished during the current turn (called from tools.run_tool)."""
    with _lock:
        if _turn is not None and 'complete' not in _turn['stages'] and len(_turn['tools']) < 200:
            entry = {'name': str(name)[:60], 'ok': bool(ok), 'ms': round(seconds*1000),
                     'at': round(max(0, time.monotonic()-_turn['started'])*1000)}
            if status:
                entry['receipt'] = status  # confirmed / sent / waiting / unknown / failed (truth_guard)
            _turn['tools'].append(entry)


def _row():
    return {'t': round(time.time(), 2), 'source': _turn['source'], 'stages': dict(_turn['stages']),
            'tools': list(_turn['tools'])}


def _under_test():
    spec = getattr(sys.modules.get('__main__'), '__spec__', None)
    return bool(spec and spec.name.startswith('unittest'))


def _save(row):
    if LOG == DEFAULT_LOG and _under_test():
        return
    try:
        with _lock:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(row) + '\n')
            if LOG.stat().st_size > KEEP * 400:
                lines = LOG.read_text(encoding='utf-8').splitlines()[-KEEP:]
                LOG.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    except OSError:
        pass


@contextmanager
def work(stage):
    if stage not in {'recognition', 'synthesis'}:
        raise ValueError('Unknown workload.')
    started = time.monotonic()
    with _lock:
        _active[stage] = _active.get(stage, 0) + 1
    _publish()
    try:
        yield
    finally:
        with _lock:
            _active[stage] = max(0, _active.get(stage, 1)-1)
            _samples.setdefault(stage, deque(maxlen=60)).append((time.monotonic()-started)*1000)
        _publish()


def _publish():
    if _emit:
        try:
            _emit('resources', active=snapshot()['active'])
        except Exception:
            pass


def snapshot():
    with _lock:
        stages = {}
        for name, samples in _samples.items():
            ordered = sorted(samples)
            stages[name] = {'last_ms': round(samples[-1], 1), 'median_ms': round(ordered[len(ordered)//2], 1),
                            'p95_ms': round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 1), 'samples': len(samples)}
        return {'active': [k for k, count in _active.items() if count], 'timings': stages,
                'turn': {k: (dict(v) if isinstance(v, dict) else v) for k, v in _turn.items() if k != 'started'} if _turn else None}
