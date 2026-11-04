"""Keeps what Jarvis says tied to what actually happened.

Three small jobs, all plain rules so they cost no time:
  - ClaimGate: a spoken "I've turned it off" in a turn where no tool succeeded is held back, and the
    brain is asked to do the thing or say the truth instead (instructions alone didn't stop this).
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
            r"tested|looked up|searched|scheduled|booked|paused|resumed|played|muted|unmuted|dimmed|"
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
UNTRUSTED_TOOLS = {"check_email", "read_email", "read_clipboard", "look_at_screen", "look_through_camera",
                   "web_search", "WebSearch", "WebFetch", "call_mcp_tool"}

_lock = threading.Lock()
_succeeded = 0
_tainted = False


def begin_turn():
    global _succeeded, _tainted
    with _lock:
        _succeeded, _tainted = 0, False


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
        if self.held or (tools_succeeded() == 0 and claims_action(sentence)):
            self.held.append(sentence)
            return False
        return True

    def correction(self):
        """What the brain is told instead of the held words being spoken. Then the gate opens."""
        claim, self.enabled = " ".join(self.held), False
        self._log(claim)
        return ("[CLAIM CHECK - from your own systems, not the user] You were about to say: \"" + claim[:800] + "\" "
                "It was not spoken, because no tool succeeded this turn, so nothing backs it. Answer the user again now, "
                "without mentioning this check. If it's an action they want, do it with the tool. If it's something you "
                "did in an earlier turn, say that's when it was and that you haven't re-checked it, or check it now. "
                "If you can't back it, say plainly what you actually know.")

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
