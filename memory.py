"""Long-term memory: facts about the user that Jarvis keeps between sessions.

Stored in data/memory.json and placed in Jarvis's system prompt at startup.
"""

import difflib
import json
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", "memory.json")
MAX_FACTS = 200
_lock = threading.Lock()


def _load() -> list[dict]:
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(facts: list[dict]):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=1, ensure_ascii=False)
    os.replace(tmp, PATH)


def facts() -> list[str]:
    return [f["fact"] for f in _load()]


def remember(fact: str) -> str:
    fact = fact.strip()
    if not fact:
        return "Nothing to remember."
    with _lock:
        items = _load()
        if any(f["fact"].lower() == fact.lower() for f in items):
            return "Already remembered."
        items.append({"fact": fact, "t": time.time()})
        _save(items[-MAX_FACTS:])
    return f"Remembered: {fact}"


def forget(fact: str) -> str:
    """Forget the stored fact that best matches `fact`."""
    with _lock:
        items = _load()
        texts = [f["fact"] for f in items]
        lower = fact.lower()
        match = next((t for t in texts if lower in t.lower()), None)
        if match is None:
            close = difflib.get_close_matches(fact, texts, n=1, cutoff=0.4)
            match = close[0] if close else None
        if match is None:
            return f"No memory matching '{fact}'."
        _save([f for f in items if f["fact"] != match])
    return f"Forgot: {match}"


def prompt_section() -> str:
    items = facts()
    if not items:
        return "Nothing yet."
    return "\n".join(f"- {f}" for f in items)
