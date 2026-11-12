"""Keeps what Jarvis says tied to what actually happened.

Four small jobs, all plain rules so they cost no time:
  - Receipts: every tool that changes something leaves a receipt for the turn: confirmed (read back), sent
    (accepted, not read back), waiting (needs the owner's OK), unknown (read back, didn't show) or failed.
    The interface shows them beside the reply, so the proof never depends on how the reply is worded.
  - ClaimGate: "I've turned it off" is held unless an action this turn was confirmed or accepted; "the TV is
    on" or "I checked" is held unless some tool succeeded. The brain is then asked to do it or say the truth.
  - unspoken_failures: if an action failed or couldn't be confirmed and the reply doesn't admit a problem,
    Jarvis adds the sentence himself.
  - parse_outcome: an agent finishing its turn doesn't mean it finished the job. It reports an
    OUTCOME line, so "I couldn't begin" is no longer recorded and announced as finished.
  - note_tool / tainted: which tools ran this turn, and whether untrusted text (email, the web, the
    screen) came in, so direct shell and file tools can insist on asking the owner afterwards.
"""
import json
import re
import threading
import time
from pathlib import Path

LOG = Path(__file__).resolve().parent / "data" / "claim_checks.jsonl"

# First person, finished action. Deliberately narrow: "the builder fixed it" and "it should work" aren't
# Jarvis claiming his own action, and "I've got", "I've no" and "I've been told" aren't actions at all.
_ACTIONS = (r"turned|switched|opened|closed|launched|started|stopped|restarted|set|sent|saved|added|created|"
            r"updated|changed|fixed|moved|deleted|removed|installed|renamed|checked|verified|confirmed|"
            r"tested|looked up|looked it up|looked that up|searched|scheduled|booked|paused|resumed|played|muted|unmuted|dimmed|"
            r"cancelled|canceled|submitted|uploaded|downloaded|booted|woken|woke|done|made|put|ran|run|reset|"
            r"written|wrote|built|cleared|edited|committed|pushed|asked")
_CLAIM = re.compile(
    rf"\b(?:I(?:'ve|’ve| have)(?: just| now| already| also| since)? (?:{_ACTIONS})\b"
    rf"|I just (?:{_ACTIONS})\b"
    r"|I (?:checked|verified|confirmed|tested|looked it up|searched)\b"
    r"|^(?:all )?done,? sir\b)",  # "Done, sir." but not "No harm done, sir."
    re.I)
_QUOTED = re.compile(r"[\"“][^\"”]*[\"”]")  # words about a claim aren't one: distinguish "I've started" from...
# "If I've checked…", "until I've saved…" and questions aren't reports of something done.
_NOT_A_REPORT = re.compile(r"\b(?:if|once|when|after|before|until|unless|whether|haven'?t|hadn'?t|didn'?t|never|not)\b[^.,;]*$", re.I)

# Tools whose output is written by someone else and may try to give Jarvis instructions.
# After one of these in a turn, a change waits for the owner's yes and unattended work can't be queued: the
# text was written by a stranger who may have aimed it at Jarvis. Email only, since 2026-11-11 (the owner's
# decision): web search, the clipboard and the screen used to count, and every lookup then cost a question.
UNTRUSTED_TOOLS = {"check_email", "read_email"}

# "The TV is on." "They're off now." A statement about the state of a thing, ending the clause, so that
# "nothing is on your calendar" and "what is on your mind" don't count.
_STATE = re.compile(
    r"(?:\b(?:is|are|they're)|\b\w+['’]s)\s+(?:now\s+|back\s+|already\s+|all\s+)?"
    r"(?:on|off|open|closed|locked|unlocked|running|playing|paused|muted|unmuted|connected|disconnected)"
    r"(?=(?:\s+(?:now|again|too|as well))?\s*(?:[.,;!]|$))", re.I)
# Reports of having looked rather than acted: any successful look-up backs these.
_LOOKED = re.compile(r"\bI(?:'ve|’ve| have)?(?: just| now| already| also)? "
                     r"(?:checked|verified|confirmed|tested|looked it up|looked that up|looked up|searched)\b", re.I)

# Tools that only look. Everything else changes something, and only those can back "I've done it".
READ_TOOLS = frozenset({
    "home_status", "list_apps", "find_files", "read_clipboard", "look_at_screen",
    "self_check", "system_status", "get_schedule", "search_history", "held_updates", "parallel_status", "get_weather", "recent_activity", "recall_memory",
    "performance_report", "list_reminders", "agent_status", "terminal_status",
    "list_app_windows", "agent_session_status", "list_agent_sessions", "search_knowledge", "read_knowledge_note",
    "read_file", "search_text", "list_mcp_tools", "list_tasks", "check_email", "read_email", "research_status",
    "watch_video", "web_search", "WebSearch", "WebFetch", "show_search_results"})
