"""Greets the owner when they walk into the bedroom: "Welcome back, sir" - but never the same line twice running.

Watches the Aqara presence sensor through Home Assistant (outbound polling from this PC, so the Pi
needs no way in). A greeting is queued only when the room was empty for a while, outside quiet hours,
past the cooldown, and when nobody was just using this PC (the desk sits under the sensor's blind
spot). The brain writes each line itself; how much it says grows with how long the owner was gone.
"""
import datetime
import json
import os
import random
import threading
import time
from pathlib import Path

SENSOR = 'binary_sensor.bedroom_presence_occupancy'
PERSON = 'person.benjamin_lema'
POLL_SECONDS = 2
MIN_EMPTY_MINUTES = 10       # require one uninterrupted clear interval
COOLDOWN_MINUTES = 30
QUIET_START = datetime.time(23, 0)
QUIET_END = datetime.time(6, 40)
RECENT_INPUT_SECONDS = 60    # keyboard/mouse this recent means they were at the desk all along
HOME_ARRIVAL_MINUTES = 20    # the phone reported "home" this recently: they just got home
KEEP = 8
# Spoken through the bedroom speaker, not the headset (which they won't be wearing as they walk in).
SPEAKER = os.getenv('JARVIS_GREETING_DEVICE', 'Speakers (Bose')

PATH = Path(__file__).resolve().parent / 'data' / 'presence-greetings.json'

# One is picked at random each time (never the same twice running) so the brain doesn't settle into
# a single formula. The classic line is the owner's favourite, so it comes up about twice as often.
STYLES = ("classic and understated, in the spirit of \"Welcome back, sir.\"",
          "dry wit, one light remark",
          "a remark on the hour or the day",
          "a remark on how long they were gone",
          "warm but brief, like a butler who noticed",
          "straight to business: lead with the most useful thing")
WEIGHTS = (2, 1, 1, 1, 1, 1)


def _load():
    try:
        saved = json.loads(PATH.read_text(encoding='utf-8'))
        return saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2), encoding='utf-8')
    temp.replace(PATH)


def quiet(now):
    t = now.time()
    return t >= QUIET_START or t < QUIET_END


def should_greet(away_minutes, now, last_greeted, idle_seconds, empty_since=None):
    """Why not to greet, or None to greet. `last_greeted` is a timestamp (0 = never)."""
    if away_minutes < MIN_EMPTY_MINUTES:
        return 'room was only briefly empty'
    if quiet(now):
        return 'quiet hours'
    # The sensor loses someone lying still, so a gap that began overnight is almost always them asleep in
    # bed. It produced "twenty-seven minutes up before the alarm, sir" to someone the alarm had just woken.
    if empty_since is not None and quiet(empty_since):
        return 'the room only looked empty overnight'
    if now.timestamp() - last_greeted < COOLDOWN_MINUTES * 60:
        return 'cooldown'
    if idle_seconds is not None and idle_seconds < RECENT_INPUT_SECONDS:
        return 'someone was just using the PC'
    return None


def tier(away_minutes, arrived_home):
    if arrived_home or away_minutes >= 180:
        return 'long'
    return 'medium' if away_minutes >= 45 else 'short'


def _away(minutes):
    if minutes < 60:
        return f"about {round(minutes)} minutes"
    hours = minutes / 60
    return f"about {hours:.0f} hour{'s' if round(hours) != 1 else ''}" if hours >= 1.5 else "about an hour"


def build_prompt(away_minutes, arrived_home, now, recent, briefing='', style=None):
    """The brain's instructions for one greeting. `recent` is the last few greetings, newest last."""
    if style is None:
        last_style = recent[-1]['style'] if recent else None
        style = random.choices([s for s in STYLES if s != last_style],
                               [w for s, w in zip(STYLES, WEIGHTS) if s != last_style])[0]
    size = tier(away_minutes, arrived_home)
    where = ("They just got home (their phone arrived home a few minutes ago)." if arrived_home else
             f"The bedroom's sensor saw nobody for {_away(away_minutes)}. It can miss someone keeping still, so "
             "you don't actually know they left, where they went or what they did.")
    said = "\n".join(f"  - {r['text']}" for r in recent[-5:]) or "  (none yet)"
    length = {
        'short': "One sentence. They only stepped out, so no briefing.",
        'medium': ("One or two sentences. Add at most one useful item (something due soon, a finished task, "
                   "or an unfinished thread from your recent conversation) only if there is one."),
        'long': ("A short spoken briefing, three or four sentences at most: greet them, then the one to three "
                 "things that matter (what's coming up, reminders, anything that finished or is waiting on them, "
                 "and what the two of you were in the middle of if the recent conversation shows unfinished "
                 "work). Weather only if it affects their plans."),
    }[size]
    prompt = f"""[PRESENCE GREETING] The owner just walked into their bedroom, where you live on their PC. Greet them out loud.

Time: {now.strftime('%A %I:%M %p').replace(' 0', ' ')}
{where}
Tone for this one: {style}
Length: {length}
Your last greetings (don't reuse their wording or opening):
{said}"""
    if briefing:
        prompt += f"\n\nWhat's going on:\n{briefing}"
    prompt += f"\n\n{VOICE}"
    return prompt, style


