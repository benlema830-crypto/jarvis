"""Weekday wake-up at 6:40: an alarm tone on the bedroom speaker, then Jarvis's morning briefing.

Turns the box fan off, starts Spotify once the briefing ends, then checks back every few minutes while the owner is still in bed, and stops
the moment they talk to Jarvis, touch the PC, or leave the room. Home Assistant wakes the PC a few
minutes early (automation "Jarvis: wake the PC for the morning alarm"), so this runs on the PC.
"""
import datetime
import json
import os
import threading
import time
from pathlib import Path

import presence_greeting

WAKE_AT = datetime.time.fromisoformat(os.getenv('JARVIS_WAKE_AT', '06:40'))  # override only for a rehearsal
DAYS = range(0, 5)               # Monday-Friday
LATE_LIMIT_MINUTES = 30          # PC woke later than this: skip rather than alarm at a random time
FOLLOWUP_MINUTES = 3
MAX_FOLLOWUPS = 5
LEFT_ROOM_SECONDS = 120          # the room empty this long counts as up
FAN = 'fan.bedroom_fan'
# After the briefing: preferences "morning_music" is a Spotify link or a music command ("play my Morning
# playlist"); unset means resume whatever Spotify last played.
DEFAULT_MUSIC = 'resume'

PATH = Path(__file__).resolve().parent / 'data' / 'morning-wakeup.json'


def keep_awake_window(now):
    """From 6:30 until the late limit on alarm days: Windows woken over the network sleeps again in ~2 min."""
    start = datetime.datetime.combine(now.date(), WAKE_AT)
    return (now.weekday() in DAYS and
            start - datetime.timedelta(minutes=10) <= now < start + datetime.timedelta(minutes=LATE_LIMIT_MINUTES))


def _stay_awake(on):
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def due(now, last_day):
    """True when today's wake-up should fire now. `last_day` is the ISO date it last fired."""
    if now.weekday() not in DAYS or last_day == now.date().isoformat():
        return False
    start = datetime.datetime.combine(now.date(), WAKE_AT)
    return start <= now < start + datetime.timedelta(minutes=LATE_LIMIT_MINUTES)


def wake_prompt(now, briefing):
    return f"""[MORNING WAKE-UP] It's {now.strftime('%A %I:%M %p').replace(' 0', ' ')}. An alarm tone just played on the bedroom speaker to wake the owner; you're the voice that follows it. They're most likely still in bed.

Wake them properly, then give the morning briefing. Open with a short, crisp wake-up line in your own words (vary it day to day: composed, dryly witty, never chirpy). Then, in three or four sentences: the weather and what to wear if it matters, today's calendar and reminders, and anything that finished or is waiting on them. You've switched the fan off for them; mention it only in passing if at all.

Briefing data:
{briefing}

Speak as JARVIS, calling them "sir". No tools, no closing question, nothing invented."""


def nudge_prompt(n, now):
    tone = ("gentle", "a touch drier", "pointed but polite", "openly amused", "the final, firm word")[min(n, 4)]
    return (f"[MORNING WAKE-UP, CHECK {n + 1}] It's {now.strftime('%I:%M %p').lstrip('0')} and the owner still "
            f"hasn't got up since your wake-up call. Give them one short sentence to get moving. Tone: {tone}. "
            "Don't repeat the briefing or your earlier wording. Speak as JARVIS, calling them \"sir\". No tools.")