# Tools whose normal return is itself the proof: they write a local record and read it back or fail loudly.
PROVEN_BY_RETURN = frozenset({
    "remember", "update_memory", "correct_memory", "forget", "set_reminder", "cancel_reminder", "add_task",
    "complete_task", "create_knowledge_note", "edit_file", "write_file"})
# A failure of one of these is always worth telling the owner, even if the brain's reply glosses over it.
MUST_REPORT_FAILURE = frozenset({"home_control", "send_telegram", "send_email", "set_reminder", "add_task", "remember",
                                 "queue_away_job", "send_agent_task", "terminal_task"})
CONFIRMED, SENT, WAITING, UNKNOWN, FAILED = "confirmed", "sent", "waiting", "unknown", "failed"
_ADMITS = re.compile(r"\b(?:not|never|no luck|unable|fail\w*|unconfirmed|problem|error|refus\w*|declin\w*|"
                     r"timed out|still|but|however|though|\w+n['’]t)\b", re.I)

_lock = threading.Lock()
_succeeded = 0
_tainted = False
_receipts = []
on_receipt = None  # the interface listens here to show each action's proof next to the reply


def begin_turn():
    global _succeeded, _tainted
    with _lock:
        _succeeded, _tainted = 0, False
        del _receipts[:]


def _subject(name, tool_input):
    """What the receipt is about, in a few plain words."""
    values = tool_input if isinstance(tool_input, dict) else {}
    for key in ("device", "app", "name", "path", "task", "message", "fact", "command", "tool_name", "request", "url"):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:60]
    return name.replace("_", " ")


def classify(name, ok, content):
    """What a tool's result proves: confirmed, sent (accepted, not read back), waiting (needs the owner's OK),
    unknown (read back and it didn't show) or failed. Look-up tools return None: they prove nothing was done."""
    if name in READ_TOOLS:
        return None
    if not ok:
        return FAILED
    text = content if isinstance(content, str) else ""
    if "NOT CONFIRMED" in text:
        return UNKNOWN
    if text.startswith("Waiting for the user's spoken confirmation") or text.startswith("Not approved"):
        return WAITING
    if name == "run_command":
        code = re.match(r"Exit code (-?\d+)", text)
        return CONFIRMED if code and code.group(1) == "0" else FAILED
    if name == "home_control":
        return CONFIRMED if ("Confirmed:" in text or "was already" in text) else SENT
    if name in PROVEN_BY_RETURN or "checked on disk" in text:
        return CONFIRMED
    return SENT


def record(name, tool_input, ok, content):
    """A tool finished (called from tools.run_tool). Returns its receipt, or None for a look-up."""
    note_tool(name, ok)
    status = classify(name, ok, content)
    if status is None:
        return None
    receipt = {"tool": name, "about": _subject(name, tool_input), "status": status}
    with _lock:
        _receipts.append(receipt)
    if on_receipt:
        try:
            on_receipt(dict(receipt))
        except Exception:
            pass
    return receipt


def receipts():
    with _lock:
        return [dict(r) for r in _receipts]


def action_backed():
    """Some action this turn was confirmed or at least accepted."""
    with _lock:
        return any(r["status"] in (CONFIRMED, SENT) for r in _receipts)


def unspoken_failures(spoken):
    """Sentences Jarvis must add himself: an action this turn failed or couldn't be confirmed, and nothing he
    said admits a problem. Only the last result for each thing counts, so a retry that worked clears it."""
    if _ADMITS.search(" ".join(spoken)):
        return []
    out = []
    for receipt in unresolved():
        if receipt["status"] == UNKNOWN:
            out.append(f"I should add: I couldn't confirm that worked for {receipt['about']}.")
        else:
            out.append(f"I should add: {receipt['tool'].replace('_', ' ')} failed for {receipt['about']}.")
    return out[:2]


def unresolved():
    """Actions this turn whose last result was a failure the owner must hear about, or couldn't be confirmed."""
    latest = {}
    for receipt in receipts():
        latest[(receipt["tool"], receipt["about"])] = receipt
    return [r for r in latest.values()
            if r["status"] == UNKNOWN or (r["status"] == FAILED and r["tool"] in MUST_REPORT_FAILURE)]


def note_tool(name, ok=True):
    """A tool finished. Called from tools.run_tool, and by the brains for their built-in web tools."""
    global _succeeded, _tainted
    with _lock:
        if ok:
            _succeeded += 1
        if name in UNTRUSTED_TOOLS:
            _tainted = True


def tainted():
    return _tainted


def tools_succeeded():
    return _succeeded


def claims_action(sentence):
    """The sentence reports something Jarvis himself did. Questions and conditions don't count."""
    sentence = _QUOTED.sub("", sentence).strip()
    if not sentence or sentence.endswith("?"):
        return False
    match = _CLAIM.search(sentence)
    return bool(match) and not _NOT_A_REPORT.search(sentence[:match.start()])


