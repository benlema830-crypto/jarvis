"""Private, synthetic retrieval benchmark. Never reads the real vault, memory or privacy settings.

    .venv\\Scripts\\python.exe scripts\\memory_benchmark.py [--mode offline|ollama|both] [--label NAME]
                                                         [--root PATH] [--out FILE]

Builds a temporary Obsidian-style vault from tests/retrieval_fixture.py, runs the questions
through the model-facing search_knowledge tool, and reports recall@1/@5, MRR, stale/deleted
hits, credential leaks, memory prompt size and latency. The report lists only synthetic
paths, ranks and timings (no note text). `--mode ollama` needs the local embedding server
on 127.0.0.1:11435 (start-local-model.bat); it is skipped honestly when unreachable.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest import mock

HERE = Path(__file__).resolve().parents[1]


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))] * 1000, 1)


def unload_model():
    """Force the embedding model out of memory so 'model cold' timings are real cold starts."""
    import requests
    import semantic_search
    with requests.Session() as session:
        session.trust_env = False
        session.post(semantic_search.BASE + '/api/embed', json={'model': semantic_search.MODEL, 'input': ['unload'],
                                                                'keep_alive': 0}, timeout=120).raise_for_status()
        loaded = session.get(semantic_search.BASE + '/api/ps', timeout=10).json().get('models', [])
    if any(m.get('name') == semantic_search.MODEL for m in loaded):
        raise RuntimeError('Embedding model did not unload; cold timings would be wrong.')


def run_mode(mode, fixture):
    import knowledge, memory, privacy, semantic_search, tools
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        vault = root / 'vault'
        vault.mkdir()
        patches = [mock.patch.object(knowledge, 'VAULT', vault),
                   mock.patch.object(semantic_search, 'STORE', root / 'vectors.sqlite3'),
                   mock.patch.object(memory, 'PATH', str(root / 'memory.json')),
                   mock.patch.object(memory, 'RECENT_PATH', str(root / 'recent.json')),
                   mock.patch.object(privacy, 'STORE', root / 'privacy.json'),
                   mock.patch.dict(os.environ, {'JARVIS_OLLAMA_ENABLED': '0' if mode == 'offline' else '1'})]
        for patcher in patches:
            patcher.start()
        try:
            if mode == 'ollama':
                try:
                    semantic_search.identity()
                except Exception as error:
                    return {'mode': mode, 'skipped': 'Local embedding server unavailable: ' + type(error).__name__}
            search = tools.TOOLS_BY_NAME['search_knowledge']
            fixture.build_vault(vault)
            if mode == 'ollama':
                unload_model()
            began = time.perf_counter()
            search.call({'query': 'warm up index'})
            cold_index = time.perf_counter() - began  # empty index, and (with Ollama) unloaded model
            fixture.delete_and_edit(vault)
            rows, first, second, modes = [], [], [], set()
            for kind, query, expected in fixture.QUESTIONS:
                began = time.perf_counter()
                output = search.call({'query': query})
                first.append(time.perf_counter() - began)
                began = time.perf_counter()
                search.call({'query': query})
                second.append(time.perf_counter() - began)
                results = json.loads(output)
                paths = [r['path'] for r in results]
                modes.update(r.get('search_mode', '?') for r in results)
                rank = next((i + 1 for i, p in enumerate(paths) if p in expected), None)
                rows.append({'kind': kind, 'query': query, 'expected': expected, 'rank': rank,
                             'top': paths[:3], 'returned': len(paths),
                             'deleted_hit': any(p in fixture.DELETED for p in paths),
                             'stale_excerpt': any('S-band' in r.get('excerpt', '') for r in results),
                             'secret_leak': any(s in output for s in fixture.FAKE_SECRETS)})
            model_cold = []
            if mode == 'ollama':
                for kind, query, _ in fixture.QUESTIONS[:3]:  # index warm, model forced cold each time
                    unload_model()
                    began = time.perf_counter()
                    search.call({'query': query})
                    model_cold.append(time.perf_counter() - began)
            answerable = [r for r in rows if r['expected']]
            report = {
                'mode': mode, 'result_modes': sorted(modes), 'questions': len(rows),
                'recall_at_1': round(sum(r['rank'] == 1 for r in answerable) / len(answerable), 3),
                'recall_at_5': round(sum(bool(r['rank']) and r['rank'] <= 5 for r in answerable) / len(answerable), 3),
                'mrr': round(sum(1 / r['rank'] for r in answerable if r['rank']) / len(answerable), 3),
                'by_kind': {}, 'deleted_hits': sum(r['deleted_hit'] for r in rows),
                'stale_excerpts': sum(r['stale_excerpt'] for r in rows),
                'secret_leaks': sum(r['secret_leak'] for r in rows),
                'unanswerable_with_results': sum(1 for r in rows if not r['expected'] and r['returned']),
                'latency_ms': {'index_cold_model_cold_first_search': round(cold_index * 1000, 1),
                               'index_warm_model_cold_median': percentile(model_cold, .5),
                               'warm_first_pass_p50': percentile(first, .5), 'warm_first_pass_p95': percentile(first, .95),
                               'warm_repeat_p50': percentile(second, .5), 'warm_repeat_p95': percentile(second, .95)},
                'rows': rows}
            for kind in sorted({r['kind'] for r in answerable}):
                group = [r for r in answerable if r['kind'] == kind]
                report['by_kind'][kind] = f"{sum(r['rank'] == 1 for r in group)}/{len(group)} top-1"
            return report
        finally:
            for patcher in reversed(patches):
                patcher.stop()


def memory_report(fixture):
    import memory, privacy
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        patches = [mock.patch.object(memory, 'PATH', str(root / 'memory.json')),
                   mock.patch.object(memory, 'RECENT_PATH', str(root / 'recent.json')),
                   mock.patch.object(privacy, 'STORE', root / 'privacy.json'),
                   mock.patch.object(memory, 'MAX_FACTS', 200)]  # the overflow check runs at a fixed cap
        for patcher in patches:
            patcher.start()
        try:
            filler = [{'fact': f'Synthetic background fact {i:03d}: the user logged widget batch WB-{1000 + i} '
                               'with a moderately detailed description of its purpose.', 't': 1_700_000_000 + i}
                      for i in range(194)]
            Path(memory.PATH).write_text(json.dumps(filler), encoding='utf-8')
            for fact in fixture.FACTS:
                memory.remember(fact)
            stored = len(memory.facts())
            overflow = memory.remember('One more synthetic fact beyond the cap.')
            report = {'stored_facts': stored, 'after_overflow': len(memory.facts()),
                      'oldest_fact_kept': memory.facts()[0].startswith('Synthetic background fact 000'),
                      'overflow_reply': overflow[:80], 'prompt_chars_200_facts': len(memory.prompt_section())}
            if not hasattr(memory, 'recall'):
                report['recall'] = 'not available in this version'
                return report
            rows = []

            def ask(kinds):
                for kind, query, expected in fixture.FACT_QUESTIONS:
                    if kind in kinds:
                        output = memory.recall(query)
                        found = not output.startswith('No saved fact')
                        rows.append({'kind': kind, 'query': query, 'correct': (expected is None and not found)
                                     or (expected is not None and expected in output)})
            ask(('exact', 'missing'))
            # Then correct one fact and forget another, as the user would.
            snapshot = memory.snapshot()
            target = next(f for f in snapshot['facts'] if 'priority' in f['fact'])
            memory.edit('update', snapshot['revision'], target['id'], 'The current project priority is the Telemetry dashboard.')
            memory.forget('locker code is 4471')
            ask(('corrected', 'deleted'))
            prompt = memory.prompt_section()
            report.update({'recall_correct': f"{sum(r['correct'] for r in rows)}/{len(rows)}",
                           'false_memories': sum(1 for r in rows if r['kind'] in ('missing', 'deleted') and not r['correct']),
                           'old_value_in_prompt': 'Orion launch tower' in prompt or '4471' in prompt,
                           'core_name_in_prompt': "name is Sam" in prompt, 'rows': rows})
            return report
        finally:
            for patcher in reversed(patches):
                patcher.stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('offline', 'ollama', 'both'), default='both')
    parser.add_argument('--label', default='current')
    parser.add_argument('--root', default=str(HERE), help='Jarvis source tree to measure (default: this one)')
    parser.add_argument('--out', default='')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(1, str(HERE / 'tests'))
    os.chdir(root)
    import retrieval_fixture as fixture
    report = {'label': args.label, 'source_tree': root.name, 'time': time.strftime('%Y-%m-%d %H:%M:%S'),
              'search': [], 'memory': memory_report(fixture)}
    for mode in (('offline', 'ollama') if args.mode == 'both' else (args.mode,)):
        report['search'].append(run_mode(mode, fixture))
    out = Path(args.out or HERE / 'data' / 'reports' / f'memory-benchmark-{args.label}.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for item in report['search']:
        summary = {k: v for k, v in item.items() if k != 'rows'}
        print(json.dumps(summary, indent=1))
        for row in item.get('rows', []):
            if row['expected'] and row['rank'] != 1:
                print(f"  miss [{row['kind']}] {row['query']!r}: rank={row['rank']} top={row['top']}")
    print(json.dumps({k: v for k, v in report['memory'].items() if k != 'rows'}, indent=1))
    print('Report:', out)


if __name__ == '__main__':
    main()
