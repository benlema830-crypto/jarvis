"""The Decision log: decisions found in each day's journal, kept in one vault note.

The nightly journal lists the day's decisions. Each finished day is read once and its decisions are appended to
Decisions/Decision log.md, marked as the journal's summary (an AI wrote it; the owner didn't sign each line).

There is no approval queue any more. The old one filled with 129 proposals and one approval in three weeks, so
nothing reached memory. Facts about the owner are now saved only when they say them (the `remember` tool, in
that turn, in their words); the journal's own "facts" were mostly one-day choices and are not harvested.
"""
import datetime
import json
import re
import threading
from pathlib import Path

import knowledge
import privacy

HERE = Path(__file__).resolve().parent
STORE = HERE / "data" / "decision_log.json"
OLD_STORE = HERE / "data" / "memory_proposals.json"  # the retired queue; its list of days already read is reused
JOURNAL = "Journal"
DECISION_LOG = "Decisions/Decision log.md"
HEADING = "Decisions"
HEADER = ("---\ntype: decisions\n---\n\n# Decision log\n\nDecisions taken from the daily journal, newest last. "
          "When one changes, add the new decision and mark the old one superseded rather than deleting it.\n")
LOCK = threading.RLock()


def _days_read():
    for path in (STORE, OLD_STORE):
        try:
            days = json.loads(path.read_text(encoding="utf-8")).get("harvested")
            if isinstance(days, list):
                return [d for d in days if isinstance(d, str)]
        except (OSError, ValueError, AttributeError):
            continue
    return []


def _save(days):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"harvested": sorted(set(days))[-800:]}, indent=1), encoding="utf-8")
    tmp.replace(STORE)


def _bullets(content, heading):
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", content, re.M | re.S)
    return [line.strip()[2:].strip() for line in (match.group(1).splitlines() if match else [])
            if line.strip().startswith(("- ", "* ")) and len(line.strip()) > 4]


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def add(text, source):
    """Append one decision. Returns False when the same words are already in the log."""
    text = privacy.redact(" ".join(str(text).split()))[:600]
    if not text:
        return False
    day = source.rsplit("/", 1)[-1]
    with knowledge.LOCK:
        path = knowledge.note_path(DECISION_LOG)
        if not path.exists():
            knowledge.create(DECISION_LOG, HEADER)
        if _norm(text) in _norm(path.read_text(encoding="utf-8")):
            return False
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## {day}: {text}\n- Status: active\n- Source: [[{source}]] (the journal's summary of "
                         f"that day, added {datetime.date.today().isoformat()})\n")
    return True


def harvest(today=None) -> int:
    """Log the decisions from finished days' journal notes. Each day is read once. Returns how many were added."""
    today = (today or datetime.date.today()).isoformat()
    folder = knowledge.VAULT / JOURNAL
    days = sorted(p.stem for p in folder.glob("*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)) \
        if folder.is_dir() else []
    added = 0
    with LOCK:
        read = _days_read()
        for day in days:
            if day in read or day >= today:
                continue
            try:
                content = knowledge.read(f"{JOURNAL}/{day}.md")["content"]
            except (ValueError, OSError):
                continue
            added += sum(add(text, f"{JOURNAL}/{day}") for text in _bullets(content, HEADING))
            read.append(day)
        _save(read)
    return added
