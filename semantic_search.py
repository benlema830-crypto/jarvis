"""Local hybrid vault search: keyword + embeddings. No network destination except loopback Ollama.

Keyword and semantic candidates are merged with reciprocal rank fusion (RRF), so raw BM25
and cosine scores are never compared. Exact identifiers (part numbers, drawing IDs) get an
explicit boost; notes marked `status: superseded` (or outdated/archived/deprecated) in their
frontmatter are labelled and ranked lower. When embeddings are unavailable the same pipeline
runs on keyword candidates alone and says so.
"""
import hashlib
from contextlib import closing
import json
import math
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

import knowledge
import numpy as np
import requests

MODEL = 'embeddinggemma:300m'
BASE = 'http://127.0.0.1:11435'
STORE = Path(__file__).resolve().parent / 'data' / 'vault-vectors.sqlite3'
LOCK = threading.RLock()
EMBED_BUDGET = 4.0  # seconds of note embedding inside one interactive search; the rest is backfilled
RRF_K = 60
SEMANTIC_FLOOR = 0.30
POOL = 20
STALE = {'superseded', 'outdated', 'archived', 'deprecated'}


_local = threading.local()


def _request(route, payload=None):
    # One keep-alive loopback session per thread; proxies and environment credentials are ignored.
    session = getattr(_local, 'session', None)
    if session is None:
        session = _local.session = requests.Session()
        session.trust_env = False
    try:
        response = session.request('POST' if payload is not None else 'GET', BASE + route,
                                   json=payload, timeout=(3, 90), allow_redirects=False)
    except requests.RequestException:
        session.close()
        _local.session = None
        raise
    if response.is_redirect:
        raise ValueError('Local embedding redirects are not allowed.')
    response.raise_for_status()
    return response.json()


def identity():
    if os.getenv('JARVIS_OLLAMA_ENABLED', '1') == '0':
        raise ValueError('Local embeddings disabled.')
    models = _request('/api/tags').get('models', [])
    match = next((m for m in models if m.get('name') == MODEL), None)
    if not match:
        raise ValueError('Local embedding model is not installed.')
    details = _request('/api/show', {'model': MODEL})
    if details.get('remote_host') or 'embedding' not in details.get('capabilities', []):
        raise ValueError('A local embedding model is required.')
    return MODEL + ':' + match['digest']


def keep_alive():
    """How long Ollama keeps the embedding model loaded after a request.

    Measured on this PC (RTX 5070 Ti, Qwen voice loaded): unloading after every request
    (0) costs ~1.7 s per search; warm requests take ~6 ms; the loaded model holds ~654 MiB
    of VRAM. Default 2m releases the GPU two minutes after the last search. Set
    JARVIS_EMBED_KEEP_ALIVE=0 to restore unload-immediately; at most 30 minutes."""
    value = os.getenv('JARVIS_EMBED_KEEP_ALIVE', '2m').strip()
    match = re.fullmatch(r'(\d{1,4})([sm]?)', value)
    if not match:
        return 0
    seconds = int(match[1]) * (60 if match[2] == 'm' else 1)
    if seconds == 0 or seconds > 1800:
        return 0
    return value if match[2] else seconds


def embed(texts):
    import privacy
    texts = privacy.payload(texts)
    rows = _request('/api/embed', {'model': MODEL, 'input': texts, 'truncate': False,
                                 'keep_alive': keep_alive()})['embeddings']
    if len(rows) != len(texts):
        raise ValueError('Incomplete embedding response.')
    output = []
    for row in rows:
        if not row or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in row):
            raise ValueError('Invalid embedding response.')
        norm = math.sqrt(sum(v*v for v in row))
        if not norm:
            raise ValueError('Empty embedding vector.')
        output.append([v/norm for v in row])
    return output


def status(content):
    """Lifecycle status from YAML frontmatter (`status: superseded`), if any."""
    match = re.match(r'---\r?\n(.*?)\r?\n---', content, re.S)
    found = match and re.search(r'(?im)^status:\s*["\']?([\w-]+)', match.group(1))
    return found.group(1).casefold() if found else ''


# Vectors are content-addressed (key = hash of vault, model, path and chunk text), so a cached
# vector can never describe different text. Only keys of current notes are ever scored.
_vectors = {}
_cache_store = None
_live_keys = frozenset()
_backfill = None


def reset_cache():
    """Forget in-memory vectors (as a restart would); the SQLite store is untouched."""
    global _vectors, _cache_store, _live_keys
    wait_for_backfill(30)
    with LOCK:
        _vectors, _cache_store, _live_keys = {}, None, frozenset()


def wait_for_backfill(timeout=None):
    thread = _backfill
    if thread is not None:
        thread.join(timeout)


