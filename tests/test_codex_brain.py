import threading
import unittest
from unittest.mock import Mock, patch

import codex_brain as cb


class CodexTests(unittest.TestCase):
    def test_subscription_only_rejects_api_selection(self):
        import model_provider
        with patch.object(model_provider.preferences, 'read', return_value={'subscription_only': True}):
            selection = model_provider.Selection()
            with self.assertRaisesRegex(ValueError, 'disabled'):
                selection.request({'provider': 'openai', 'model': 'gpt-4.1-mini'})

    def test_api_key_auth_is_rejected(self):
        conn = Mock()
        conn.call.side_effect = [{}, {'account': {'type': 'apiKey'}}]
        with patch.object(cb, 'Connection', return_value=conn):
            with self.assertRaisesRegex(RuntimeError, 'ChatGPT'):
                cb.connect(lambda e: None)
        conn.close.assert_called_once()

    def test_dynamic_tool_uses_existing_dispatcher(self):
        brain = cb.CodexBrain()
        brain.conn = Mock()
        brain.cancel = threading.Event()
        brain.run_tool = Mock(return_value={'content': 'test result'})
        brain._event({'id': 5, 'method': 'item/tool/call', 'params':
            {'tool': 'search_knowledge', 'callId': 'abc', 'arguments': {'query': 'note'}}})
        call = brain.run_tool.call_args.args[0]
        self.assertEqual((call.name, call.id, call.input), ('search_knowledge', 'abc', {'query': 'note'}))
        self.assertEqual(brain.conn.send.call_args.args[0]['result'],
                         {'contentItems': [{'type': 'inputText', 'text': 'test result'}], 'success': True})
        brain.close()

    def test_cancelled_tool_never_executes(self):
        brain = cb.CodexBrain()
        brain.conn = Mock()
        brain.cancel = threading.Event()
        brain.cancel.set()
        brain.run_tool = Mock()
        brain._event({'id': 5, 'method': 'item/tool/call', 'params': {}})
        brain.run_tool.assert_not_called()
        self.assertFalse(brain.conn.send.call_args.args[0]['result']['success'])
        brain.close()

    def test_native_approval_cannot_bypass_jarvis(self):
        brain = cb.CodexBrain()
        brain.conn = Mock()
        brain._event({'id': 7, 'method': 'item/commandExecution/requestApproval', 'params': {}})
        self.assertEqual(brain.conn.send.call_args.args[0]['result'], {'decision': 'decline'})
        brain.close()

    def test_qwen_render_never_uses_network_voice(self):
        import voice
        import numpy as np
        v = voice.Voice.__new__(voice.Voice)
        v.local = Mock()
        v.local.render.return_value = np.ones(100, dtype=np.float32)
        v.eleven = Mock()
        self.assertEqual(len(list(v._render('Hello.'))), 1)
        v.eleven.stream.assert_not_called()
        self.assertEqual(v.engine, 'qwen')

    def test_stop_discards_speech_without_unloading_qwen(self):
        import voice
        import queue
        v = voice.Voice.__new__(voice.Voice)
        v.local = Mock()
        v._lock = threading.Lock()
        v._gen = 0
        v._text_q = queue.Queue()
        v._pending = 0
        v._player = Mock()
        v._idle = threading.Event()
        v.stop()
        v.local.cancel.assert_not_called()
        v._pending = 1
        v.stop()
        v.local.cancel.assert_not_called()
        self.assertEqual(v._pending, 0)
        self.assertTrue(v._idle.is_set())
        self.assertEqual(v._player.clear.call_count, 2)
        self.assertEqual(v._gen, 2)
