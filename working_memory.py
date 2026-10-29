"""Working memory: a compact brief of where things stand, so Jarvis knows where we left off.

Assembled on demand from what is already recorded, with no AI call and no store of its own:
  - agent sessions (data/agent_sessions.json): running work and recent results
  - open to-dos (the vault's Tasks.md)
  - open threads and decisions from recent days (the vault's Journal/, summarized nightly by Codex)
  - each project's latest handoff (data/handoffs/)
  - how many memory proposals wait for the owner's approval (memory_proposals.py)

jarvis.py adds the brief to the conversation whenever it changes, and the startup briefing uses it.
Everything here is a record or an AI summary, so the brief says where each part came from.
"""
import datetime
import json
import re
import time
from pathlib import Path

import knowledge
import privacy

HERE = Path(__file__).resolve().parent
SESSIONS = HERE / "data" / "agent_sessions.json"
HANDOFFS = HERE / "data" / "handoffs"
JOURNAL = "Journal"

SESSION_DAYS = 7      # finished agent work older than this is left out
JOURNAL_DAYS = 3      # recent journal notes read for open threads and decisions
HANDOFF_DAYS = 30
MAX_CHARS = 3500      # the whole brief; each part is also capped
LIVE = {"running", "waiting", "paused"}


def _ago(t, now):
    """Absolute, so the brief stays identical between turns and is only re-sent when work changes."""
    when, today = datetime.datetime.fromtimestamp(t), datetime.datetime.fromtimestamp(now).date()
    if when.date() == today:
        return when.strftime("today %H:%M")
    return when.strftime("%a %b %d %H:%M")


def _clip(text, limit):
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", str(text or ""))  # markdown links -> their text
    text = " ".join(text.replace("**", "").replace("`", "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def agent_work(now=None):
    now = now or time.time()
    try:
        raw = json.loads(SESSIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    sessions = raw.get("sessions", {}) if isinstance(raw, dict) else {}
    sessions = list(sessions.values()) if isinstance(sessions, dict) else []
    lines = []
    for s in sorted((s for s in sessions if isinstance(s, dict)), key=lambda s: -(s.get("reported_at") or 0)):
        status, when = s.get("status") or "idle", s.get("reported_at") or 0
        live = status in LIVE
        if not s.get("task") or not (live or now - when < SESSION_DAYS * 86400):
            continue
        head = f"- {s.get('name', '?')} ({s.get('project', '?')}): {status}"
        if not live and when:
            head += f", {_ago(when, now)}"
        line = head + f". Task: {_clip(s.get('task'), 160)}"
        if s.get("report") and not live:
            line += f" Result: {_clip(s['report'], 220)}"
        lines.append(line)
    return lines[:5]


def open_tasks():
    import tasks
    try:
        return [f"- {t['text']}" for t in tasks.items() if not t["done"]][:10]
    except (OSError, ValueError):
        return []


def _section(content, heading):
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", content, re.M | re.S)
    if not match:
        return []
    return [line.strip()[2:].strip() for line in match.group(1).splitlines()
            if line.strip().startswith(("- ", "* ")) and len(line.strip()) > 2]


def journal(today=None):
    """(open threads, decisions) from the latest journal notes, newest first, without repeats."""
    today = today or datetime.date.today()
    threads, decisions, seen = [], [], set()
    for back in range(0, 14):
        if len({d for d, _ in threads + decisions}) >= JOURNAL_DAYS:
            break
        day = (today - datetime.timedelta(days=back)).isoformat()
        try:
            content = knowledge.read(f"{JOURNAL}/{day}.md")["content"]
        except (ValueError, OSError):
            continue
        for heading, out in (("Open threads", threads), ("Decisions", decisions), ("Decisions and preferences", decisions)):
            for item in _section(content, heading):
                key = item.casefold()
                if key not in seen:
                    seen.add(key)
                    out.append((day, item))
    return threads[:8], decisions[:6]


def handoffs(now=None):
    now = now or time.time()
    lines = []
    if not HANDOFFS.is_dir():
        return lines
    for folder in sorted(p for p in HANDOFFS.iterdir() if p.is_dir()):
        for path in sorted(folder.glob("*.json"), reverse=True):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                when = datetime.datetime.fromisoformat(entry["created_at"]).timestamp()
            except (OSError, ValueError, KeyError, TypeError):
                continue
            claims = entry.get("claims") or {}
            if now - when < HANDOFF_DAYS * 86400 and (claims.get("next_action") or claims.get("summary")):
                text = claims.get("next_action") or claims.get("summary")
                lines.append(f"- {folder.name} ({_ago(when, now)}): next: {_clip(text, 220)}")
            break
    return lines


def brief(now=None, today=None) -> str:
    """The working-memory brief, or "" when nothing is recorded."""
    parts = []
    work = agent_work(now)
    if work:
        parts.append("Agent work (from agent session records):\n" + "\n".join(work))
    todo = open_tasks()
    if todo:
        parts.append("Open to-dos (Tasks.md):\n" + "\n".join(todo))
    threads, decisions = journal(today)
    if threads:
        parts.append("Open threads (nightly AI summaries of past conversations; may be resolved since):\n"
                     + "\n".join(f"- {item} ({day})" for day, item in threads))
    if decisions:
        parts.append("Recent decisions and preferences (same AI summaries; not confirmed facts):\n"
                     + "\n".join(f"- {item} ({day})" for day, item in decisions))
    projects = handoffs(now)
    if projects:
        parts.append("Project handoffs:\n" + "\n".join(projects))
    import memory_proposals
    if waiting := memory_proposals.count_line():
        parts.append(waiting)
    text = "\n\n".join(parts)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS - 1].rstrip() + "…"
    return privacy.redact(text)
