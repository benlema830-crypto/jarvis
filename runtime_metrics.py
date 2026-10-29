"""Bounded timing and GPU workload telemetry. No prompts, speech or audio are stored."""
from collections import deque
from contextlib import contextmanager
import math
import threading
import time

_lock = threading.RLock()
_samples = {}
_active = {}
_turn = None
_sequence = 0
_emit = None
STAGES = {'recognition', 'synthesis', 'accepted', 'first_text', 'first_audio', 'complete'}


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
                 'started': ended_at, 'stages': {}}
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
