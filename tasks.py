"""A to-do list kept as Markdown checkboxes in the vault's Tasks.md.

Obsidian shows and edits the same file, and it appears in the Brain graph like any note.
JARVIS only adds lines and ticks boxes here; every other line is preserved as written.
"""
import datetime
import difflib
import re

import knowledge

FILE = "Tasks.md"
_BOX = re.compile(r"^(\s*[-*]\s+\[)([ xX])(\]\s+)(.+?)\s*$")


def _lines():
    path = knowledge.note_path(FILE)
    return path, (path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else [])


def items():
    """[{n, text, done}] in file order; n numbers the open tasks the way JARVIS reads them out."""
    _, lines = _lines()
    out, n = [], 0
    for line in lines:
        m = _BOX.match(line)
        if m:
            done = m.group(2) != " "
            n += 0 if done else 1
            out.append({"n": None if done else n, "text": m.group(4), "done": done})
    return out


def add(text: str, due: str = "") -> str:
    text = " ".join(str(text).split())[:300]
    if not text:
        return "Say what the task is."
    if due:
        text += f" (due {due.strip()[:40]})"
    with knowledge.LOCK:
        path, lines = _lines()
        if not lines:
            lines = ["# Tasks", "", "Kept by JARVIS. Tick boxes here or ask him to.", ""]
        lines.append(f"- [ ] {text}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"Added: {text}"


def complete(which: str) -> str:
    which = str(which).strip()
    with knowledge.LOCK:
        path, lines = _lines()
        open_rows = [(i, _BOX.match(line)) for i, line in enumerate(lines)]
        open_rows = [(i, m) for i, m in open_rows if m and m.group(2) == " "]
        if not open_rows:
            return "There are no open tasks."
        target = None
        if which.isdigit() and 1 <= int(which) <= len(open_rows):
            target = open_rows[int(which) - 1]
        else:
            texts = [m.group(4) for _, m in open_rows]
            hit = next((t for t in texts if which.lower() in t.lower()), None) if which else None
            hit = hit or next(iter(difflib.get_close_matches(which, texts, n=1, cutoff=0.45)), None)
            target = next(((i, m) for i, m in open_rows if m.group(4) == hit), None)
        if not target:
            return f"No open task matches '{which}'."
        i, m = target
        stamp = datetime.date.today().isoformat()
        lines[i] = f"{m.group(1)}x{m.group(3)}{m.group(4)} ✓ {stamp}"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"Done: {m.group(4)}"


def describe(include_done: bool = False) -> str:
    rows = items()
    open_rows = [r for r in rows if not r["done"]]
    if not open_rows and not include_done:
        return "No open tasks."
    lines = [f"{r['n']}. {r['text']}" for r in open_rows]
    if include_done:
        lines += [f"(done) {r['text']}" for r in rows if r["done"]][-10:]
    return "\n".join(lines)
