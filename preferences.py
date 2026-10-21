"""Local UI preferences, kept in git-ignored data and never sent to the model."""
import json
import os
from pathlib import Path
import threading
import time

PATH = Path(__file__).resolve().parent / "data" / "preferences.json"
_lock = threading.RLock()


def read():
    with _lock:
        try:
            value = json.loads(PATH.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}


def update(**changes):
    with _lock:
        value = read()
        value.update(changes)
        PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
        for attempt in range(20):
            try:
                temp.replace(PATH)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
        return value


def listening_mode():
    mode = read().get("listening_mode", os.getenv("JARVIS_LISTENING_MODE", "wake"))
    return mode if mode in ("wake", "continuous") else "wake"


def set_listening_mode(mode):
    if mode not in ("wake", "continuous"):
        raise ValueError("Choose wake or continuous listening.")
    update(listening_mode=mode)

