"""The owner's yes, for the few things that still need one.

A task calls ask(question) and waits. Jarvis says the question out loud and texts it to the owner's phone, and
their next words are passed straight to answer() by jarvis.py: spoken at the PC, the Yes button on the phone
page, or a message from their phone or Telegram. The AI never answers for them. Only one question is open at a
time. No answer within two minutes counts as no; ten minutes when they are away from the PC.

What still asks (the owner's decision, 2026-11-11: "there should be little to no rules"): spending money and
sending a message to other people, plus a question an agent chose to put itself. Deleting, installing, system
settings, git pushes, edits anywhere and outside tools all run without a question. preferences "auto_approve"
can change that: "none" asks for everything, "all" asks for nothing.
"""

import re
import threading

import hud
import preferences

YES = re.compile(r"^(?:please\s+)?(yes|yeah|yep|yup|sure|do it|go ahead|go for it|confirm(ed)?|please do|proceed|"
                 r"affirmative|ok(ay)?|(i\s+)?approved?|(you\s+have\s+)?my\s+(approval|permission)|permission\s+granted|"
                 r"granted|you\s+(may|can)(?!')\b)\b", re.I)
NO = re.compile(r"\b(no|nope|not|don'?t|can'?t|cannot|cancel|wait|stop|hold on)\b", re.I)
TIMEOUT = 120
AWAY_TIMEOUT = 600  # the owner is out and answering by text

MESSAGE, MONEY = "message other people", "spend money"
# The kinds that still wait for the owner under the default setting. Every other kind runs.
ASKS = {MESSAGE, MONEY}
# An outside tool is known only by its name (gmail_send_email, createPost, checkout). The words are matched
# whole, and only in the name, never the arguments: "remove the background" or "share of voice" in a request
# used to trip a much longer list (the owner's complaint).
_READS = {"get", "list", "search", "read", "fetch", "find", "check", "view", "show", "lookup", "query", "count"}
_MESSAGE_WORDS = {"send", "reply", "forward", "post", "publish", "tweet", "comment", "invite", "dm", "sms"}
_MONEY_WORDS = {"pay", "buy", "purchase", "checkout", "order", "donate", "subscribe", "tip", "transfer"}


def tool_kind(name: str) -> str | None:
    """MESSAGE or MONEY when an outside tool's name says it does that, else None."""
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", name or "").replace("_", " ").replace("-", " ").lower().split()
    if not words or words[0] in _READS:
        return None
    if _MONEY_WORDS & set(words):
        return MONEY
    if _MESSAGE_WORDS & set(words):
        return MESSAGE
    return None


def auto_approved(question: str, kind: str | None = None) -> bool:
    """True when nobody needs to be asked. A question with no kind is one an agent decided to ask, so it is."""
    mode = preferences.read().get("auto_approve", "routine")
    if mode == "all":
        return True
    if mode == "none":
        return False
    return kind is not None and kind not in ASKS


on_question = None  # set by jarvis.py: says the question out loud
on_text = None      # set by jarvis.py: texts the question to the owner's phone
is_away = None      # set by jarvis.py: True when nobody has touched the PC for a while
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


def _away() -> bool:
    try:
        return bool(is_away and is_away())
    except Exception:
        return False


def ask(question: str, cancel: threading.Event | None = None, *, spoken: str | None = None,
        kind: str | None = None, always: bool = False, free_text: bool = False, away: bool = False) -> tuple[bool, str]:
    """Ask the user out loud; returns (approved, what they said). Blocks until answered.
    `kind` names the category when the caller knows it (see ASKS). `always` skips the owner's
    auto_approve setting. `free_text` is a real question, not yes or no: whatever they say is the answer,
    so it can't be auto-approved (the "answer" would be meaningless) or rejected as "please say yes or no".
    `away` is for work running with nobody at the PC: the owner answers by text, so they get longer."""
    global _pending
    if not (always or free_text) and auto_approved(question, kind):
        hud.emit("event", text=f"Auto-approved: {question[:300]}")
        return True, "(auto-approved by your settings)"
    with _one_at_a_time:
        speech = spoken_question(spoken if spoken is not None else question)
        item = {"question": speech, "details": question, "event": threading.Event(), "answer": None, "free_text": free_text}
        _pending = item
        hud.emit("event", text=f"Approval needed: {question}")
        limit = AWAY_TIMEOUT if away or _away() else TIMEOUT
        if on_question:
            on_question(speech)
        if on_text:
            try:
                on_text(speech, question, free_text)
            except Exception:
                pass  # a text that can't be sent mustn't cost the spoken question
        waited = 0.0
        while not item["event"].wait(0.5):
            waited += 0.5
            if (cancel and cancel.is_set()) or waited >= limit:
                break
        _pending = None
        if item["answer"]:
            return item["answer"]
        return False, "(stopped)" if cancel and cancel.is_set() else (
            "(no answer within two minutes)" if limit == TIMEOUT else "(no answer within ten minutes)")


def waiting() -> str | None:
    """The open question, if any."""
    return _pending["question"] if _pending else None


def waiting_for_answer() -> bool:
    """The open question takes any words, not a yes or no."""
    return bool(_pending and _pending.get("free_text"))


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
    if item.get("free_text"):
        item["answer"] = (True, text)
        item["event"].set()
        return True
    approved = classify_answer(text)
    if approved is None:
        return None
    item["answer"] = (approved, text)
    item["event"].set()
    return approved