# How JARVIS sounds: shown to the brain as a register to match, never lines to reuse.
VOICE = """Speak as JARVIS: a composed British butler-AI. Understated, quick, dry; warmth shows in what he notices, not in gushing. He calls them "sir", but not always first. He remarks on something real (the hour, how long they were gone, what's waiting, what they were doing) instead of generic pleasantries.
The register, not lines to copy:
  - "Welcome back, sir."
  - "Ah. The room was getting rather quiet without you, sir."
  - "Forty minutes, sir. The world carried on without incident; the research didn't."
  - "Good evening, sir. Nothing caught fire in your absence, which I count as a success."
Vary the structure and the first word from his recent greetings. Never: "How can I help", "Hope you're doing well", exclamation marks, or chirpiness. Don't mention the sensor, don't ask a closing question, and use no tools.
Every fact must come from this message or your records, stated no more strongly than they support. Don't invent details or draw conclusions about what they were doing. Weather here is a forecast, so never say it's raining now or that it's cold out. An item from your records may be out of date: "still waiting on" only if it clearly is. If there's nothing real to remark on, a plain "Welcome back, sir." is the right answer."""


class Watcher:
    def __init__(self, put, read_state, idle_seconds=None, briefing=None, clock=time.time):
        self.put, self.read_state, self.idle_seconds = put, read_state, idle_seconds
        self.briefing, self.clock = briefing, clock
        self.occupied = None
        self.empty_since = None
        self.last_poll = None
        self.saved = _load()

    def poll(self):
        """Read the sensor once; queue a greeting on an empty -> occupied change that passes the checks."""
        now_ts = self.clock()
        try:
            state = self.read_state(SENSOR)
        except Exception:
            # A gap in observations cannot prove continuous absence.
            self.occupied, self.empty_since, self.last_poll = None, None, None
            raise
        if state['state'] not in ('on', 'off'):
            self.occupied, self.empty_since, self.last_poll = None, None, None
            return None
        on = state['state'] == 'on'
        changed = min(now_ts, _since(state, now_ts))
        previous_poll = self.last_poll
        self.last_poll = now_ts
        if self.occupied is None:  # Learn current state; never greet at startup/recovery.
            self.occupied = on
            self.empty_since = None if on else changed
            return None
        if not on:
            # HA last_changed is the start of THIS continuous clear interval.
            # Even if an on/off flicker happened between polls, a newer timestamp
            # invalidates the old interval. Never restore an earlier absence.
            if self.occupied or self.empty_since is None:
                self.empty_since = changed
            elif 'last_changed' in state:
                self.empty_since = max(self.empty_since, changed)
            self.occupied = False
            return None
        if self.occupied:
            return None
        self.occupied = True
        empty_since, self.empty_since = self.empty_since, None
        # A stalled poller may have missed whole occupied/clear cycles. Fail
        # closed rather than greeting from an interval we did not observe.
        if previous_poll is not None and now_ts - previous_poll > max(10, POLL_SECONDS * 3):
            return 'observation gap'
        away = max(0, changed - empty_since) / 60 if empty_since is not None else 0
        now = datetime.datetime.fromtimestamp(now_ts)
        idle = self.idle_seconds() if self.idle_seconds else None
        began = datetime.datetime.fromtimestamp(empty_since) if empty_since is not None else None
        reason = should_greet(away, now, self.saved.get('last_greeted', 0), idle, began)
        if reason:
            return reason
        arrived = self._arrived_home(now_ts)
        extra = ''
        if self.briefing and tier(away, arrived) != 'short':
            try:
                extra = self.briefing()
            except Exception:
                extra = ''
        prompt, style = build_prompt(away, arrived, now, self.saved.get('recent', []), extra)
        self.saved['last_greeted'] = now_ts
        _save(self.saved)
        self.put({'label': 'Welcome back', 'prompt': prompt, 'output': SPEAKER,
                  'after': lambda text: self.remember(text, style)})
        return 'greeted'

    def _arrived_home(self, now_ts):
        try:
            person = self.read_state(PERSON)
        except Exception:
            return False
        return person['state'] == 'home' and now_ts - _since(person, now_ts) < HOME_ARRIVAL_MINUTES * 60

    def remember(self, text, style):
        if text.strip():
            recent = self.saved.get('recent', []) + [{'text': text.strip(), 'style': style}]
            self.saved['recent'] = recent[-KEEP:]
            _save(self.saved)


def _since(state, fallback):
    try:
        return datetime.datetime.fromisoformat(state['last_changed']).timestamp()
    except (KeyError, TypeError, ValueError):
        return fallback


def start(put, briefing=None):
    """Watch the bedroom sensor in the background. False when Home Assistant isn't configured."""
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
    watcher = Watcher(put, lambda entity: home_assistant._api('GET', f'/api/states/{entity}'), idle, briefing)

    def loop():
        while True:
            try:
                watcher.poll()
            except Exception:
                pass  # Pi unreachable or sensor missing; try again next poll
            time.sleep(POLL_SECONDS)
    threading.Thread(target=loop, daemon=True, name='presence-greeting').start()
    return True
