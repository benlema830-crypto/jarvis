"""Notices when the PC was asleep, so a request made before it slept isn't carried out after it wakes.

2026-11-12: "pause everything, I'm going to bed" was still waiting on the local model when the PC went to sleep at
00:44. The turn picked up where it left off when the PC woke for the 06:40 alarm, said "understood" to a sleeping
room and put the PC back to sleep five minutes before the alarm, which then never rang.

A thread ticks every few seconds. When the wall clock has jumped far past one tick, the PC was suspended (or frozen)
for that long. Nothing here needs Windows power events, so it also works when started hidden.
"""
import threading
import time

TICK = 5
GAP = 90            # the clock moved this much during one tick: asleep, not just busy
STALE = 300         # a turn that slept through this long is no longer what the owner wants now
_naps = []          # (woke at, seconds asleep), oldest first
_lock = threading.Lock()
_started = False
_last_tick = 0.0    # wall-clock time of the watcher's latest tick


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_watch, daemon=True, name="suspend-watch").start()


def _watch():
    global _last_tick
    _last_tick = time.time()
    while True:
        time.sleep(TICK)
        now = time.time()
        note(_last_tick, now)
        _last_tick = now


def note(last, now):
    """One tick: `last` and `now` are the wall-clock times either side of it."""
    if now - last >= GAP:
        with _lock:
            _naps.append((now, now - last))
            del _naps[:-20]


def slept_since(when):
    """Seconds the PC spent asleep after `when` (a wall-clock time). 0 when it stayed awake."""
    with _lock:
        asleep = sum(length for woke, length in _naps if woke > when)
    # Just woken: the watcher may not have ticked yet, and the first tool call can beat it. Only for a turn
    # that began before that last tick; one begun since the PC woke has slept through nothing.
    unseen = time.time() - _last_tick if _last_tick and when <= _last_tick + TICK else 0
    return asleep + (unseen if unseen >= GAP else 0)


def stale(turn_began):
    """The PC slept long enough during this turn that acting on it now would be acting on old words."""
    return bool(turn_began) and slept_since(turn_began) >= STALE


def describe(seconds):
    minutes = round(seconds / 60)
    if minutes < 90:
        return f"about {max(minutes, 1)} minute{'s' if minutes != 1 else ''}"
    return f"about {round(minutes / 60)} hours"
