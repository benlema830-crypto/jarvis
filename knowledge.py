"""Local, Obsidian-compatible Markdown knowledge. No plugin or cloud index required."""
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import quote, unquote, urlsplit

VAULT = Path.home() / "Documents" / "JARVIS Knowledge"
MAX_NOTES = 1000
MAX_BYTES = 256_000
LOCK = threading.RLock()


def note_path(relative):
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("Supply a vault-relative Markdown path.")
    relative = relative.replace("\\", "/")
    parts = relative.split("/")
    if any(not p or p.startswith(".") or re.search(r'[<>:"|?*\x00-\x1f]', p)
           or p.endswith((" ", ".")) or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p)
           for p in parts):
        raise ValueError("Use a normal note path inside the vault, without hidden or parent folders.")
    path = VAULT.joinpath(*parts)
    if path.suffix.lower() != ".md":
        raise ValueError("Only Markdown notes (.md) are supported.")
    root = VAULT.resolve()
    if not path.resolve().is_relative_to(root):
        raise ValueError("The note must stay inside the knowledge vault.")
    # Do not index or write through symbolic links / Windows junctions.
    for part in (path, *path.parents):
        if part == VAULT.parent:
            break
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Linked folders and files are excluded from the vault.")
    return path


def uri(relative):
    return "obsidian://open?path=" + quote(str(note_path(relative).absolute()), safe="")


def read(relative):
    path = note_path(relative)
    if not path.is_file():
        raise ValueError("Note not found in the vault.")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("This note exceeds the 256 KB limit.")
    content = path.read_text(encoding="utf-8-sig")
    title = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), path.stem)
    return {"path": path.relative_to(VAULT).as_posix(), "title": title, "content": content,
            "uri": uri(relative), "modified": path.stat().st_mtime}


def notes():
    """Validated vault notes and the number skipped, without link analysis (used by search)."""
    found, skipped = [], 0
    if not VAULT.is_dir():
        return found, skipped
    for directory, folders, files in os.walk(VAULT, followlinks=False):
        folders[:] = sorted(f for f in folders if not f.startswith('.') and
                            not (Path(directory) / f).is_symlink() and
                            not (Path(directory) / f).is_junction())
        for name in sorted(files):
            if name.startswith('.') or not name.lower().endswith('.md'):
                continue
            if len(found) >= MAX_NOTES:
                skipped += 1
                continue
            try:
                found.append(read((Path(directory) / name).relative_to(VAULT).as_posix()))
            except (OSError, ValueError, UnicodeError):
                skipped += 1
    return found, skipped


def index():
    notes_found, skipped = notes()
    if not VAULT.is_dir():
        return {"notes": [], "links": [], "skipped": 0, "unresolved": 0}
    return _with_links(notes_found, skipped)


def _with_links(notes, skipped):
    by_path = {n['path'].casefold(): n['path'] for n in notes}
    by_stem = {}
    for n in notes:
        by_stem.setdefault(Path(n['path']).stem.casefold(), []).append(n['path'])
    links, seen, unresolved = [], set(), 0
    for note in notes:
        # Code examples and comments are not relationships.
        text = re.sub(r'```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`]*`|<!--[\s\S]*?-->', '', note['content'])
        targets = [(t.split('|')[0], True) for t in re.findall(r'\[\[([^\]\n]+)\]\]', text)]
        targets += [(t, False) for t in re.findall(r'(?<!!)\[[^\]\n]*\]\(([^)\n]+)\)', text)]
        for target, wiki in targets:
            target = unquote(target.strip().strip('<>')).split('#')[0].strip()
            if not target or urlsplit(target).scheme or target.startswith('//'):
                continue
            if Path(target).suffix and Path(target).suffix.lower() != '.md':
                continue
            if not target.lower().endswith('.md'):
                target += '.md'
            candidates = [target, (Path(note['path']).parent / target).as_posix()] if wiki else [(Path(note['path']).parent / target).as_posix(), target]
            resolved = None
            for candidate in candidates:
                try:
                    normalized = (VAULT / candidate).resolve().relative_to(VAULT.resolve()).as_posix()
                    resolved = by_path.get(normalized.casefold())
                    if resolved:
                        break
                except ValueError:
                    continue
            if not resolved and wiki and '/' not in target:
                matches = by_stem.get(Path(target).stem.casefold(), [])
                resolved = matches[0] if len(matches) == 1 else None
            if not resolved:
                unresolved += 1
                continue
            pair = (note['path'], resolved)
            if resolved != note['path'] and pair not in seen:
                seen.add(pair)
                links.append({"source": note['path'], "target": resolved})
    return {"notes": notes, "links": links, "skipped": skipped, "unresolved": unresolved}


