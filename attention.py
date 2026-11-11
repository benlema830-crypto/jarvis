"""When Jarvis may speak up without being asked.

Finished-work reports, the daily review and "welcome back" used to be spoken whenever they came up: about
eleven a day, into an empty room or over whatever the owner was doing. Each one now gets one of two outcomes:

  say   the owner is talking with Jarvis right now, or is at the PC and today's budget isn't spent
  hold  nobody is at the PC (it would be said to an empty room), or today's budget is spent

Held updates are not lost. They are listed in the Console, and the next "welcome back" or morning briefing
delivers them together, as one interruption instead of several. The held_updates tool reads them on request.

Never held: reminders and timers, the morning alarm, questions that need a yes or no, and anything the owner
just asked for. preferences "interruptions": {"daily_cap": 5} sets the budget; 0 holds everything, -1 never holds.
"""
import datetime
import json
import threading
import time
from pathlib import Path

import preferences

STORE = DEFAULT_STORE = Path(__file__).resolve().parent / "data" / "attention.json"
DAILY_CAP = 5
ENGAGED_SECONDS = 600   # spoke or typed to Jarvis this recently: he's part of the conversation, so just say it
AWAY_SECONDS = 300      # no keyboard or mouse for this long: nobody is there to hear it
MAX_HELD = 40
_lock = threading.RLock()


def cap() -> int:
    value = (preferences.read().get("interruptions") or {}).get("daily_cap", DAILY_CAP)
    return value if type(value) is int and -1 <= value <= 100 else DAILY_CAP


def _load(today=None):
    today = today or datetime.date.today().isoformat()
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("held"), list):
            raise ValueError
    except (OSError, ValueError):
        data = {"day": today, "spoken": 0, "held": []}
    if data.get("day") != today:  # a new day: the budget resets, held updates carry over until delivered
        data.update(day=today, spoken=0)
    return data


def _save(data):
    import testing_guard
    if STORE == DEFAULT_STORE and testing_guard.under_test():
        return
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STORE)


def decide(label, text="", *, since_owner_spoke=None, input_idle=None, today=None) -> str:
    """"say" or "hold" for one unprompted update, recording the outcome. Times are seconds; None means unknown."""
    with _lock:
        data = _load(today)
        limit = cap()
        engaged = since_owner_spoke is not None and since_owner_spoke < ENGAGED_SECONDS
        away = input_idle is not None and input_idle >= AWAY_SECONDS and not engaged
        if limit == -1 or engaged:
            return "say"
        if not away and data["spoken"] < limit:
            data["spoken"] += 1
            _save(data)
            return "say"
        data["held"].append({"t": time.time(), "label": str(label)[:120], "text": " ".join(str(text).split())[:600],
                             "why": "nobody at the PC" if away else "today's limit reached"})
        del data["held"][:-MAX_HELD]
        _save(data)
        return "hold"


def held() -> list[dict]:
    with _lock:
        return [dict(item) for item in _load()["held"]]


def take() -> list[dict]:
    """The held updates, removed from the list: they are about to be delivered."""
    with _lock:
        data = _load()
        items, data["held"] = data["held"], []
        if items:
            _save(data)
        return items


def lines(items) -> str:
    """Held updates as text for a briefing or the held_updates tool."""
    if not items:
        return ""
    rows = [f"- {time.strftime('%H:%M', time.localtime(i.get('t', 0)))} {i['label']}"
            + (f": {i['text'][:260]}" if i.get("text") else "") for i in items]
    return (f"{len(items)} update{'s' if len(items) != 1 else ''} held while the owner was away or busy (agents' "
            "reports are their own claims):\n" + "\n".join(rows))


def snapshot() -> dict:
    with _lock:
        data = _load()
        return {"cap": cap(), "spoken_today": data["spoken"],
                "held": [{"t": i.get("t"), "label": i.get("label", ""), "why": i.get("why", "")} for i in data["held"]]}