def _open():
    STORE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STORE, timeout=10)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector TEXT)')
    except sqlite3.DatabaseError:
        db.close()
        # A damaged cache is derived data: set it aside (not deleted) and rebuild from the notes.
        STORE.replace(STORE.with_name(STORE.name + time.strftime('.corrupt-%Y%m%d-%H%M%S')))
        db = sqlite3.connect(STORE, timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector TEXT)')
    return db


def _store(db, pairs):
    db.executemany('INSERT OR REPLACE INTO vectors VALUES (?, ?)',
                   [(key, json.dumps([round(float(v), 7) for v in vector])) for key, vector in pairs])
    for key, vector in pairs:
        _vectors[key] = np.asarray(vector, dtype=np.float32)


def _backfill_run(pending, store):
    """Embed the rest of a large first index outside interactive turns, one batch at a time."""
    try:
        for start in range(0, len(pending), 32):
            batch = [c for c in pending[start:start+32] if c['key'] not in _vectors]
            if not batch:
                continue
            vectors = embed([c['text'] for c in batch])
            with LOCK:
                if store != STORE or _cache_store != STORE:
                    return  # vault/store changed or cache was reset; a later search starts over
                # Notes deleted or edited meanwhile are no longer live; never store their vectors.
                fresh = [(c['key'], v) for c, v in zip(batch, vectors) if c['key'] in _live_keys]
                with closing(_open()) as db, db:
                    _store(db, fresh)
    except Exception:
        pass  # the next search retries whatever is still missing


def _semantic(query, notes, timings, counts):
    """Ranked [(note, similarity, excerpt)] above the similarity floor, best chunk per note."""
    global _cache_store, _live_keys, _backfill
    with LOCK:
        began = time.perf_counter()
        model = identity()
        scope = str(knowledge.VAULT.resolve()) + '\n' + model
        if _cache_store != STORE:
            _vectors.clear()
            _cache_store, _live_keys = STORE, frozenset()
        chunks = []
        for note in notes:
            for offset in range(0, len(note['content']), 1000):
                excerpt = note['content'][offset:offset+1200]
                text = note['title'] + '\n' + excerpt
                key = hashlib.sha256((scope + '\n' + note['path'] + '\n' + text).encode()).hexdigest()
                chunks.append(dict(key=key, text=text, note=note, excerpt=excerpt))
        if len(chunks) > 12000:
            raise ValueError('Vault exceeds the local embedding index limit.')
        live = frozenset(c['key'] for c in chunks)
        with closing(_open()) as db, db:
            unknown = [k for k in live if k not in _vectors]
            for start in range(0, len(unknown), 500):
                group = unknown[start:start+500]
                rows = db.execute('SELECT key, vector FROM vectors WHERE key IN (%s)' % ','.join('?' * len(group)), group)
                for key, vector in rows:
                    _vectors[key] = np.asarray(json.loads(vector), dtype=np.float32)
            if live != _live_keys:
                # Deleted or edited notes: purge their vectors so nothing stale can be scored or kept.
                stale = [k for (k,) in db.execute('SELECT key FROM vectors') if k not in live]
                db.executemany('DELETE FROM vectors WHERE key=?', [(k,) for k in stale])
                for key in [k for k in _vectors if k not in live]:
                    del _vectors[key]
                _live_keys = live
            missing = [c for c in chunks if c['key'] not in _vectors]
            timings['index_check'] = time.perf_counter() - began
            began = time.perf_counter()
            embedded = 0
            for start in range(0, len(missing), 32):
                if time.perf_counter() - began >= EMBED_BUDGET:
                    break  # the rest is embedded in the background; keyword results still cover it
                batch = missing[start:start+32]
                _store(db, [(c['key'], v) for c, v in zip(batch, embed([c['text'] for c in batch]))])
                embedded += len(batch)
        pending = [c for c in missing if c['key'] not in _vectors]
        if pending and (_backfill is None or not _backfill.is_alive()):
            _backfill = threading.Thread(target=_backfill_run, args=(pending, STORE), daemon=True,
                                         name='vault-embedding-backfill')
            _backfill.start()
        timings['embed_notes'] = time.perf_counter() - began
        counts.update(embedded_chunks=embedded, pending_chunks=len(pending))
        began = time.perf_counter()
        needle = np.asarray(embed([query])[0], dtype=np.float32)
        timings['embed_query'] = time.perf_counter() - began
        began = time.perf_counter()
        ready = [c for c in chunks if c['key'] in _vectors]
        best = {}
        if ready:
            matrix = np.stack([_vectors[c['key']] for c in ready])
            if matrix.shape[1] != needle.shape[0]:
                raise ValueError('Embedding dimensions changed; rebuild the local index.')
            for chunk, score in zip(ready, (matrix @ needle).tolist()):
                path = chunk['note']['path']
                if score >= SEMANTIC_FLOOR and (path not in best or score > best[path][1]):
                    best[path] = (chunk['note'], score, chunk['excerpt'])
        timings['similarity'] = time.perf_counter() - began
        counts['indexed_chunks'] = len(ready)
        return sorted(best.values(), key=lambda item: (-item[1], item[0]['path']))[:POOL]


