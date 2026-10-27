"""Reminders and timers that survive restarts.

Stored in data/reminders.json. A background thread calls `on_due(reminder)`
when one comes due; reminders that came due while Jarvis was off fire at startup.
"""

import datetime
import json
import os
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", "reminders.json")
_lock = threading.Lock()


def _load() -> list[dict]:
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(items: list[dict]):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1, ensure_ascii=False)
    for attempt in range(20):  # Windows briefly locks files (antivirus, sync tools) - retry like preferences.py
        try:
            os.replace(tmp, PATH)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def _when(ts: float) -> str:
    dt = datetime.datetime.fromtimestamp(ts)
    day = ("today" if dt.date() == datetime.date.today() else
           "tomorrow" if dt.date() == datetime.date.today() + datetime.timedelta(days=1) else
           dt.strftime("%A %b %d"))
    return f"{day} at {dt.strftime('%I:%M %p').lstrip('0')}"


def parse_time(minutes_from_now: float = 0, at: str = "") -> float:
    """Due time as a timestamp. `at` is local "YYYY-MM-DD HH:MM" (24-hour) or "HH:MM"."""
    if at.strip():
        at = at.strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%H:%M"):
            try:
                dt = datetime.datetime.strptime(at, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Couldn't read the time '{at}'. Use 'YYYY-MM-DD HH:MM' (24-hour).")
        if fmt == "%H:%M":
            now = datetime.datetime.now()
            dt = dt.replace(year=now.year, month=now.month, day=now.day)
            if dt <= now:
                dt += datetime.timedelta(days=1)
        return dt.timestamp()
    if minutes_from_now <= 0:
        raise ValueError("Give minutes_from_now or at.")
    return time.time() + minutes_from_now * 60


def add(message: str, due: float, timer: bool = False) -> dict:
    item = {"id": uuid.uuid4().hex[:6], "message": message.strip(), "due": due,
            "timer": timer, "created": time.time()}
    with _lock:
        items = _load()
        items.append(item)
        _save(items)
    return item


def describe(item: dict) -> str:
    kind = "Timer" if item["timer"] else "Reminder"
    return f"{kind} {item['id']}: '{item['message']}' due {_when(item['due'])}"


def pending() -> list[dict]:
    return sorted(_load(), key=lambda r: r["due"])


def cancel(query: str) -> str:
    with _lock:
        items = _load()
        q = query.lower().strip()
        match = next((r for r in items if r["id"] == q), None) or \
            next((r for r in items if q and q in r["message"].lower()), None)
        if match is None:
            return f"No reminder matching '{query}'."
        _save([r for r in items if r is not match])
    return f"Cancelled: {describe(match)}"


def start(on_due, stop: threading.Event | None = None) -> threading.Event:
    """Deliver due reminders in the background until `stop` is set. Returns the stop event."""
    stop = stop or threading.Event()

    def loop():
        while not stop.is_set():
            try:
                now = time.time()
                with _lock:
                    items = _load()
                    due = [r for r in items if r["due"] <= now]
                    if due:
                        _save([r for r in items if r["due"] > now])
                for r in due:
                    on_due(r)
            except Exception as e:  # a failed save must not stop every future reminder; retry next tick
                print(f"(reminders: {e!r})", flush=True)
            stop.wait(1)

    threading.Thread(target=loop, daemon=True).start()
    return stop
