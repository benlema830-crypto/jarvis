"""Local, incremental vault embeddings. No network destination except loopback Ollama."""
import hashlib
from contextlib import closing
import json
import math
import os
import sqlite3
import threading
from pathlib import Path

import knowledge
import requests

MODEL = 'embeddinggemma:300m'
BASE = 'http://127.0.0.1:11435'
STORE = Path(__file__).resolve().parent / 'data' / 'vault-vectors.sqlite3'
LOCK = threading.RLock()


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


def search(query, limit=8):
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError('Enter a search query of 1–2000 characters.')
    limit = max(1, min(20, int(limit)))
    try:
        with LOCK:
            model = identity()
            notes = knowledge.index()['notes']
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
                for start in range(0, len(missing), 32):
                    batch = missing[start:start+32]
                    for chunk, vector in zip(batch, embed([c['text'] for c in batch])):
                        vectors[chunk['key']] = json.dumps(vector)
                        db.execute('INSERT OR REPLACE INTO vectors VALUES (?, ?)', (chunk['key'], json.dumps(vector)))
                live = {c['key'] for c in chunks}
                db.executemany('DELETE FROM vectors WHERE key=?', [(k,) for k in vectors if k not in live])
                needle = embed([query])[0]
                ranked = {}
                for chunk in chunks:
                    vector = json.loads(vectors[chunk['key']])
                    if len(vector) != len(needle):
                        raise ValueError('Embedding dimensions changed; rebuild the local index.')
                    score = sum(a*b for a, b in zip(needle, vector))
                    if score < 0.30:
                        continue
                    note = chunk['note']
                    item = dict(path=note['path'], title=note['title'], uri=note['uri'],
                                excerpt=chunk['excerpt'], score=round(score, 4), search_mode='semantic')
                    if note['path'] not in ranked or score > ranked[note['path']]['score']:
                        ranked[note['path']] = item
                return {'mode': 'semantic', 'model': MODEL, 'indexed_chunks': len(chunks),
                        'results': sorted(ranked.values(), key=lambda r: r['score'], reverse=True)[:limit]}
    except (requests.RequestException, OSError, ValueError, KeyError, sqlite3.Error) as error:
        return {'mode': 'keyword', 'reason': 'Local semantic search unavailable: ' + type(error).__name__,
                'results': [dict(n, search_mode='keyword') for n in knowledge.search(query, limit)]}
