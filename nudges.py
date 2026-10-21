"""Proactive heads-up before calendar events: "Heads up, sir: Standup starts in 8 minutes."

Polls the connected ICS calendar every few minutes (read-only, no Outlook automation) and
announces each timed event once, 5-10 minutes before it starts. The line is spoken
directly, so it costs no AI request. Nothing runs without a connected calendar.
"""
import datetime
import threading
import time

POLL_SECONDS = 300
LEAD_MINUTES = 10


def due(events, announced, now=None):
    """Events to announce now, as (key, sentence); updates `announced`."""
    now = now or datetime.datetime.now().astimezone()
    out = []
    for start, title in events:
        minutes = int((start - now).total_seconds() // 60)
        key = (start.isoformat(), title)
        if 0 <= minutes <= LEAD_MINUTES and key not in announced:
            announced.add(key)
            when = "now" if minutes <= 1 else f"in {minutes} minutes"
            out.append((key, f"Heads up, sir: {title} starts {when}."))
    return out


def start(put, upcoming=None):
    """put(item) queues a spoken event on the assistant; upcoming() -> [(start, title)]."""
    if upcoming is None:
        import context
        if not context.calendar_urls():
            return False
        upcoming = lambda: context.starting_soon(LEAD_MINUTES + POLL_SECONDS // 60)
    announced = set()

    def loop():
        while True:
            try:
                for _, sentence in due(upcoming(), announced):
                    put({"label": "Upcoming event", "chime": True, "say": sentence})
            except Exception:
                pass  # feed unreachable; try again next poll
            time.sleep(POLL_SECONDS)
    threading.Thread(target=loop, daemon=True, name="calendar-nudges").start()
    return True
