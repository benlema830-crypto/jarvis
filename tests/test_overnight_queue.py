import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('overnight_queue', Path(__file__).resolve().parents[1] / 'scripts/overnight_queue.py')
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


class QueueTests(unittest.TestCase):
    def exercise(self, *, failure=False, duplicate=False, stop=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            posts = []
            sessions = [{'name': 'Jarvis Builder', 'status': 'completed'}]
            if duplicate:
                sessions.append({'name': 'Reference Night 1', 'status': 'completed'})
            def api(path, body=None):
                if body is not None:
                    posts.append(body)
                    number = len(posts)
                    sessions.append({'name': f'Reference Night {number}', 'task': 'assigned',
                                     'status': 'failed' if failure else 'completed', 'report': 'test'})
                    return {'ok': True}
                return {'sessions': sessions}
            if stop:
                (root / 'STOP').touch()
            with patch.multiple(queue, REPORTS=root, STATE=root / 'state.json',
                                STOP=root / 'STOP', LOCK=root / 'lock'), patch.object(queue, 'api', api):
                queue.run()
            return posts, json.loads((root / 'state.json').read_text())

    def test_four_sequential_stages(self):
        posts, state = self.exercise()
        self.assertEqual(len(posts), 4)
        self.assertEqual(state['status'], 'completed')
        for i, body in enumerate(posts, 1):
            self.assertIn(f'only STAGE {i}', body['text'])

    def test_failed_stage_stops_queue(self):
        posts, state = self.exercise(failure=True)
        self.assertEqual(len(posts), 1)
        self.assertEqual(state['status'], 'stopped')

    def test_duplicate_run_does_not_dispatch(self):
        posts, state = self.exercise(duplicate=True)
        self.assertEqual(posts, [])
        self.assertEqual(state['status'], 'stopped')

    def test_stop_file_prevents_dispatch(self):
        posts, state = self.exercise(stop=True)
        self.assertEqual(posts, [])
        self.assertEqual(state['status'], 'stopped')
