from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import ollama_brain as ob
import model_provider as mp


class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.replies = [], []
        self.remote = False
        test = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, result, stream=False):
                data = (b''.join(json.dumps(x).encode() + b'\n' for x in result) if stream else json.dumps(result).encode())
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson' if stream else 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                test.calls.append((self.path, None))
                self.send({'models': [{'name': 'local:test'}, {'name': 'remote:cloud'}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                test.calls.append((self.path, body))
                if self.path == '/api/show':
                    result = {'capabilities': ['completion', 'tools'], 'model_info': {'parameter_count': 100}}
                    if test.remote:
                        result['remote_host'] = 'https://cloud.example'
                    self.send(result)
                else:
                    self.send(test.replies.pop(0) if test.replies else [{'message': {'content': 'OK.'}, 'done': True}], True)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        p = patch.dict(os.environ, {'JARVIS_OLLAMA_ENABLED': '1', 'JARVIS_OLLAMA_URL': self.url})
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        ob._catalog = (0, '', [])

    def test_opt_in_and_loopback_only(self):
        with patch.dict(os.environ, {'JARVIS_OLLAMA_ENABLED': '0'}):
            self.assertEqual(ob.models(), [])
            with self.assertRaises(ob.OllamaError):
                ob.validate('local:test')
        for endpoint in ('https://example.com', 'http://localhost:11434', 'http://127.0.0.1:11434/other', 'http://user:pass@127.0.0.1:11434'):
            with patch.dict(os.environ, {'JARVIS_OLLAMA_URL': endpoint}), self.assertRaises(ob.OllamaError):
                ob.base_url()
        self.assertEqual(self.calls, [])

    def test_lists_local_models_without_loading_and_validation_uses_no_history(self):
        self.assertEqual(ob.models(), ['local:test'])
        self.assertEqual(ob.models(), ['local:test'])
        self.assertEqual(len(self.calls), 1)
        ob.validate('local:test')
        payload = next(p for path, p in self.calls if path == '/api/chat')
        self.assertEqual(payload['messages'], [{'role': 'user', 'content': 'Reply with OK.'}])
        self.assertNotIn('tools', payload)

    def test_cloud_alias_is_rejected_before_private_history(self):
        self.remote = True
        with self.assertRaisesRegex(ob.OllamaError, 'Cloud'):
            ob.ask('local:test', 'private system', [{'role': 'user', 'content': 'private user'}], [], Mock(), Mock(), threading.Event())
        self.assertFalse(any(path == '/api/chat' for path, _ in self.calls))

    def ask(self, cancel=None, delta=None, run_tool=None):
        return ob.ask('local:test', 'system', [{'role': 'user', 'content': 'find note'}],
                      [{'name': 'search_knowledge', 'input_schema': {'type': 'object'}}],
                      run_tool or Mock(return_value={'content': 'a real note'}), delta or Mock(), cancel or threading.Event())

    def test_native_tool_round_trip_uses_existing_dispatcher(self):
        self.replies = [
            [{'message': {'content': 'Checking. ', 'thinking': 'not spoken'}, 'done': False},
             {'message': {'tool_calls': [{'function': {'name': 'search_knowledge', 'arguments': {'query': 'note'}}}]}, 'done': True}],
            [{'message': {'content': 'Found it.'}, 'done': True}]]
        run = Mock(return_value={'content': 'a real note'})
        said = []
        answer = self.ask(run_tool=run, delta=said.append)
        self.assertEqual(answer, 'Checking. Found it.')
        self.assertNotIn('not spoken', ''.join(said))
        block = run.call_args.args[0]
        self.assertEqual((block.name, block.input), ('search_knowledge', {'query': 'note'}))
        payloads = [p for path, p in self.calls if path == '/api/chat']
        self.assertIn({'role': 'tool', 'tool_name': 'search_knowledge', 'content': 'a real note'}, payloads[1]['messages'])
        self.assertEqual(payloads[1]['messages'][-2]['thinking'], 'not spoken')

    def test_incomplete_stream_and_unknown_tool_execute_nothing(self):
        for reply in [
                [{'message': {'tool_calls': [{'function': {'name': 'search_knowledge', 'arguments': {}}}]}, 'done': False}],
                [{'message': {'tool_calls': [{'function': {'name': 'delete_everything', 'arguments': {}}}]}, 'done': True}],
                [{'message': {'tool_calls': [{'function': {'name': 'search_knowledge', 'arguments': 'invalid'}}]}, 'done': True}]]:
            self.replies = [reply]
            run = Mock()
            with self.assertRaises(ob.OllamaError):
                self.ask(run_tool=run)
            run.assert_not_called()

    def test_interruption_prevents_tool_dispatch(self):
        self.replies = [[{'message': {'content': 'Checking.'}, 'done': False},
                         {'message': {'tool_calls': [{'function': {'name': 'search_knowledge', 'arguments': {}}}]}, 'done': True}]]
        cancel, run = threading.Event(), Mock()
        with self.assertRaises(InterruptedError):
            self.ask(cancel=cancel, delta=lambda text: cancel.set(), run_tool=run)
        run.assert_not_called()

    def test_repeated_identical_tool_requests_execute_once(self):
        call = {'function': {'name': 'search_knowledge', 'arguments': {'query': 'note'}}}
        self.replies = [[{'message': {'tool_calls': [call, call]}, 'done': True}],
                        [{'message': {'tool_calls': [call]}, 'done': True}],
                        [{'message': {'content': 'Found it.'}, 'done': True}]]
        run = Mock(return_value={'content': 'Already found the note.'})
        self.assertEqual(self.ask(run_tool=run), 'Found it.')
        run.assert_called_once()

    def test_no_vision_model_reports_missing_images(self):
        self.replies = [[{'message': {'tool_calls': [{'function': {'name': 'search_knowledge', 'arguments': {}}}]}, 'done': True}],
                        [{'message': {'content': 'I cannot see images.'}, 'done': True}]]
        run = Mock(return_value={'content': [{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'not-an-image'}}]})
        self.ask(run_tool=run)
        last = [p for path, p in self.calls if path == '/api/chat'][-1]
        self.assertIn('does not support vision', last['messages'][-1]['content'])
        self.assertNotIn('not-an-image', json.dumps(last))

    def test_subscription_only_allows_local_but_preserves_current_until_validation(self):
        entered, release = threading.Event(), threading.Event()
        def validate(config):
            entered.set()
            release.wait(5)
        selection = mp.Selection(validate=validate, persist=Mock())
        selection.active = {'provider': 'codex', 'model': 'current'}
        selection.ready = True
        with patch.object(mp.preferences, 'read', return_value={'subscription_only': True}), \
             patch.object(mp, 'catalog', return_value={'ollama': ['local:test']}), \
             patch.object(mp, 'credential_state', return_value='unused'):
            selection.request({'provider': 'ollama', 'model': 'local:test'})
            self.assertTrue(entered.wait(2))
            self.assertEqual(selection.active['provider'], 'codex')
            release.set()
            for _ in range(100):
                if not selection.pending:
                    break
                threading.Event().wait(.01)
            self.assertEqual(selection.active['provider'], 'ollama')
            with self.assertRaisesRegex(ValueError, 'disabled'):
                selection.request({'provider': 'openai', 'model': 'paid'})

    def test_jarvis_routes_local_provider_and_records_text_history(self):
        import jarvis
        selection = mp.Selection(validate=Mock(), persist=Mock())
        config = {'provider': 'ollama', 'model': 'local:test'}
        with patch.object(mp, 'SELECTION', selection), \
             patch.object(jarvis.preferences, 'read', return_value={'subscription_only': True, 'conversation_model': config}), \
             patch.object(jarvis.memory, 'prompt_section', return_value=''), \
             patch.object(jarvis.memory, 'recent_prompt', return_value=''), \
             patch.object(jarvis.memory, 'record_turn') as record:
            brain = jarvis.Brain()
            said = []
            brain.ask('hello', said.append)
        self.assertEqual(said, ['OK.'])
        self.assertEqual(brain.messages[-1]['content'], 'OK.')
        self.assertFalse(selection.busy)
        record.assert_called_once_with('hello', 'OK.')


if __name__ == '__main__':
    unittest.main()
