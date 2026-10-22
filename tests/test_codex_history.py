"""Long conversations: every new user message must reach the persistent Codex thread.

text_history() keeps only the last 40 messages, and CodexBrain used to remember how far it
had sent by an index into that capped list. Past ~20 exchanges the slice was always empty, so
Codex received "[]", answered nothing, and Jarvis went silent."""
import json
import threading
import unittest
from unittest import mock

import codex_brain


class FakeConnection:
    def __init__(self):
        self.inputs, self.proc = [], mock.Mock(poll=mock.Mock(return_value=None))
        self.pending = []

    def call(self, method, params, timeout=60):
        if method == 'thread/start':
            return {'thread': {'id': 'thread-1'}}
        if method == 'turn/start':
            self.inputs.append(json.loads(params['input'][0]['text']))
            self.pending = [{'method': 'item/agentMessage/delta', 'params': {'delta': 'Reply.'}},
                            {'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}}]
        return {}

    def receive(self, timeout=0.25):
        return self.pending.pop(0) if self.pending else {}

    def close(self):
        pass


class CodexHistoryTest(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConnection()
        patcher = mock.patch.object(codex_brain, 'connect', return_value=self.conn)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.brain = codex_brain.CodexBrain()
        self.messages = []

    def turn(self, text):
        self.messages.append({'role': 'user', 'content': text})
        answer = self.brain.ask('model', 'system', self.messages, [], None, lambda d: None, threading.Event())
        self.messages.append({'role': 'assistant', 'content': answer})
        return self.conn.inputs[-1]

    def test_every_turn_of_a_long_conversation_sends_the_new_message(self):
        for i in range(60):
            sent = self.turn(f'message {i}')
            self.assertTrue(sent, f'turn {i} sent nothing to Codex')
            self.assertEqual(sent[-1], {'role': 'user', 'content': f'message {i}'})

    def test_follow_up_turns_send_only_what_is_new(self):
        self.turn('first')
        self.assertEqual(self.turn('second'), [{'role': 'user', 'content': 'second'}])

    def test_notes_between_turns_are_included(self):
        self.turn('first')
        for _ in range(30):  # e.g. many agent reports recorded with Brain.note()
            self.messages += [{'role': 'user', 'content': '[TASK FINISHED] report'},
                              {'role': 'assistant', 'content': 'Report read out.'}]
        sent = self.turn('what next?')
        self.assertEqual(sent[-1]['content'], 'what next?')
        self.assertIn({'role': 'user', 'content': '[TASK FINISHED] report'}, sent)


if __name__ == '__main__':
    unittest.main()
