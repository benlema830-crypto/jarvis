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
MIN_EMPTY_MINUTES = 3        # shorter gaps are sensor flicker or stepping into the hall
COOLDOWN_MINUTES = 30
QUIET_START = datetime.time(23, 0)
QUIET_END = datetime.time(6, 40)
RECENT_INPUT_SECONDS = 60    # keyboard/mouse this recent means they were at the desk all along
PASS_THROUGH_SECONDS = 90    # left again this fast: a pass-through, so it doesn't count as being back
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


def should_greet(away_minutes, now, last_greeted, idle_seconds):
    """Why not to greet, or None to greet. `last_greeted` is a timestamp (0 = never)."""
    if away_minutes < MIN_EMPTY_MINUTES:
        return 'room was only briefly empty'
    if quiet(now):
        return 'quiet hours'
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
             f"They were out of the bedroom for {_away(away_minutes)}.")
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
Vary the structure and the first word from his recent greetings. Never: "How can I help", "Hope you're doing well", exclamation marks, or chirpiness. Don't invent details, don't mention the sensor, don't ask a closing question, and use no tools."""


class Watcher:
    def __init__(self, put, read_state, idle_seconds=None, briefing=None, clock=time.time):
        self.put, self.read_state, self.idle_seconds = put, read_state, idle_seconds
        self.briefing, self.clock = briefing, clock
        self.occupied = None
        self.empty_since = None
        self.entered = None          # (when they came in, empty_since before that, last_greeted before that)
        self.saved = _load()

    def poll(self):
        """Read the sensor once; queue a greeting on an empty -> occupied change that passes the checks."""
        state = self.read_state(SENSOR)
        if state['state'] not in ('on', 'off'):
            return None  # unavailable: keep what we knew
        on = state['state'] == 'on'
        if self.occupied is None:  # first look: learn the state, never greet for it
            self.occupied = on
            self.empty_since = None if on else _since(state, self.clock())
            return None
        if on == self.occupied:
            return None
        self.occupied = on
        now_ts = self.clock()
        if not on:
            self.empty_since = now_ts
            if self.entered and now_ts - self.entered[0] < PASS_THROUGH_SECONDS:
                # In and out again: keep timing the whole absence, and give back the cooldown if a
                # greeting went out that they most likely didn't stay to hear.
                _, self.empty_since, before = self.entered
                if self.saved.get('last_greeted', 0) >= self.entered[0]:
                    self.saved['last_greeted'] = before
                    _save(self.saved)
            self.entered = None
            return None
        if self.empty_since is not None:
            self.entered = (now_ts, self.empty_since, self.saved.get('last_greeted', 0))
        away = (now_ts - (self.empty_since or now_ts)) / 60
        now = datetime.datetime.fromtimestamp(now_ts)
        idle = self.idle_seconds() if self.idle_seconds else None
        reason = should_greet(away, now, self.saved.get('last_greeted', 0), idle)
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