_unavailable_until = 0.0  # after a failed connection, skip embeddings briefly
UNAVAILABLE_RETRY = 60    # a refused loopback connection costs ~2 s on Windows; don't pay it every search


def search(query, limit=8):
    global _unavailable_until
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError('Enter a search query of 1–2000 characters.')
    limit = max(1, min(20, int(limit)))
    timings, counts = {}, {'embedded_chunks': 0, 'pending_chunks': 0, 'indexed_chunks': 0}
    started = time.perf_counter()
    notes, _ = knowledge.notes()
    timings['scan'] = time.perf_counter() - started
    began = time.perf_counter()
    keyword = knowledge.search(query, POOL, notes) if notes else []
    timings['keyword'] = time.perf_counter() - began
    mode, reason = 'hybrid', ''
    try:
        if time.monotonic() < _unavailable_until:
            raise requests.ConnectionError('embedding service was unreachable moments ago')
        semantic = _semantic(query, notes, timings, counts) if notes else []
    except (requests.RequestException, OSError, ValueError, KeyError, sqlite3.Error) as error:
        semantic, mode = [], 'keyword'
        reason = 'Local semantic search unavailable: ' + type(error).__name__
        if isinstance(error, requests.ConnectionError):
            _unavailable_until = time.monotonic() + UNAVAILABLE_RETRY

    wanted = knowledge.codes(query)
    phrase = ' '.join(query.casefold().split())
    merged = {}
    for rank, item in enumerate(keyword, 1):
        merged.setdefault(item['path'].casefold(), {'item': item})['keyword'] = (rank, item['excerpt'])
    by_path = {n['path']: n for n in notes}
    for rank, (note, similarity, excerpt) in enumerate(semantic, 1):
        entry = merged.setdefault(note['path'].casefold(), {'item': {
            'path': note['path'], 'title': note['title'], 'uri': note['uri'], 'excerpt': excerpt}})
        entry['semantic'] = (rank, excerpt, similarity)
    ranked = []
    for entry in merged.values():
        item, note = entry['item'], by_path.get(entry['item']['path'], {})
        text = item['title'] + ' ' + item['path'] + ' ' + note.get('content', '')
        exact = [c for c in wanted if knowledge.exact(c, text)]
        title_hit = phrase == ' '.join(item['title'].casefold().split())
        score = sum(1 / (RRF_K + entry[k][0]) for k in ('keyword', 'semantic') if k in entry)
        score += (bool(exact) + title_hit) / RRF_K
        lifecycle = status(note.get('content', ''))
        if lifecycle in STALE:
            score /= 2
        # Prefer the chunk that actually matched: exact IDs use the keyword window, meaning uses its chunk.
        excerpt = entry['keyword'][1] if exact and 'keyword' in entry else \
            entry['semantic'][1] if 'semantic' in entry else entry['keyword'][1]
        result = {'path': item['path'], 'title': item['title'], 'uri': item['uri'], 'excerpt': excerpt,
                  'search_mode': mode, 'matched_by': [k for k in ('keyword', 'semantic') if k in entry],
                  'score': round(score, 5)}
        if note.get('modified'):
            result['modified'] = time.strftime('%Y-%m-%d', time.localtime(note['modified']))
        if lifecycle:
            result['status'] = lifecycle
        ranked.append((result, {'path': item['path'], 'keyword_rank': entry.get('keyword', (None,))[0],
                                'semantic_rank': entry.get('semantic', (None,))[0],
                                'similarity': round(entry['semantic'][2], 3) if 'semantic' in entry else None,
                                'exact_id': bool(exact), 'title_match': title_hit, 'status': lifecycle or None}))
    # Exact RRF ties (e.g. keyword #1 vs semantic #1) go to the stronger meaning match.
    ranked.sort(key=lambda pair: (-pair[0]['score'], -(pair[1]['similarity'] or 0), pair[0]['path']))
    timings['total'] = time.perf_counter() - started
    response = {'mode': mode, 'results': [result for result, _ in ranked[:limit]],
                'diagnostics': {'timings_ms': {k: round(v * 1000, 1) for k, v in timings.items()},
                                'keyword_candidates': len(keyword), 'semantic_candidates': len(semantic),
                                **counts, 'ranks': [rank for _, rank in ranked[:limit]]}}
    if mode == 'hybrid':
        response.update(model=MODEL, indexed_chunks=counts['indexed_chunks'])
    else:
        response['reason'] = reason
    return response
