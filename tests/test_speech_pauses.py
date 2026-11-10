import queue
import threading
import unittest
from unittest import mock

import numpy as np
import ears


class SpeechPausesTest(unittest.TestCase):
    def run_audio(self, speech, busy=False, turns=None):
        source = ears.Ears.__new__(ears.Ears)
        source.turns = turns
        source._log = mock.Mock()
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

    def detector(self, *scores):
        turns = mock.Mock()
        turns.probability.side_effect = list(scores)
        return turns

    def test_finished_sentence_ends_after_a_short_pause(self):
        turns = self.detector(0.9)
        source = self.run_audio([True]*5 + [False]*4, turns=turns)
        self.assertEqual(source._phrases.qsize(), 1)
        self.assertEqual(turns.probability.call_count, 1)

    def test_unfinished_sentence_still_gets_the_full_pause(self):
        turns = self.detector(0.1, 0.2)
        source = self.run_audio([True]*5 + [False]*10 + [True]*5 + [False]*15, turns=self.detector(0.1, 0.2, 0.1, 0.2))
        self.assertEqual(source._phrases.qsize(), 1)
        self.assertEqual(len(source._phrases.get()[0]), 35 * ears.BLOCK)
        source = self.run_audio([True]*5 + [False]*10, turns=turns)
        self.assertTrue(source._phrases.empty())

    def test_second_check_can_end_the_phrase(self):
        source = self.run_audio([True]*5 + [False]*8, turns=self.detector(0.3, 0.8))
        self.assertEqual(source._phrases.qsize(), 1)

    def test_interruptions_do_not_use_the_detector(self):
        turns = self.detector(0.9)
        source = self.run_audio([True]*5 + [False]*6, busy=True, turns=turns)
        turns.probability.assert_not_called()
        self.assertEqual(source._busy_phrases.qsize(), 1)

    def test_a_broken_detector_falls_back_to_the_timer(self):
        turns = mock.Mock()
        turns.probability.side_effect = RuntimeError("model gone")
        source = self.run_audio([True]*5 + [False]*15, turns=turns)
        self.assertEqual(source._phrases.qsize(), 1)
        self.assertIsNone(source.turns)
        self.assertEqual(turns.probability.call_count, 1)

    def test_noise_too_short_to_be_speech_is_not_checked(self):
        turns = self.detector(0.9)
        source = self.run_audio([True]*2 + [False]*4, turns=turns)
        turns.probability.assert_not_called()
        self.assertTrue(source._phrases.empty())


class TurnDetectorTest(unittest.TestCase):
    def test_probability_is_between_zero_and_one_for_any_length(self):
        import turn_detector
        if not turn_detector.MODEL.is_file():
            self.skipTest("turn model not downloaded")
        detector = turn_detector.TurnDetector()
        for seconds in (0.2, 3, 12):
            score = detector.probability(np.zeros(int(seconds * 16000), dtype=np.int16))
            self.assertTrue(0.0 <= score <= 1.0)


if __name__ == "__main__":
    unittest.main()