def claims_state(sentence):
    """The sentence says what state something is in ("the TV is on"). Hedged or negated ones don't count."""
    sentence = _QUOTED.sub("", sentence).strip()
    if not sentence or sentence.endswith("?"):
        return False
    match = _STATE.search(sentence)
    if not match:
        return False
    before = sentence[:match.start()]
    return not re.search(r"\b(?:if|once|when|whether|unless|until|last I knew|I think|should|might|may|probably|"
                         r"supposed to|assuming|not sure|can't tell|don't know)\b", before, re.I)


def unbacked(sentence):
    """Why this sentence can't be said yet, or '' if it can. The test is what the tools proved this turn:
    having done something needs an action that was confirmed or accepted; having looked, or saying what state
    a thing is in, needs at least one tool to have succeeded. And when something this turn failed or couldn't be
    confirmed, a report of success has to mention the problem in the same breath."""
    if (claims_action(sentence) or claims_state(sentence)) and unresolved() and not _ADMITS.search(sentence):
        return "an action this turn failed or could not be confirmed, and this doesn't say so"
    if claims_action(sentence):
        if _LOOKED.search(sentence) or re.match(r"\s*I (?:checked|verified|confirmed|tested|searched)\b", sentence, re.I):
            return "" if tools_succeeded() else "no tool looked at anything this turn"
        return "" if action_backed() else "no action was confirmed or accepted this turn"
    if claims_state(sentence):
        return "" if tools_succeeded() else "nothing read that state this turn"
    return ""


def system_turn(text):
    """[REMINDER DUE], [PRESENCE GREETING]... come from Jarvis's own systems; [Via Phone] is the owner."""
    return bool(re.match(r"\s*\[(?!Via\b)", text))


class ClaimGate:
    """Holds a turn's speech from the first unbacked claim on, so a false report is never said aloud."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.held = []

    def admit(self, sentence):
        """True to speak the sentence now; False when it (and everything after it) is held."""
        if not self.enabled:
            return True
        if not self.held:
            self.why = unbacked(sentence)
        if self.held or self.why:
            self.held.append(sentence)
            return False
        return True

    def correction(self):
        """What the brain is told instead of the held words being spoken. Then the gate opens."""
        claim, self.enabled = " ".join(self.held), False
        self._log(claim)
        return ("[CLAIM CHECK - from your own systems, not the user] You were about to say: \"" + claim[:800] + "\" "
                f"It was not spoken, because {getattr(self, 'why', '') or 'nothing backs it'}. Answer the user again "
                "now, without mentioning this check. If it's an action they want, do it with the tool. If it's "
                "something you did or saw in an earlier turn, say that's when it was and that you haven't re-checked "
                "it, or check it now. If you can't back it, say plainly what you actually know.")

    @staticmethod
    def _log(claim):
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"t": time.time(), "held": claim[:500]}, ensure_ascii=False) + "\n")
        except OSError:
            pass


# ---------- Agent outcomes ----------

OUTCOME_INSTRUCTIONS = ("Finish your final message with one last line, exactly `OUTCOME: done`, `OUTCOME: partial`, "
                        "`OUTCOME: blocked` or `OUTCOME: failed`. done means everything asked for was finished and you "
                        "checked it. partial means some of it was. blocked means you couldn't start or continue without "
                        "the user. failed means you tried and it doesn't work. A finished investigation or recommendation "
                        "is done. When in doubt, choose the lesser one; Jarvis tells the user this word as fact.")
OUTCOMES = ("done", "partial", "blocked", "failed")
_OUTCOME_LINE = re.compile(r"(?:^|\n)[ \t>*_`]*OUTCOME\s*:\s*\**`?(done|partial|blocked|failed)\b[^\n]*\s*$", re.I)
# For a report with no OUTCOME line: agents reliably open with these when nothing was accomplished.
_UNFINISHED_OPENING = re.compile(
    r"\b(?:couldn[’']t (?:begin|start)|nothing was changed|no changes were made|can[’']t (?:begin|start|verify)|"
    r"did not (?:reliably )?(?:work|turn on|finish)|didn[’']t (?:work|finish)|remains? unresolved|is(?:n[’']t| not) running)\b",
    re.I)


def parse_outcome(report):
    """(outcome, report without the OUTCOME line). A missing line is judged from how the report opens."""
    text = str(report or "").strip()
    match = _OUTCOME_LINE.search(text)
    if match:
        return match.group(1).lower(), text[:match.start()].rstrip()
    return ("blocked" if _UNFINISHED_OPENING.search(text[:300]) else "done"), text


def is_success(outcome):
    return outcome == "done"


STATUS_WORDS = {"done": "finished", "partial": "only partly finished", "blocked": "got blocked",
                "failed": "didn't work", "stopped": "was stopped"}


def status_words(outcome):
    return STATUS_WORDS.get(outcome, "didn't finish")
