"""The agent board's data: every agent and what it is doing, shaped for one page read at a glance (hud/board.html).

hud.py serves snapshot() at /agents. It is the agent sessions (agent_sessions.MANAGER.snapshot()) cut down to what
a card shows, plus the parallel job that is running (parallel.GROUPS): its goal, its stages and each round's
agents. It only reads; nothing here starts, stops or changes an agent.
"""
import ntpath
import time

LIVE = ("running", "waiting")
LEAD = "Parallel Lead"
MAX_ROUNDS = 5      # parallel.MAX_ROUNDS; repeated so this module can be read and tested without the agents loaded
STEPS = 5           # of an agent's latest actions
EARLIER = 12        # finished agents listed
SHELL = '"C:\\\\Windows\\\\System32\\\\WindowsPowerShell\\\\v1.0\\\\powershell.exe" -Command '


def short(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _step(event):
    """One action in words: what the worker itself reported, without the shell's own path in front."""
    label, detail = str(event.get("label") or ""), str(event.get("detail") or "")
    if detail.startswith(SHELL):
        detail = detail[len(SHELL):].strip('"')
    if detail == "fileChange":
        detail = ""
    text = detail if label == "Worker activity" and detail else f"{label}: {detail}" if detail else label
    return {"text": short(text, 160), "state": str(event.get("status") or ""), "at": _number(event.get("started_at"))}


def _card(entry, role, now):
    status = str(entry.get("status") or "idle")
    live = status in LIVE
    started, updated = _number(entry.get("started_at")), _number(entry.get("updated_at"))
    seconds = (now if live else updated) - started if started else 0
    return {
        "name": entry.get("name", ""), "role": role, "status": status, "live": live,
        "model": entry.get("model_words") or str(entry.get("provider") or "").capitalize(),
        "mode": entry.get("mode") or "", "project": entry.get("project") or "",
        "folder": ntpath.basename(str(entry.get("cwd") or "").rstrip("\\/")),
        "task": short(entry.get("task"), 600), "doing": short(entry.get("progress"), 400),
        "steps": [_step(e) for e in (entry.get("timeline") or [])[-STEPS:]],
        "seconds": max(0, round(seconds)), "quiet": max(0, round(now - updated)) if live and updated else 0,
        "updated_at": updated, "files": len(entry.get("changed_files") or []),
        "evidence": short(entry.get("evidence"), 200), "report": "" if live else short(entry.get("report"), 1200),
    }


def _stages(group):
    """The job's steps in order, each done, now or next. A led job plans, runs a round, checks it, and either
    runs another round or answers; how many rounds there will be isn't known until the lead decides."""
    lead, current = group.get("lead"), int(group.get("round") or 1)
    if not lead:
        return [{"label": "Agents", "state": "now"}, {"label": "Answer", "state": "next"}]
    phase = lead.get("phase")
    stages = [{"label": "Plan", "state": "now" if phase == "planning" else "done"}]
    for number in range(1, current + 1):
        past = number < current
        running = not past and phase == "working"
        checking = not past and phase == "merging"
        stages.append({"label": f"Round {number}",
                       "state": "done" if past or checking else "now" if running else "next"})
        stages.append({"label": "Check", "state": "done" if past else "now" if checking else "next"})
    return stages + [{"label": "Answer", "state": "next"}]


def _job(group, now):
    lead = group.get("lead")
    rounds = {}
    for item in [*group.get("earlier", []), *group.get("parts", {}).values()]:
        rounds.setdefault(int(item.get("round") or 1), []).append(
            {"name": item.get("name", ""), "outcome": str(item.get("outcome") or "")})
    return {"goal": short(group.get("goal"), 400), "mode": group.get("mode") or "", "round": int(group.get("round") or 1),
            "max_rounds": MAX_ROUNDS, "seconds": max(0, round(now - _number(group.get("began")))),
            "lead": {"model": lead.get("words", ""), "phase": lead.get("phase", "")} if lead else None,
            # between rounds, on a wait the lead ordered for a long run: seconds until the next round starts
            "wait": max(0, round(_number(group.get("wait_until")) - now)) if lead and lead.get("phase") == "waiting" else 0,
            "stages": _stages(group), "note": short(group.get("note"), 300),
            "rounds": [{"round": number, "parts": parts} for number, parts in sorted(rounds.items())]}


def snapshot(sessions, groups, now=None):
    """{"now", "job", "agents", "counts"}: the running parallel job (or None), then a card for each agent - the
    job's lead and this round's agents first, then anything else working, then what finished most recently."""
    now = now or time.time()
    with groups.lock:
        group = next(iter(groups.groups.values()), None)
        job = _job(group, now) if group else None
        members = list(group["parts"]) if group else []
        led = bool(group and group.get("lead"))
    entries = {str(e.get("name", "")).casefold(): e for e in sessions.get("sessions", [])}
    cards = []
    if led and LEAD.casefold() in entries:
        cards.append(_card(entries.pop(LEAD.casefold()), "lead", now))
    cards += [_card(entries.pop(key), "part", now) for key in members if key in entries]
    rest = [_card(e, "solo", now) for e in entries.values()
            if e.get("task") or e.get("status") not in ("ready", "idle", None)]  # never given a task: nothing to show
    working = sorted((c for c in rest if c["live"]), key=lambda c: -c["seconds"])
    finished = sorted((c for c in rest if not c["live"]), key=lambda c: -c["updated_at"])[:EARLIER]
    cards += working + finished
    return {"now": now, "job": job, "agents": cards,
            "counts": {"working": sum(c["live"] for c in cards),
                       "done": sum(c["status"] == "completed" for c in cards),
                       "failed": sum(c["status"] == "failed" for c in cards)}}
