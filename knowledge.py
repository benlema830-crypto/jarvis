"""Local, Obsidian-compatible Markdown knowledge. No plugin or cloud index required."""
import json
import os
from pathlib import Path
import re
import threading
import time
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
    import hashlib
    raw = path.read_bytes()
    content = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")  # as read_text() did
    title = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), path.stem)
    return {"path": path.relative_to(VAULT).as_posix(), "title": title, "content": content,
            "uri": uri(relative), "modified": path.stat().st_mtime, "sha256": hashlib.sha256(raw).hexdigest()}


_scan_cache = {}  # (vault, relative path) -> ((mtime_ns, size), note); only files seen in the latest scan


def notes():
    """Validated vault notes and the number skipped, without link analysis (used by search).

    Files whose modification time and size are unchanged since the last scan are not re-read;
    deleted files drop out because the cache is rebuilt from each scan."""
    global _scan_cache
    found, skipped, seen = [], 0, {}
    if not VAULT.is_dir():
        _scan_cache = {}
        return found, skipped
    vault = str(VAULT)
    pending = [VAULT]
    while pending:  # same order as os.walk: a folder's files, then its sorted subfolders
        directory = pending.pop()
        try:
            with os.scandir(directory) as listing:
                entries = sorted(listing, key=lambda e: e.name)
        except OSError:
            continue
        folders = []
        for entry in entries:
            if entry.name.startswith('.'):
                continue
            if entry.is_symlink() or entry.is_junction():
                if entry.name.lower().endswith('.md'):
                    skipped += 1  # linked notes are excluded, as read() would refuse them
                continue
            if entry.is_dir(follow_symlinks=False):
                folders.append(Path(entry.path))
                continue
            if not entry.name.lower().endswith('.md'):
                continue
            if len(found) >= MAX_NOTES:
                skipped += 1
                continue
            relative = Path(entry.path).relative_to(VAULT).as_posix()
            try:
                stat = entry.stat(follow_symlinks=False)
                fingerprint = (stat.st_mtime_ns, stat.st_size)
                cached = _scan_cache.get((vault, relative))
                note = cached[1] if cached and cached[0] == fingerprint else read(relative)
                seen[(vault, relative)] = (fingerprint, note)
                found.append(dict(note))
            except (OSError, ValueError, UnicodeError):
                skipped += 1
        pending.extend(reversed(folders))
    _scan_cache = seen
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


_token_cache = {}  # (path, mtime, length, content hash) -> (body word counts, title words)


def search(query, limit=8, pool=None):
    """Word-level BM25-style ranking with title and exact-identifier boosts."""
    import math
    from collections import Counter
    pool = notes()[0] if pool is None else pool
    terms = {_stem(t) for t in re.findall(r'\w+', query.casefold()) if t not in STOP_WORDS}
    wanted = codes(query)
    global _token_cache
    docs, tokens = [], {}
    for note in pool:
        key = (note['path'], note.get('modified'), len(note['content']), hash(note['content']))
        words = _token_cache.get(key) or (Counter(_words(note['content'])), set(_words(note['title'] + ' ' + note['path'])))
        tokens[key] = words
        docs.append((note, *words))
    _token_cache = tokens
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


# ---------- Targeted edits of existing notes (separate from create, which never overwrites) ----------

EDIT_ACTIONS = ('replace_section', 'append_to_section', 'set_frontmatter')
_HEADING = re.compile(r'(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$')


def _existing(relative):
    path = note_path(relative)
    if not path.is_file():
        raise ValueError("Note not found in the vault. Existing notes only; use create for new ones.")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("This note exceeds the 256 KB limit.")
    return path


def _headings(lines, start):
    """(index, level, normalized text) of real headings, skipping fenced code."""
    found, fence = [], None
    for i in range(start, len(lines)):
        stripped = lines[i].rstrip('\r\n')
        marker = stripped.lstrip()[:3]
        if marker in ('```', '~~~'):
            fence = None if fence == marker else fence or marker
            continue
        match = None if fence else _HEADING.fullmatch(stripped)
        if match:
            found.append((i, len(match[1]), ' '.join(match[2].casefold().split())))
    return found


