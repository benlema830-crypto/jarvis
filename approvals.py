"""Spoken approvals for background tasks (the screen agent and terminal tasks).

A task calls ask(question) and waits. Jarvis says the question out loud, and the user's
next words are passed straight to answer() by jarvis.py - the AI never answers for them.
Only one question is open at a time; no answer within two minutes counts as no.
"""

import re
import threading

import hud

YES = re.compile(r"^(?:please\s+)?(yes|yeah|yep|yup|sure|do it|go ahead|go for it|confirm(ed)?|please do|proceed|"
                 r"affirmative|ok(ay)?|(i\s+)?approved?|(you\s+have\s+)?my\s+(approval|permission)|permission\s+granted|"
                 r"granted|you\s+(may|can)(?!')\b)\b", re.I)
NO = re.compile(r"\b(no|nope|not|don'?t|can'?t|cannot|cancel|wait|stop|hold on)\b", re.I)
TIMEOUT = 120

on_question = None  # set by jarvis.py: says the question out loud
_one_at_a_time = threading.Lock()
_pending: dict | None = None


def spoken_question(question: str) -> str:
    """Never send command/code payloads to TTS, even if an agent embeds one in a reason."""
    text = re.split(r"\b(?:command|script|technical details)\s*:", question, maxsplit=1, flags=re.I)[0]
    text = " ".join(text.split())
    technical = re.search(
        r"[`{}\[\]\\|;$]|https?://|\b[A-Za-z]:[/\\]|\s--?[A-Za-z]|"
        r"\b(?:powershell|pwsh|cmd\.exe|python(?:\.exe)?|bash|npm|git)\s+|"
        r"\b(?:Remove-Item|Set-ItemProperty|Start-Process|Invoke-Expression)\b", text, re.I)
    if not text or technical or len(text) > 220 or len(text.split()) > 38:
        return "An action needs your approval. Please review the details on screen. May I proceed?"
    return text


def ask(question: str, cancel: threading.Event | None = None, *, spoken: str | None = None) -> tuple[bool, str]:
    """Ask the user out loud; returns (approved, what they said). Blocks until answered."""
    global _pending
    with _one_at_a_time:
        speech = spoken_question(spoken if spoken is not None else question)
        item = {"question": speech, "details": question, "event": threading.Event(), "answer": None}
        _pending = item
        hud.emit("event", text=f"Approval needed: {question}")
        if on_question:
            on_question(speech)
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


def classify_answer(text: str) -> bool | None:
    """Only explicit answers decide; questions and unclear transcripts stay pending."""
    text = text.strip(" .,!?")
    if NO.search(text):
        return False
    if YES.search(text):
        return True
    return None


def answer(text: str) -> bool | None:
    """Return yes/no, or None when the reply needs clarification."""
    item = _pending
    if not item:
        return False
    approved = classify_answer(text)
    if approved is None:
        return None
    item["answer"] = (approved, text)
    item["event"].set()
    return approved
