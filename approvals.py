"""Spoken approvals for background tasks (the screen agent and terminal tasks).

A task calls ask(question) and waits. Jarvis says the question out loud, and the user's
next words are passed straight to answer() by jarvis.py - the AI never answers for them.
Only one question is open at a time; no answer within two minutes counts as no.
"""

import re
import threading

import hud

YES = re.compile(r"\b(yes|yeah|yep|yup|sure|do it|go ahead|go for it|confirm(ed)?|please do|proceed|affirmative|ok(ay)?)\b", re.I)
NO = re.compile(r"\b(no|nope|don'?t|cancel|wait|stop|hold on)\b", re.I)
TIMEOUT = 120

on_question = None  # set by jarvis.py: says the question out loud
_one_at_a_time = threading.Lock()
_pending: dict | None = None


def ask(question: str, cancel: threading.Event | None = None) -> tuple[bool, str]:
    """Ask the user out loud; returns (approved, what they said). Blocks until answered."""
    global _pending
    with _one_at_a_time:
        item = {"question": question, "event": threading.Event(), "answer": None}
        _pending = item
        hud.emit("event", text=f"Approval needed: {question}")
        if on_question:
            on_question(question)
        waited = 0.0
        while not item["event"].wait(0.5):
            waited += 0.5
            if (cancel and cancel.is_set()) or waited >= TIMEOUT:
                break
        _pending = None
        if item["answer"]:
            return item["answer"]
        return False, "(stopped)" if cancel and cancel.is_set() else "(no answer within two minutes)"


def waiting() -> str | None:
    """The open question, if any."""
    return _pending["question"] if _pending else None


def answer(text: str) -> bool:
    """The user's spoken reply. Returns whether it counts as yes."""
    item = _pending
    if not item:
        return False
    approved = bool(YES.search(text)) and not NO.search(text)
    item["answer"] = (approved, text)
    item["event"].set()
    return approved
