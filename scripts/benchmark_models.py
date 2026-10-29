"""Compare conversation models on the same questions before switching Jarvis's brain.

Each model answers a fixed set of Jarvis-style questions in one conversation, the way Jarvis
uses it. The report records time to the first sentence and to the end, plus every answer, so
quality can be judged side by side. Real conversation history and timing logs are not touched.

Usage (from the Jarvis folder):
  .venv\\Scripts\\python.exe scripts\\benchmark_models.py codex:gpt-6.1-terra claude_code:claude-opus-5-5
  options: --prompts N (use the first N questions), --allow-paid (needed for anthropic/openai,
  which spend API credits; codex, claude_code and ollama use subscriptions or the local model)
Report: data/reports/model-benchmark-<date>-<time>.md
"""
import argparse
import datetime
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAID = {"anthropic", "openai"}
# Questions that need judgment, not tools, so no model acts on the PC during a benchmark.
PROMPTS = [
    "How many minutes are in a day and a half? Just the number.",
    "In two sentences: what's the difference between RAM and storage?",
    "Without looking anything up, where do my projects stand and what should I pick up next?",
    "I want to sell an AI clipping service to streamers. Give me the two biggest risks and one way to test demand this week.",
    "Be honest: is it smarter to keep polishing my Roblox game or ship the private test now? Short answer with your reason.",
    "Rewrite this to sound confident and brief: 'um so I was kind of wondering if maybe we could push the meeting'.",
]


def run_model(spec, prompts):
    import jarvis
    import model_provider
    provider, model = spec.split(":", 1)
    brain = jarvis.Brain()
    brain.selection = model_provider.Selection(persist=lambda config: None)
    brain.selection.active = {"provider": provider, "model": model}
    brain.selection.ready = True
    rows = []
    with mock.patch.object(jarvis.router, "choose", return_value=None):  # the model itself, not the local router
        for prompt in prompts:
            said, first = [], []
            began = time.monotonic()

            def speak(sentence):
                if not first:
                    first.append(time.monotonic() - began)
                said.append(sentence)
            try:
                brain.ask(prompt, speak)
                error = ""
            except Exception as exc:  # one failed question shouldn't end the run
                error = f"{type(exc).__name__}: {exc}"[:200]
            rows.append({"prompt": prompt, "first": first[0] if first else None,
                         "total": time.monotonic() - began, "answer": " ".join(said), "error": error})
    for adapter in (brain._codex_brain, brain._claude_code_brain):
        if adapter is not None:
            adapter.close()
    return rows


def report(results):
    stamp = datetime.datetime.now()
    lines = [f"# Model benchmark {stamp:%Y-%m-%d %H:%M}", "",
             "| Model | Answered | First sentence (median) | Whole answer (median) |", "| --- | --- | --- | --- |"]
    for spec, rows in results.items():
        firsts = [r["first"] for r in rows if r["first"] is not None]
        totals = [r["total"] for r in rows if not r["error"]]
        lines.append(f"| {spec} | {len(totals)}/{len(rows)} | "
                     f"{statistics.median(firsts):.1f}s | {statistics.median(totals):.1f}s |" if firsts and totals
                     else f"| {spec} | {len(totals)}/{len(rows)} | - | - |")
    lines += ["", "Speed is measured; quality is for you (or Jarvis) to judge from the answers below.", ""]
    for i, prompt in enumerate(next(iter(results.values())), 1):
        lines += [f"## {i}. {prompt['prompt']}", ""]
        for spec, rows in results.items():
            row = rows[i - 1]
            timing = f"{row['first']:.1f}s to first sentence" if row["first"] is not None else "no answer"
            lines += [f"**{spec}** ({timing}): {row['error'] or row['answer'] or '(empty)'}", ""]
    folder = ROOT / "data" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"model-benchmark-{stamp:%Y-%m-%d-%H%M}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models", nargs="+", help="provider:model, e.g. codex:gpt-6.1-terra")
    parser.add_argument("--prompts", type=int, default=len(PROMPTS))
    parser.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    for spec in args.models:
        if ":" not in spec:
            parser.error(f"{spec}: write provider:model")
        if spec.split(":", 1)[0] in PAID and not args.allow_paid:
            parser.error(f"{spec} spends API credits; add --allow-paid to include it")
    import memory
    import performance
    with tempfile.TemporaryDirectory() as temp:
        # Benchmark turns stay out of the real recent conversation and timing record.
        with mock.patch.object(memory, "RECENT_PATH", str(Path(temp) / "recent.json")), \
                mock.patch.object(performance, "TURNS", Path(temp) / "turns.jsonl"):
            results = {}
            for spec in args.models:
                print(f"Benchmarking {spec}...", flush=True)
                results[spec] = run_model(spec, PROMPTS[:max(1, args.prompts)])
    print(f"Report: {report(results)}")


if __name__ == "__main__":
    main()