def _edited(raw, action, target, content):
    bom = raw.startswith(b'\xef\xbb\xbf')
    text = raw[3 if bom else 0:].decode('utf-8')
    lines = text.splitlines(keepends=True)
    newline = '\r\n' if text.count('\r\n') * 2 > text.count('\n') else '\n'
    if lines and not lines[-1].endswith(('\n', '\r')):
        lines[-1] += newline
    front_end = None
    if lines and lines[0].rstrip('\r\n') == '---':
        front_end = next((i for i in range(1, len(lines)) if lines[i].rstrip('\r\n') == '---'), None)
    if action == 'set_frontmatter':
        if not re.fullmatch(r'[A-Za-z][\w-]{0,40}', target or ''):
            raise ValueError("Use a simple frontmatter key such as status.")
        if not isinstance(content, str) or not content.strip() or len(content) > 200 or '\n' in content or '\r' in content:
            raise ValueError("Use a one-line frontmatter value of at most 200 characters.")
        value = content.strip()
        value = json.dumps(value) if re.search(r'[:#\[\]{}&*!|>\'"%@`]|^[-?]', value) else value
        entry = f'{target}: {value}{newline}'
        if front_end is None:
            return bom, ['---' + newline, entry, '---' + newline] + lines
        keys = [i for i in range(1, front_end) if re.match(re.escape(target) + r'\s*:', lines[i])]
        if len(keys) > 1:
            raise ValueError(f"The frontmatter has several '{target}' keys; edit it in Obsidian.")
        if keys:
            lines[keys[0]] = entry
        else:
            lines.insert(front_end, entry)
        return bom, lines
    wanted = ' '.join(re.sub(r'^#+\s*', '', target or '').casefold().split())
    headings = _headings(lines, 0 if front_end is None else front_end + 1)
    matches = [h for h in headings if h[2] == wanted]
    if not matches:
        raise ValueError(f"No heading '{target}' in this note.")
    if len(matches) > 1:
        raise ValueError(f"Several headings are called '{target}'; edit it in Obsidian or rename one first.")
    index, level, _ = matches[0]
    end = next((i for i, lvl, _ in headings if i > index and lvl <= level), len(lines))
    body = lines[index + 1:end]
    trailing = 0
    while trailing < len(body) and not body[len(body) - 1 - trailing].strip():
        trailing += 1
    new = [line + newline for line in content.strip('\r\n').replace('\r\n', '\n').split('\n')]
    if action == 'replace_section':
        return bom, lines[:index + 1] + new + body[len(body) - trailing:] + lines[end:]
    insert = index + 1 + len(body) - trailing
    return bom, lines[:insert] + new + lines[insert:]


def plan_edit(relative, action, target, content, expected_sha256):
    """Validate an edit and return its preview; nothing is written until apply_edit()."""
    import difflib
    import hashlib
    if action not in EDIT_ACTIONS:
        raise ValueError("Choose replace_section, append_to_section or set_frontmatter.")
    if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_BYTES:
        raise ValueError("Provide text under 256 KB.")
    with LOCK:
        path = _existing(relative)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("The note changed since it was read. Read it again before editing.")
        bom, lines = _edited(raw, action, target, content)
    new = (b'\xef\xbb\xbf' if bom else b'') + ''.join(lines).encode('utf-8')
    if len(new) > MAX_BYTES:
        raise ValueError("The edited note would exceed the 256 KB limit.")
    if new == raw:
        raise ValueError("That edit would not change the note.")
    old_text = raw.decode('utf-8-sig').splitlines()
    diff = '\n'.join(difflib.unified_diff(old_text, ''.join(lines).splitlines(), 'before', 'after', n=1, lineterm=''))
    relative = path.relative_to(VAULT).as_posix()
    return {'path': relative, 'action': action, 'target': target, 'expected_sha256': expected_sha256,
            'diff': diff[:4000] + ('\n…' if len(diff) > 4000 else ''), 'new': new}


def apply_edit(plan):
    """Write a planned edit only if the note is still exactly the version that was previewed."""
    import hashlib
    with LOCK:
        path = _existing(plan['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != plan['expected_sha256']:
            raise ValueError("The note changed since it was read (perhaps edited in Obsidian). Nothing was written.")
        temp = path.with_name('.jarvis-edit-' + os.urandom(6).hex() + '.tmp')  # hidden: Obsidian ignores it
        try:
            with open(temp, 'xb') as handle:
                handle.write(plan['new'])
                handle.flush()
                os.fsync(handle.fileno())
            # Win32 ReplaceFile is avoided on purpose: when antivirus briefly holds the new file it
            # can delete the original and leave the replacement under its temporary name.
            for attempt in range(5):
                if not path.is_file():  # deleted meanwhile: never recreate it
                    raise ValueError("The note was deleted before the edit was written. Nothing was changed.")
                try:
                    os.replace(temp, path)  # atomic; the note is either fully old or fully new
                    break
                except PermissionError:
                    if attempt == 4:
                        raise ValueError("The note is locked by another program. Nothing was changed.") from None
                    time.sleep(0.1 * (attempt + 1))
        finally:
            temp.unlink(missing_ok=True)
        return {'updated': plan['path'], 'sha256': hashlib.sha256(plan['new']).hexdigest(), 'uri': uri(plan['path'])}
