"""Memory proposals: facts and decisions found in the nightly journal, waiting for the owner's OK.

The journal is an AI summary, so nothing in it becomes memory by itself. harvest() turns its
"Facts to remember" and "Decisions" bullets into proposals; the owner approves or rejects them by
voice (review_memory_proposals / decide_memory_proposals) or on the Brain page. Only then does a
fact join saved memory (with its source) or a decision join the vault's decision log.
"""
import datetime
import hashlib
import json
import re
import threading
import time
from pathlib import Path

import knowledge
import memory
import privacy

HERE = Path(__file__).resolve().parent
STORE = HERE / "data" / "memory_proposals.json"
JOURNAL = "Journal"
DECISION_LOG = "Decisions/Decision log.md"
# Journal heading -> what an approved bullet becomes. Older journals mixed decisions and
# preferences under one heading; those are offered as facts.
HEADINGS = {"Facts to remember": "fact", "Decisions": "decision", "Decisions and preferences": "fact"}
MAX_KEPT = 500  # decided proposals are trimmed oldest-first; pending ones are always kept
LOCK = threading.RLock()


def _load():
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            data.setdefault("harvested", [])
            return data
    except (OSError, ValueError):
        pass
    return {"harvested": [], "items": []}


def _save(data):
    pending = [i for i in data["items"] if i["status"] == "pending"]
    decided = [i for i in data["items"] if i["status"] != "pending"][-MAX_KEPT:]
    data["items"] = sorted(pending + decided, key=lambda i: i["t"])
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STORE)


def _bullets(content, heading):
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", content, re.M | re.S)
    return [line.strip()[2:].strip() for line in (match.group(1).splitlines() if match else [])
            if line.strip().startswith(("- ", "* ")) and len(line.strip()) > 4]


def harvest(today=None) -> int:
    """Turn finished days' journal bullets into pending proposals. Each day is read once."""
    today = (today or datetime.date.today()).isoformat()
    folder = knowledge.VAULT / JOURNAL
    days = sorted(p.stem for p in folder.glob("*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)) \
        if folder.is_dir() else []
    added = 0
    with LOCK:
        data = _load()
        known = {memory._norm(i["text"]) for i in data["items"]}
        saved = memory.facts()
        for day in days:
            if day in data["harvested"] or day >= today:
                continue
            try:
                content = knowledge.read(f"{JOURNAL}/{day}.md")["content"]
            except (ValueError, OSError):
                continue
            for heading, kind in HEADINGS.items():
                for text in _bullets(content, heading):
                    text = privacy.redact(" ".join(text.split()))[:600]
                    key = memory._norm(text)
                    if key in known or any(memory._same(f, text) for f in saved):
                        continue
                    known.add(key)
                    ident = hashlib.sha256(f"{day}|{text}".encode()).hexdigest()[:10]
                    data["items"].append({"id": ident, "text": text, "kind": kind, "source": f"{JOURNAL}/{day}",
                                          "status": "pending", "t": time.time()})
                    added += 1
            data["harvested"].append(day)
        _save(data)
    return added


def pending():
    with LOCK:
        return [i for i in _load()["items"] if i["status"] == "pending"]


def count_line() -> str:
    """One line for working memory, or "" when nothing waits."""
    n = len(pending())
    if not n:
        return ""
    return (f"{n} memory proposal{'s' if n != 1 else ''} from the nightly journal await the owner's approval. "
            "Offer to go through them (review_memory_proposals) when there's a natural moment, not mid-task.")


def listing() -> str:
    items = pending()
    if not items:
        return "No memory proposals are waiting."
    lines = [f"{n}. [{i['kind']}] {i['text']} (from {i['source']})" for n, i in enumerate(items, 1)]
    return ("Proposals from the nightly journal (AI summaries of past conversations; not facts until the owner "
            "approves). Read them to the owner briefly and ask which to keep:\n" + "\n".join(lines))


def _which(spec, items):
    spec = (spec or "").strip().casefold()
    if spec == "all":
        return list(items)
    chosen = []
    for part in re.split(r"[,\s]+(?:and\s+)?|\s+and\s+", spec):
        if part.isdigit() and 1 <= int(part) <= len(items):
            chosen.append(items[int(part) - 1])
        elif part:
            match = [i for i in items if i["id"] == part]
            if not match:
                raise ValueError(f"No waiting proposal '{part}'. List them again with review_memory_proposals.")
            chosen += match
    if not chosen:
        raise ValueError("Say which proposals: numbers from the latest list, or 'all'.")
    return list({i["id"]: i for i in chosen}.values())


def _log_decision(text, source):
    """Append an approved decision to the vault's decision log, history kept by appending."""
    day = source.rsplit("/", 1)[-1]
    entry = (f"\n## {day}: {text}\n- Status: active\n- Source: [[{source}]], approved by the owner "
             f"{datetime.date.today().isoformat()}\n")
    with knowledge.LOCK:
        path = knowledge.note_path(DECISION_LOG)
        if not path.exists():
            knowledge.create(DECISION_LOG, "---\ntype: decisions\n---\n\n# Decision log\n\nDecisions the owner "
                             "approved, newest last. When one changes, add the new decision and mark the old one "
                             "superseded rather than deleting it.\n")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(entry)


def decide(which: str, approve: bool, reword: str = "") -> str:
    """Approve or reject waiting proposals. `reword` replaces the text of a single approved item."""
    with LOCK:
        data = _load()
        waiting = [i for i in data["items"] if i["status"] == "pending"]
        chosen = _which(which, waiting)
        if reword and (len(chosen) != 1 or not approve):
            raise ValueError("Reword one approved proposal at a time.")
        done = []
        for item in chosen:
            text = privacy.redact(reword.strip())[:2000] if reword else item["text"]
            if approve:
                if item["kind"] == "decision":
                    _log_decision(text, item["source"])
                else:
                    memory.remember(text, source=f"{item['source']} (journal proposal, approved by the owner)")
            item.update(status="approved" if approve else "rejected", decided=time.time(),
                        **({"text": text} if reword else {}))
            done.append(text)
        _save(data)
    verb = "Saved" if approve else "Dropped"
    left = len(waiting) - len(chosen)
    return f"{verb} {len(done)}: " + " | ".join(done) + f". {left} still waiting."


def snapshot():
    return {"pending": pending()}