class Alarm:
    def __init__(self, put, read_state, call_service, briefing, idle_seconds=None, last_user_turn=None,
                 clock=time.time):
        self.put, self.read_state, self.call_service = put, read_state, call_service
        self.briefing, self.idle_seconds = briefing, idle_seconds
        self.last_user_turn = last_user_turn or (lambda: 0.0)
        self.clock = clock
        self.woke_at = None
        self.followups = 0
        self.empty_since = None
        self.saved = _load()

    def poll(self):
        now_ts = self.clock()
        now = datetime.datetime.fromtimestamp(now_ts)
        if self.woke_at is None:
            if due(now, self.saved.get('last_day')):
                return self._wake(now_ts, now)
            return None
        return self._follow_up(now_ts, now)

    def _wake(self, now_ts, now):
        self.saved['last_day'] = now.date().isoformat()
        _save(self.saved)
        try:
            if self.read_state(presence_greeting.PERSON)['state'] != 'home':
                return 'not home'
        except Exception:
            pass  # can't tell: better to ring than to let them oversleep
        try:
            self.call_service('fan', 'turn_off', {'entity_id': FAN})
        except Exception:
            pass
        try:
            briefing = self.briefing()
        except Exception:
            briefing = 'Unavailable.'
        self.woke_at, self.followups, self.empty_since = now_ts, 0, None
        self.put({'label': 'Morning wake-up', 'alarm': 4, 'output': presence_greeting.SPEAKER,
                  'prompt': wake_prompt(now, briefing), 'after': lambda _: self.play_music()})
        return 'woke'

    def play_music(self):
        """Start Spotify in the background so the next turn isn't held up while it opens."""
        threading.Thread(target=start_music, daemon=True, name='morning-music').start()

    def _up(self, now_ts):
        if self.last_user_turn() > self.woke_at:
            return True
        if self.idle_seconds and self.idle_seconds() < min(60, now_ts - self.woke_at):
            return True  # touched the PC since the wake-up
        try:
            occupied = self.read_state(presence_greeting.SENSOR)['state'] == 'on'
        except Exception:
            return False
        if occupied:
            self.empty_since = None
            return False
        self.empty_since = self.empty_since or now_ts
        return now_ts - self.empty_since >= LEFT_ROOM_SECONDS

    def _follow_up(self, now_ts, now):
        if self._up(now_ts) or self.followups >= MAX_FOLLOWUPS:
            self.woke_at = None
            return 'up' if self.followups < MAX_FOLLOWUPS else 'gave up'
        if now_ts - self.woke_at < (self.followups + 1) * FOLLOWUP_MINUTES * 60:
            return None
        self.put({'label': 'Wake-up check', 'alarm': 1, 'output': presence_greeting.SPEAKER,
                  'prompt': nudge_prompt(self.followups, now)})
        self.followups += 1
        return 'nudged'


def start_music():
    import music
    import preferences
    command = str(preferences.read().get('morning_music') or DEFAULT_MUSIC)
    if command == 'resume':
        problem = music.perform('resume')
    elif command.startswith('spotify:'):  # a playlist/album link, e.g. the "Jarvis Morning" playlist
        problem = music.perform('play', command)
        if not problem:  # it's ordered easy-to-energetic; shuffle would scramble that
            try:
                import spotify_mcp
                spotify_mcp.api('PUT', '/me/player/shuffle', params={'state': 'false'})
            except Exception:
                pass
    else:
        problem = music.run(command)
    if problem:
        print(f"(Morning music didn't start: {problem})", flush=True)


def _load():
    try:
        saved = json.loads(PATH.read_text(encoding='utf-8'))
        return saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(state), encoding='utf-8')
    temp.replace(PATH)


def start(put, briefing, last_user_turn):
    """Run the weekday alarm in the background. False when Home Assistant isn't configured."""
    import home_assistant
    try:
        home_assistant._config()
    except home_assistant.HomeError:
        return False
    try:
        import activity
        idle = activity._idle_seconds
    except Exception:
        idle = None
    alarm = Alarm(put, lambda entity: home_assistant._api('GET', f'/api/states/{entity}'),
                  lambda domain, service, data: home_assistant._api('POST', f'/api/services/{domain}/{service}', data),
                  briefing, idle, last_user_turn)

    def loop():
        awake = False
        while True:
            try:
                alarm.poll()
                wanted = alarm.woke_at is not None or keep_awake_window(datetime.datetime.now())
                if wanted != awake:  # the execution state belongs to this thread, so set it here
                    _stay_awake(wanted)
                    awake = wanted
            except Exception:
                pass
            time.sleep(10)
    threading.Thread(target=loop, daemon=True, name='morning-wakeup').start()
    return True
