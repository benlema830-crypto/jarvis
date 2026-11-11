"""Where the owner is, for two decisions: may Jarvis text them, and is anyone there to hear him speak.

The owner's rule for texts (2026-11-11): "i only want jarvis to respond over text if im not in my room aka phone
location and or bedroom sensor for more then 30 minutes, or i text him myself". So Jarvis starts a text only when
they are out of the room:
  - their phone is away from home (Home Assistant's person tracker), or
  - the bedroom presence sensor has been clear for thirty minutes and the PC hasn't been touched in that time.
The PC counts because the desk sits in the sensor's blind spot (see presence_greeting.py). Replying to a message
they sent is not decided here: that always goes back the way it came.

The sensor loses someone lying still, so "clear for thirty minutes" can also be them asleep in bed. Texts are
silent, so that mistake is cheap; speaking is not, which is why can_hear() never trusts the sensor at night.
"""
import datetime
import threading
import time

import presence_greeting

OUT_SECONDS = 30 * 60
CACHE_SECONDS = 20
_lock = threading.Lock()
_cache = {}


def _read(entity):
    """A Home Assistant state, or None when it can't be read. Cached briefly: several texts can be decided at once."""
    import testing_guard
    if testing_guard.under_test():
        return None  # a test supplies its own; the real house isn't asked
    with _lock:
        at, state = _cache.get(entity, (0, None))
        if time.time() - at < CACHE_SECONDS:
            return state
    try:
        import home_assistant
        state = home_assistant._api('GET', f'/api/states/{entity}')
        state = state if isinstance(state, dict) else None
    except Exception:
        state = None
    with _lock:
        _cache[entity] = (time.time(), state)
    return state


def _idle():
    try:
        import activity
        return activity._idle_seconds()
    except Exception:
        return None


def _value(state):
    value = (state or {}).get('state')
    return None if value in (None, 'unknown', 'unavailable') else value


def _seconds_in_state(state, now):
    try:
        return now - datetime.datetime.fromisoformat(state['last_changed']).timestamp()
    except (KeyError, TypeError, ValueError):
        return None


def out_of_room(idle_seconds=None, now=None) -> bool:
    """True when the owner has left the room, so a text is the way to reach them."""
    now = now or time.time()
    idle = _idle() if idle_seconds is None else idle_seconds
    phone = _value(_read(presence_greeting.PERSON))
    if phone is not None and phone != 'home':
        return True  # away from home, whatever the PC says: they may be using it by remote desktop
    if idle is not None and idle < OUT_SECONDS:
        return False  # at the desk within the half hour
    sensor = _read(presence_greeting.SENSOR)
    occupied = _value(sensor)
    if occupied is None:
        return True  # the house can't say, and the PC has sat untouched: a text is the safer miss
    if occupied == 'on':
        return False
    clear_for = _seconds_in_state(sensor, now)
    return clear_for is None or clear_for >= OUT_SECONDS


def can_hear(now=None) -> bool:
    """True when the sensor shows someone in the room right now, in waking hours, with their phone at home. For
    saying an update aloud to someone in the room who isn't at the PC."""
    moment = datetime.datetime.fromtimestamp(now) if now else datetime.datetime.now()
    if presence_greeting.quiet(moment):
        return False
    if _value(_read(presence_greeting.PERSON)) not in (None, 'home'):
        return False
    return _value(_read(presence_greeting.SENSOR)) == 'on'


def describe(now=None) -> str:
    """One line of facts for self_check: what the sensors say, and so whether Jarvis would speak or text."""
    now = now or time.time()
    idle = _idle()
    phone, sensor = _read(presence_greeting.PERSON), _read(presence_greeting.SENSOR)
    seen = {"on": "sees someone", "off": "clear"}.get(_value(sensor), "not readable")
    since = _seconds_in_state(sensor, now)
    if _value(sensor) and since is not None:
        seen += f" for {int(since // 60)} minutes"
    facts = (f"phone {_value(phone) or 'not readable'}; bedroom sensor {seen}; "
             f"PC last used {'unknown' if idle is None else f'{int(idle // 60)} minutes ago'}")
    if out_of_room(idle, now):
        return f"The owner is out of their room ({facts}): a question or away-work news is texted, updates are held."
    hears = "updates are spoken" if can_hear(now) or (idle is not None and idle < 300) else "updates are held until they are back at the PC"
    return f"The owner counts as in their room ({facts}): nothing is texted unless they text first, and {hears}."

