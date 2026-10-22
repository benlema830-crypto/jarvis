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
import requests

MODEL = 'embeddinggemma:300m'
BASE = 'http://127.0.0.1:11435'
STORE = Path(__file__).resolve().parent / 'data' / 'vault-vectors.sqlite3'
LOCK = threading.RLock()
RRF_K = 60
SEMANTIC_FLOOR = 0.30
POOL = 20
STALE = {'superseded', 'outdated', 'archived', 'deprecated'}


def _request(route, payload=None):
    with requests.Session() as session:
        session.trust_env = False
        response = session.request('POST' if payload is not None else 'GET', BASE + route,
                                   json=payload, timeout=(3, 90), allow_redirects=False)
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


def embed(texts):
    import privacy
    texts = privacy.payload(texts)
    rows = _request('/api/embed', {'model': MODEL, 'input': texts, 'truncate': False,
                                 'keep_alive': 0})['embeddings']
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


def _semantic(query, notes, timings):
    """Ranked [(note, similarity, excerpt)] above the similarity floor, best chunk per note."""
    with LOCK:
        began = time.perf_counter()
        model = identity()
        scope = str(knowledge.VAULT.resolve()) + '\n' + model
        STORE.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(STORE)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector TEXT)')
            chunks = []
            for note in notes:
                for offset in range(0, len(note['content']), 1000):
                    excerpt = note['content'][offset:offset+1200]
                    text = note['title'] + '\n' + excerpt
                    key = hashlib.sha256((scope + '\n' + note['path'] + '\n' + text).encode()).hexdigest()
                    chunks.append(dict(key=key, text=text, note=note, excerpt=excerpt))
            if len(chunks) > 12000:
                raise ValueError('Vault exceeds the local embedding index limit.')
            # Only current validated notes participate; deleted/edited notes cannot leak stale results.
            vectors = dict(db.execute('SELECT key, vector FROM vectors'))
            missing = [c for c in chunks if c['key'] not in vectors]
            timings['index_check'] = time.perf_counter() - began
            began = time.perf_counter()
            for start in range(0, len(missing), 32):
                batch = missing[start:start+32]
                for chunk, vector in zip(batch, embed([c['text'] for c in batch])):
                    vectors[chunk['key']] = json.dumps(vector)
                    db.execute('INSERT OR REPLACE INTO vectors VALUES (?, ?)', (chunk['key'], json.dumps(vector)))
            live = {c['key'] for c in chunks}
            db.executemany('DELETE FROM vectors WHERE key=?', [(k,) for k in vectors if k not in live])
            timings['embed_notes'] = time.perf_counter() - began
            timings['embedded_chunks'] = len(missing)
            began = time.perf_counter()
            needle = embed([query])[0]
            timings['embed_query'] = time.perf_counter() - began
            began = time.perf_counter()
            best = {}
            for chunk in chunks:
                vector = json.loads(vectors[chunk['key']])
                if len(vector) != len(needle):
                    raise ValueError('Embedding dimensions changed; rebuild the local index.')
                score = sum(a*b for a, b in zip(needle, vector))
                path = chunk['note']['path']
                if score >= SEMANTIC_FLOOR and (path not in best or score > best[path][1]):
                    best[path] = (chunk['note'], score, chunk['excerpt'])
            timings['similarity'] = time.perf_counter() - began
            timings['indexed_chunks'] = len(chunks)
            return sorted(best.values(), key=lambda item: (-item[1], item[0]['path']))[:POOL]


def search(query, limit=8):
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError('Enter a search query of 1–2000 characters.')
    limit = max(1, min(20, int(limit)))
    timings = {}
    started = time.perf_counter()
    notes, _ = knowledge.notes()
    timings['scan'] = time.perf_counter() - started
    began = time.perf_counter()
    keyword = knowledge.search(query, POOL, notes) if notes else []
    timings['keyword'] = time.perf_counter() - began
    mode, reason = 'hybrid', ''
    try:
        semantic = _semantic(query, notes, timings) if notes else []
    except (requests.RequestException, OSError, ValueError, KeyError, sqlite3.Error) as error:
        semantic, mode = [], 'keyword'
        reason = 'Local semantic search unavailable: ' + type(error).__name__

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
                'diagnostics': {'timings_ms': {k: (round(v * 1000, 1) if isinstance(v, float) else v)
                                               for k, v in timings.items()},
                                'keyword_candidates': len(keyword), 'semantic_candidates': len(semantic),
                                'ranks': [rank for _, rank in ranked[:limit]]}}
    if mode == 'hybrid':
        response.update(model=MODEL, indexed_chunks=timings.get('indexed_chunks', 0))
    else:
        response['reason'] = reason
    return response
