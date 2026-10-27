"""Adaptive effort: learn from past tasks which kinds need harder thinking.

Every background task (screen agent, Claude Code, Codex) is recorded with the effort it
ran at and how it went. Before a new task, the most similar past tasks of the same kind
decide where to start:
  - nothing similar yet, or similar tasks went smoothly -> the agent's normal effort
  - the latest similar task was hard (failed, gave up, ran long, or had to escalate)
    -> start one level higher
  - two similar tasks in a row were quick at the higher level -> drop back to normal,
    so a one-off struggle doesn't slow that kind of task forever
Only the escalation is ever above normal, so ordinary tasks are never made slower.
User stops aren't counted as failures. Data stays in data/task_effort.jsonl.
"""
import json
import re
import sys
import threading
import time
from pathlib import Path

PATH = DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "task_effort.jsonl"
KEEP = 500           # newest records kept
SIMILAR = 0.35       # word-overlap needed to count as "a task like this"
LONG_SECONDS = {"screen": 240, "terminal": 600, "codex": 600}
QUICK_SECONDS = {"screen": 60, "terminal": 180, "codex": 180}
GAVE_UP = re.compile(r"\b(couldn'?t|could not|unable|blocked|blocker|ran out of time|taking too long|"
                     r"stopped after|failed|not verified|unverified)\b", re.I)
STOP_WORDS = set("""a an and are as at be but by can could do does for from get go have how i if in into is it
its me my now of on or our please so some that the then this to up us we what when with would you your
jarvis just also want need make sure""".split())
_lock = threading.Lock()


def words(task: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", task.lower()) if len(w) > 2 and w not in STOP_WORDS}


def similarity(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _read() -> list[dict]:
    try:
        lines = PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def hard(row: dict) -> bool:
    if row.get("stopped_by_user"):
        return False
    return (not row.get("ok") or row.get("escalated") or GAVE_UP.search(row.get("report", "")) is not None
            or row.get("seconds", 0) > LONG_SECONDS.get(row.get("kind"), 600))


def choose(kind: str, task: str, normal: str, higher: str) -> tuple[str, str]:
    """Pick the starting effort for a task. Returns (effort, short reason)."""
    mine = words(task)
    similar = [r for r in reversed(_read()) if r.get("kind") == kind
               and similarity(mine, set(r.get("words", []))) >= SIMILAR and not r.get("stopped_by_user")]
    if not similar:
        return normal, "new kind of task"
    last = similar[0]
    if hard(last):
        return higher, "a similar task was hard last time"
    if last.get("effort") == higher:
        quick = 0
        for r in similar:
            if r.get("effort") != higher or hard(r) or r.get("seconds", 1e9) > QUICK_SECONDS.get(kind, 180):
                break
            quick += 1
        return (normal, "similar tasks are now quick") if quick >= 2 else (higher, "similar tasks needed more thought")
    return normal, "similar tasks went smoothly"


def record(kind: str, task: str, effort: str, ok: bool, seconds: float, report: str = "",
           steps: int = 0, escalated: bool = False, stopped_by_user: bool = False):
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    if PATH == DEFAULT_PATH and spec and spec.name.startswith("unittest"):
        return  # test runs exercise agents with fake tasks; keep them out of the real history
    row = {"t": time.time(), "kind": kind, "words": sorted(words(task)), "effort": effort, "ok": bool(ok),
           "seconds": round(seconds, 1), "steps": steps, "escalated": escalated,
           "stopped_by_user": stopped_by_user, "report": (report or "")[:300]}
    with _lock:
        try:
            rows = _read()[-(KEEP - 1):] + [row]
            PATH.parent.mkdir(parents=True, exist_ok=True)
            PATH.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        except OSError:
            pass
