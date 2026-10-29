"""Phase A2: saved facts are never silently evicted at the cap."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import memory
import privacy


class MemoryCapacityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for module, field, value in [(memory, 'PATH', str(root / 'memory.json')),
                                     (memory, 'RECENT_PATH', str(root / 'recent.json')),
                                     (privacy, 'STORE', root / 'privacy.json'),
                                     (memory, 'MAX_FACTS', 200)]:  # the cap's behaviour, not its size; keeps the test fast
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fill(self, count):
        for i in range(count):
            self.assertTrue(memory.remember(f'Synthetic fact {i:03d} about topic {i}.').startswith('Remembered'))

    def test_full_memory_refuses_explicitly_and_keeps_every_fact(self):
        self.fill(memory.MAX_FACTS)
        before = Path(memory.PATH).read_bytes()
        result = memory.remember('One fact too many.')
        self.assertIn('full', result.lower())
        self.assertIn('nothing was removed', result.lower())
        self.assertEqual(Path(memory.PATH).read_bytes(), before)
        stored = memory.facts()
        self.assertEqual(len(stored), memory.MAX_FACTS)
        self.assertEqual(stored[0], 'Synthetic fact 000 about topic 0.')
        self.assertNotIn('One fact too many.', stored)

    def test_room_returns_after_forgetting(self):
        self.fill(memory.MAX_FACTS)
        memory.forget('Synthetic fact 007 about topic 7.')
        self.assertTrue(memory.remember('A newer fact.').startswith('Remembered'))
        self.assertEqual(len(memory.facts()), memory.MAX_FACTS)

    def test_duplicates_do_not_consume_capacity(self):
        self.fill(memory.MAX_FACTS - 1)
        for variant in ('Synthetic fact 000 about topic 0.', 'synthetic   FACT 000 about topic 0', 'Synthetic fact 000 about topic 0!'):
            self.assertEqual(memory.remember(variant), 'Already remembered.')
        self.assertTrue(memory.remember('The last free slot.').startswith('Remembered'))

    def test_similar_but_different_facts_are_not_merged(self):
        memory.remember('The user likes tea.')
        memory.remember('The user likes green tea.')
        memory.remember("The user's sister likes tea.")
        self.assertEqual(len(memory.facts()), 3)

    def test_concurrent_writes_are_atomic_and_complete(self):
        errors = []

        def write(i):
            try:
                memory.remember(f'Concurrent fact {i}.')
            except Exception as error:  # pragma: no cover - reported below
                errors.append(error)
        threads = [threading.Thread(target=write, args=(i,)) for i in range(40)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        data = json.loads(Path(memory.PATH).read_text(encoding='utf-8'))
        self.assertEqual(sorted(item['fact'] for item in data), sorted(f'Concurrent fact {i}.' for i in range(40)))

    def test_legacy_records_load_unchanged(self):
        legacy = [{'fact': 'Legacy fact one.', 't': 1700000000.0}, {'fact': 'Legacy fact two.', 't': 1700000001.0}]
        Path(memory.PATH).write_text(json.dumps(legacy), encoding='utf-8')
        self.assertEqual(memory.facts(), ['Legacy fact one.', 'Legacy fact two.'])
        memory.remember('A new fact.')
        data = json.loads(Path(memory.PATH).read_text(encoding='utf-8'))
        self.assertEqual(data[:2], legacy)


if __name__ == '__main__':
    unittest.main()