STOP_WORDS = {'the', 'a', 'an', 'about', 'what', 'did', 'we', 'is', 'of', 'and', 'to', 'in', 'on', 'for', 'my',
              'i', 'do', 'does', 'how', 'when', 'which', 'who', 'it', 'that', 'this', 'with', 'are', 'was', 'be',
              'from', 'at', 'by', 'as', 'us', 'our', 'you', 'your', 'me', 'or', 'if', 'so', 'can', 'should', 'will',
              'would', 'could', 'has', 'have', 'had', 'were', 'been', 'its', 'there', 'then', 'now', 'any', 'all'}


def _stem(word):
    """Tiny suffix folding so change/changed/changes match; not a linguistic stemmer."""
    for suffix in ('ing', 'ed', 'es', 's'):
        if suffix == 's' and word.endswith(('ss', 'us', 'is')):
            break  # pass, status, analysis are not plurals
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[:-len(suffix)]
            if suffix in ('ing', 'ed') and len(word) >= 4 and word[-1] == word[-2] and word[-1] not in 'aeioulsfz':
                word = word[:-1]  # shipped -> ship, running -> run; keeps pull, staff, pass
            break
    return word[:-1] if word.endswith('e') and len(word) > 3 else word


def _words(text):
    return [_stem(w) for w in re.findall(r'\w+', text.casefold())]


def codes(query):
    """Identifier-like tokens (PN-4471-B, DWG-0193, v2.3) that deserve an exact match."""
    return [c for c in re.findall(r'[A-Za-z0-9]+(?:[-_./][A-Za-z0-9]+)+|\b\w*\d\w*\b', query) if len(c) >= 3]


def exact(code, text):
    return re.search(r'(?<![\w-])' + re.escape(code) + r'(?![\w-])', text, re.I) is not None


def search(query, limit=8, pool=None):
    """Word-level BM25-style ranking with title and exact-identifier boosts."""
    import math
    from collections import Counter
    pool = notes()[0] if pool is None else pool
    terms = {_stem(t) for t in re.findall(r'\w+', query.casefold()) if t not in STOP_WORDS}
    wanted = codes(query)
    docs = []
    for note in pool:
        title = set(_words(note['title'] + ' ' + note['path']))
        docs.append((note, Counter(_words(note['content'])), title))
    total = len(docs)
    frequency = {t: sum(1 for _, body, title in docs if t in body or t in title) for t in terms}
    matches = []
    for note, body, title in docs:
        score = 0.0
        for t in terms:
            if t in body or t in title:
                weight = math.log(1 + (total - frequency[t] + .5) / (frequency[t] + .5))
                score += weight * (body[t] / (body[t] + 1.2) + 1.5 * (t in title))
        hits = [c for c in wanted if exact(c, note['title'] + ' ' + note['path'] + ' ' + note['content'])]
        score += 3 * len(hits)
        if not terms or score:
            text = note['content']
            spots = [m.start() for c in hits for m in [re.search(re.escape(c), text, re.I)] if m]
            spots += [m.start() for t in terms for m in [re.search(r'\b' + re.escape(t), text, re.I)] if m]
            start = max(0, min(spots, default=0) - 100)
            matches.append((score, {"path": note['path'], "title": note['title'], "uri": note['uri'],
                                    "excerpt": text[start:start+1200]}))
    return [item for _, item in sorted(matches, key=lambda pair: (-pair[0], pair[1]['path']))[:max(1, min(limit, 20))]]


def create(relative, content):
    if not isinstance(content, str) or not content.strip() or len(content.encode('utf-8')) > MAX_BYTES:
        raise ValueError("Provide nonempty Markdown under 256 KB.")
    with LOCK:
        path = note_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation: never overwrite user edits or existing notes.
        try:
            with path.open('x', encoding='utf-8') as handle:
                handle.write(content.rstrip() + '\n')
        except FileExistsError:
            raise ValueError("That note already exists. Choose another name; existing notes are never overwritten.") from None
    return {"created": relative, "uri": uri(relative)}
