"""The numbers the owner feels, from saved records. Read-only; prints one table.

    .venv\\Scripts\\python.exe scripts\\measure.py [--days 7] [--since 2026-11-10]

data/turn_stages.jsonl  each turn's stages in ms after the end of speech (voice) or the keypress (typed),
                        plus every tool that ran and whether it worked (written by runtime_metrics.py)
data/turn_metrics.jsonl older record: seconds from the brain being asked to its first sentence
data/claim_checks.jsonl each reply the claim gate stopped because no receipt backed it (truth_guard.py)
"""
import argparse
import datetime
import json
import statistics
import time
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def rows(name, since):
    try:
        lines = (DATA / name).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("t", 0) >= since:
            out.append(row)
    return out


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


def line(label, values, unit="s", scale=1.0):
    if not values:
        return f"{label:<46} no data yet"
    values = [v * scale for v in values]
    return (f"{label:<46} median {statistics.median(values):5.1f}{unit}   slowest tenth {pct(values, .9):5.1f}{unit}+"
            f"   n={len(values)}")


def report(since):
    out = [f"Since {datetime.datetime.fromtimestamp(since):%Y-%m-%d %H:%M}"]
    stages = rows("turn_stages.jsonl", since)
    for source, name in (("voice", "Spoken"), ("keyboard", "Typed")):
        turns = [r for r in stages if r.get("source") == source]
        plain = [r for r in turns if not r.get("tools")]
        tooled = [r for r in turns if r.get("tools")]
        heard = "first_audio" if source == "voice" else "first_text"
        what = "first audio" if source == "voice" else "first text"
        out.append(line(f"{name}, no tool: to {what}", [r["stages"][heard] for r in plain if heard in r["stages"]], scale=.001))
        out.append(line(f"{name}, with a tool: to {what}", [r["stages"][heard] for r in tooled if heard in r["stages"]], scale=.001))
    calls = [t for r in stages for t in r.get("tools", [])]
    if calls:
        failed = Counter(t["name"] for t in calls if not t.get("ok"))
        out.append(f"{'Tool calls':<46} {len(calls)} run, {sum(failed.values())} failed "
                   f"({100 * sum(failed.values()) / len(calls):.1f}%)"
                   + (f"   most: {', '.join(f'{n} x{c}' for n, c in failed.most_common(3))}" if failed else ""))
        out.append(line("Tool run time", [t["ms"] for t in calls], scale=.001))
    else:
        out.append(f"{'Tool calls':<46} no data yet")
    brain = rows("turn_metrics.jsonl", since)
    firsts = [r["first"] for r in brain if r.get("first") is not None]
    out.append(line("Brain asked -> first sentence (all turns)", firsts))
    if brain:
        cut = sum(r.get("outcome") == "interrupted" for r in brain)
        out.append(f"{'Turns cut off by the owner':<46} {cut} of {len(brain)} ({100 * cut / len(brain):.0f}%)")
        out.append(f"{'Turns with first sentence under 1 s':<46} {sum(f < 1 for f in firsts)} of {len(firsts)}")
    proof = Counter(t["receipt"] for t in calls if t.get("receipt"))
    if proof:
        out.append(f"{'Action receipts':<46} " + ", ".join(f"{count} {status}" for status, count in proof.most_common()))
    stopped = rows("claim_checks.jsonl", since)
    out.append(f"{'Unbacked claims stopped before being spoken':<46} {len(stopped)}"
               + (f" in {len(stages)} turns" if stages else ""))
    tasks = rows("task_effort.jsonl", since)
    for kind in sorted({t.get("kind") for t in tasks}):
        mine = [t for t in tasks if t.get("kind") == kind]
        out.append(f"{'Background work: ' + str(kind):<46} {sum(bool(t.get('ok')) for t in mine)} of {len(mine)} finished, "
                   f"median {statistics.median(t.get('seconds', 0) for t in mine) / 60:.1f} min")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=float, default=7)
    parser.add_argument("--since", help="YYYY-MM-DD or YYYY-MM-DDTHH:MM; overrides --days")
    args = parser.parse_args()
    since = (datetime.datetime.fromisoformat(args.since).timestamp() if args.since
             else time.time() - args.days * 86400)
    print(report(since))


if __name__ == "__main__":
    main()
