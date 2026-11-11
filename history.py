"""Looking back: search what was said in earlier conversations, and a readable copy of what Jarvis remembers.

  search()        every saved conversation line (data/transcripts/, one file per day) by plain words. Finished
                  agent jobs are already searchable as vault notes (Reports/) through search_knowledge.
  write_mirror()  Memory/What Jarvis knows about you.md in the vault: the saved facts, each with when it was
                  saved, where it came from and any earlier wording. A copy for reading; memory.json stays the
                  record, and edits are made by telling Jarvis or in More > Memory & privacy.
  learned()       facts saved in the last few days, for the weekly "anything wrong?" check.
"""
import datetime
import json
import math
import re
import time
from pathlib import Path

import privacy

HERE = Path(__file__).resolve().parent
TRANSCRIPTS = HERE / "data" / "transcripts"
MIRROR = "Memory/What Jarvis knows about you.md"
WHO = {"you": "You", "jarvis": "Jarvis"}
_STOP = {"the", "a", "an", "is", "are", "was", "were", "of", "and", "or", "to", "in", "on", "for", "my", "me", "i",
         "we", "you", "it", "that", "this", "did", "do", "what", "when", "about", "said", "say", "with", "have", "had"}


def _terms(text):
    return [w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in _STOP and len(w) > 1]


def _rows(days):
    """(day, time, who, text) for each spoken or typed line in the last `days` days, oldest first."""
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    for path in sorted(TRANSCRIPTS.glob("*.jsonl")) if TRANSCRIPTS.is_dir() else []:
        if path.stem < since:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") in WHO and isinstance(event.get("text"), str) and event["text"].strip():
                clock = time.strftime("%H:%M", time.localtime(event.get("t", 0)))
                yield path.stem, clock, WHO[event["type"]], " ".join(event["text"].split())


def search(query: str, days: int = 60, limit: int = 8) -> str:
    """Lines from earlier conversations that match the words, best first, each with the line after it."""
    days, limit = max(1, min(730, int(days))), max(1, min(20, int(limit)))
    terms = _terms(query or "")
    if not terms:
        return "Give a few words to look for in earlier conversations."
    rows = list(_rows(days))
    if not rows:
        return f"No saved conversations in the last {days} days."
    words = [set(_terms(text)) for _, _, _, text in rows]
    weight = {t: math.log(1 + len(rows) / (1 + sum(t in w for w in words))) for t in terms}
    scored = sorted(((sum(weight[t] for t in terms if t in w), i) for i, w in enumerate(words)), key=lambda p: (-p[0], -p[1]))
    best = scored[0][0]
    if best <= 0:
        return f"Nothing in the last {days} days of conversation matches '{privacy.redact(query)}'."
    out, used = [], set()
    for score, i in scored:
        if score < best * 0.6 or len(out) >= limit:
            break
        if i in used:
            continue
        day, clock, who, text = rows[i]
        line = f"- {day} {clock} {who}: {text[:320]}"
        if i + 1 < len(rows) and rows[i + 1][0] == day and i + 1 not in used:  # what was said next, for context
            line += f"\n    then {rows[i + 1][2]}: {rows[i + 1][3][:240]}"
            used.add(i + 1)
        used.add(i)
        out.append(line)
    return privacy.redact(f"Earlier conversation matching '{query}' (a record of what was said then; things may have "
                          "changed since):\n" + "\n".join(out))


def learned(days: int = 7, now=None) -> list[str]:
    """Facts saved or changed in the last `days` days, oldest first."""
    import memory
    now = now or time.time()
    items = [i for i in memory._load() if now - memory._when(i) < days * 86400]
    return [" ".join(i["fact"].split()) for i in sorted(items, key=memory._when)]


def weekly_line(now=None) -> str:
    """One spoken sentence for the weekly check, or "" when nothing new was saved."""
    new = learned(7, now)
    if not new:
        return ""
    return (f"This week I saved {len(new)} thing{'s' if len(new) != 1 else ''} about you. The full list is in your "
            "vault under Memory. Tell me if any of it is wrong and I'll fix it.")


def mirror_text(items) -> str:
    day = lambda t: time.strftime("%Y-%m-%d", time.localtime(t)) if t else "unknown date"
    lines = ["---", "type: memory", "generated: true", "---", "", "# What Jarvis knows about you", "",
             f"{len(items)} saved facts, newest first. This note is rewritten whenever memory changes, so edits made "
             "here are lost. To change something, tell Jarvis (\"that's wrong, it's ...\", \"forget that ...\") or use "
             "More > Memory & privacy on the Jarvis page.", ""]
    for item in sorted(items, key=lambda i: -(i.get("updated") or i.get("t") or 0)):
        note = f"saved {day(item.get('t'))}"
        if item.get("updated"):
            note += f", changed {day(item['updated'])}"
        if item.get("source"):
            note += f", from {item['source']}"
        lines.append(f"- {' '.join(item['fact'].split())}  \n  _{note}_")
        for old in (item.get("history") or [])[::-1][:3]:
            lines.append(f"  - earlier, until {day(old.get('until'))}: {' '.join(old['fact'].split())}")
    return privacy.redact("\n".join(lines) + "\n")


def write_mirror(items) -> bool:
    """Rewrite the vault note from the saved facts. Never raises; returns whether it was written."""
    import testing_guard
    if testing_guard.under_test():
        return False  # tests save fake facts; the owner's vault is not theirs to write
    try:
        import knowledge
        if not knowledge.VAULT.is_dir():
            return False
        path = knowledge.VAULT.joinpath(*MIRROR.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(mirror_text(items), encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        return False
