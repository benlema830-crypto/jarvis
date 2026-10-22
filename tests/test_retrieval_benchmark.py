"""Phase C3 guard: the synthetic benchmark runs offline and its quality/privacy floors hold."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

import retrieval_fixture

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('memory_benchmark', ROOT / 'scripts' / 'memory_benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class RetrievalBenchmarkTest(unittest.TestCase):
    def test_offline_search_floors(self):
        report = benchmark.run_mode('offline', retrieval_fixture)
        self.assertGreaterEqual(len(retrieval_fixture.QUESTIONS), 25)
        self.assertEqual(report['result_modes'], ['keyword'])
        self.assertGreaterEqual(report['recall_at_1'], 0.9)   # 0.792 before the hybrid/keyword rework
        self.assertEqual(report['deleted_hits'], 0)
        self.assertEqual(report['stale_excerpts'], 0)
        self.assertEqual(report['secret_leaks'], 0)
        exact = [r for r in report['rows'] if r['kind'] == 'exact']
        self.assertTrue(all(r['rank'] == 1 for r in exact))

    def test_memory_floors(self):
        report = benchmark.memory_report(retrieval_fixture)
        self.assertTrue(report['oldest_fact_kept'])
        self.assertEqual(report['after_overflow'], 200)
        self.assertLessEqual(report['prompt_chars_200_facts'], 4400)  # 24,406 before the budget
        self.assertEqual(report['false_memories'], 0)
        self.assertFalse(report['old_value_in_prompt'])
        self.assertTrue(report['core_name_in_prompt'])
        self.assertEqual(report['recall_correct'], f'{len(retrieval_fixture.FACT_QUESTIONS)}/{len(retrieval_fixture.FACT_QUESTIONS)}')

    def test_report_rows_hold_no_note_text(self):
        report = benchmark.run_mode('offline', retrieval_fixture)
        text = str(report)
        for note in retrieval_fixture.NOTES.values():
            body = note.splitlines()[-1]
            self.assertNotIn(body[:40], text)


if __name__ == '__main__':
    unittest.main()
