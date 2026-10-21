import collections
import threading
import queue
import unittest
from unittest import mock

import numpy as np
import jarvis
import voice
import ears


class ResponsivenessTest(unittest.TestCase):
    def test_owner_can_interrupt_without_name_in_continuous_mode(self):
        self.assertEqual(jarvis.interruption_command("Open Roblox, please.", True, "continuous"), "Open Roblox, please.")
        self.assertIsNone(jarvis.interruption_command("Open Roblox", False, "continuous"))
        self.assertIsNone(jarvis.interruption_command("Open Roblox", True, "wake"))
        self.assertEqual(jarvis.interruption_command("stop", True, "wake"), "stop")

    def test_stop_does_not_swallow_unrelated_words(self):
        self.assertTrue(jarvis.is_stop("Okay, stop!"))
        self.assertFalse(jarvis.is_stop("stopwatch"))
        self.assertFalse(jarvis.is_stop("cancelled flights today"))

    def test_direct_launch_only_for_exact_single_action(self):
        with mock.patch.object(jarvis.apps, "names", return_value=["roblox", "teams"]), \
             mock.patch.object(jarvis.tools.open_app, "call", return_value="Opened roblox") as launch, \
             mock.patch.object(jarvis.hud, "emit"):
            self.assertEqual(jarvis.quick_reply("Can you open Roblox, please?"), "Roblox opened.")
            launch.assert_called_once_with({"name": "roblox"})
            launch.reset_mock()
            for text in ("open Roblox and do something", "open teams", "open roblo", "explain Roblox"):
                self.assertIsNone(jarvis.quick_reply(text))
            launch.assert_not_called()

    def test_failed_launch_is_not_reported_as_success(self):
        with mock.patch.object(jarvis.apps, "names", return_value=["roblox"]), \
             mock.patch.object(jarvis.tools.open_app, "call", side_effect=OSError), \
             mock.patch.object(jarvis.hud, "emit"):
            self.assertEqual(jarvis.quick_reply("open Roblox"), "Couldn't open roblox.")

    def test_cancelled_generation_cannot_requeue_audio(self):
        speaker = voice.Voice.__new__(voice.Voice)
        speaker._lock = threading.Lock()
        speaker._gen = 2
        speaker._play = mock.Mock()
        speaker._play_current(np.zeros(5), 1)
        speaker._play.assert_not_called()
        speaker._play_current(np.zeros(5), 2)
        speaker._play.assert_called_once()

    def test_audio_callbacks_run_outside_player_lock(self):
        player = voice._Player.__new__(voice._Player)
        player._lock = threading.Lock()
        player._cur = None
        acquired = []
        def done():
            locked = player._lock.acquire(blocking=False)
            acquired.append(locked)
            if locked:
                player._lock.release()
        player._chunks = collections.deque([(np.ones(4), done)])
        output = np.empty((8, 1), dtype=np.float32)
        player._fill(output, 8, None, None)
        self.assertEqual(acquired, [True])
        np.testing.assert_array_equal(output[:, 0], [1, 1, 1, 1, 0, 0, 0, 0])

    def test_stale_synthesis_does_not_consume_next_turn(self):
        speaker = voice.Voice.__new__(voice.Voice)
        speaker._gen = 2
        speaker._text_q = mock.Mock()
        speaker._text_q.get.side_effect = [(1, "old reply"), (2, "new reply"), StopIteration()]
        speaker._render = mock.Mock(return_value=[np.ones(5)])
        speaker._shape = lambda samples, *_: samples
        speaker._pause = np.zeros(2)
        speaker._play_current = mock.Mock()
        with self.assertRaises(StopIteration):
            speaker._synth_worker()
        speaker._render.assert_called_once_with("new reply")

    def test_recognition_failure_does_not_disable_interruptions(self):
        source = ears.Ears.__new__(ears.Ears)
        source._busy_phrases = mock.Mock()
        source._busy_phrases.get.side_effect = [(None, False, 0), (None, True, 0.8), StopIteration()]
        source._handle_barge_phrase = mock.Mock(side_effect=[RuntimeError(), None])
        source._log = mock.Mock()
        with self.assertRaises(StopIteration):
            source._barge_in_worker()
        self.assertEqual(source._handle_barge_phrase.call_count, 2)
        source._log.assert_called_once()

    def test_interrupted_tool_history_remains_valid(self):
        with mock.patch.object(jarvis.anthropic, "Anthropic"), mock.patch.object(jarvis.memory, "prompt_section", return_value=""):
            brain = jarvis.Brain()
        def partial(speak):
            brain.messages.append({"role": "assistant", "content": [{"type": "tool_use", "id": "unfinished"}]})
            raise jarvis.Interrupted()
        brain._run = partial
        with mock.patch.object(jarvis.memory, "record_turn"), self.assertRaises(jarvis.Interrupted):
            brain.ask("open Roblox", mock.Mock())
        self.assertEqual(len(brain.messages), 2)
        self.assertIsInstance(brain.messages[-1]["content"], str)
