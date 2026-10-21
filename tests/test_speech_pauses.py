import queue
import threading
import unittest
from unittest import mock

import numpy as np
import ears


class SpeechPausesTest(unittest.TestCase):
    def run_audio(self, speech, busy=False):
        source = ears.Ears.__new__(ears.Ears)
        source.accepting = threading.Event()
        if not busy:
            source.accepting.set()
        source.on_wake = None
        source.wake = mock.Mock()
        source.wake.predict.return_value = {ears.WAKE_MODEL: 0.0}
        source._phrases = queue.Queue()
        source._busy_phrases = queue.Queue(maxsize=1)
        source._is_speech = mock.Mock(side_effect=speech)
        source._blocks = mock.Mock()
        source._blocks.get.side_effect = [np.zeros(ears.BLOCK, dtype=np.int16) for _ in speech] + [StopIteration()]
        with mock.patch.object(ears, "END_SILENCE", 1.2), mock.patch.object(ears, "BARGE_END_SILENCE", .48):
            with self.assertRaises(StopIteration):
                source._process()
        return source

    def test_pause_inside_request_stays_one_phrase(self):
        source = self.run_audio([True]*5 + [False]*10 + [True]*5 + [False]*15)
        self.assertEqual(source._phrases.qsize(), 1)
        self.assertEqual(len(source._phrases.get()[0]), 35 * ears.BLOCK)
        self.assertTrue(source._busy_phrases.empty())

    def test_short_pause_does_not_submit_request(self):
        source = self.run_audio([True]*5 + [False]*10)
        self.assertTrue(source._phrases.empty())

    def test_full_pause_submits_request(self):
        source = self.run_audio([True]*5 + [False]*15)
        self.assertEqual(source._phrases.qsize(), 1)

    def test_interruptions_keep_short_endpoint(self):
        source = self.run_audio([True]*5 + [False]*6, busy=True)
        self.assertEqual(source._busy_phrases.qsize(), 1)
        self.assertTrue(source._phrases.empty())
