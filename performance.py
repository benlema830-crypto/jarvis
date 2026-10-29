"""Performance records and the scorecard: how fast Jarvis answers and how agent work goes.

  data/turn_metrics.jsonl  one line per conversation turn: which model answered, time to the
                           first spoken sentence and to the end. No words are stored.
  data/task_effort.jsonl   one line per background task (written by task_effort.py).

scorecard() summarizes both per model and per kind of task, so a new model can be compared with
the current one on real use (and with scripts/benchmark_models.py on a fixed prompt set).
"""
import json
import statistics
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TURNS = DEFAULT_TURNS = HERE / "data" / "turn_metrics.jsonl"
KEEP_TURNS = 5000
_lock = threading.Lock()


def record_turn(provider, model, local, first_sentence, total, outcome):
    """outcome: "ok", "interrupted" or "failed". Times in seconds (first_sentence may be None)."""
    if TURNS == DEFAULT_TURNS and under_test():
        return  # test runs drive the brain with fake models; keep them out of the real record
    entry = {"t": time.time(), "provider": provider, "model": model, "local": bool(local),
             "first": round(first_sentence, 2) if first_sentence is not None else None,
             "total": round(total, 2), "outcome": outcome}
    with _lock:
        TURNS.parent.mkdir(parents=True, exist_ok=True)
        with TURNS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        if TURNS.stat().st_size > KEEP_TURNS * 300:  # trim rarely, keeping the newest
            lines = TURNS.read_text(encoding="utf-8").splitlines()[-KEEP_TURNS:]
            TURNS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def under_test() -> bool:
    """True when the process was started by unittest (same rule as task_effort.record)."""
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    return bool(spec and spec.name.startswith("unittest"))


def _rows(path, since):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("t", 0) >= since:
            rows.append(row)
    return rows


def _pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


def conversation(days=14, now=None):
    """Per model: turns, median and p90 seconds to the first sentence, failures."""
    since = (now or time.time()) - days * 86400
    groups = defaultdict(list)
    for row in _rows(TURNS, since):
        groups[f"{row.get('provider')}/{row.get('model')}" + (" (local router)" if row.get("local") else "")].append(row)
    out = {}
    for name, rows in groups.items():
        firsts = [r["first"] for r in rows if r.get("first") is not None]
        out[name] = {"turns": len(rows), "failed": sum(r.get("outcome") == "failed" for r in rows),
                     "first_median_s": round(statistics.median(firsts), 1) if firsts else None,
                     "first_p90_s": round(_pct(firsts, 0.9), 1) if firsts else None}
    return out


def tasks(days=30, now=None):
    """Per kind of background task: count, finished, median minutes, stopped by the user, recent misses."""
    import task_effort
    since = (now or time.time()) - days * 86400
    groups = defaultdict(list)
    for row in _rows(Path(task_effort.PATH), since):
        groups[row.get("kind", "?")].append(row)
    out = {}
    for kind, rows in groups.items():
        hard = [r for r in rows if task_effort.GAVE_UP.search(r.get("report") or "") or not r.get("ok")]
        out[kind] = {"tasks": len(rows), "finished": sum(bool(r.get("ok")) for r in rows),
                     "struggled": len(hard), "stopped_by_user": sum(bool(r.get("stopped_by_user")) for r in rows),
                     "median_min": round(statistics.median(r.get("seconds", 0) for r in rows) / 60, 1),
                     "recent_struggles": [" ".join((r.get("report") or "").split())[:160] for r in hard[-3:]]}
    return out


def scorecard(days=14) -> str:
    """Plain-text scorecard for Jarvis, the daily review and the owner."""
    lines = [f"Conversation, last {days} days (time to first spoken sentence):"]
    talk = conversation(days)
    if not talk:
        lines.append("- No timed turns yet.")
    for name, s in sorted(talk.items(), key=lambda kv: -kv[1]["turns"]):
        lines.append(f"- {name}: {s['turns']} turns, median {s['first_median_s']}s, slowest tenth "
                     f"{s['first_p90_s']}s+, {s['failed']} failed")
    lines.append(f"Background tasks, last {max(days, 30)} days:")
    work = tasks(max(days, 30))
    if not work:
        lines.append("- No tasks recorded.")
    for kind, s in sorted(work.items()):
        lines.append(f"- {kind}: {s['tasks']} tasks, {s['finished']} finished, {s['struggled']} struggled "
                     f"or reported a blocker, {s['stopped_by_user']} stopped by the user, median {s['median_min']} min")
        for text in s["recent_struggles"]:
            lines.append(f"    struggle: {text}")
    return "\n".join(lines)
