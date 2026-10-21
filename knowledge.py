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


def index():
    notes, skipped = [], 0
    if not VAULT.is_dir():
        return {"notes": [], "links": [], "skipped": 0, "unresolved": 0}
    for directory, folders, files in os.walk(VAULT, followlinks=False):
        folders[:] = sorted(f for f in folders if not f.startswith('.') and
                            not (Path(directory) / f).is_symlink() and
                            not (Path(directory) / f).is_junction())
        for name in sorted(files):
            if name.startswith('.') or not name.lower().endswith('.md'):
                continue
            if len(notes) >= MAX_NOTES:
                skipped += 1
                continue
            try:
                notes.append(read((Path(directory) / name).relative_to(VAULT).as_posix()))
            except (OSError, ValueError, UnicodeError):
                skipped += 1
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


def search(query, limit=8):
    terms = set(re.findall(r'\w+', query.casefold())) - {'the', 'a', 'an', 'about', 'what', 'did', 'we', 'is', 'of', 'and', 'to', 'in'}
    matches = []
    for note in index()['notes']:
        body = note['content'].casefold()
        title = (note['title'] + ' ' + note['path']).casefold()
        score = sum(5 * (t in title) + body.count(t) for t in terms)
        if not terms or score:
            pos = min((body.find(t) for t in terms if t in body), default=0)
            start = max(0, pos - 100)
            matches.append((score, {"path": note['path'], "title": note['title'], "uri": note['uri'],
                                    "excerpt": note['content'][start:start+1200]}))
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
